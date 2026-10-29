#!/usr/bin/env python3
"""SQLite database backup with rotation.

Uses Python's sqlite3.backup() for online-safe backups (no locking issues
even while the bot is actively writing). Keeps a configurable number of
daily backups and removes older ones.

Usage:
    python3 deploy/backup_db.py                     # backs up all .db files in data/
    python3 deploy/backup_db.py data/mainnet.db     # backs up specific file
"""

import shutil
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent.parent
DATA_DIR = PROJECT_DIR / "data"
BACKUP_DIR = DATA_DIR / "backups"
MAX_BACKUPS = 7


def backup_database(db_path: Path) -> Path:
    """Create a safe online backup of a SQLite database.

    Uses sqlite3.backup() which handles WAL mode and concurrent writers
    correctly, unlike a simple file copy.

    Returns:
        Path to the backup file.
    """
    if not db_path.exists():
        raise FileNotFoundError(f"Database not found: {db_path}")

    timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    backup_name = f"{db_path.stem}_{timestamp}.db"
    backup_path = BACKUP_DIR / backup_name

    BACKUP_DIR.mkdir(parents=True, exist_ok=True)

    source = sqlite3.connect(str(db_path))
    dest = sqlite3.connect(str(backup_path))
    try:
        source.backup(dest)
    finally:
        dest.close()
        source.close()

    size_kb = backup_path.stat().st_size / 1024
    print(f"  Backed up {db_path.name} -> {backup_name} ({size_kb:.0f} KB)")
    return backup_path


def rotate_backups(db_stem: str) -> None:
    """Remove old backups beyond MAX_BACKUPS for a given database."""
    if not BACKUP_DIR.exists():
        return

    backups = sorted(
        BACKUP_DIR.glob(f"{db_stem}_*.db"),
        key=lambda p: p.stat().st_mtime,
        reverse=True,
    )

    for old in backups[MAX_BACKUPS:]:
        old.unlink()
        print(f"  Removed old backup: {old.name}")


def main() -> None:
    if len(sys.argv) > 1:
        db_files = [Path(sys.argv[1]).resolve()]
    else:
        db_files = sorted(DATA_DIR.glob("*.db"))

    if not db_files:
        print("No databases found to back up.")
        return

    print(f"Backing up {len(db_files)} database(s) to {BACKUP_DIR}/")
    for db_path in db_files:
        try:
            backup_database(db_path)
            rotate_backups(db_path.stem)
        except Exception as e:
            print(f"  ERROR backing up {db_path.name}: {e}", file=sys.stderr)

    # Show backup disk usage
    if BACKUP_DIR.exists():
        total = sum(f.stat().st_size for f in BACKUP_DIR.glob("*.db"))
        print(f"Total backup size: {total / 1024:.0f} KB")


if __name__ == "__main__":
    main()
