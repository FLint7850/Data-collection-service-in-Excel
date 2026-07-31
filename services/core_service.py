"""Extracted application service module."""

import json


import os


import csv


import hashlib


import html as html_lib


import io


import faulthandler


import re


import shutil


import smtplib


import ssl


import base64


import subprocess


import sys


import threading


import time


import traceback


import uuid


import zipfile


from collections import deque


from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait


from dataclasses import dataclass


from datetime import datetime, time as datetime_time, timedelta, timezone


from email.message import EmailMessage


from fnmatch import fnmatch


from functools import lru_cache


from pathlib import Path


from queue import Empty, Queue


from typing import Any, Callable, Deque, Dict, Hashable, Iterable, List, Optional, Set


from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse


import xml.etree.ElementTree as ET


import requests


from bs4 import BeautifulSoup


from flask import Flask, Response, g, jsonify as flask_jsonify, request, send_file, session


from sqlalchemy import delete, select


from sqlalchemy.exc import OperationalError


from werkzeug.exceptions import HTTPException


from werkzeug.security import check_password_hash, generate_password_hash


from api_dto import news_monitor_dto, news_monitor_state_dto


from db import SessionLocal, init_db, session_scope


from models import (
    AppSetting,
    Brand,
    ConnectionMethod,
    Donor,
    FeedComparison,
    FileImport,
    OwnSite,
    Project,
    SupplierFeed,
    User,
)


from progress_tracker import ProgressTracker


from query_utils import normalize_search_text


BASE_DIR = Path(__file__).resolve().parents[1]


def load_local_env() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    try:
        for raw_line in env_path.read_text(encoding="utf-8").splitlines():
            line = raw_line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, value = line.split("=", 1)
            key = key.strip()
            value = value.strip().strip('"').strip("'")
            if key:
                os.environ.setdefault(key, value)
    except OSError:
        return


load_local_env()


os.environ["PYTHON_DOTENV_DISABLED"] = "1"


def env_str(name: str, default: str = "") -> str:
    return str(os.environ.get(name, default) or default).strip()


