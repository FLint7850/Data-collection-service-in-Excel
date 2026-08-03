"""Cursor-based progress polling endpoint."""

from flask import Blueprint, jsonify, request

from services.application import ensure_storage
from services.news import get_news_monitor, public_news_brand_monitors
from services.progress_service import progress_payload
from services.projects import get_project, public_project

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
    detail_project_id = str(request.args.get("project_detail") or "")
    if include_projects and detail_project_id:
        detail_project = get_project(detail_project_id)
        payload["project_detail"] = (
            public_project(detail_project) if detail_project else None
        )
    detail_monitor_id = str(request.args.get("news_detail") or "")
    if include_news and detail_monitor_id:
        detail_monitor = get_news_monitor(detail_monitor_id)
        payload["news_details"] = (
            public_news_brand_monitors(detail_monitor) if detail_monitor else []
        )
    return jsonify(payload)
