"""Application log API backed by SQLite."""

import time

from flask import Blueprint, jsonify, request

from services.application import ensure_storage
from services.log_service import (
    clear_logs,
    logs_metadata,
    prune_old_logs,
    query_logs,
    set_log_auto_cleanup,
)

bp = Blueprint("routes_logs", __name__)
_last_cleanup_at = 0.0


def _positive_int(name: str, default: int, maximum: int) -> int:
    try:
        return max(1, min(int(request.args.get(name) or default), maximum))
    except (TypeError, ValueError):
        return default


@bp.get("/api/logs")
def api_logs():
    ensure_storage()
    global _last_cleanup_at
    metadata = logs_metadata()
    auto_cleanup = bool(metadata["auto_cleanup"])
    if auto_cleanup and time.time() - _last_cleanup_at >= 60:
        prune_old_logs()
        _last_cleanup_at = time.time()
        metadata = logs_metadata()

    signature = str(metadata["signature"])
    requested_signature = str(request.args.get("signature") or "")
    if requested_signature and requested_signature == signature:
        return jsonify(
            {
                "not_modified": True,
                "logs_signature": signature,
                "logs_total": int(signature.rsplit(":", 1)[-1]),
                "auto_cleanup": auto_cleanup,
            }
        )

    try:
        after_id = max(0, int(request.args.get("after_id") or 0))
    except (TypeError, ValueError):
        after_id = 0
    if requested_signature:
        try:
            requested_last_id, requested_total = (
                int(part) for part in requested_signature.rsplit(":", 1)
            )
            current_last_id, current_total = (
                int(part) for part in signature.rsplit(":", 1)
            )
            if current_last_id < after_id or (
                current_last_id == requested_last_id
                and current_total != requested_total
            ):
                after_id = 0
        except (TypeError, ValueError):
            after_id = 0
    payload = query_logs(
        page=_positive_int("page", 1, 100_000),
        limit=_positive_int("limit", 200, 1000),
        after_id=after_id,
        total=int(metadata["total"]),
        last_id=int(metadata["last_id"]),
    )
    payload["auto_cleanup"] = auto_cleanup
    return jsonify(payload)


@bp.delete("/api/logs")
def api_clear_logs():
    ensure_storage()
    clear_logs()
    return jsonify({"ok": True})


@bp.post("/api/logs/settings")
def api_logs_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    return jsonify({"auto_cleanup": set_log_auto_cleanup(bool(payload.get("auto_cleanup")))})
