"""HTTP routes for this application area."""

from flask import Blueprint

from flask import g, request, session
from models import User
from services.application import ensure_storage
from services.normalization import jsonify
from sqlalchemy import select
from werkzeug.security import check_password_hash

bp = Blueprint("routes_auth", __name__)


@bp.get("/api/health")
def healthcheck():
    ensure_storage()
    return jsonify({"ok": True})


@bp.get("/api/auth/session")
def api_auth_session():
    ensure_storage()
    return jsonify(
        {
            "authenticated": bool(session.get("user_id")),
            "username": str(session.get("username") or ""),
        }
    )


@bp.post("/api/auth/login")
def api_auth_login():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    username = str(payload.get("username") or "").strip()
    password = str(payload.get("password") or "")
    user = g.db.scalar(select(User).where(User.username == username, User.is_active.is_(True)))
    if not user or not check_password_hash(user.password_hash, password):
        return jsonify({"error": "Неверный логин или пароль"}), 401
    session.clear()
    session["user_id"] = int(user.id)
    session["username"] = user.username
    return jsonify({"authenticated": True, "username": user.username})


@bp.post("/api/auth/logout")
def api_auth_logout():
    session.clear()
    return jsonify({"ok": True})