def env_int(name: str, default: int, minimum: Optional[int] = None, maximum: Optional[int] = None) -> int:
    try:
        value = int(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_float(name: str, default: float, minimum: Optional[float] = None, maximum: Optional[float] = None) -> float:
    try:
        value = float(os.environ.get(name, str(default)) or default)
    except (TypeError, ValueError):
        value = default
    if minimum is not None:
        value = max(minimum, value)
    if maximum is not None:
        value = min(maximum, value)
    return value


def env_list(name: str, default: Iterable[str]) -> List[str]:
    raw_value = os.environ.get(name)
    if raw_value is None:
        return [str(item).strip() for item in default if str(item).strip()]
    return [item.strip() for item in raw_value.replace("\n", ",").split(",") if item.strip()]


def env_path(name: str, default: str) -> Path:
    value = env_str(name, default)
    path = Path(value)
    return path if path.is_absolute() else BASE_DIR / path


@lru_cache(maxsize=2)
def botasaurus_browser_executable(prefer_headless_shell: bool = True) -> Optional[str]:
    """Return a Playwright browser executable, preferring headless shell for headless work."""
    env_executable = os.environ.get("PLAYWRIGHT_BROWSER_EXECUTABLE", "").strip()
    if env_executable and Path(env_executable).is_file():
        return env_executable

    try:
        from playwright.sync_api import sync_playwright

        playwright = sync_playwright().start()
        try:
            executable = Path(playwright.chromium.executable_path)
        finally:
            playwright.stop()
        if prefer_headless_shell:
            browser_root = executable
            for parent in executable.parents:
                if parent.name.startswith("chromium-"):
                    browser_root = parent.parent
                    break
            shell_names = ("headless_shell.exe", "headless_shell")
            for shell_dir in sorted(browser_root.glob("chromium_headless_shell-*"), reverse=True):
                for shell_name in shell_names:
                    matches = list(shell_dir.rglob(shell_name))
                    if matches:
                        return str(matches[0])
        return str(executable) if executable.is_file() else None
    except Exception:
        return None


LOG_DIR = env_path("LOG_DIR", "logs")


FEED_DIR = env_path("FEED_DIR", "feeds")


LOGS_FILE = env_path("LOGS_FILE", str(LOG_DIR / "logs.json"))


UNIFIED_LOG_FILE = env_path("UNIFIED_LOG_FILE", str(LOG_DIR / "app.log"))


EXPORT_DIR = env_path("EXPORT_DIR", "exports")


FILE_IMPORT_DIR = env_path("FILE_IMPORT_DIR", "storage/file-import")


PROJECT_PROFILE_DIR = BASE_DIR / "profiles" / "projects"


DEFAULT_START_URL = env_str("DEFAULT_START_URL", "")


DEFAULT_FEED_URL = env_str("DEFAULT_FEED_URL", "https://mega-kuhnya.ru/price/last_modified.xml")


DEFAULT_FEED_GENERATE_URL = env_str(
    "DEFAULT_FEED_GENERATE_URL",
    "https://mega-kuhnya.ru/index.php?route=extension/feed/unixml/new_product",
)


MSK_TZ = timezone(timedelta(hours=env_int("APP_TIMEZONE_OFFSET_HOURS", 3)))


DEFAULT_EXCLUSIONS = env_list(
    "DEFAULT_EXCLUSIONS",
    [
        "/catalog/rasprodazha/",
        "/catalog/utsenka/",
        "/about/",
        "/contacts/",
    ],
)


REQUEST_TIMEOUT = env_int("REQUEST_TIMEOUT", 20, minimum=1)


CONNECTION_METHOD_TIMEOUT_SECONDS = env_int("CONNECTION_METHOD_TIMEOUT_SECONDS", 60, minimum=1)


REQUEST_DELAY_SECONDS = env_float("REQUEST_DELAY_SECONDS", 0.05, minimum=0.0)


MAX_RETRIES = env_int("MAX_RETRIES", 3, minimum=1)


FEED_WORKER_COUNT = env_int("FEED_WORKER_COUNT", 6, minimum=1, maximum=12)


FEED_SNAPSHOT_CACHE_SECONDS = env_int("FEED_SNAPSHOT_CACHE_SECONDS", 120, minimum=0, maximum=3600)


FEED_SNAPSHOT_RETAIN = env_int("FEED_SNAPSHOT_RETAIN", 3, minimum=2, maximum=10)


NEWS_SCAN_STALL_TIMEOUT = env_int("NEWS_SCAN_STALL_TIMEOUT", 180, minimum=1)


SCHEDULE_DUE_GRACE_SECONDS = env_int("SCHEDULE_DUE_GRACE_SECONDS", 90, minimum=0)


CONNECTION_METHOD_CACHE_SECONDS = env_int("CONNECTION_METHOD_CACHE_SECONDS", 30, minimum=1)


PRICE_RE = re.compile(r"\d[\d\s\u2009\xa0]{1,}(?:\u20bd|\u0440\u0443\u0431\.?)", re.IGNORECASE)


BLOCKED_PAGE_MARKERS = tuple(
    env_list(
        "BLOCKED_PAGE_MARKERS",
        [
            "cloudflare",
            "captcha",
            "access denied",
            "http 403",
            "__qrator",
            "qauth.js",
            "qrator",
            "доступ ограничен",
            "проверяем ваш браузер",
            "enable javascript",
        ],
    )
)


def log_unhandled_exception(error: Exception):
    if isinstance(error, HTTPException):
        return flask_jsonify({"error": error.description}), error.code or 500

    LOG_DIR.mkdir(exist_ok=True)
    with (LOG_DIR / "flask-error.log").open("a", encoding="utf-8") as error_file:
        error_file.write(f"\n[{datetime.now().isoformat(timespec='seconds')}] {request.method} {request.path}\n")
        error_file.write("".join(traceback.format_exception(type(error), error, error.__traceback__)))
    return flask_jsonify({"error": "Внутренняя ошибка сервера"}), 500


def open_request_db_session() -> None:
    g.db = SessionLocal()


def ensure_default_user() -> None:
    with session_scope() as db_session:
        existing_user = db_session.scalar(select(User.id).limit(1))
        if existing_user:
            return
        username = env_str("AUTH_DEFAULT_USERNAME", "admin")
        password = env_str("AUTH_DEFAULT_PASSWORD", "admin")
        db_session.add(
            User(
                username=username,
                password_hash=generate_password_hash(password),
                is_active=True,
            )
        )


def is_public_endpoint() -> bool:
    endpoint = (request.endpoint or "").rsplit(".", 1)[-1]
    return endpoint in {
        "healthcheck",
        "api_auth_session",
        "api_auth_login",
        "api_auth_logout",
    }


def require_login() -> Optional[Response]:
    if is_public_endpoint():
        return None
    if session.get("user_id"):
        return None
    return jsonify({"error": "Требуется авторизация"}), 401


def close_request_db_session(error: Optional[BaseException] = None) -> None:
    db = g.pop("db", None)
    if db is None:
        return
    if error is None:
        db.commit()
    else:
        db.rollback()
    db.close()


state_lock = threading.RLock()


projects_lock = threading.RLock()


news_lock = threading.RLock()


file_import_lock = threading.RLock()


feed_comparison_lock = threading.RLock()


active_stop_event = threading.Event()


active_finish_event = threading.Event()


file_import_stop_event = threading.Event()


feed_comparison_stop_event = threading.Event()


active_run_id = 0


worker_thread: Optional[threading.Thread] = None


file_import_worker_thread: Optional[threading.Thread] = None


feed_comparison_worker_thread: Optional[threading.Thread] = None


active_crawler = None


projects: Dict[str, Dict[str, object]] = {}


news_settings: Dict[str, object] = {}


news_scheduler_thread: Optional[threading.Thread] = None


LOG_AUTO_CLEANUP = False


last_log_cleanup_at = 0.0


VISIBLE_BROWSER_LOCK = threading.Lock()


STANDALONE_BROWSER_SEMAPHORE = threading.BoundedSemaphore(1)


FEED_STORAGE_LOCK = threading.RLock()


feed_snapshot_cache: Dict[str, object] = {"signature": (), "created_at": 0.0, "feeds": []}


UNIFIED_LOG_LOCK = threading.Lock()


connection_method_cache_lock = threading.Lock()


connection_method_cache: Dict[str, object] = {"loaded_at": 0.0, "methods": []}


news_stop_events: Dict[str, threading.Event] = {}


news_stop_modes: Dict[str, str] = {}


news_scan_threads: Dict[str, threading.Thread] = {}


news_state_persisted_at: Dict[str, float] = {}


NEWS_TRANSITION_TIMEOUT_SECONDS = 180


PROGRESS_STREAM_INTERVAL_SECONDS = env_float("PROGRESS_STREAM_INTERVAL_SECONDS", 2.0, minimum=0.5, maximum=30.0)


progress_tracker = ProgressTracker(
    journal_limit=env_int(
        "PROGRESS_REVISION_JOURNAL_LIMIT",
        4096,
        minimum=128,
        maximum=100_000,
    )
)


FEED_COMPARISON_PROGRESS_COMMIT_INTERVAL_SECONDS = env_float(
    "FEED_COMPARISON_PROGRESS_COMMIT_INTERVAL_SECONDS",
    2.0,
    minimum=0.5,
    maximum=30.0,
)


@dataclass(frozen=True)
class ScanTask:
    key: Hashable
    run: Callable[[], None]
    on_start: Optional[Callable[[threading.Thread], None]] = None
    on_finish: Optional[Callable[[threading.Thread], None]] = None


class ScanDispatcher:
    """FIFO launcher shared by full project and news scans."""

    def __init__(self) -> None:
        self._queue: Deque[ScanTask] = deque()
        self._queued: Set[Hashable] = set()
        self._active: Set[Hashable] = set()
        self._lock = threading.RLock()

    def enqueue(
        self,
        key: Hashable,
        run: Callable[[], None],
        *,
        on_start: Optional[Callable[[threading.Thread], None]] = None,
        on_finish: Optional[Callable[[threading.Thread], None]] = None,
    ) -> bool:
        with self._lock:
            if key in self._queued or key in self._active:
                return False
            self._queued.add(key)
            self._queue.append(ScanTask(key, run, on_start, on_finish))
        self._dispatch()
        return True

    def cancel(self, key: Hashable) -> bool:
        with self._lock:
            if key not in self._queued:
                return False
            self._queued.remove(key)
            return True

    def contains(self, key: Hashable) -> bool:
        with self._lock:
            return key in self._queued or key in self._active

    def _dispatch(self) -> None:
        while True:
            with self._lock:
                if not self._queue:
                    return
                task = self._queue.popleft()
                if task.key not in self._queued:
                    continue
                self._queued.remove(task.key)
                self._active.add(task.key)
            threading.Thread(target=self._run, args=(task,), daemon=True).start()

    def _run(self, task: ScanTask) -> None:
        thread = threading.current_thread()
        try:
            if task.on_start:
                task.on_start(thread)
            task.run()
        finally:
            try:
                if task.on_finish:
                    task.on_finish(thread)
            finally:
                with self._lock:
                    self._active.discard(task.key)
            self._dispatch()


scan_dispatcher = ScanDispatcher()


BLOCKED_BROWSER_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}


