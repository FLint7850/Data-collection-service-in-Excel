"""Cursor-based progress polling endpoint."""

from flask import Blueprint, jsonify, request

from services.application import ensure_storage
from services.news import get_news_monitor
from services.progress_service import progress_payload, public_news_monitor_progress

bp = Blueprint("routes_progress", __name__)


@bp.get("/progress")
def progress_poll():
    ensure_storage()
    include_projects = request.args.get("projects", "1") == "1"
    include_news = request.args.get("news") == "1"
    payload = progress_payload(
        include_projects,
        include_news,
        str(request.args.get("cursor") or ""),
    )
    detail_monitor_id = str(request.args.get("news_detail") or "")
    if include_news and detail_monitor_id:
        detail_monitor = get_news_monitor(detail_monitor_id)
        if detail_monitor:
            detail_progress = public_news_monitor_progress(detail_monitor)
            state_changes = [
                item
                for item in payload.get("news", [])
                if str(item.get("id")) != detail_monitor_id
            ]
            state_changes.append(detail_progress)
            payload["news"] = state_changes
    return jsonify(payload)
