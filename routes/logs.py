"""HTTP routes for this application area."""

from flask import Blueprint

from services.core_service import (
    ensure_storage,
    jsonify,
    news_lock,
    news_settings,
    projects,
    projects_lock,
    request,
    time,
)
from services.log_service import (
    clear_runtime_log_files,
    combined_log_entries,
    get_log_auto_cleanup,
    is_recent_log_entry,
    logs_signature,
    prune_old_log_files,
    read_logs_file,
    set_log_auto_cleanup,
    write_logs_file,
)
from services.news_service import save_news_settings

bp = Blueprint("routes_logs", __name__)

_last_cleanup_at = 0.0


@bp.get("/api/logs")
def api_logs():
    ensure_storage()
    global _last_cleanup_at
    auto_cleanup = get_log_auto_cleanup()
    cleanup_due = auto_cleanup and time.time() - _last_cleanup_at >= 60
    requested_signature = str(request.args.get("signature") or "")
    try:
        requested_total = max(0, int(request.args.get("since_total") or 0))
    except (TypeError, ValueError):
        requested_total = 0
    current_logs_signature = logs_signature()
    if (
        requested_signature
        and requested_signature == current_logs_signature
        and not cleanup_due
    ):
        return jsonify(
            {
                "not_modified": True,
                "logs_signature": current_logs_signature,
                "logs_total": requested_total,
                "auto_cleanup": auto_cleanup,
            }
        )

    json_logs = read_logs_file()
    if cleanup_due:
        cutoff = time.time() - 7 * 24 * 60 * 60
        filtered_logs = [
            item
            for item in json_logs
            if is_recent_log_entry(item, cutoff)
        ]
        if len(filtered_logs) != len(json_logs):
            json_logs = filtered_logs
            write_logs_file(json_logs)
        prune_old_log_files(cutoff)
        with projects_lock:
            for project in projects.values():
                logs = project.get("logs", [])
                project["logs"] = [
                    item
                    for item in logs
                    if is_recent_log_entry(item, cutoff)
                ]
        with news_lock:
            logs = news_settings.get("logs", [])
            news_settings["logs"] = [
                item
                for item in logs
                if is_recent_log_entry(item, cutoff)
            ]
        _last_cleanup_at = time.time()

    all_logs = combined_log_entries()
    all_logs.sort(key=lambda item: item.get("time", ""))
    try:
        limit = max(1, min(int(request.args.get("limit") or 200), 1000))
    except (TypeError, ValueError):
        limit = 200
    try:
        page = max(1, int(request.args.get("page") or 1))
    except (TypeError, ValueError):
        page = 1
    total = len(all_logs)
    current_logs_signature = logs_signature()
    end = max(0, total - (page - 1) * limit)
    start = max(0, end - limit)
    page_logs = all_logs[start:end]
    delta = False
    if page == 1 and requested_signature:
        try:
            since_total = int(request.args.get("since_total") or -1)
        except (TypeError, ValueError):
            since_total = -1
        added_count = total - since_total
        if since_total >= 0 and 0 < added_count <= limit:
            page_logs = all_logs[since_total:total]
            delta = True
    return jsonify(
        {
            "logs": page_logs,
            "logs_total": total,
            "logs_page": page,
            "logs_limit": limit,
            "auto_cleanup": auto_cleanup,
            "logs_signature": current_logs_signature,
            "delta": delta,
        }
    )


@bp.delete("/api/logs")
def api_clear_logs():
    ensure_storage()
    with projects_lock:
        for project in projects.values():
            project["logs"] = []
    with news_lock:
        news_settings["logs"] = []
        save_news_settings()
    clear_runtime_log_files()
    return jsonify({"ok": True})


@bp.post("/api/logs/settings")
def api_logs_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    auto_cleanup = set_log_auto_cleanup(bool(payload.get("auto_cleanup")))
    with news_lock:
        news_settings["auto_cleanup"] = auto_cleanup
    return jsonify({"auto_cleanup": auto_cleanup})