BLOCKED_BROWSER_URL_PARTS = (
    "google-analytics",
    "googletagmanager",
    "doubleclick",
    "adservice",
    "adsystem",
    "yandex.ru/metrika",
    "mc.yandex",
    "metrika",
    "analytics",
    "counter",
    "facebook.net",
    "vk.com/rtrg",
    "top-fwz1.mail.ru",
    "mail.ru/counter",
)


SESSION_BROWSER_METHODS = {
    "protected-site",
}


BOTASAURUS_HEADLESS_METHODS = {
    "botasaurus-browser",
    "botasaurus-browser-direct",
    "botasaurus-visible",
}


DEBUG_VISIBLE_METHODS = {"botasaurus-debug-visible"}


STATIC_BROWSER_RENDER_METHODS = {
    *SESSION_BROWSER_METHODS,
    *BOTASAURUS_HEADLESS_METHODS,
    *DEBUG_VISIBLE_METHODS,
    "crawl4ai",
    "playwright",
    "scrapegraphai",
}


FETCH_DEBUG_HTML = env_str("FETCH_DEBUG_HTML", "0").lower() in {"1", "true", "yes", "on"}


FETCH_DEBUG_HTML_DIR = LOG_DIR / "debug-html"


scan_state: Dict[str, object] = {
    "status": "idle",
    "percent": 0,
    "currenturl": "",
    "totalprocessed": 0,
    "processed_products": 0,
    "found_products": 0,
    "skipped": 0,
    "error": "",
    "download_ready": False,
    "download_url": "",
    "filename": "",
    "thread_count": 4,
}


