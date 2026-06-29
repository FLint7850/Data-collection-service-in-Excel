from __future__ import annotations

import os
import sqlite3
from datetime import datetime
from pathlib import Path

base_dir = Path(__file__).resolve().parent.parent
db_path = Path(os.environ.get("DATABASE_PATH", base_dir / "data" / "app.db"))
if not db_path.is_absolute():
    db_path = base_dir / db_path

backup_dir = base_dir / "backups"
backup_dir.mkdir(exist_ok=True)
backup_path = backup_dir / f"app_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"

if not db_path.exists():
    raise SystemExit(f"DB not found: {db_path}")

source = sqlite3.connect(db_path)
target = sqlite3.connect(backup_path)
try:
    source.backup(target)
finally:
    target.close()
    source.close()

print(backup_path)
