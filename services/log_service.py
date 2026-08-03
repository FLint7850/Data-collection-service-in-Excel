"""Indexed SQLite-backed application log storage."""

from datetime import datetime, timedelta
from typing import Dict, Optional

from sqlalchemy import delete, func, select

from database.session import session_scope
from models import AppSetting, ApplicationLog
from services.normalization import repair_mojibake, repair_mojibake_text


LOG_LEVELS = {"info", "success", "warning", "error"}


def _normalized_level(value: object) -> str:
    level = str(value or "info").strip().lower()
    return level if level in LOG_LEVELS else "info"


def _public_log(row: ApplicationLog) -> Dict[str, object]:
    return repair_mojibake(
        {
            "id": row.id,
            "time": row.created_at.isoformat(timespec="seconds"),
            "level": row.level,
            "message": row.message,
            "project_id": row.project_id or "",
            "project_name": row.project_name or "",
            "brand": row.brand or "",
            "group": row.group_name or "",
        }
    )


def append_log(item: Dict[str, object]) -> int:
    """Persist one event without rewriting any existing log data."""
    with session_scope() as db_session:
        row = ApplicationLog(
            created_at=_parse_log_time(item.get("time")),
            level=_normalized_level(item.get("level")),
            message=repair_mojibake_text(item.get("message") or ""),
            project_id=str(item.get("project_id") or "")[:64],
            project_name=repair_mojibake_text(item.get("project_name") or "")[:255],
            brand=repair_mojibake_text(item.get("brand") or "")[:255],
            group_name=repair_mojibake_text(item.get("group") or "")[:255],
        )
        db_session.add(row)
        db_session.flush()
        return int(row.id)


def _parse_log_time(value: object) -> datetime:
    try:
        return datetime.fromisoformat(str(value or ""))
    except (TypeError, ValueError):
        return datetime.now()


def append_unified_log(item: Dict[str, object]) -> None:
    """Compatibility name used by scanners; storage is SQLite only."""
    append_log(item)


def fetch_debug_log(message: str, level: str = "info") -> None:
    append_log(
        {
            "project_id": "fetch-debug",
            "project_name": "fetch-debug",
            "level": level,
            "message": message,
        }
    )


def log_fetch_result(method: str, url: str, html: Optional[str], elapsed: float = 0.0, extra: str = "") -> None:
    html_text = html or ""
    suffix = f"; {extra}" if extra else ""
    fetch_debug_log(
        f"method={method}; url={url}; html_len={len(html_text)}; elapsed={elapsed:.2f}s{suffix}",
        "info" if html_text else "warning",
    )


def log_fetch_exception(method: str, url: str, error: BaseException) -> None:
    fetch_debug_log(f"method={method}; url={url}; error={type(error).__name__}: {error}", "warning")


def get_log_auto_cleanup() -> bool:
    with session_scope() as db_session:
        app_setting = db_session.get(AppSetting, 1)
        return bool(app_setting.auto_cleanup) if app_setting else False


def set_log_auto_cleanup(value: bool) -> bool:
    auto_cleanup = bool(value)
    with session_scope() as db_session:
        app_setting = db_session.get(AppSetting, 1)
        if app_setting is None:
            app_setting = AppSetting(id=1)
            db_session.add(app_setting)
        app_setting.auto_cleanup = auto_cleanup
    return auto_cleanup


def prune_old_logs(days: int = 7) -> int:
    cutoff = datetime.now() - timedelta(days=max(1, days))
    with session_scope() as db_session:
        result = db_session.execute(delete(ApplicationLog).where(ApplicationLog.created_at < cutoff))
        return int(result.rowcount or 0)


def clear_logs() -> None:
    with session_scope() as db_session:
        db_session.execute(delete(ApplicationLog))


def logs_signature() -> str:
    with session_scope() as db_session:
        last_id = db_session.scalar(select(func.max(ApplicationLog.id))) or 0
        total = db_session.scalar(select(func.count(ApplicationLog.id))) or 0
        return f"{int(last_id)}:{int(total)}"


def query_logs(
    *,
    page: int = 1,
    limit: int = 200,
    after_id: int = 0,
) -> Dict[str, object]:
    page = max(1, page)
    limit = max(1, min(limit, 1000))
    with session_scope() as db_session:
        total = int(db_session.scalar(select(func.count(ApplicationLog.id))) or 0)
        last_id = int(db_session.scalar(select(func.max(ApplicationLog.id))) or 0)
        counts = {
            str(level): int(count)
            for level, count in db_session.execute(
                select(ApplicationLog.level, func.count(ApplicationLog.id)).group_by(ApplicationLog.level)
            ).all()
        }
        delta = after_id > 0 and total > 0 and after_id <= last_id
        if delta:
            rows = list(
                db_session.scalars(
                    select(ApplicationLog)
                    .where(ApplicationLog.id > after_id)
                    .order_by(ApplicationLog.id.asc())
                    .limit(limit)
                )
            )
        else:
            newest = list(
                db_session.scalars(
                    select(ApplicationLog)
                    .order_by(ApplicationLog.id.desc())
                    .offset((page - 1) * limit)
                    .limit(limit)
                )
            )
            rows = list(reversed(newest))
        return {
            "logs": [_public_log(row) for row in rows],
            "logs_total": total,
            "logs_page": page,
            "logs_limit": limit,
            "logs_signature": f"{last_id}:{total}",
            "logs_last_id": last_id,
            "logs_counts": counts,
            "delta": delta,
        }
