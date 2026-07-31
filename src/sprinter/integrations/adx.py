from __future__ import annotations

import re
from typing import Any

import httpx
from azure.identity import ClientSecretCredential

from sprinter.config import Settings

WRITE_KQL = re.compile(
    r"(?i)\.(?:set|append|set-or-append|drop|delete|alter|create|clear|rename|move|replace)\b"
    r"|(?:^|\|)\s*into\b"
)
TABLE = re.compile(r"^\s*([A-Za-z_][A-Za-z0-9_]*)")


class AdxClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.adx_cluster_url)

    def validate(self, query: str) -> str:
        clean = query.strip()
        if ";" in clean or WRITE_KQL.search(clean):
            raise ValueError("ADX query must be one read-only statement")
        table = TABLE.match(clean)
        if not table or table.group(1) not in self.settings.allowed_adx_tables:
            raise ValueError("ADX query must begin with an allowlisted table")
        return clean

    def query(self, query: str, max_rows: int = 50) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("ADX is not configured")
        query = self.validate(query)
        credential = ClientSecretCredential(
            tenant_id=self.settings.adx_tenant_id,
            client_id=self.settings.adx_client_id,
            client_secret=self.settings.secret_value("adx"),
        )
        token = credential.get_token(f"{self.settings.adx_cluster_url.rstrip('/')}/.default")
        with httpx.Client(timeout=httpx.Timeout(30), verify=True) as client:
            response = client.post(
                f"{self.settings.adx_cluster_url.rstrip('/')}/v2/rest/query",
                headers={"Authorization": f"Bearer {token.token}"},
                json={"db": self.settings.adx_database, "csl": f"{query}\n| take {max_rows}"},
            )
            response.raise_for_status()
            payload = response.json()
        primary: dict[str, Any] = next(
            (table for table in payload if table.get("TableKind") == "PrimaryResult"),
            {},
        )
        columns = [column["ColumnName"] for column in primary.get("Columns", [])]
        rows = [dict(zip(columns, row, strict=False)) for row in primary.get("Rows", [])][:max_rows]
        return {"rows": rows, "count": len(rows), "query": query}
