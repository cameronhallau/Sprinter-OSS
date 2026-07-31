#!/usr/bin/env python3
from __future__ import annotations

import getpass
import hashlib
import sys


def main() -> int:
    token = getpass.getpass("API token: ")
    if len(token) < 24:
        print("token must contain at least 24 characters", file=sys.stderr)
        return 2
    print(hashlib.sha256(token.encode("utf-8")).hexdigest())
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
