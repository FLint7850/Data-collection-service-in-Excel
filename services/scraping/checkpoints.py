"""Durable crawler checkpoints used by project and news resume flows."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Dict, Optional

from config import SCRAPE_CHECKPOINT_DIR
from services.normalization import safe_filename


CHECKPOINT_VERSION = 1


def scrape_checkpoint_path(kind: str, item_id: object) -> Path:
    safe_kind = "news" if str(kind) == "news" else "projects"
    safe_id = safe_filename(str(item_id or "item"))
    return SCRAPE_CHECKPOINT_DIR / safe_kind / f"{safe_id}.json"


def save_scrape_checkpoint(kind: str, item_id: object, payload: Dict[str, object]) -> Path:
    path = scrape_checkpoint_path(kind, item_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    document = {"version": CHECKPOINT_VERSION, **payload}
    temporary.write_text(
        json.dumps(document, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return path


def load_scrape_checkpoint(kind: str, item_id: object) -> Optional[Dict[str, object]]:
    path = scrape_checkpoint_path(kind, item_id)
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, TypeError):
        return None
    if not isinstance(document, dict) or document.get("version") != CHECKPOINT_VERSION:
        return None
    return document


def delete_scrape_checkpoint(kind: str, item_id: object) -> None:
    path = scrape_checkpoint_path(kind, item_id)
    try:
        path.unlink(missing_ok=True)
    except OSError:
        pass
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        temporary.unlink(missing_ok=True)
    except OSError:
        pass
