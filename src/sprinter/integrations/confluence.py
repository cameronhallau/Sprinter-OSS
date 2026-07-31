from __future__ import annotations

from typing import Any

import httpx

from sprinter.config import Settings


class ConfluenceClient:
    def __init__(self, settings: Settings):
        self.settings = settings

    @property
    def configured(self) -> bool:
        return bool(self.settings.confluence_base_url)

    def search(self, query: str, limit: int = 10) -> dict[str, Any]:
        if not self.configured:
            raise RuntimeError("Confluence is not configured")
        escaped = query.replace('"', '\\"')
        clauses = [f'text ~ "{escaped}"']
        spaces = self.settings.allowed_confluence_spaces
        if spaces:
            clauses.append("space in (" + ",".join(f'"{space}"' for space in sorted(spaces)) + ")")
        cql = " and ".join(clauses)
        with httpx.Client(
            timeout=httpx.Timeout(30),
            verify=True,
            auth=(self.settings.confluence_email, self.settings.secret_value("confluence")),
        ) as client:
            response = client.get(
                f"{self.settings.confluence_base_url.rstrip('/')}/rest/api/content/search",
                params={"cql": cql, "limit": limit, "expand": "space,version"},
            )
            response.raise_for_status()
            payload = response.json()
        results = []
        for item in payload.get("results", [])[:limit]:
            webui = (item.get("_links") or {}).get("webui") or ""
            results.append(
                {
                    "id": item.get("id"),
                    "title": item.get("title"),
                    "space": ((item.get("space") or {}).get("key")),
                    "url": f"{self.settings.confluence_base_url.rstrip('/')}{webui}" if webui else "",
                }
            )
        return {"results": results, "count": len(results)}
