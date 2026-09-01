"""Flask request lifecycle and one-time application bootstrap."""

import threading
import traceback
from typing import Optional

from flask import Response, g, jsonify, request, session
from sqlalchemy import select, text
from werkzeug.exceptions import HTTPException
from werkzeug.security import generate_password_hash

from config import ATTRIBUTE_ASSISTANT_DIR, EXPORT_DIR, FEED_DIR, FILE_IMPORT_DIR, PRICE_CONVERTER_DIR, PROJECT_PROFILE_DIR, SCRAPE_CHECKPOINT_DIR, env_str
from database.session import SessionLocal, init_db, session_scope
from models import User


def log_unhandled_exception(error: Exception):
    if isinstance(error, HTTPException):
        return jsonify({"error": error.description}), error.code or 500
    message = (
        f"{request.method} {request.path}\n"
        + "".join(traceback.format_exception(type(error), error, error.__traceback__))
    )
    try:
        from services.log_service import append_log

        append_log(
            {
                "project_id": "flask",
                "project_name": "Flask",
                "level": "error",
                "message": message,
            }
        )
    except Exception:
        # Logging must never replace the original API error with Flask's HTML 500 page.
        print(message, flush=True)
    return jsonify({"error": "Внутренняя ошибка сервера"}), 500


def open_request_db_session() -> None:
    g.db = SessionLocal()


def ensure_default_user() -> None:
    with session_scope() as db_session:
        if db_session.scalar(select(User.id).limit(1)):
            return
        db_session.add(
            User(
                username=env_str("AUTH_DEFAULT_USERNAME", "admin"),
                password_hash=generate_password_hash(env_str("AUTH_DEFAULT_PASSWORD", "admin")),
                is_active=True,
            )
        )


def run_data_migrations() -> None:
    """Apply idempotent data migrations outside request handlers."""

    migration_name = "20260901_attribute_url_current_values_v1"
    with session_scope() as db_session:
        applied = db_session.scalar(
            text("SELECT name FROM app_data_migrations WHERE name = :name"),
            {"name": migration_name},
        )
        if applied:
            return
        from services.attribute_assistant import backfill_cached_site_current_values

        changed = backfill_cached_site_current_values(db_session)
        db_session.execute(
            text(
                "INSERT INTO app_data_migrations (name, details, applied_at) "
                "VALUES (:name, json(:details), CURRENT_TIMESTAMP)"
            ),
            {
                "name": migration_name,
                "details": f'{{"changed":{int(changed)}}}',
            },
        )


def is_public_endpoint() -> bool:
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    return endpoint in {"healthcheck", "api_auth_session", "api_auth_login", "api_auth_logout"}


def require_login() -> Optional[Response]:
    if is_public_endpoint() or session.get("user_id"):
        return None
    return jsonify({"error": "Требуется авторизация"}), 401


def close_request_db_session(error: Optional[BaseException] = None) -> None:
    db = g.pop("db", None)
    if db is None:
        return
    try:
        # A registered Flask error handler turns an exception into a response,
        # so teardown may receive error=None even after a failed SQL flush.
        if error is None and db.is_active:
            db.commit()
        else:
            db.rollback()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


_storage_init_lock = threading.RLock()
_storage_initialized = False


def ensure_storage() -> None:
    global _storage_initialized
    if _storage_initialized:
        return
    with _storage_init_lock:
        if _storage_initialized:
            return
        from runtime.news_tasks import start_news_scheduler
        from services.feeds import recover_interrupted_feed_comparison
        from services.file_import_service import recover_interrupted_file_import_scan
        from services.price_converter_service import recover_interrupted_price_conversion
        from services.news import load_news_settings
        from services.projects import load_projects

        EXPORT_DIR.mkdir(exist_ok=True)
        FEED_DIR.mkdir(exist_ok=True)
        FILE_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        PRICE_CONVERTER_DIR.mkdir(parents=True, exist_ok=True)
        ATTRIBUTE_ASSISTANT_DIR.mkdir(parents=True, exist_ok=True)
        SCRAPE_CHECKPOINT_DIR.mkdir(parents=True, exist_ok=True)
        PROJECT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        init_db()
        ensure_default_user()
        run_data_migrations()
        recover_interrupted_file_import_scan()
        recover_interrupted_price_conversion()
        recover_interrupted_feed_comparison()
        load_projects()
        load_news_settings()
        start_news_scheduler()
        _storage_initialized = True