_storage_init_lock = threading.RLock()


_storage_initialized = False


def ensure_storage() -> None:
    """Создает рабочие файлы при первом запуске."""
    from runtime.news_tasks import start_news_scheduler
    from services.feed_service import recover_interrupted_feed_comparison
    from services.file_import_service import recover_interrupted_file_import_scan
    from services.news_service import load_news_settings
    from services.project_service import load_projects
    global _storage_initialized
    if _storage_initialized:
        return
    with _storage_init_lock:
        if _storage_initialized:
            return
        EXPORT_DIR.mkdir(exist_ok=True)
        LOG_DIR.mkdir(exist_ok=True)
        FEED_DIR.mkdir(exist_ok=True)
        FILE_IMPORT_DIR.mkdir(parents=True, exist_ok=True)
        PROJECT_PROFILE_DIR.mkdir(parents=True, exist_ok=True)
        init_db()
        ensure_default_user()
        recover_interrupted_file_import_scan()
        recover_interrupted_feed_comparison()
        load_projects()
        load_news_settings()
        start_news_scheduler()
        _storage_initialized = True


def normalize_start_urls(value: object, allow_empty: bool = False) -> List[str]:
    from services.scraping_service import normalize_url
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [] if allow_empty else [DEFAULT_START_URL]

    urls = []
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        normalized = normalize_url(item, item)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls or ([] if allow_empty else [DEFAULT_START_URL])


