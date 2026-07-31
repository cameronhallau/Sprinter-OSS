from __future__ import annotations

import json
import re
from typing import Any
from urllib.parse import quote

import httpx

from sprinter.config import Settings, read_secret

INDEX = re.compile(r"(?i)(?:^|[\s|(])index\s*=\s*(?:\"([^\"]+)\"|'([^']+)'|([A-Za-z0-9_.:-]+))")
BLOCKED = re.compile(
    r"(?i)(?:^|\|)\s*(?:delete|outputlookup|collect|sendemail|script|run|map|rest|loadjob|savedsearch)\b"
)


class SplunkClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.splunk_base_url)

    @property
    def audit_configured(self) -> bool:
        return bool(self.settings.splunk_hec_url)

    def validate(self, search: str) -> str:
        clean = " ".join(search.strip().split())
        if BLOCKED.search(clean):
            raise ValueError("Splunk search contains a disallowed command")
        indexes = {next(value for value in match if value) for match in INDEX.findall(clean)}
        if not indexes:
            raise ValueError("Splunk searches must include an explicit index")
        forbidden = indexes - self.settings.allowed_splunk_indexes
        if forbidden:
            raise ValueError(f"Splunk indexes are not allowed: {sorted(forbidden)}")
        return clean if clean.lower().startswith("search ") else f"search {clean}"

    def search(
        self,
        search: str,
        *,
        earliest: str = "-24h",
        latest: str = "now",
        max_rows: int = 50,
    ) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Splunk is not configured")
        search = self.validate(search)
        verify: bool | str = str(self.settings.splunk_ca_file) if self.settings.splunk_ca_file else True
        with httpx.Client(
            verify=verify,
            timeout=httpx.Timeout(30),
            auth=(self.settings.splunk_username, self.settings.secret_value("splunk")),
        ) as client:
            response = client.post(
                f"{self.settings.splunk_base_url.rstrip('/')}/services/search/jobs/export",
                data={
                    "search": search,
                    "earliest_time": earliest,
                    "latest_time": latest,
                    "output_mode": "json",
                    "count": str(max_rows),
                },
            )
            response.raise_for_status()
        rows = []
        for line in response.text.splitlines():
            if not line.strip():
                continue
            item = json.loads(line)
            if isinstance(item, dict) and isinstance(item.get("result"), dict):
                rows.append(item["result"])
        return {
            "rows": rows[:max_rows],
            "count": min(len(rows), max_rows),
            "search": search,
            "url": self.search_url(search),
        }

    def search_url(self, search: str) -> str:
        if not self.settings.splunk_web_url:
            return ""
        base = self.settings.splunk_web_url.rstrip("/")
        return f"{base}/en-US/app/search/search?q={quote(search, safe='')}"

    def post_event(self, event: dict[str, Any], sourcetype: str = "sprinter:audit") -> None:
        if not self.audit_configured:
            raise RuntimeError("Splunk HEC is not configured")
        token = read_secret(self.settings.splunk_hec_token, self.settings.splunk_hec_token_file)
        verify: bool | str = str(self.settings.splunk_ca_file) if self.settings.splunk_ca_file else True
        with httpx.Client(verify=verify, timeout=httpx.Timeout(30)) as client:
            response = client.post(
                self.settings.splunk_hec_url,
                headers={"Authorization": f"Splunk {token}"},
                json={"event": event, "sourcetype": sourcetype},
            )
            response.raise_for_status()
