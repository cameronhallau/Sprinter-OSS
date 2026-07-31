from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import shutil
import sqlite3
from pathlib import Path

from sprinter.config import Settings


def restore_database(backup: Path, checksum: Path, destination: Path) -> None:
    if destination.exists():
        raise FileExistsError(f"refusing to replace existing database: {destination}")
    expected = checksum.read_text(encoding="ascii").split()[0]
    actual = hashlib.sha256(backup.read_bytes()).hexdigest()
    if not expected or not hmac.compare_digest(expected, actual):
        raise ValueError("backup checksum does not match")
    with sqlite3.connect(backup) as connection:
        integrity = connection.execute("pragma integrity_check").fetchone()
        revision = connection.execute("select version_num from alembic_version").fetchone()
    if not integrity or integrity[0] != "ok":
        raise ValueError("backup failed SQLite integrity check")
    if not revision or revision[0] != "0001_clean_v1":
        raise ValueError("backup is not a supported Sprinter v1 database")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    temporary = destination.with_suffix(destination.suffix + ".restoring")
    shutil.copyfile(backup, temporary)
    os.chmod(temporary, 0o600)
    temporary.replace(destination)


def main() -> None:
    parser = argparse.ArgumentParser(description="Restore a verified Sprinter v1 SQLite backup")
    parser.add_argument("backup", type=Path)
    parser.add_argument("checksum", type=Path)
    args = parser.parse_args()
    restore_database(args.backup, args.checksum, Settings().database_path)


if __name__ == "__main__":
    main()