def normalize_feed_url(raw_url: str) -> str:
    raw_url = str(raw_url or "").strip()
    if not raw_url:
        return ""
    if not raw_url.startswith(("http://", "https://")):
        raw_url = "https://" + raw_url
    absolute_url, _fragment = urldefrag(raw_url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return ""
    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    return urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", parsed.query, ""))


def normalize_feed_urls(value: object, fallback: str) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [fallback]

    urls = []
    for item in raw_items:
        normalized = normalize_feed_url(item)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls or [fallback]


def normalize_patterns(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []

    patterns = []
    for item in raw_items:
        item = item.strip()
        if item and item not in patterns:
            patterns.append(item)
    return patterns


def normalize_file_import_exclusions(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = value.splitlines()
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            raw_items.extend(str(item or "").splitlines())
    else:
        raw_items = []

    exclusions = []
    for item in raw_items:
        item = str(item or "").strip()
        if item and item not in exclusions:
            exclusions.append(item)
    return exclusions


def file_import_exclusions_text(value: object) -> str:
    return "\n".join(normalize_file_import_exclusions(value))


def normalize_file_import_rules_text(value: object) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()


def normalize_emails(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,;]+", value)
    elif isinstance(value, list):
        raw_items = []
        for item in value:
            raw_items.extend(re.split(r"[\n,;]+", str(item)))
    else:
        raw_items = []

    emails = []
    for item in raw_items:
        item = item.strip()
        if item and "@" in item and item not in emails:
            emails.append(item)
    return emails


def normalize_selector_settings(value: object) -> Dict[str, object]:
    from services.scraping_service import clean_text
    if not isinstance(value, dict):
        value = {}
    allowed = {"name_selector", "availability_selector"}
    settings: Dict[str, object] = {}
    for key in allowed:
        text = clean_text(str(value.get(key, "")))
        if text:
            settings[key] = text
    status_exclusions = normalize_patterns(value.get("availability_exclusions", []))
    if status_exclusions:
        settings["availability_exclusions"] = status_exclusions
    return settings


PROJECT_PROGRESS_FIELDS = (
    "totalprocessed",
    "processed_products",
    "found_products",
    "in_memory_products",
    "queue_size",
    "active_tasks",
    "skipped",
    "failed_pages",
)


NEWS_PROGRESS_FIELDS = (
    "processed",
    "found_products",
    "candidate_products",
    "compared_products",
    "in_memory_products",
    "queue_size",
    "active_tasks",
    "failed_pages",
    "availability_skipped",
)


UNIFIED_LOG_RE = re.compile(r"^(?P<time>\S+) \[(?P<level>[^\]]+)\] (?P<project_name>.*?): (?P<message>.*)$")


LOG_TAIL_LINES = 2000


def normalize_model_key(value: str) -> str:
    from services.scraping_service import clean_text
    return re.sub(r"\s+", " ", clean_text(value)).upper()


def repair_mojibake_text(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    markers = (
        "\u0402",
        "\u0405",
        "\u0406",
        "\u040e",
        "\u0451",
        "\u0452",
        "\u0455",
        "\u045f",
        "\u20ac",
        "С",
        "П",
        "О",
        "М",
        "Н",
        "Д",
        "Г",
        "Ц",
        "Р",
        "С",
    )
    markers = markers + ("\u0420", "\u0421")
    text = value
    for _ in range(3):
        if not any(marker in text for marker in markers):
            break
        try:
            repaired = text.encode("cp1251").decode("utf-8")
        except UnicodeError:
            break
        if repaired == text:
            break
        text = repaired
    return text


def repair_mojibake(value: object) -> object:
    if isinstance(value, dict):
        return {key: repair_mojibake(item) for key, item in value.items()}
    if isinstance(value, list):
        return [repair_mojibake(item) for item in value]
    return repair_mojibake_text(value)


def jsonify(*args: object, **kwargs: object):
    repaired_args = tuple(repair_mojibake(item) for item in args)
    repaired_kwargs = repair_mojibake(kwargs) if kwargs else {}
    return flask_jsonify(*repaired_args, **repaired_kwargs)


def output_text(value: object) -> str:
    if value is None:
        return ""
    return str(repair_mojibake_text(str(value)) or "")


def reset_state(status: str = "idle", run_id: Optional[int] = None, thread_count: Optional[int] = None) -> None:
    with state_lock:
        if run_id is not None and run_id != active_run_id:
            return
        current_thread_count = thread_count or int(scan_state.get("thread_count", 4) or 4)
        scan_state.update(
            {
                "status": status,
                "percent": 0,
                "currenturl": "",
                "totalprocessed": 0,
                "processed_products": 0,
                "found_products": 0,
                "skipped": 0,
                "error": "",
                "download_ready": False,
                "download_url": "",
                "filename": "",
                "thread_count": current_thread_count,
            }
        )


def update_state(run_id: Optional[int] = None, **kwargs: object) -> None:
    with state_lock:
        if run_id is not None and run_id != active_run_id:
            return
        scan_state.update(kwargs)


def snapshot_state() -> Dict[str, object]:
    with state_lock:
        return dict(scan_state)


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
        append_unified_log({
            "project_id": "system",
            "project_name": "system",
            "level": "warning",
            "message": f"Не удалось прочитать способы подключения из БД: {error}",
        })

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


def parse_db_int(value: object) -> Optional[int]:
    try:
        return int(str(value).strip())
    except (TypeError, ValueError):
        return None


def parse_datetime_value(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.replace(tzinfo=None) if value.tzinfo else value
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def datetime_to_input_value(value: object) -> str:
    if not value:
        return ""
    if isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value))
        except ValueError:
            return str(value or "")
    if parsed.tzinfo is None:
        return parsed.isoformat(timespec="minutes")
    return parsed.astimezone(MSK_TZ).replace(tzinfo=None).isoformat(timespec="minutes")


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


def connection_method_id_for(session, code: object) -> Optional[int]:
    method = normalize_connection_method(code)
    row = session.scalar(select(ConnectionMethod).where(ConnectionMethod.code == method))
    return row.id if row else None


def normalize_extraction_rules(value: object) -> Dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    single_line_fields = {
        "product_card_selector",
        "product_url_selector",
        "model_selector",
        "price_selector",
        "model_start_marker",
        "model_end_marker",
    }
    multiline_fields = {"model_replace_rules"}
    rules = {}
    for key in single_line_fields:
        text = str(value.get(key, "")).strip()
        if text:
            rules[key] = text
    for key in multiline_fields:
        text = str(value.get(key, "")).strip()
        if text:
            rules[key] = text
    return rules


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")


def safe_filename(value: str) -> str:
    value = output_text(value)
    cleaned = re.sub(r"[^A-Za-z\u0400-\u04FF0-9_-]+", "_", value, flags=re.IGNORECASE).strip("_")
    return cleaned or "project"


FILE_IMPORT_ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}


FILE_IMPORT_ACTIVE_STATUSES = {"queued", "running"}


VISUAL_MODEL_TRANSLATION = str.maketrans(
    {
        "А": "A",
        "В": "B",
        "Е": "E",
        "К": "K",
        "М": "M",
        "Н": "H",
        "О": "O",
        "Р": "P",
        "С": "C",
        "Т": "T",
        "Х": "X",
        "а": "A",
        "в": "B",
        "е": "E",
        "к": "K",
        "м": "M",
        "н": "H",
        "о": "O",
        "р": "P",
        "с": "C",
        "т": "T",
        "х": "X",
    }
)


FILE_IMPORT_RESULT_FIELDS = [
    "row",
    "name",
    "price",
    "brand",
    "model_candidates",
    "selected_model",
    "missing_on",
]


FEED_COMPARISON_ACTIVE_STATUSES = {"queued", "running"}


FEED_COMPARISON_RESULT_FIELDS = [
    "row",
    "name",
    "price",
    "brand",
    "model_candidates",
    "selected_model",
    "missing_on",
]


