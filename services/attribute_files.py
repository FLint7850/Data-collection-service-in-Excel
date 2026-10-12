"""Transaction-aware filesystem changes for Attribute Assistant."""

from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.orm import Session


_WRITES_KEY = "attribute_assistant_pending_writes"
_DELETES_KEY = "attribute_assistant_pending_deletes"
_PROMOTED_KEY = "attribute_assistant_promoted_writes"


def staged_path(db: Session, destination: Path) -> Path:
    """Return a temporary path promoted to destination only on commit."""

    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.tmp")
    db.info.setdefault(_WRITES_KEY, []).append((temporary, destination))
    return temporary


def stage_bytes(db: Session, destination: Path, data: bytes) -> Path:
    temporary = staged_path(db, destination)
    temporary.write_bytes(data)
    return destination.resolve()


def stage_text(
    db: Session,
    destination: Path,
    data: str,
    *,
    encoding: str = "utf-8",
) -> Path:
    temporary = staged_path(db, destination)
    temporary.write_text(data, encoding=encoding)
    return destination.resolve()


def delete_after_commit(
    db: Session,
    path: Path | str,
    *,
    root: Path | None = None,
) -> None:
    resolved = Path(path).resolve()
    if root is not None:
        resolved_root = root.resolve()
        if resolved != resolved_root and resolved_root not in resolved.parents:
            return
    pending = db.info.setdefault(_DELETES_KEY, [])
    if resolved not in pending:
        pending.append(resolved)


def file_ready(db: Session | None, path: Path | str) -> bool:
    resolved = Path(path).resolve()
    if resolved.is_file():
        return True
    return bool(db and any(destination == resolved for _temporary, destination in db.info.get(_WRITES_KEY, [])))


def _remove(path: Path) -> None:
    try:
        if path.is_dir():
            shutil.rmtree(path, ignore_errors=True)
        else:
            path.unlink(missing_ok=True)
    except OSError:
        pass


@event.listens_for(Session, "before_commit")
def _promote_attribute_files(db: Session) -> None:
    promoted = db.info.setdefault(_PROMOTED_KEY, [])
    for temporary, destination in db.info.get(_WRITES_KEY, []):
        if not temporary.is_file():
            raise FileNotFoundError(f"Не подготовлен файл Attribute Assistant: {temporary.name}")
        os.replace(temporary, destination)
        promoted.append(destination)


@event.listens_for(Session, "after_commit")
def _finish_attribute_files(db: Session) -> None:
    for path in db.info.pop(_DELETES_KEY, []):
        _remove(path)
    db.info.pop(_WRITES_KEY, None)
    db.info.pop(_PROMOTED_KEY, None)


@event.listens_for(Session, "after_rollback")
def _rollback_attribute_files(db: Session) -> None:
    for temporary, _destination in db.info.pop(_WRITES_KEY, []):
        _remove(temporary)
    for destination in db.info.pop(_PROMOTED_KEY, []):
        _remove(destination)
    db.info.pop(_DELETES_KEY, None)
