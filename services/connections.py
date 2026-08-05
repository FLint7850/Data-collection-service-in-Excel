"""Connection-method catalog and lookup helpers."""

import time
from typing import Dict, Iterable, List, Optional, Set

from sqlalchemy import select

from config import CONNECTION_METHOD_CACHE_SECONDS, DEBUG_VISIBLE_METHODS, STATIC_BROWSER_RENDER_METHODS
from database.session import session_scope
from models import ConnectionMethod, Donor
from runtime.state import connection_method_cache, connection_method_cache_lock
from services.normalization import parse_db_int

def load_connection_methods(force_refresh: bool = False) -> List[Dict[str, object]]:
    """Возвращает способы подключения из БД в порядке их id."""
    from services.log_service import append_unified_log
    now = time.time()
    with connection_method_cache_lock:
        cached_methods = list(connection_method_cache.get("methods") or [])
        loaded_at = float(connection_method_cache.get("loaded_at") or 0.0)
        if cached_methods and not force_refresh and now - loaded_at < CONNECTION_METHOD_CACHE_SECONDS:
            return cached_methods

    methods: List[Dict[str, object]] = []
    try:
        with session_scope() as session:
            rows = session.execute(select(ConnectionMethod).order_by(ConnectionMethod.id)).scalars().all()
        seen_codes: Set[str] = set()
        for row in rows:
            code = str(row.code or "").strip()
            if not code or code in seen_codes:
                continue
            seen_codes.add(code)
            methods.append({
                "id": int(row.id),
                "code": code,
                "name": str(row.name or row.code or "").strip(),
                "is_browser_render": bool(row.is_browser_render),
                "is_debug_visible": bool(row.is_debug_visible),
            })
    except Exception as error:
        # This lookup can run before the database bootstrap (for example while
        # importing isolated modules in a clean build environment).  Failure to
        # persist the warning must not hide the original recoverable lookup
        # failure or prevent the built-in Requests fallback below.
        try:
            append_unified_log({
                "project_id": "system",
                "project_name": "system",
                "level": "warning",
                "message": f"Не удалось прочитать способы подключения из БД: {error}",
            })
        except Exception:
            pass

    if not methods:
        methods = [{
            "id": 0,
            "code": "requests",
            "name": "Requests",
            "is_browser_render": False,
            "is_debug_visible": False,
        }]

    with connection_method_cache_lock:
        connection_method_cache["methods"] = list(methods)
        connection_method_cache["loaded_at"] = now
    return methods


def get_connection_method_codes(force_refresh: bool = False) -> List[str]:
    return [str(method["code"]) for method in load_connection_methods(force_refresh)]


def public_connection_methods() -> List[Dict[str, object]]:
    return [
        {
            "id": method["id"],
            "code": method["code"],
            "name": method["name"],
        }
        for method in load_connection_methods()
    ]


def connection_method_has_flag(method: str, flag_name: str) -> bool:
    for row in load_connection_methods():
        if row["code"] == method:
            return bool(row.get(flag_name))
    return False


def is_browser_render_method(method: str) -> bool:
    method = str(method or "").strip()
    return method in STATIC_BROWSER_RENDER_METHODS or connection_method_has_flag(method, "is_browser_render")


def is_debug_visible_method(method: str) -> bool:
    method = str(method or "").strip()
    return method in DEBUG_VISIBLE_METHODS or connection_method_has_flag(method, "is_debug_visible")


def ordered_db_connection_methods(
    preferred: Optional[Iterable[str]] = None,
) -> List[str]:
    """Строит fallback-цепочку только из методов, которые есть в БД."""
    db_codes = get_connection_method_codes()
    ordered: List[str] = []

    if preferred:
        for method in preferred:
            if method in db_codes and method not in ordered:
                ordered.append(method)

    for method in db_codes:
        if method not in ordered:
            ordered.append(method)
    return ordered


def normalize_connection_method(value: object) -> str:
    method = str(value or "requests").strip()
    codes = get_connection_method_codes()
    if method in codes:
        return method
    return codes[0] if codes else "requests"

def get_donor_row(session, public_id: object) -> Optional[Donor]:
    db_id = parse_db_int(public_id)
    if db_id is not None:
        row = session.get(Donor, db_id)
        if row is not None:
            return row
    legacy_id = str(public_id or "").strip()
    if not legacy_id:
        return None
    return session.scalar(select(Donor).where(Donor.legacy_id == legacy_id))


def connection_method_id_for(_session, code: object) -> Optional[int]:
    method = normalize_connection_method(code)
    for row in load_connection_methods():
        if row.get("code") == method:
            method_id = parse_db_int(row.get("id"))
            return method_id if method_id and method_id > 0 else None
    return None
