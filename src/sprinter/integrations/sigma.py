from __future__ import annotations

from typing import Any

import yaml
from sigma.backends.splunk import SplunkBackend  # type: ignore[attr-defined]
from sigma.collection import SigmaCollection


class SigmaConverter:
    def convert(self, rule: dict[str, Any]) -> dict[str, Any]:
        collection = SigmaCollection.from_yaml(yaml.safe_dump(rule, sort_keys=False))
        queries = SplunkBackend().convert(collection)
        return {"queries": queries, "count": len(queries)}
