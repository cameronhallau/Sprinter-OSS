#!/usr/bin/env python3
from __future__ import annotations

import getpass
import hashlib
import os
import sys


def main() -> int:
    token = getpass.getpass("API token: ")
    if len(token) < 24:
        print("token must contain at least 24 characters", file=sys.stderr)
        return 2
    salt = os.urandom(16)
    digest = hashlib.scrypt(
        token.encode("utf-8"),
        salt=salt,
        n=2**14,
        r=8,
        p=1,
        dklen=32,
    )
    print(f"scrypt_16384_8_1_{salt.hex()}_{digest.hex()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
