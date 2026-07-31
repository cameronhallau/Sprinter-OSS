from __future__ import annotations

import argparse
import hashlib
import os
import sqlite3
from pathlib import Path

from sprinter.config import Settings


def backup_database(source: Path, destination: Path) -> str:
    if destination.exists():
        raise FileExistsError(f"refusing to replace existing backup: {destination}")
    destination.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    with sqlite3.connect(source) as source_db, sqlite3.connect(destination) as backup_db:
        source_db.backup(backup_db)
        result = backup_db.execute("pragma integrity_check").fetchone()
        if not result or result[0] != "ok":
            raise RuntimeError("backup failed SQLite integrity check")
        revision = backup_db.execute("select version_num from alembic_version").fetchone()
        if not revision:
            raise RuntimeError("backup is not a Sprinter v1 database")
    os.chmod(destination, 0o600)
    digest = hashlib.sha256(destination.read_bytes()).hexdigest()
    checksum = destination.with_suffix(destination.suffix + ".sha256")
    checksum.write_text(f"{digest}  {destination.name}\n", encoding="ascii")
    os.chmod(checksum, 0o600)
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description="Create a verified online Sprinter SQLite backup")
    parser.add_argument("destination", type=Path)
    args = parser.parse_args()
    backup_database(Settings().database_path, args.destination)


if __name__ == "__main__":
    main()
