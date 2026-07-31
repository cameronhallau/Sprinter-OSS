#!/usr/bin/env python3

from __future__ import annotations

import argparse
import json
import ssl
import stat
import sys
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener

MAX_SUMMARY_BYTES = 1_048_576
LOCAL_HOSTS = frozenset({"127.0.0.1", "::1", "localhost"})


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self,
        req: Request,
        fp: Any,
        code: int,
        msg: str,
        headers: Any,
        newurl: str,
    ) -> None:
        return None


def private_text_file(path: Path, label: str) -> str:
    if not path.is_file():
        raise ValueError(f"{label} is not a readable file: {path}")
    if stat.S_IMODE(path.stat().st_mode) & 0o077:
        raise ValueError(f"{label} must not be accessible by group or other users: {path}")
    value = path.read_text(encoding="utf-8").strip()
    if len(value) < 24:
        raise ValueError(f"{label} must contain at least 24 characters")
    return value


def load_summary(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise ValueError(f"summary is not a readable file: {path}")
    if path.stat().st_size > MAX_SUMMARY_BYTES:
        raise ValueError(f"summary exceeds {MAX_SUMMARY_BYTES} bytes")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("summary must contain one JSON object")
    return payload


def endpoint(base_url: str) -> str:
    parsed = urlparse(base_url)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError("Sprinter URL must be an absolute HTTP(S) URL")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise ValueError("Sprinter URL must not contain credentials, a query, or a fragment")
    if parsed.scheme != "https" and parsed.hostname not in LOCAL_HOSTS:
        raise ValueError("Sprinter URL must use HTTPS except for a local loopback address")
    return f"{base_url.rstrip('/')}/api/v1/review-jobs"


def build_payload(summary: dict[str, Any], run_id: str | None = None) -> tuple[dict[str, Any], str]:
    selected_run_id = run_id or summary.get("run_id")
    if not isinstance(selected_run_id, str) or not selected_run_id.strip():
        raise ValueError("run_id must be supplied or present in the summary")
    selected_run_id = selected_run_id.strip()
    if len(selected_run_id) > 96:
        raise ValueError("run_id must not exceed 96 characters")
    workflow = summary.get("workflow", "stix_ingest")
    if not isinstance(workflow, str) or not workflow.strip():
        raise ValueError("workflow must be a non-empty string")
    if len(workflow.strip()) > 128:
        raise ValueError("workflow must not exceed 128 characters")
    payload = {
        "selector": {"type": "run", "run_id": selected_run_id, "workflow": workflow.strip()},
        "source": "seer-stix-runner",
        "summary": summary,
        "limit": 20,
    }
    return payload, selected_run_id


def submit(
    *,
    base_url: str,
    token: str,
    payload: dict[str, Any],
    idempotency_key: str,
    ca_file: Path | None = None,
    opener: Any = None,
) -> dict[str, Any]:
    body = json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")
    request = Request(  # noqa: S310 - endpoint() permits only HTTPS or loopback HTTP.
        endpoint(base_url),
        data=body,
        method="POST",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "Idempotency-Key": idempotency_key,
        },
    )
    if opener is None:
        context = ssl.create_default_context(cafile=str(ca_file) if ca_file else None)
        opener = build_opener(NoRedirect(), HTTPSHandler(context=context))
    with opener.open(request, timeout=30) as response:
        if response.status != 202:
            raise RuntimeError(f"Sprinter returned unexpected HTTP {response.status}")
        result = json.loads(response.read())
    if not isinstance(result, dict):
        raise RuntimeError("Sprinter returned a non-object response")
    return result


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Submit one completed Seer STIX run to Sprinter.")
    parser.add_argument("--sprinter-url", required=True)
    parser.add_argument("--token-file", type=Path, required=True)
    parser.add_argument("--summary-file", type=Path, required=True)
    parser.add_argument("--run-id")
    parser.add_argument("--idempotency-key")
    parser.add_argument("--ca-file", type=Path)
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        token = private_text_file(args.token_file, "token file")
        summary = load_summary(args.summary_file)
        payload, run_id = build_payload(summary, args.run_id)
        key = args.idempotency_key or f"seer:osint-bot:{run_id}"
        result = submit(
            base_url=args.sprinter_url,
            token=token,
            payload=payload,
            idempotency_key=key,
            ca_file=args.ca_file,
        )
    except (ValueError, RuntimeError, HTTPError, URLError, json.JSONDecodeError) as exc:
        print(f"submission failed: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
