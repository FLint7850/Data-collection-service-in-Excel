"""Cursor-based progress polling endpoint."""

from flask import Blueprint, jsonify, request

from services.application import ensure_storage
from services.progress_service import progress_payload

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
    return jsonify(payload)
