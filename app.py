import json
import os
import csv
import html as html_lib
import faulthandler
import re
import shutil
import smtplib
import ssl
import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from datetime import datetime, time as datetime_time, timedelta, timezone
from email.message import EmailMessage
from fnmatch import fnmatch
from pathlib import Path
from queue import Empty, Queue
from typing import Any, Dict, Iterable, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urldefrag, urljoin, urlparse, urlunparse
import xml.etree.ElementTree as ET

import requests
from bs4 import BeautifulSoup
from flask import Flask, Response, g, jsonify, render_template, request, send_file
from sqlalchemy import delete, select

from db import SessionLocal, init_db, session_scope
from models import AppSetting, Brand, ConnectionMethod, Donor, OwnSite, Project

BASE_DIR = Path(__file__).resolve().parent
LOG_DIR = BASE_DIR / "logs"
FEED_DIR = BASE_DIR / "feeds"
EXCLUSIONS_FILE = BASE_DIR / "exclusions.json"
LOGS_FILE = LOG_DIR / "logs.json"
LEGACY_LOGS_FILE = BASE_DIR / "logs.json"
EXPORT_DIR = BASE_DIR / "exports"
DEFAULT_START_URL = "https://www.maunfeld.ru/"
DEFAULT_FEED_URL = "https://mega-kuhnya.ru/price/last_modified.xml"
DEFAULT_FEED_GENERATE_URL = "https://mega-kuhnya.ru/index.php?route=extension/feed/unixml/new_product"
MSK_TZ = timezone(timedelta(hours=3))
DEFAULT_EXCLUSIONS = [
    "/catalog/rasprodazha/",
    "/catalog/utsenka/",
    "/about/",
    "/contacts/",
]

REQUEST_TIMEOUT = 20
REQUEST_DELAY_SECONDS = 0.25
MAX_RETRIES = 3
CONNECTION_METHODS = (
    "requests",
    "botasaurus-request",
    "botasaurus-browser",
    "botasaurus-browser-direct",
    "botasaurus-visible",
    "crawl4ai",
    "firecrawl",
    "scrapy",
    "crawlee",
)
GENERIC_FALLBACK_METHODS = (
    "requests",
    "botasaurus-request",
    "botasaurus-browser-direct",
    "botasaurus-browser",
    "crawl4ai",
    "firecrawl",
    "scrapy",
    "crawlee",
)
PRICE_RE = re.compile(r"\d[\d\s\u2009\xa0]{1,}(?:\u20bd|\u0440\u0443\u0431\.?)", re.IGNORECASE)
BLOCKED_PAGE_MARKERS = (
    "cloudflare",
    "captcha",
    "access denied",
    "http 403",
    "__qrator",
    "qauth.js",
    "qrator",
    "РґРѕСЃС‚СѓРї РѕРіСЂР°РЅРёС‡РµРЅ",
    "РїСЂРѕРІРµСЂСЏРµРј РІР°С€ Р±СЂР°СѓР·РµСЂ",
    "enable javascript",
)

app = Flask(__name__)


def load_env_file() -> None:
    env_path = BASE_DIR / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


load_env_file()


@app.before_request
def open_request_db_session() -> None:
    g.db = SessionLocal()


@app.teardown_request
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
exclusions_lock = threading.Lock()
projects_lock = threading.RLock()
news_lock = threading.RLock()
active_stop_event = threading.Event()
active_finish_event = threading.Event()
active_run_id = 0
worker_thread: Optional[threading.Thread] = None
active_crawler = None

projects: Dict[str, Dict[str, object]] = {}
news_settings: Dict[str, object] = {}
news_scheduler_thread: Optional[threading.Thread] = None
LOG_AUTO_CLEANUP = False
VISIBLE_BROWSER_LOCK = threading.Lock()
HEADLESS_BROWSER_SEMAPHORE = threading.BoundedSemaphore(3)
FEED_STORAGE_LOCK = threading.Lock()
news_stop_events: Dict[str, threading.Event] = {}
news_stop_modes: Dict[str, str] = {}
news_state_persisted_at: Dict[str, float] = {}

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


def make_state(thread_count: int = 4) -> Dict[str, object]:
    return {
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
        "thread_count": thread_count,
        "started_at": "",
        "finished_at": "",
        "elapsed_seconds": 0,
        "eta_seconds": None,
        "paused_with_result": False,
    }


def ensure_storage() -> None:
    """РЎРѕР·РґР°РµС‚ СЂР°Р±РѕС‡РёРµ С„Р°Р№Р»С‹ РїСЂРё РїРµСЂРІРѕРј Р·Р°РїСѓСЃРєРµ."""
    EXPORT_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    FEED_DIR.mkdir(exist_ok=True)
    init_db()
    if not EXCLUSIONS_FILE.exists():
        save_exclusions(DEFAULT_EXCLUSIONS)
    load_projects()
    load_news_settings()
    start_news_scheduler()


def normalize_start_urls(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = [DEFAULT_START_URL]

    urls = []
    for item in raw_items:
        item = item.strip()
        if not item:
            continue
        normalized = normalize_url(item, item)
        if normalized and normalized not in urls:
            urls.append(normalized)
    return urls or [DEFAULT_START_URL]


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


def normalize_emails(value: object) -> List[str]:
    if isinstance(value, str):
        raw_items = re.split(r"[\n,;]+", value)
    elif isinstance(value, list):
        raw_items = [str(item) for item in value]
    else:
        raw_items = []

    emails = []
    for item in raw_items:
        item = item.strip()
        if item and "@" in item and item not in emails:
            emails.append(item)
    return emails


def normalize_selector_settings(value: object) -> Dict[str, str]:
    if not isinstance(value, dict):
        value = {}
    allowed = {"name_selector", "availability_selector", "photo_selector"}
    settings = {}
    for key in allowed:
        text = clean_text(str(value.get(key, "")))
        if text:
            settings[key] = text
    return settings


def make_project(name: str = "РџСЂРѕРµРєС‚ 1", start_urls: Optional[List[str]] = None) -> Dict[str, object]:
    project_id = uuid.uuid4().hex[:10]
    return {
        "id": project_id,
        "name": name,
        "start_urls": start_urls or [DEFAULT_START_URL],
        "thread_count": 4,
        "exclusions": DEFAULT_EXCLUSIONS.copy(),
        "product_url_filters": [],
        "extraction_rules": {},
        "state": make_state(4),
        "logs": [],
        "auto_cleanup": False,
        "connection_method": "requests",
        "auto_connection_fallback": True,
        "worker_thread": None,
        "stop_event": threading.Event(),
        "finish_event": threading.Event(),
        "crawler": None,
        "run_id": 0,
    }


def public_project(project: Dict[str, object]) -> Dict[str, object]:
    return {
        "id": project["id"],
        "name": project["name"],
        "start_urls": project["start_urls"],
        "thread_count": project["thread_count"],
        "exclusions": project["exclusions"],
        "product_url_filters": project.get("product_url_filters", []),
        "extraction_rules": project.get("extraction_rules", {}),
        "state": project["state"],
        "auto_cleanup": project.get("auto_cleanup", False),
        "connection_method": project.get("connection_method", "requests"),
        "auto_connection_fallback": project.get("auto_connection_fallback", True),
    }


def project_model_to_dict(row: Project) -> Dict[str, object]:
    thread_count = parse_thread_count(row.thread_count)
    project = {
        "id": str(row.id),
        "name": row.name,
        "start_urls": normalize_start_urls(row.start_urls or [DEFAULT_START_URL]),
        "thread_count": thread_count,
        "exclusions": normalize_patterns(row.exclusions or DEFAULT_EXCLUSIONS),
        "product_url_filters": normalize_patterns(row.product_url_filters or []),
        "extraction_rules": normalize_extraction_rules(row.extraction_rules or {}),
        "state": {**make_state(thread_count), **(row.state or {})},
        "logs": [],
        "auto_cleanup": bool(row.auto_cleanup),
        "connection_method": normalize_connection_method(row.connection_method),
        "auto_connection_fallback": bool(row.auto_connection_fallback),
        "worker_thread": None,
        "stop_event": threading.Event(),
        "finish_event": threading.Event(),
        "crawler": None,
        "run_id": 0,
    }
    if project["state"].get("status") == "running":
        project["state"]["status"] = "error"
        project["state"]["error"] = "РЎР±РѕСЂ Р±С‹Р» РїСЂРµСЂРІР°РЅ РїРµСЂРµР·Р°РїСѓСЃРєРѕРј СЃРµСЂРІРµСЂР°. Р—Р°РїСѓСЃС‚РёС‚Рµ РµРіРѕ СЃРЅРѕРІР°."
    return project


def upsert_project_model(session, project: Dict[str, object]) -> int:
    row = get_project_row(session, project.get("id"))
    if row is None:
        legacy_id = str(project.get("id") or "").strip()
        row = Project(legacy_id=legacy_id if legacy_id and parse_db_int(legacy_id) is None else "", name=str(project.get("name") or "Проект"))
        session.add(row)
    row.name = str(project.get("name") or "Проект")
    row.start_urls = normalize_start_urls(project.get("start_urls") or DEFAULT_START_URL)
    row.thread_count = parse_thread_count(project.get("thread_count", 4))
    row.exclusions = normalize_patterns(project.get("exclusions", DEFAULT_EXCLUSIONS))
    row.product_url_filters = normalize_patterns(project.get("product_url_filters", []))
    row.extraction_rules = normalize_extraction_rules(project.get("extraction_rules", {}))
    row.state = dict(project.get("state") or make_state(row.thread_count))
    row.auto_cleanup = bool(project.get("auto_cleanup", False))
    row.connection_method = normalize_connection_method(project.get("connection_method"))
    row.auto_connection_fallback = bool(project.get("auto_connection_fallback", True))
    session.flush()
    return int(row.id)

def save_projects() -> None:
    with projects_lock:
        with session_scope() as session:
            current_ids = set()
            rekey: List[tuple[str, str]] = []
            for old_key, project in list(projects.items()):
                db_id = upsert_project_model(session, project)
                public_id = str(db_id)
                current_ids.add(db_id)
                if str(project.get("id")) != public_id:
                    project["id"] = public_id
                if old_key != public_id:
                    rekey.append((old_key, public_id))
            for old_key, new_key in rekey:
                projects[new_key] = projects.pop(old_key)
            if current_ids:
                session.execute(delete(Project).where(Project.id.not_in(current_ids)))


def write_logs_file(data: List[Dict[str, object]]) -> None:
    LOGS_FILE.parent.mkdir(exist_ok=True)
    LOGS_FILE.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def read_logs_file() -> List[Dict[str, object]]:
    source_file = LOGS_FILE if LOGS_FILE.exists() else LEGACY_LOGS_FILE
    if not source_file.exists():
        return []
    try:
        data = json.loads(source_file.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    if not isinstance(data, list):
        return []
    return [item for item in data if isinstance(item, dict)]


def save_logs() -> None:
    with projects_lock:
        data = []
        for project in projects.values():
            data.extend(project.get("logs", []))
    with news_lock:
        data.extend(news_settings.get("logs", []) if isinstance(news_settings.get("logs"), list) else [])
    write_logs_file(data)


def logs_signature() -> str:
    source_file = LOGS_FILE if LOGS_FILE.exists() else LEGACY_LOGS_FILE
    if not source_file.exists():
        return "missing"
    try:
        stat = source_file.stat()
    except OSError:
        return "unavailable"
    return f"{stat.st_mtime_ns}:{stat.st_size}"


def load_logs() -> None:
    for item in read_logs_file():
        project_id = item.get("project_id")
        project = projects.get(project_id)
        if project:
            project.setdefault("logs", []).append(item)


def load_news_logs_from_file() -> List[Dict[str, object]]:
    return [
        item
        for item in read_logs_file()
        if str(item.get("project_id") or "").startswith("news")
    ]


def load_projects() -> None:
    with projects_lock:
        if projects:
            return
        with session_scope() as session:
            rows = session.scalars(select(Project).order_by(Project.created_at, Project.id)).all()

        if not rows:
            project = make_project("РџСЂРѕРµРєС‚ 1", [DEFAULT_START_URL])
            projects[project["id"]] = project
            save_projects()
        else:
            for row in rows:
                projects[str(row.id)] = project_model_to_dict(row)

        if not projects:
            project = make_project("РџСЂРѕРµРєС‚ 1", [DEFAULT_START_URL])
            projects[project["id"]] = project
            save_projects()
        load_logs()


def get_project(project_id: str) -> Optional[Dict[str, object]]:
    ensure_storage()
    with projects_lock:
        return projects.get(project_id)


def update_project_state(project: Dict[str, object], **kwargs: object) -> None:
    with projects_lock:
        state = dict(project.get("state", make_state(parse_thread_count(project.get("thread_count", 4)))))
        state.update(kwargs)
        project["state"] = state


def reset_project_state(project: Dict[str, object], status: str = "idle") -> None:
    thread_count = parse_thread_count(project.get("thread_count", 4))
    state = make_state(thread_count)
    state["status"] = status
    project["state"] = state


def add_project_log(project: Dict[str, object], message: str, level: str = "info") -> None:
    with projects_lock:
        logs = project.setdefault("logs", [])
        logs.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "project_id": project["id"],
                "project_name": project["name"],
                "level": level,
                "message": message,
            }
        )
        if project.get("auto_cleanup"):
            cutoff = time.time() - 7 * 24 * 60 * 60
            logs[:] = [
                item
                for item in logs
                if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
            ]
        save_logs()


def normalize_model_key(value: str) -> str:
    return re.sub(r"\s+", " ", clean_text(value)).upper()


def repair_mojibake_text(value: object) -> object:
    if not isinstance(value, str) or not value:
        return value
    markers = ("\u0402", "\u0405", "\u0406", "\u040e", "\u0451", "\u0452", "\u0455", "\u045f", "\u20ac", "РЎ", "Рџ", "Рћ", "Рњ")
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


def default_news_settings() -> Dict[str, object]:
    return {
        "feed_url": DEFAULT_FEED_URL,
        "feed_generate_url": DEFAULT_FEED_GENERATE_URL,
        "feed_urls": [DEFAULT_FEED_URL],
        "feed_generate_urls": [DEFAULT_FEED_GENERATE_URL],
        "auto_cleanup": False,
        "smtp": {
            "host": "smtp.yandex.ru",
            "port": 465,
            "security": "ssl",
            "username": "",
            "password": os.environ.get("YANDEX_SMTP_PASSWORD", ""),
            "recipients": [],
        },
        "monitors": [],
        "logs": [],
        "feed_storage": [],
    }


def make_news_monitor(group: str, brand: str, urls: List[str]) -> Dict[str, object]:
    monitor_id = uuid.uuid4().hex[:10]
    site_url = urls[0] if urls else ""
    return {
        "id": monitor_id,
        "group": group,
        "brand": brand,
        "created_at": datetime.now().isoformat(timespec="milliseconds"),
        "site_url": site_url,
        "start_urls": [site_url] if site_url else [],
        "enabled": True,
        "schedule_type": "daily",
        "scan_time": "01:00",
        "weekday": 0,
        "next_run_at": "",
        "thread_count": 4,
        "connection_method": "requests",
        "auto_connection_fallback": True,
        "exclusions": DEFAULT_EXCLUSIONS.copy(),
        "product_url_filters": [],
        "extraction_rules": {},
        "selector_settings": {},
        "seen_models": [],
        "known_new_products": {},
        "state": make_news_state(),
        "collapsed": True,
    }


def make_news_state(status: str = "idle") -> Dict[str, object]:
    return {
        "status": status,
        "stage": "",
        "percent": 0,
        "currenturl": "",
        "processed": 0,
        "found_products": 0,
        "candidate_products": 0,
        "compared_products": 0,
        "new_count": 0,
        "missing_by_feed": [],
        "skipped": 0,
        "last_scan_at": "",
        "last_csv": "",
        "error": "",
        "started_at": "",
        "finished_at": "",
        "elapsed_seconds": 0,
        "next_run_at": "",
    }


def normalize_news_monitor(item: Dict[str, object]) -> Dict[str, object]:
    monitor = make_news_monitor(
        clean_text(str(item.get("group") or "РњР°СЂР¶Р°")),
        clean_text(str(item.get("brand") or "Р”РѕРЅРѕСЂ")),
        normalize_start_urls(item.get("start_urls") or item.get("site_url") or DEFAULT_START_URL),
    )
    monitor["id"] = str(item.get("id") or monitor["id"])
    monitor["created_at"] = str(item.get("created_at") or monitor["created_at"])
    monitor["site_url"] = str(item.get("site_url") or monitor["start_urls"][0])
    monitor["enabled"] = bool(item.get("enabled", True))
    monitor["schedule_type"] = str(item.get("schedule_type") or "daily")
    monitor["scan_time"] = str(item.get("scan_time") or "01:00")[:5]
    monitor["weekday"] = max(0, min(int(item.get("weekday", 0) or 0), 6))
    monitor["next_run_at"] = str(item.get("next_run_at") or "")
    monitor["thread_count"] = parse_thread_count(item.get("thread_count", 4))
    monitor["connection_method"] = normalize_connection_method(item.get("connection_method"))
    monitor["auto_connection_fallback"] = bool(item.get("auto_connection_fallback", True))
    monitor["exclusions"] = normalize_patterns(item.get("exclusions", DEFAULT_EXCLUSIONS))
    monitor["product_url_filters"] = normalize_patterns(item.get("product_url_filters", []))
    monitor["extraction_rules"] = normalize_extraction_rules(item.get("extraction_rules", {}))
    monitor["selector_settings"] = normalize_selector_settings(item.get("selector_settings", {}))
    monitor["seen_models"] = [normalize_model_key(str(value)) for value in item.get("seen_models", []) if str(value).strip()]
    known = item.get("known_new_products", {})
    monitor["known_new_products"] = known if isinstance(known, dict) else {}
    state = item.get("state", {})
    monitor["state"] = {**make_news_state(), **state} if isinstance(state, dict) else make_news_state()
    monitor["state"].pop("last_feeds", None)
    if monitor["state"].get("status") in {"running", "queued", "pausing", "stopping"}:
        monitor["state"]["status"] = "error"
        monitor["state"]["stage"] = "Прервано"
        monitor["state"]["error"] = "Сканирование было прервано перезапуском сервера. Запустите его снова."
        monitor["state"]["currenturl"] = ""
    monitor["brand_state"] = dict(monitor["state"])
    monitor["collapsed"] = bool(item.get("collapsed", True))
    return monitor


def split_news_monitor_by_site(item: Dict[str, object]) -> List[Dict[str, object]]:
    urls = normalize_start_urls(item.get("start_urls") or item.get("site_url") or DEFAULT_START_URL)
    monitors = []
    for index, url in enumerate(urls):
        copy_item = dict(item)
        copy_item["id"] = str(item.get("id") or uuid.uuid4().hex[:10]) if index == 0 else uuid.uuid4().hex[:10]
        copy_item["site_url"] = url
        copy_item["start_urls"] = [url]
        monitors.append(normalize_news_monitor(copy_item))
    return monitors


def group_type_from_group(group: str) -> str:
    normalized = clean_text(group).lower()
    if "РЅРµРјР°СЂР¶" in normalized or "РЅРµ РјР°СЂР¶" in normalized or "non_margin" in normalized or "non-margin" in normalized:
        return "non_margin"
    return "margin" if "РјР°СЂР¶" in normalized or "margin" in normalized else "non_margin"


def unique_news_brand_name(group: str, base_name: str = "РќРѕРІС‹Р№ Р±СЂРµРЅРґ") -> str:
    base_name = clean_text(base_name) or "РќРѕРІС‹Р№ Р±СЂРµРЅРґ"
    group_type = group_type_from_group(group)
    names = {
        clean_text(str(item.get("brand") or ""))
        for item in news_settings.get("monitors", [])
        if isinstance(item, dict) and group_type_from_group(str(item.get("group") or "")) == group_type
    }
    if base_name not in names:
        return base_name
    index = 2
    while True:
        candidate = f"{base_name} {index}"
        if candidate not in names:
            return candidate
        index += 1


def donor_model_to_monitor(row: Donor) -> Dict[str, object]:
    brand = row.brand
    brand_exclusions = normalize_patterns(brand.exclusions or DEFAULT_EXCLUSIONS) if brand else DEFAULT_EXCLUSIONS
    brand_state = repair_mojibake({**make_news_state(), **(brand.state or {})}) if brand else make_news_state()
    monitor = {
        "id": str(row.id),
        "group": brand.group_name if brand else "",
        "brand": brand.name if brand else "Р”РѕРЅРѕСЂ",
        "brand_id": brand.id if brand else None,
        "brand_state": brand_state,
        "created_at": row.created_at.isoformat(timespec="milliseconds") if row.created_at else "",
        "site_url": row.site_url,
        "start_urls": normalize_start_urls(row.start_urls or row.site_url or DEFAULT_START_URL),
        "enabled": bool(row.enabled),
        "schedule_type": row.schedule_type,
        "scan_time": row.scan_time,
        "weekday": max(0, min(int(row.weekday or 0), 6)),
        "next_run_at": datetime_to_input_value(row.next_run_at),
        "thread_count": parse_thread_count(row.thread_count),
        "connection_method": normalize_connection_method(row.connection_method),
        "auto_connection_fallback": bool(row.auto_connection_fallback),
        "exclusions": brand_exclusions,
        "product_url_filters": normalize_patterns(row.product_url_filters or []),
        "extraction_rules": normalize_extraction_rules(row.extraction_rules or {}),
        "selector_settings": normalize_selector_settings(row.selector_settings or {}),
        "seen_models": [normalize_model_key(str(value)) for value in (row.seen_models or []) if str(value).strip()],
        "known_new_products": row.known_new_products or {},
        "state": dict(brand_state),
        "collapsed": bool(brand.collapsed) if brand else True,
    }
    if monitor["state"].get("status") in {"running", "queued", "pausing", "stopping"}:
        monitor["state"]["status"] = "error"
        monitor["state"]["stage"] = "Прервано"
        monitor["state"]["error"] = "Сканирование было прервано перезапуском сервера. Запустите его снова."
        monitor["state"]["currenturl"] = ""
        monitor["brand_state"] = dict(monitor["state"])
    return monitor


def get_or_create_brand(session, monitor: Dict[str, object]) -> Brand:
    name = clean_text(str(monitor.get("brand") or "Р”РѕРЅРѕСЂ"))
    group_name = clean_text(str(monitor.get("group") or "РњР°СЂР¶Р°"))
    group_type = group_type_from_group(group_name)
    row = session.scalar(select(Brand).where(Brand.name == name, Brand.group_type == group_type))
    if row is None:
        row = Brand(
            name=name,
            group_name=group_name,
            group_type=group_type,
            collapsed=bool(monitor.get("collapsed", True)),
            exclusions=normalize_patterns(monitor.get("exclusions", DEFAULT_EXCLUSIONS)),
            state=dict(monitor.get("brand_state") or make_news_state()),
        )
        session.add(row)
        session.flush()
    else:
        row.group_name = group_name
        row.collapsed = bool(monitor.get("collapsed", row.collapsed))
        row.exclusions = normalize_patterns(monitor.get("exclusions", row.exclusions or DEFAULT_EXCLUSIONS))
        row.state = {**make_news_state(), **(monitor.get("brand_state") or row.state or {})}
    return row


def upsert_donor_model(session, monitor: Dict[str, object]) -> int:
    normalized = normalize_news_monitor(monitor)
    brand = get_or_create_brand(session, normalized)
    row = get_donor_row(session, normalized.get("id"))
    if row is None:
        legacy_id = str(normalized.get("id") or "").strip()
        row = Donor(
            legacy_id=legacy_id if legacy_id and parse_db_int(legacy_id) is None else "",
            brand_id=brand.id,
        )
        session.add(row)
    row.brand_id = brand.id
    row.site_url = str(normalized.get("site_url") or "")
    row.start_urls = normalize_start_urls(normalized.get("start_urls") or normalized.get("site_url") or DEFAULT_START_URL)
    row.enabled = bool(normalized.get("enabled", True))
    row.schedule_type = str(normalized.get("schedule_type") or "daily")
    row.scan_time = str(normalized.get("scan_time") or "01:00")[:5]
    row.weekday = max(0, min(int(normalized.get("weekday", 0) or 0), 6))
    row.next_run_at = parse_datetime_value(normalized.get("next_run_at"))
    row.thread_count = parse_thread_count(normalized.get("thread_count", 4))
    row.connection_method = normalize_connection_method(normalized.get("connection_method"))
    row.connection_method_id = connection_method_id_for(session, row.connection_method)
    row.auto_connection_fallback = bool(normalized.get("auto_connection_fallback", True))
    row.exclusions = normalize_patterns(brand.exclusions or normalized.get("exclusions", DEFAULT_EXCLUSIONS))
    row.product_url_filters = normalize_patterns(normalized.get("product_url_filters", []))
    row.extraction_rules = normalize_extraction_rules(normalized.get("extraction_rules", {}))
    row.selector_settings = normalize_selector_settings(normalized.get("selector_settings", {}))
    row.seen_models = [normalize_model_key(str(value)) for value in normalized.get("seen_models", []) if str(value).strip()]
    row.known_new_products = normalized.get("known_new_products", {}) if isinstance(normalized.get("known_new_products"), dict) else {}
    brand.state = {**make_news_state(), **(normalized.get("brand_state") or normalized.get("state") or brand.state or {})}
    session.flush()
    return int(row.id)


def aggregate_brand_state(monitors: List[Dict[str, object]]) -> Dict[str, object]:
    states = [{**make_news_state(), **(monitor.get("state") or {})} for monitor in monitors if isinstance(monitor, dict)]
    if not states:
        return make_news_state()
    priority = ["running", "queued", "pausing", "stopping", "error", "partial", "stopped", "completed"]
    selected = next((state for status in priority for state in states if state.get("status") == status), states[0])
    result = {**make_news_state(), **selected}
    result["found_products"] = sum(int(state.get("found_products", 0) or 0) for state in states)
    result["new_count"] = sum(int(state.get("new_count", 0) or 0) for state in states)
    last_scan_at = max((str(state.get("last_scan_at") or state.get("finished_at") or "") for state in states), default="")
    if last_scan_at:
        result["last_scan_at"] = last_scan_at
    return result


def own_sites_from_settings(settings: Dict[str, object]) -> List[Dict[str, str]]:
    if isinstance(settings.get("own_sites"), list):
        sites = []
        for index, item in enumerate(settings.get("own_sites", []), start=1):
            if not isinstance(item, dict):
                continue
            feed_url = normalize_feed_url(str(item.get("feed_url") or "").strip())
            if not feed_url:
                continue
            sites.append(
                {
                    "name": clean_text(str(item.get("name") or "")) or f"Р¤РёРґ {index}",
                    "feed_url": feed_url,
                    "feed_generate_url": normalize_feed_url(str(item.get("feed_generate_url") or "").strip()),
                }
            )
        if sites:
            return sites
    feed_urls = normalize_feed_urls(settings.get("feed_urls") or settings.get("feed_url") or DEFAULT_FEED_URL, DEFAULT_FEED_URL)
    generate_urls = normalize_feed_urls(settings.get("feed_generate_urls") or settings.get("feed_generate_url") or DEFAULT_FEED_GENERATE_URL, DEFAULT_FEED_GENERATE_URL)
    sites = []
    for index, feed_url in enumerate(feed_urls):
        generate_url = generate_urls[index] if index < len(generate_urls) else (generate_urls[0] if generate_urls else "")
        sites.append({"name": feed_source_label(feed_url), "feed_url": feed_url, "feed_generate_url": generate_url})
    return sites


def save_news_settings() -> None:
    with news_lock:
        with session_scope() as session:
            smtp = dict(news_settings.get("smtp", {}))
            smtp.pop("sender", None)
            app_setting = session.get(AppSetting, 1)
            if app_setting is None:
                app_setting = AppSetting(id=1)
                session.add(app_setting)
            app_setting.auto_cleanup = bool(news_settings.get("auto_cleanup", False))
            app_setting.smtp = smtp
            app_setting.feed_storage = list(news_settings.get("feed_storage", [])) if isinstance(news_settings.get("feed_storage"), list) else []

            current_donor_ids = set()
            for monitor in news_settings.get("monitors", []):
                if not isinstance(monitor, dict):
                    continue
                db_id = upsert_donor_model(session, monitor)
                current_donor_ids.add(db_id)
                if str(monitor.get("id")) != str(db_id):
                    monitor["id"] = str(db_id)
            grouped_monitors: Dict[tuple[str, str], List[Dict[str, object]]] = {}
            for monitor in news_settings.get("monitors", []):
                if not isinstance(monitor, dict):
                    continue
                group_name = clean_text(str(monitor.get("group") or "РњР°СЂР¶Р°"))
                brand_name = clean_text(str(monitor.get("brand") or "Р”РѕРЅРѕСЂ"))
                grouped_monitors.setdefault((brand_name, group_type_from_group(group_name)), []).append(monitor)
            for (brand_name, group_type), brand_monitors in grouped_monitors.items():
                brand_row = session.scalar(select(Brand).where(Brand.name == brand_name, Brand.group_type == group_type))
                if brand_row:
                    brand_row.state = aggregate_brand_state(brand_monitors)
            if current_donor_ids:
                session.execute(delete(Donor).where(Donor.id.not_in(current_donor_ids)))
            else:
                session.execute(delete(Donor))
            session.execute(delete(Brand).where(~Brand.donors.any()))

            current_feed_urls = set()
            for site in own_sites_from_settings(news_settings):
                current_feed_urls.add(site["feed_url"])
                row = session.scalar(select(OwnSite).where(OwnSite.feed_url == site["feed_url"]))
                if row is None:
                    row = OwnSite(name=site["name"], feed_url=site["feed_url"], feed_generate_url=site["feed_generate_url"])
                    session.add(row)
                else:
                    row.name = site["name"]
                    row.feed_generate_url = site["feed_generate_url"]
            if current_feed_urls:
                session.execute(delete(OwnSite).where(OwnSite.feed_url.not_in(current_feed_urls)))


def load_news_settings() -> None:
    with news_lock:
        if news_settings:
            return
        settings = default_news_settings()
        with session_scope() as session:
            donor_rows = session.scalars(
                select(Donor)
                .join(Brand)
                .order_by(Brand.group_name, Brand.name, Donor.id)
            ).all()
            app_setting = session.get(AppSetting, 1)
            if app_setting:
                settings["auto_cleanup"] = bool(app_setting.auto_cleanup)
                if isinstance(app_setting.smtp, dict):
                    smtp = dict(settings["smtp"])
                    smtp.update(app_setting.smtp)
                    smtp.pop("sender", None)
                    settings["smtp"] = smtp
                if isinstance(app_setting.feed_storage, list):
                    settings["feed_storage"] = app_setting.feed_storage
            own_sites = session.scalars(select(OwnSite).order_by(OwnSite.id)).all()
            if own_sites:
                settings["own_sites"] = [
                    {
                        "name": site.name or feed_source_label(site.feed_url),
                        "feed_url": site.feed_url,
                        "feed_generate_url": site.feed_generate_url,
                    }
                    for site in own_sites
                ]
                feed_urls = [site.feed_url for site in own_sites]
                generate_urls = [site.feed_generate_url for site in own_sites]
                settings["feed_urls"] = feed_urls
                settings["feed_generate_urls"] = generate_urls
                settings["feed_url"] = feed_urls[0]
                settings["feed_generate_url"] = generate_urls[0] if generate_urls else DEFAULT_FEED_GENERATE_URL
            settings["monitors"] = [donor_model_to_monitor(row) for row in donor_rows]
            settings["logs"] = load_news_logs_from_file()
        news_settings.update(settings)
        save_news_settings()


def add_news_log(monitor: Optional[Dict[str, object]], message: str, level: str = "info") -> None:
    with news_lock:
        logs = news_settings.setdefault("logs", [])
        logs.append(
            {
                "time": datetime.now().isoformat(timespec="seconds"),
                "project_id": f"news:{monitor.get('id')}" if monitor else "news",
                "project_name": repair_mojibake_text(f"РќРѕРІРёРЅРєРё: {monitor.get('brand')}") if monitor else "Новинки",
                "level": level,
                "message": repair_mojibake_text(message),
            }
        )
        if news_settings.get("auto_cleanup"):
            cutoff = time.time() - 7 * 24 * 60 * 60
            logs[:] = [
                item
                for item in logs
                if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
            ]
        save_logs()


def get_news_monitor(monitor_id: str) -> Optional[Dict[str, object]]:
    ensure_storage()
    with news_lock:
        for monitor in news_settings.get("monitors", []):
            if str(monitor.get("id")) == str(monitor_id):
                return monitor
    return None


def public_news_settings() -> Dict[str, object]:
    with news_lock:
        smtp = dict(news_settings.get("smtp", {}))
        smtp.pop("sender", None)
        smtp["password_set"] = bool(news_settings.get("smtp", {}).get("password"))
        own_sites = own_sites_from_settings(news_settings)
        feed_urls = [site["feed_url"] for site in own_sites]
        feed_generate_urls = [site["feed_generate_url"] for site in own_sites]
        return {
            "feed_url": feed_urls[0] if feed_urls else DEFAULT_FEED_URL,
            "feed_generate_url": feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL,
            "feed_urls": feed_urls,
            "feed_generate_urls": feed_generate_urls,
            "own_sites": own_sites,
            "auto_cleanup": bool(news_settings.get("auto_cleanup", False)),
            "smtp": smtp,
            "feed_storage": list(news_settings.get("feed_storage", [])) if isinstance(news_settings.get("feed_storage"), list) else [],
            "monitors": [repair_mojibake(dict(monitor)) for monitor in news_settings.get("monitors", [])],
        }



def load_exclusions() -> List[str]:
    ensure_storage_without_exclusions_loop()
    try:
        data = json.loads(EXCLUSIONS_FILE.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = DEFAULT_EXCLUSIONS
    if not isinstance(data, list):
        return DEFAULT_EXCLUSIONS.copy()
    return [str(item).strip() for item in data if str(item).strip()]


def save_exclusions(items: Iterable[str]) -> None:
    EXCLUSIONS_FILE.write_text(
        json.dumps(list(items), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def ensure_storage_without_exclusions_loop() -> None:
    EXPORT_DIR.mkdir(exist_ok=True)
    LOG_DIR.mkdir(exist_ok=True)
    FEED_DIR.mkdir(exist_ok=True)
    if not EXCLUSIONS_FILE.exists():
        EXCLUSIONS_FILE.write_text(
            json.dumps(DEFAULT_EXCLUSIONS, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


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


def parse_thread_count(value: object) -> int:
    try:
        return max(1, min(int(value or 4), 16))
    except (TypeError, ValueError):
        return 4


def normalize_connection_method(value: object) -> str:
    method = str(value or "requests").strip()
    return method if method in CONNECTION_METHODS else "requests"


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


def get_project_row(session, public_id: object) -> Optional[Project]:
    db_id = parse_db_int(public_id)
    if db_id is not None:
        row = session.get(Project, db_id)
        if row is not None:
            return row
    legacy_id = str(public_id or "").strip()
    if not legacy_id:
        return None
    return session.scalar(select(Project).where(Project.legacy_id == legacy_id))


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


def normalize_url(raw_url: str, base_url: str) -> Optional[str]:
    """РџСЂРёРІРѕРґРёС‚ СЃСЃС‹Р»РєСѓ Рє РєР°РЅРѕРЅРёС‡РµСЃРєРѕРјСѓ РІРёРґСѓ РІРЅСѓС‚СЂРё СЃР°Р№С‚Р°."""
    if not raw_url:
        return None
    raw_url = raw_url.strip()
    if raw_url.startswith(("mailto:", "tel:", "javascript:")):
        return None

    absolute_url = urljoin(base_url, raw_url)
    absolute_url, _fragment = urldefrag(absolute_url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = re.sub(r"/{2,}", "/", parsed.path or "/")
    keep_trailing_slash = parsed.netloc.lower().endswith("technopark.ru")
    if path != "/" and path.endswith("/") and not keep_trailing_slash:
        path = path[:-1]

    # РЎРѕС…СЂР°РЅСЏРµРј С‚РѕР»СЊРєРѕ РїР°РіРёРЅР°С†РёСЋ. РћСЃС‚Р°Р»СЊРЅС‹Рµ РїР°СЂР°РјРµС‚СЂС‹ РѕР±С‹С‡РЅРѕ СЃРѕР·РґР°СЋС‚ РґСѓР±Р»РёРєР°С‚С‹:
    # СЃРѕСЂС‚РёСЂРѕРІРєРё, UTM-РјРµС‚РєРё, СЃСЂР°РІРЅРµРЅРёРµ, С„РёР»СЊС‚СЂС‹ СЃ С‚РµРјРё Р¶Рµ С‚РѕРІР°СЂР°РјРё.
    pagination_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower == "page" or key_lower.startswith("pagen_"):
            pagination_params.append((key, value))
    query = urlencode(pagination_params)

    result = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))
    if parsed.netloc.lower().endswith("technopark.ru"):
        result = technopark_slash_url(result)
    return result


def same_site(url: str, root_netloc: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    root = root_netloc.lower()
    return netloc == root or netloc.endswith("." + root)


def is_maunfeld_url(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("maunfeld.ru")


def is_technopark_url(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("technopark.ru")


def is_kuppersberg_url(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("kuppersberg.ru")


def is_kuppersberg_product_url(url: str) -> bool:
    if not is_kuppersberg_url(url):
        return False
    parts = [part for part in urlparse(url).path.split("/") if part]
    return len(parts) == 2 and parts[0] == "products"


def is_technopark_product_url(url: str) -> bool:
    path = urlparse(url).path.rstrip("/")
    if not is_technopark_url(url):
        return False
    if path.startswith(("/photos/", "/support/", "/about/", "/action/", "/brand/")):
        return False
    path_parts = [part for part in path.split("/") if part]
    if len(path_parts) != 1:
        return False
    slug = path_parts[0].lower()
    known_brand = "|".join(re.escape(brand.lower()) for brand in MODEL_BRANDS if brand != "MAUNFELD")
    return bool(
        re.search(r"-\d{5,}$", slug)
        or re.search(rf"-({known_brand})-[a-z0-9][a-z0-9-]*\d[a-z0-9-]*$", slug)
    )


def technopark_slash_url(url: str) -> str:
    parsed = urlparse(url)
    if not parsed.netloc.lower().endswith("technopark.ru"):
        return url
    path = parsed.path or "/"
    if path == "/" or path.endswith("/") or "." in path.rsplit("/", 1)[-1]:
        return url
    return urlunparse((parsed.scheme, parsed.netloc, path + "/", parsed.params, parsed.query, parsed.fragment))


def has_static_extension(url: str) -> bool:
    return bool(
        re.search(
            r"\.(?:jpg|jpeg|png|gif|svg|webp|pdf|doc|docx|xls|xlsx|zip|rar|mp4|avi|css|js)$",
            urlparse(url).path,
            flags=re.IGNORECASE,
        )
    )


def looks_like_product_path(path: str) -> bool:
    path_parts = [part for part in path.split("/") if part]
    if not path_parts:
        return False
    slug = path_parts[-1]
    if len(path_parts) >= 3 and path_parts[0] == "catalog":
        return "-" in slug or any(char.isdigit() for char in slug)
    if len(path_parts) >= 2 and slug.lower().endswith(".html"):
        service_prefixes = {
            "articles",
            "reviews",
            "delivery-and-payment",
            "services",
            "credit",
            "guarantee",
            "contacts",
        }
        if path_parts[0].lower() in service_prefixes:
            return False
        product_slug = slug.rsplit(".", 1)[0]
        return "-" in product_slug and any(char.isdigit() for char in product_slug)
    return False


def is_obvious_service_path(path: str) -> bool:
    first = next((part.lower() for part in path.split("/") if part), "")
    return first in {
        "articles",
        "reviews",
        "delivery-and-payment",
        "services",
        "credit",
        "guarantee",
        "contacts",
        "favorites",
        "compare",
        "cart",
        "login",
        "personal",
        "search",
        "upload",
        "bitrix",
        "ajax",
    }


def looks_blocked_or_empty(html: str) -> bool:
    """РћРїСЂРµРґРµР»СЏРµС‚ СЃС‚СЂР°РЅРёС†С‹ Р±Р»РѕРєРёСЂРѕРІРєРё РёР»Рё РїРѕС‡С‚Рё РїСѓСЃС‚С‹Рµ HTML-РѕР±РѕР»РѕС‡РєРё."""
    lowered = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    text = clean_text(soup.get_text(" ", strip=True))
    links_count = len(soup.select("a[href]"))
    if PRICE_RE.search(text) and links_count > 10:
        return False
    if any(marker in lowered for marker in BLOCKED_PAGE_MARKERS):
        return len(text) < 1200 or links_count < 10
    return len(text) < 250 and links_count < 5


def should_follow_url(url: str, start_url: str, root_netloc: str) -> bool:
    """РћРіСЂР°РЅРёС‡РёРІР°РµС‚ РѕР±С…РѕРґ СЃС‚СЂР°РЅРёС†Р°РјРё СЃР°Р№С‚Р°, РїРѕР»РµР·РЅС‹РјРё РґР»СЏ РїРѕРёСЃРєР° С‚РѕРІР°СЂРѕРІ."""
    if not same_site(url, root_netloc) or has_static_extension(url):
        return False

    path = urlparse(url).path or "/"
    start_path = urlparse(start_url).path or "/"
    normalized_start_path = start_path.rstrip("/") or "/"

    if normalized_start_path not in {"/", "/catalog"}:
        return path == normalized_start_path or path.startswith(normalized_start_path + "/")

    if path == "/" or path == "/catalog" or path.startswith("/catalog/"):
        return True

    return False


def should_follow_project_url(url: str, start_urls: List[str], root_netloc: str) -> bool:
    if has_static_extension(url):
        return False

    path = urlparse(url).path or "/"
    if is_obvious_service_path(path):
        return False
    allowed_domain = False
    for start_url in start_urls:
        start_netloc = urlparse(start_url).netloc
        if not same_site(url, start_netloc or root_netloc):
            continue
        allowed_domain = True
        start_path = (urlparse(start_url).path or "/").rstrip("/") or "/"
        if start_path in {"/", "/catalog"}:
            if not is_maunfeld_url(start_url):
                return True
            return path == "/" or path == "/catalog" or path.startswith("/catalog/")
        if path == start_path or path.startswith(start_path + "/"):
            return True

    if allowed_domain and is_probable_product_url(url):
        return True

    return False


def is_catalog_url(url: str) -> bool:
    path = urlparse(url).path or "/"
    return path == "/catalog" or path.startswith("/catalog/")


def exclusion_matches(url: str, pattern: str) -> bool:
    """РџСЂРѕРІРµСЂСЏРµС‚ URL РїРѕ РїРѕР»СЊР·РѕРІР°С‚РµР»СЊСЃРєРѕРјСѓ С€Р°Р±Р»РѕРЅСѓ РёСЃРєР»СЋС‡РµРЅРёСЏ."""
    pattern = pattern.strip()
    if not pattern:
        return False

    parsed = urlparse(url)
    full_url = url.rstrip("/") + "/"
    path = (parsed.path or "/").rstrip("/") + "/"
    normalized_pattern = pattern.rstrip("/") + "/"

    if "*" in pattern or "?" in pattern:
        return fnmatch(full_url, pattern) or fnmatch(path, pattern)

    if pattern.startswith(("http://", "https://")):
        return full_url.startswith(normalized_pattern)

    return path.startswith(normalized_pattern) or pattern in parsed.path


def product_url_matches_filters(url: str, filters: Iterable[str]) -> bool:
    patterns = [str(pattern).strip().lower() for pattern in filters if str(pattern).strip()]
    if not patterns:
        return True

    parsed = urlparse(url)
    haystack = f"{url} {parsed.path}".lower()
    return any(pattern in haystack or fnmatch(haystack, pattern) for pattern in patterns)


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ").replace("\u2009", " ")).strip()


def split_text_lines(value: str) -> List[str]:
    return [clean_text(line) for line in re.split(r"[\n\r]+", value) if clean_text(line)]


MODEL_BRANDS = {
    "QYRON",
    "BORK",
    "DYSON",
    "DREAME",
    "SMEG",
    "POLARIS",
    "HAIER",
    "ROWENTA",
    "TEFAL",
    "BRAUN",
    "BOSCH",
    "KITFORT",
    "MAUNFELD",
}

MODEL_COLOR_WORDS = {
    "BLACK",
    "WHITE",
    "GREY",
    "GRAY",
    "SILVER",
    "GOLD",
    "RED",
    "BLUE",
    "GREEN",
    "PINK",
    "BEIGE",
    "BROWN",
    "ORANGE",
    "IVORY",
    "Р§Р•Р РќР«Р™",
    "Р§РЃР РќР«Р™",
    "Р‘Р•Р›Р«Р™",
    "РЎР•Р Р«Р™",
    "РЎР•Р Р•Р‘Р РРЎРўР«Р™",
    "Р—РћР›РћРўРћР™",
    "РљР РђРЎРќР«Р™",
    "РЎРРќРР™",
    "Р—Р•Р›Р•РќР«Р™",
    "Р—Р•Р›РЃРќР«Р™",
    "Р РћР—РћР’Р«Р™",
    "Р‘Р•Р–Р•Р’Р«Р™",
    "РљРћР РР§РќР•Р’Р«Р™",
}


def model_tokens_after_brand(value: str) -> str:
    tokens = re.findall(r"[A-Za-z\u0400-\u04FF0-9]+(?:[./_-][A-Za-z\u0400-\u04FF0-9]+)*", clean_text(value))
    if not tokens:
        return ""

    for index, token in enumerate(tokens):
        if token.upper() not in MODEL_BRANDS:
            continue

        model_parts = []
        for candidate in tokens[index + 1 : index + 6]:
            candidate_clean = candidate.strip(" .,/\\_-")
            candidate_upper = candidate_clean.upper()
            if not candidate_clean or candidate_upper in MODEL_COLOR_WORDS:
                break
            if not re.search(r"[A-Za-z0-9]", candidate_clean):
                break
            if any(char.isdigit() for char in candidate_clean) or model_parts:
                model_parts.append(candidate_clean)
                continue
            if re.fullmatch(r"[A-Za-z]{1,5}", candidate_clean):
                model_parts.append(candidate_clean)
                continue
            break

        if model_parts and any(any(char.isdigit() for char in part) for part in model_parts):
            return " ".join(model_parts).upper()

    return ""


def brand_slug_from_url(url: str) -> str:
    parts = [part.lower() for part in urlparse(url).path.split("/") if part]
    if not parts:
        return ""
    candidate = parts[-1]
    if candidate in {brand.lower() for brand in MODEL_BRANDS if brand != "MAUNFELD"}:
        return candidate
    return ""


def matches_listing_brand(current_url: str, product_url: str, source_text: str = "") -> bool:
    brand = brand_slug_from_url(current_url)
    if not brand:
        return True
    haystack = f"{product_url} {source_text}".lower()
    return brand in haystack


def technopark_model_from_url(product_url: str) -> str:
    if not is_technopark_url(product_url):
        return ""
    slug = urlparse(product_url).path.rstrip("/").split("/")[-1].lower()
    brands = "|".join(re.escape(brand.lower()) for brand in MODEL_BRANDS if brand != "MAUNFELD")
    match = re.search(rf"-(?:{brands})-([a-z0-9][a-z0-9-]*?)(?:-\d{{5,}})?$", slug)
    if not match:
        return ""
    model = match.group(1).replace("-", " ").strip()
    return model.upper()


def kuppersberg_model_from_url(product_url: str) -> str:
    if not is_kuppersberg_product_url(product_url):
        return ""
    slug = urlparse(product_url).path.strip("/").split("/")[-1]
    parts = [part for part in re.split(r"[_-]+", slug) if part]
    if not parts:
        return ""
    return " ".join(part.upper() if re.search(r"\d", part) or len(part) <= 3 else part.capitalize() for part in parts)


def normalize_kuppersberg_model(value: str, product_url: str = "") -> str:
    text = clean_text(value)
    if text:
        tokens = re.findall(r"[A-Za-z0-9]+", text)
        for index, token in enumerate(tokens):
            if re.search(r"[A-Za-z]", token) and (re.search(r"\d", token) or len(token) <= 4):
                return " ".join(tokens[index : index + 5]).strip()
    return kuppersberg_model_from_url(product_url)


def normalize_model(value: str, product_url: str = "") -> str:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ РјР°СЂРєРёСЂРѕРІРєСѓ РјРѕРґРµР»Рё Р±РµР· РїРѕР»РЅРѕРіРѕ С‚РѕРІР°СЂРЅРѕРіРѕ РЅР°Р·РІР°РЅРёСЏ."""
    text = clean_text(value)
    url_model = technopark_model_from_url(product_url)
    if url_model:
        return url_model
    if is_kuppersberg_url(product_url):
        kuppersberg_model = normalize_kuppersberg_model(text, product_url)
        if kuppersberg_model:
            return kuppersberg_model

    if not text:
        return ""

    # Р§Р°СЃС‚С‹Р№ СЃР»СѓС‡Р°Р№: "РЁРєР°С„ РґСѓС…РѕРІРѕР№ MAUNFELD AEOC6040B" -> "AEOC6040B".
    brand_match = re.search(r"\bMAUNFELD\b\s+([A-Z0-9][A-Z0-9./\\_-]{2,})", text, re.IGNORECASE)
    if brand_match:
        return brand_match.group(1).strip(" .,/\\_-").replace("\\", "/").upper()

    generic_brand_model = model_tokens_after_brand(text)
    if generic_brand_model:
        return generic_brand_model

    latin_model_text = text.replace("\\", "/")
    latin_model_tokens = re.findall(r"[A-Za-z0-9./_-]+", latin_model_text)
    if (
        latin_model_tokens
        and " ".join(latin_model_tokens).strip() == re.sub(r"\s+", " ", latin_model_text).strip()
        and 1 <= len(latin_model_tokens) <= 6
        and any(any(char.isdigit() for char in token) for token in latin_model_tokens)
        and any(any(char.isalpha() for char in token) for token in latin_model_tokens)
        and latin_model_tokens[0].upper() not in {"SERIE", "SERIES"}
        and latin_model_tokens[0].upper() not in MODEL_BRANDS
    ):
        return " ".join(token.strip(" .,/\\_-").upper() for token in latin_model_tokens if token.strip(" .,/\\_-"))

    ascii_tokens = re.findall(r"[A-Za-z0-9]+(?:[./_-][A-Za-z0-9]+)*", text)
    for start_index in range(max(0, len(ascii_tokens) - 6), len(ascii_tokens)):
        candidate_tokens = [token.strip(" .,/\\_-") for token in ascii_tokens[start_index:] if token.strip(" .,/\\_-")]
        if not (2 <= len(candidate_tokens) <= 6):
            continue
        if not any(any(char.isdigit() for char in token) for token in candidate_tokens):
            continue
        if not all(re.fullmatch(r"[A-Z0-9./_-]+", token) for token in candidate_tokens):
            continue
        if candidate_tokens[0].upper() in MODEL_BRANDS or candidate_tokens[0].upper() in {"SERIE", "SERIES"}:
            continue
        return " ".join(candidate_tokens).upper()

    ignored_tokens = {
        "MAUNFELD",
        "ONLINE",
        "SALE",
        "NEW",
        "РћРќР›РђР™Рќ",
        "Р РђРЎРџР РћР”РђР–Рђ",
        "РќРћР’РРќРљРђ",
    }
    code_tokens = []
    for token in re.findall(r"[A-Z\u0400-\u04FF0-9][A-Z\u0400-\u04FF0-9./\\_-]{2,}", text, flags=re.IGNORECASE):
        cleaned = token.strip(" .,/\\_-")
        if cleaned.upper() in ignored_tokens:
            continue
        has_digit = any(char.isdigit() for char in cleaned)
        has_letter = any(char.isalpha() for char in cleaned)
        if has_digit and has_letter:
            code_tokens.append(cleaned)

    if code_tokens:
        return code_tokens[-1].replace("\\", "/").upper()

    # РџРѕСЃР»РµРґРЅРёР№ С€Р°РЅСЃ РґР»СЏ Maunfeld: РјРѕРґРµР»СЊ С‡Р°СЃС‚Рѕ Р»РµР¶РёС‚ РІ РєРѕРЅС†Рµ slug РїРѕСЃР»Рµ "-maunfeld-".
    slug = urlparse(product_url).path.rstrip("/").split("/")[-1]
    slug_match = re.search(r"(?:^|-)maunfeld-([a-z0-9-]+)$", slug, re.IGNORECASE)
    if slug_match:
        return slug_match.group(1).replace("-", "").upper()

    return text


def first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return ""


def normalize_price_value(value: object) -> str:
    text = clean_text(str(value or ""))
    if not text:
        return ""
    match = PRICE_RE.search(text)
    if match:
        return clean_text(match.group(0))
    digits = re.sub(r"[^\d]", "", text)
    if digits and len(digits) >= 2:
        return f"{int(digits):,}".replace(",", " ") + " \u20bd"
    return ""


def jsonld_items(soup: BeautifulSoup) -> Iterable[Any]:
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data


def iter_json_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_nodes(child)


def type_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.lower() == expected.lower()
    if isinstance(value, list):
        return any(type_contains(item, expected) for item in value)
    return False


def extract_offer_price(offers: Any) -> str:
    for offer in iter_json_nodes(offers):
        for key in ("price", "lowPrice", "highPrice"):
            price = normalize_price_value(offer.get(key))
            if price:
                return price
    return ""


def extract_schema_product(soup: BeautifulSoup, url: str, fallback_price: str = "") -> Optional[Dict[str, str]]:
    for item in jsonld_items(soup):
        for node in iter_json_nodes(item):
            if not type_contains(node.get("@type"), "Product"):
                continue
            model = clean_text(str(node.get("model") or node.get("sku") or node.get("name") or ""))
            price = extract_offer_price(node.get("offers")) or fallback_price
            item_url = normalize_url(str(node.get("url") or ""), url) or url
            if model and price:
                return {"url": item_url, "model": normalize_model(model, item_url), "price": price}
    return None


def extract_schema_listing_products(soup: BeautifulSoup, current_url: str) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()
    for item in jsonld_items(soup):
        for node in iter_json_nodes(item):
            if not type_contains(node.get("@type"), "Product"):
                continue
            product_url = normalize_url(str(node.get("url") or ""), current_url) or ""
            if product_url and not is_probable_product_url(product_url):
                product_url = ""
            model = clean_text(str(node.get("model") or node.get("sku") or node.get("name") or ""))
            price = extract_offer_price(node.get("offers"))
            if not product_url or not model or not price or product_url in seen_urls:
                continue
            seen_urls.add(product_url)
            products.append({"url": product_url, "model": normalize_model(model, product_url), "price": price})
    return products


def find_labeled_value(soup: BeautifulSoup, labels: Iterable[str]) -> str:
    """РС‰РµС‚ Р·РЅР°С‡РµРЅРёРµ СЂСЏРґРѕРј СЃ РїРѕРґРїРёСЃСЊСЋ РІСЂРѕРґРµ 'РђСЂС‚РёРєСѓР»' РёР»Рё 'РњРѕРґРµР»СЊ'."""
    label_regex = re.compile("|".join(re.escape(label) for label in labels), re.IGNORECASE)

    for row in soup.select("tr, li, .row, .item, .chars__item, .characteristics__item"):
        row_text = clean_text(row.get_text(" ", strip=True))
        if not label_regex.search(row_text):
            continue

        value_node = row.select_one(".val, .value, td:last-child, span:last-child, div:last-child")
        if value_node:
            value = clean_text(value_node.get_text(" ", strip=True))
            value = label_regex.sub("", value).strip(" :вЂ”-")
            if value:
                return value

        value = label_regex.sub("", row_text).strip(" :вЂ”-")
        if value:
            return value

    page_text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"(?:Артикул|Модель|Art:)\s*[:\-]?\s*([A-Za-z\u0400-\u04FF0-9][^|]{1,80})", page_text)
    if match:
        return clean_text(match.group(1)).split(" Р’ РЅР°Р»РёС‡РёРё")[0].strip()

    return ""


def extract_maunfeld_article(soup: BeautifulSoup) -> str:
    """Р”Р»СЏ Maunfeld РјРѕРґРµР»СЊ Р±РµСЂРµРј С‚РѕР»СЊРєРѕ РёР· С…Р°СЂР°РєС‚РµСЂРёСЃС‚РёРєРё 'РђСЂС‚РёРєСѓР»'."""
    for row in soup.select("li, tr, .item, .features-grid__item, .characteristics__item"):
        name_node = row.select_one(".name")
        value_node = row.select_one(".val")
        if name_node and value_node:
            name = clean_text(name_node.get_text(" ", strip=True))
            value = clean_text(value_node.get_text(" ", strip=True))
            if name.lower() == "Р°СЂС‚РёРєСѓР»" and value:
                return value

        row_text = clean_text(row.get_text(" ", strip=True))
        if not row_text.lower().startswith("Р°СЂС‚РёРєСѓР»"):
            continue

        value = re.sub(r"^РђСЂС‚РёРєСѓР»\s*", "", row_text, flags=re.IGNORECASE).strip(" :вЂ”-")
        if value:
            return value

    # Fallback РґР»СЏ С‚РµРєСЃС‚РѕРІРѕРіРѕ HTML, РіРґРµ С…Р°СЂР°РєС‚РµСЂРёСЃС‚РёРєРё СѓР¶Рµ СЂР°Р·РІРµСЂРЅСѓС‚С‹ Р±РµР· РєР»Р°СЃСЃРѕРІ.
    page_lines = split_text_lines(soup.get_text("\n", strip=True))
    for line in page_lines:
        if line.lower().startswith("Р°СЂС‚РёРєСѓР» "):
            value = re.sub(r"^РђСЂС‚РёРєСѓР»\s*", "", line, flags=re.IGNORECASE).strip(" :вЂ”-")
            if value:
                return value

    return ""


def extract_price(soup: BeautifulSoup) -> str:
    meta_price = soup.select_one(
        '[itemprop="price"], meta[property="product:price:amount"], meta[property="og:price:amount"]'
    )
    if meta_price:
        value = meta_price.get("content") or meta_price.get("value") or meta_price.get_text(" ", strip=True)
        if value:
            return normalize_price_value(value)

    price = first_text(
        soup,
        [
            "span.price--detail .nobr",
            ".price--detail .nobr",
            ".price.price--detail",
            ".product-detail .price",
            ".detail .price",
            ".product-price",
            ".price-current",
            "[class*='current-price']",
            "[class*='product-price']",
            "[class*='price--detail']",
        ],
    )
    if price:
        match = PRICE_RE.search(price)
        return clean_text(match.group(0) if match else price)

    page_text = clean_text(soup.get_text(" ", strip=True))
    match = PRICE_RE.search(page_text)
    return clean_text(match.group(0)) if match else ""


def is_probable_product_url(url: str) -> bool:
    if is_technopark_product_url(url):
        return True
    if is_kuppersberg_product_url(url):
        return True
    return looks_like_product_path(urlparse(url).path)


def find_card_container(price_node, current_url: str) -> Optional[object]:
    """РќР°С…РѕРґРёС‚ Р±Р»РёР¶Р°Р№С€РёР№ РєРѕРЅС‚РµР№РЅРµСЂ РєР°СЂС‚РѕС‡РєРё С‚РѕРІР°СЂР° РІРѕРєСЂСѓРі С†РµРЅС‹."""
    node = price_node if hasattr(price_node, "select") else price_node.parent
    best = None
    for _ in range(10):
        if not node or getattr(node, "name", None) in {"body", "html"}:
            break

        text = clean_text(node.get_text(" ", strip=True))
        links = node.select("a[href]") if hasattr(node, "select") else []
        images = node.select("img") if hasattr(node, "select") else []
        product_links = [
            link
            for link in links
            if is_probable_product_url(normalize_url(link.get("href", ""), current_url) or "")
        ]

        if len(text) <= 1800 and (product_links or images):
            best = node
            if product_links:
                break
        node = node.parent
    return best


def extract_model_from_card(card, price: str) -> str:
    title_selectors = [
        "[class*='name']",
        "[class*='title']",
        "[class*='product'] a",
        "a[href*='/catalog/']",
    ]
    for selector in title_selectors:
        for node in card.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if is_good_model_text(text):
                return text

    ignored = {
        "РѕРЅР»Р°Р№РЅ",
        "СЂР°СЃРїСЂРѕРґР°Р¶Р°",
        "РЅРѕРІРёРЅРєР°",
        "СЃРґРµР»Р°РЅРѕ РІ РµРІСЂРѕРїРµ",
        "РєСѓС…РѕРЅРЅС‹Рј СЃС‚СѓРґРёСЏРј",
        "РІ РЅР°Р»РёС‡РёРё",
        "РЅРµС‚ РІ РЅР°Р»РёС‡РёРё",
        "РїРѕ СѓРјРѕР»С‡Р°РЅРёСЋ",
        "РїРѕ РїРѕРїСѓР»СЏСЂРЅРѕСЃС‚Рё",
    }
    lines = split_text_lines(card.get_text("\n", strip=True))
    lines = [
        line
        for line in lines
        if line.lower() not in ignored and not PRICE_RE.search(line) and line != price
    ]

    for line in lines:
        if is_good_model_text(line):
            return line

    return ""


def is_good_model_text(text: str) -> bool:
    text = clean_text(text)
    if len(text) < 8 or len(text) > 180:
        return False
    lowered = text.lower()
    if lowered in {
        "РІ РЅР°Р»РёС‡РёРё",
        "РЅРµС‚ РІ РЅР°Р»РёС‡РёРё",
        "РѕРЅР»Р°Р№РЅ",
        "СЂР°СЃРїСЂРѕРґР°Р¶Р°",
        "РЅРѕРІРёРЅРєР°",
        "РєСѓРїРёС‚СЊ",
        "РїРѕРґСЂРѕР±РЅРµРµ",
    }:
        return False
    if PRICE_RE.search(text):
        return False
    return "maunfeld" in lowered or bool(re.search(r"[A-Z\u0400-\u04FF]{2,}[\w.\-/]*\d", text, re.IGNORECASE))


def extract_product_url_from_card(card, current_url: str) -> str:
    for link in card.select("a[href]"):
        normalized = normalize_url(link.get("href", ""), current_url)
        if normalized and is_probable_product_url(normalized):
            return normalized
    return current_url


def find_card_container_from_link(link, current_url: str) -> Optional[object]:
    node = link
    best = None
    target_url = normalize_url(link.get("href", ""), current_url)
    for _ in range(10):
        if not node or getattr(node, "name", None) in {"body", "html"}:
            break
        if not hasattr(node, "select"):
            node = node.parent
            continue

        text = clean_text(node.get_text(" ", strip=True))
        links = [
            item
            for item in node.select("a[href]")
            if is_probable_product_url(normalize_url(item.get("href", ""), current_url) or "")
        ]
        same_product_links = [
            item
            for item in links
            if normalize_url(item.get("href", ""), current_url) == target_url
        ]
        class_text = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
        if same_product_links and (getattr(node, "name", None) == "article" or "product-card" in class_text):
            return node
        if PRICE_RE.search(text) and len(text) <= 2200 and links:
            best = node
            if same_product_links and len({normalize_url(item.get("href", ""), current_url) for item in links}) <= 3:
                break
        node = node.parent
    return best


def extract_listing_products_from_links(soup: BeautifulSoup, current_url: str, seen_urls: Set[str]) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    for link in soup.select("a[href]"):
        product_url = normalize_url(link.get("href", ""), current_url)
        if not product_url or not is_probable_product_url(product_url) or product_url in seen_urls:
            continue
        if not matches_listing_brand(current_url, product_url, link.get_text(" ", strip=True)):
            continue

        card = find_card_container_from_link(link, current_url)
        if not card:
            continue
        text = card.get_text(" ", strip=True)
        price_match = PRICE_RE.search(text)
        if not price_match:
            continue

        price = clean_text(price_match.group(0))
        model_source = clean_text(link.get_text(" ", strip=True)) or extract_model_from_card(card, price)
        model = normalize_model(model_source, product_url)
        if not model:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})

    return products


def decode_script_text(value: str) -> str:
    text = html_lib.unescape(value or "")
    text = text.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    if "\\u" in text:
        try:
            text = text.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")
        except UnicodeError:
            pass
    return text


def extract_price_near_text(value: str) -> str:
    price_match = PRICE_RE.search(value)
    if price_match:
        return clean_text(price_match.group(0))

    for key in ("price", "currentPrice", "actualPrice", "value"):
        match = re.search(rf'"{key}"\s*:\s*"?(\d{{3,9}})"?', value, re.IGNORECASE)
        if match:
            return normalize_price_value(match.group(1))
    return ""


def extract_name_near_text(value: str) -> str:
    for key in ("name", "title", "productName"):
        matches = re.findall(rf'"{key}"\s*:\s*"([^"]{{3,220}})"', value, flags=re.IGNORECASE)
        for match in matches:
            text = clean_text(html_lib.unescape(match))
            if is_good_model_text(text) or model_tokens_after_brand(text):
                return text
    return ""


def extract_listing_products_from_scripts(soup: BeautifulSoup, current_url: str, seen_urls: Set[str]) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    known_brand = "|".join(re.escape(brand.lower()) for brand in MODEL_BRANDS if brand != "MAUNFELD")
    product_url_re = re.compile(
        rf'(?:https?://[^"\'<>\s]+)?/[^"\'<>\s]+(?:-\d{{5,}}|-({known_brand})-[^"\'<>\s/]*\d[^"\'<>\s/]*)/?',
        re.IGNORECASE,
    )

    for script in soup.select("script"):
        raw = script.string or script.get_text("", strip=False)
        if not raw:
            continue
        text = decode_script_text(raw)
        if not text or "price" not in text.lower():
            continue

        for match in product_url_re.finditer(text):
            product_url = normalize_url(match.group(0), current_url)
            if not product_url or not is_probable_product_url(product_url) or product_url in seen_urls:
                continue

            left = max(0, match.start() - 2500)
            right = min(len(text), match.end() + 2500)
            window = text[left:right]
            if not matches_listing_brand(current_url, product_url, window):
                continue
            price = extract_price_near_text(window)
            name = extract_name_near_text(window)
            model = normalize_model(name, product_url)
            if not price or not model:
                continue

            seen_urls.add(product_url)
            products.append({"url": product_url, "model": model, "price": price})

    return products


def apply_extract_regex(value: str, pattern: str) -> str:
    text = clean_text(value)
    if not pattern:
        return text
    try:
        match = re.search(pattern, text, flags=re.IGNORECASE)
    except re.error:
        return text
    if not match:
        return text
    return clean_text(match.group(1) if match.groups() else match.group(0))


def replacement_flags(flag_text: str) -> int:
    flags = 0
    flags_text = flag_text.lower()
    if "i" in flags_text:
        flags |= re.IGNORECASE
    if "m" in flags_text:
        flags |= re.MULTILINE
    if "s" in flags_text:
        flags |= re.DOTALL
    return flags


def wildcard_rule_to_regex(pattern: str) -> str:
    result = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("{skip}", index):
            result.append(".*?")
            index += len("{skip}")
        elif pattern.startswith("{.}", index):
            result.append(".")
            index += len("{.}")
        else:
            result.append(re.escape(pattern[index]))
            index += 1
    return "".join(result)


def apply_replace_rules(value: str, rules_text: str) -> str:
    text = html_lib.unescape(value or "")
    if not rules_text:
        return text

    for raw_line in rules_text.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue
        pattern, replacement = line.split("|", 1)
        pattern = pattern.strip()
        replacement = replacement.strip()

        try:
            if pattern == "{br}":
                text = re.sub(r"\r\n|\r|\n", replacement, text)
                continue

            regex_match = re.fullmatch(r"\{reg\[#(.*)#([a-zA-Z]*)\]\}", pattern)
            if regex_match:
                regex_pattern, flags_text = regex_match.groups()
                text = re.sub(regex_pattern, replacement, text, flags=replacement_flags(flags_text))
                continue

            if "{skip}" in pattern or "{.}" in pattern:
                text = re.sub(wildcard_rule_to_regex(pattern), replacement, text, flags=re.DOTALL)
                continue

            text = text.replace(pattern, replacement)
        except re.error:
            continue

    return text


def strip_html_to_text(value: str) -> str:
    raw = html_lib.unescape(value or "")
    if "<" in raw and ">" in raw:
        return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return raw


def extract_between_markers(source: str, start_marker: str, end_marker: str) -> str:
    if not start_marker and not end_marker:
        return ""

    text = source or ""
    start_index = 0
    if start_marker:
        found_start = text.find(start_marker)
        if found_start < 0:
            return ""
        start_index = found_start + len(start_marker)

    end_index = len(text)
    if end_marker:
        found_end = text.find(end_marker, start_index)
        if found_end < 0:
            return ""
        end_index = found_end

    return text[start_index:end_index]


def extract_model_by_markers(source: str, rules: Dict[str, str]) -> str:
    return extract_between_markers(
        source,
        str(rules.get("model_start_marker", "")),
        str(rules.get("model_end_marker", "")),
    )


def prepare_rule_model(value: str, rules: Dict[str, str]) -> str:
    text = apply_replace_rules(value, str(rules.get("model_replace_rules", "")))
    text = strip_html_to_text(text)
    return clean_text(text)


def first_by_selector(root, selector: str) -> str:
    if not selector or not hasattr(root, "select"):
        return ""
    node = root.select_one(selector)
    if not node:
        return ""
    return clean_text(node.get("content") or node.get("value") or node.get_text(" ", strip=True))


def extract_prices(value: str) -> List[str]:
    return [clean_text(match.group(0)) for match in PRICE_RE.finditer(value or "")]


def extract_listing_products_by_rules(
    soup: BeautifulSoup,
    current_url: str,
    rules: Dict[str, str],
    seen_urls: Set[str],
) -> List[Dict[str, str]]:
    card_selector = rules.get("product_card_selector", "")
    if not card_selector:
        return []
    products: List[Dict[str, str]] = []
    for card in soup.select(card_selector):
        link_node = card.select_one(rules.get("product_url_selector", "")) if rules.get("product_url_selector") else None
        if not link_node:
            link_node = card.select_one("a[href]")
        product_url = normalize_url(link_node.get("href", "") if link_node else "", current_url)
        if not product_url or product_url in seen_urls or not is_probable_product_url(product_url):
            continue
        if not matches_listing_brand(current_url, product_url, card.get_text(" ", strip=True)):
            continue

        model = extract_model_by_markers(str(card), rules)
        if not model:
            model = first_by_selector(card, rules.get("model_selector", ""))
        if not model:
            model = extract_model_from_card(card, "")
        model = prepare_rule_model(model, rules)
        model = normalize_model(model, product_url)

        price = first_by_selector(card, rules.get("price_selector", ""))
        prices = extract_prices(price) or extract_prices(card.get_text(" ", strip=True))
        price = prices[-1] if prices else normalize_price_value(price)
        if not model or not price:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})
    return products


def extract_listing_products_from_common_cards(
    soup: BeautifulSoup,
    current_url: str,
    rules: Dict[str, str],
    seen_urls: Set[str],
) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    card_selectors = [
        ".catalog-card.js-ecom_product-item",
        ".js-ecom_product-item",
        "[class*='product-item']",
        "[class*='product-card']",
    ]
    cards = []
    seen_card_ids: Set[int] = set()
    for selector in card_selectors:
        for card in soup.select(selector):
            if id(card) in seen_card_ids:
                continue
            seen_card_ids.add(id(card))
            cards.append(card)

    for card in cards:
        product_url = extract_product_url_from_card(card, current_url)
        if not product_url or product_url in seen_urls or not is_probable_product_url(product_url):
            continue
        if not matches_listing_brand(current_url, product_url, card.get_text(" ", strip=True)):
            continue

        price_text = first_by_selector(card, rules.get("price_selector", ""))
        if not price_text:
            price_text = first_text(card, [".catalog-card__price", "[class*='price']"])
        prices = extract_prices(price_text) or extract_prices(card.get_text(" ", strip=True))
        price = prices[-1] if prices else normalize_price_value(price_text)
        if not price:
            continue

        model = extract_model_by_markers(str(card), rules)
        if not model:
            model = first_by_selector(card, rules.get("model_selector", ""))
        if not model:
            title_link = None
            for link in card.select("a[title][href]"):
                if normalize_url(link.get("href", ""), current_url) == product_url:
                    title_link = link
                    break
            if title_link is None:
                title_link = card.select_one("a[title][href]")
            model = title_link.get("title", "") if title_link else ""
        if not model:
            model = extract_model_from_card(card, price)
        model = prepare_rule_model(model, rules)
        model = normalize_model(model, product_url)
        if not model:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})

    return products


def extract_listing_products(current_url: str, html: str, rules: Optional[Dict[str, str]] = None) -> List[Dict[str, str]]:
    """РЎРѕР±РёСЂР°РµС‚ С‚РѕРІР°СЂС‹ РїСЂСЏРјРѕ СЃРѕ СЃС‚СЂР°РЅРёС†С‹ РєР°С‚РµРіРѕСЂРёРё/РєР°С‚Р°Р»РѕРіР°."""
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, str]] = extract_schema_listing_products(soup, current_url)
    price_sources = []
    seen_urls: Set[str] = {product["url"] for product in products}
    seen_source_ids: Set[int] = set()
    rules = normalize_extraction_rules(rules or {})

    products.extend(extract_listing_products_from_common_cards(soup, current_url, rules, seen_urls))

    for price_node in soup.find_all(string=PRICE_RE):
        price_sources.append(price_node)

    for node in soup.select("[class*='price'], [itemprop='price']"):
        text = clean_text(node.get_text(" ", strip=True) or node.get("content", "") or "")
        if PRICE_RE.search(text) and id(node) not in seen_source_ids:
            seen_source_ids.add(id(node))
            price_sources.append(node)

    for price_node in price_sources:
        if hasattr(price_node, "get_text"):
            source_text = price_node.get_text(" ", strip=True)
        else:
            source_text = str(price_node)
        price_match = PRICE_RE.search(source_text)
        if not price_match:
            continue

        price = clean_text(price_match.group(0))
        card = find_card_container(price_node, current_url)
        if not card:
            continue
        if is_kuppersberg_url(current_url):
            card_prices = extract_prices(card.get_text(" ", strip=True))
            if card_prices:
                price = card_prices[-1]

        product_url = extract_product_url_from_card(card, current_url)
        if product_url == current_url and not is_probable_product_url(current_url):
            continue
        if not matches_listing_brand(current_url, product_url, card.get_text(" ", strip=True)):
            continue
        model = normalize_model(extract_model_from_card(card, price), product_url)

        if not model or product_url in seen_urls:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})

    products.extend(extract_listing_products_from_links(soup, current_url, seen_urls))
    products.extend(extract_listing_products_from_scripts(soup, current_url, seen_urls))
    if rules:
        products.extend(extract_listing_products_by_rules(soup, current_url, rules, seen_urls))
    return products


def extract_product_data_by_rules(
    url: str,
    html: str,
    soup: BeautifulSoup,
    rules: Dict[str, str],
    fallback_price: str = "",
) -> Optional[Dict[str, str]]:
    if not rules:
        return None
    model = extract_model_by_markers(html, rules)
    if not model:
        model = first_by_selector(soup, rules.get("model_selector", ""))
    price = first_by_selector(soup, rules.get("price_selector", ""))
    model = prepare_rule_model(model, rules)
    prices = extract_prices(price) or extract_prices(soup.get_text(" ", strip=True))
    price = prices[-1] if prices else normalize_price_value(price or fallback_price)
    model = normalize_model(model, url)
    if model and price and is_probable_product_url(url):
        return {"url": url, "model": model, "price": price}
    return None


def extract_product_data(
    url: str,
    html: str,
    fallback_price: str = "",
    rules: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    ruled_product = extract_product_data_by_rules(url, html, soup, rules or {}, fallback_price)
    if ruled_product:
        return ruled_product
    path_parts = [part for part in urlparse(url).path.split("/") if part]
    h1 = first_text(soup, ["h1"])
    price = extract_price(soup) or fallback_price
    if is_maunfeld_url(url):
        model = extract_maunfeld_article(soup)
    else:
        schema_product = extract_schema_product(soup, url, price)
        if schema_product:
            return schema_product
        model = find_labeled_value(soup, ["РђСЂС‚РёРєСѓР»", "РњРѕРґРµР»СЊ", "Art:"])
    if not is_maunfeld_url(url):
        precise_model = first_text(
            soup,
            [
                ".product-description__subtitle",
                ".product-code",
                ".article",
                ".articul",
                ".sku",
            ],
        )
        if precise_model:
            model = precise_model
    model_from_labeled_value = bool(model)

    if not model:
        fallback_selectors = [
            ".product-description__subtitle",
            ".product-code",
            ".article",
            ".articul",
            ".sku",
        ]
        model = first_text(soup, fallback_selectors)
    if not model and h1:
        model = h1

    if price and model and is_maunfeld_url(url) and model_from_labeled_value:
        return {"url": url, "model": clean_text(model), "price": price}

    if rules:
        model = prepare_rule_model(model, rules)
    model = normalize_model(model, url)

    page_text = clean_text(soup.get_text(" ", strip=True))
    has_product_signal = any(
        signal in page_text
        for signal in ("РљРѕРґ С‚РѕРІР°СЂР°", "Р’ РєРѕСЂР·РёРЅСѓ", "РҐР°СЂР°РєС‚РµСЂРёСЃС‚РёРєРё", "Р’Р°С€Р° С†РµРЅР°", "РЎРѕРѕР±С‰РёС‚СЊ Рѕ РїРѕСЃС‚СѓРїР»РµРЅРёРё")
    )
    looks_like_product_url = is_probable_product_url(url)

    if price and model and looks_like_product_url and (
        has_product_signal
        or "MAUNFELD" in h1.upper()
        or is_kuppersberg_url(url)
        or (is_maunfeld_url(url) and model_from_labeled_value)
    ):
        return {"url": url, "model": model, "price": price}

    return None


def fetch_with_botasaurus_request(url: str) -> Optional[str]:
    """Fallback С‡РµСЂРµР· Botasaurus Request: Р±СЂР°СѓР·РµСЂРѕРїРѕРґРѕР±РЅС‹Р№ HTTP-Р·Р°РїСЂРѕСЃ СЃ Google Referrer."""
    try:
        from botasaurus.request import Request
        from botasaurus.request import request as botasaurus_request
    except ImportError:
        return None

    @botasaurus_request(max_retry=MAX_RETRIES)
    def _fetch_html(request_client: Request, target_url: str):
        response = request_client.get(target_url)
        response.raise_for_status()
        return {
            "content_type": response.headers.get("content-type", ""),
            "text": response.text,
        }

    try:
        result = _fetch_html(url)
    except Exception:
        return None

    if isinstance(result, list):
        result = result[0] if result else None
    if not isinstance(result, dict):
        return None

    content_type = result.get("content_type", "")
    html = result.get("text", "")
    if html and ("text/html" in content_type or "application/xhtml" in content_type or not content_type):
        return html
    return None


def fetch_with_botasaurus_browser(url: str, navigation: str = "direct") -> Optional[str]:
    """Fallback С‡РµСЂРµР· Botasaurus Browser РґР»СЏ СЃС‚СЂР°РЅРёС†, РєРѕС‚РѕСЂС‹Рј РЅСѓР¶РµРЅ РЅР°СЃС‚РѕСЏС‰РёР№ СЂРµРЅРґРµСЂРёРЅРі."""
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError:
        return None

    @browser(
        headless=True,
        add_arguments=["--headless=new"],
        window_size=[1280, 720],
        block_images_and_css=True,
        wait_for_complete_page_load=False,
        max_retry=1,
        output=None,
        close_on_crash=True,
        create_error_logs=False,
    )
    def _render_html(driver: Driver, target_url: str):
        if navigation == "direct" and hasattr(driver, "get"):
            driver.get(target_url)
        else:
            driver.google_get(target_url)
        driver.sleep(2)
        for _ in range(4):
            try:
                driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            driver.sleep(0.8)
        return driver.page_html

    try:
        with HEADLESS_BROWSER_SEMAPHORE:
            result = _render_html(url)
    except Exception:
        return None

    if isinstance(result, list):
        result = result[0] if result else None
    return result if isinstance(result, str) and result.strip() else None


def fetch_with_botasaurus_visible_browser(url: str) -> Optional[str]:
    """Р’РёРґРёРјС‹Р№ Р±СЂР°СѓР·РµСЂ СЃ РїРѕСЃС‚РѕСЏРЅРЅС‹Рј РїСЂРѕС„РёР»РµРј: РЅСѓР¶РµРЅ РґР»СЏ Qrator/JS-С‡РµР»Р»РµРЅРґР¶РµР№ РІСЂРѕРґРµ Technopark."""
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError:
        return None

    @browser(
        headless=False,
        profile="protected_sites_visible",
        window_size=[1280, 720],
        add_arguments=["--window-position=40,40"],
        block_images_and_css=False,
        wait_for_complete_page_load=True,
        reuse_driver=False,
        output=None,
        close_on_crash=True,
        create_error_logs=False,
        max_retry=1,
    )
    def _render_html(driver: Driver, target_url: str):
        driver.get(target_url)
        driver.sleep(8)
        for _ in range(3):
            try:
                driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            driver.sleep(0.8)
        return driver.page_html

    try:
        with VISIBLE_BROWSER_LOCK:
            result = _render_html(technopark_slash_url(url))
    except Exception:
        return None

    if isinstance(result, list):
        result = result[0] if result else None
    return result if isinstance(result, str) and result.strip() else None


def fetch_with_crawl4ai(url: str) -> Optional[str]:
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler
    except ImportError:
        return None

    async def _fetch() -> Optional[str]:
        async with AsyncWebCrawler() as crawler:
            result = await crawler.arun(url=url)
            html = getattr(result, "html", "") or getattr(result, "cleaned_html", "")
            return html if isinstance(html, str) else None

    try:
        return asyncio.run(_fetch())
    except Exception:
        return None


def fetch_with_firecrawl(url: str) -> Optional[str]:
    api_key = os.environ.get("FIRECRAWL_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from firecrawl import FirecrawlApp
    except ImportError:
        try:
            from firecrawl import Firecrawl
        except ImportError:
            return None
        try:
            app_client = Firecrawl(api_key=api_key)
            result = app_client.scrape(url, formats=["html"])
        except Exception:
            return None
    else:
        try:
            app_client = FirecrawlApp(api_key=api_key)
            result = app_client.scrape_url(url, formats=["html"])
        except Exception:
            return None

    if isinstance(result, dict):
        for key in ("html", "rawHtml", "content"):
            value = result.get(key)
            if isinstance(value, str) and value.strip():
                return value
        data = result.get("data")
        if isinstance(data, dict):
            for key in ("html", "rawHtml", "content"):
                value = data.get(key)
                if isinstance(value, str) and value.strip():
                    return value
    return None


def fetch_with_scrapy(url: str) -> Optional[str]:
    try:
        import scrapy  # noqa: F401
    except ImportError:
        return None
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.text
    except Exception:
        return None


def fetch_with_crawlee(url: str) -> Optional[str]:
    try:
        import crawlee  # noqa: F401
    except ImportError:
        return None
    try:
        response = requests.get(
            url,
            headers={
                "User-Agent": (
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
            timeout=REQUEST_TIMEOUT,
        )
        response.raise_for_status()
        return response.text
    except Exception:
        return None


class MaunfeldCrawler:
    def __init__(
        self,
        start_urls: List[str],
        run_id: int,
        stop_signal: threading.Event,
        finish_signal: threading.Event,
        thread_count: int,
        project: Optional[Dict[str, object]] = None,
        exclusions: Optional[List[str]] = None,
        product_url_filters: Optional[List[str]] = None,
        extraction_rules: Optional[Dict[str, str]] = None,
        connection_method: str = "requests",
        auto_connection_fallback: bool = True,
    ):
        self.run_id = run_id
        self.stop_signal = stop_signal
        self.finish_signal = finish_signal
        self.thread_count = max(1, min(int(thread_count or 4), 16))
        self.start_urls = normalize_start_urls(start_urls)
        self.start_url = self.start_urls[0]
        self.root_netloc = urlparse(self.start_url).netloc
        self.project = project
        self.exclusions = exclusions if exclusions is not None else load_exclusions()
        self.product_url_filters = normalize_patterns(product_url_filters or [])
        self.extraction_rules = normalize_extraction_rules(extraction_rules or {})
        self.connection_method = normalize_connection_method(connection_method)
        self.auto_connection_fallback = bool(auto_connection_fallback)
        self.thread_local = threading.local()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        self.queue: Queue[str] = Queue()
        self.queued: Set[str] = set()
        self.in_progress: Set[str] = set()
        self.visited: Set[str] = set()
        self.skipped_urls: Set[str] = set()
        self.result_urls: Set[str] = set()
        self.pending_prices: Dict[str, str] = {}
        self.results: List[Dict[str, str]] = []
        self.failed_attempts: Dict[str, int] = {}
        self.data_lock = threading.Lock()
        self.excel_finalized = False
        self.started_at = 0.0
        self.elapsed_before_resume = 0.0

    def update_state(self, **kwargs: object) -> None:
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            update_project_state(self.project, **kwargs)
        else:
            update_state(self.run_id, **kwargs)

    def reset_state(self, status: str = "idle") -> None:
        if self.project is not None:
            reset_project_state(self.project, status)
        else:
            reset_state(status, self.run_id, self.thread_count)

    def log(self, message: str, level: str = "info") -> None:
        if self.project is not None:
            add_project_log(self.project, message, level)

    def get_session(self) -> requests.Session:
        session = getattr(self.thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            self.thread_local.session = session
        return session

    def fetch_with_requests(self, url: str) -> Optional[str]:
        last_error = ""
        candidate_urls = [url]
        slash_url = technopark_slash_url(url)
        if slash_url != url:
            candidate_urls.append(slash_url)
        for attempt in range(1, MAX_RETRIES + 1):
            if self.stop_signal.is_set():
                return None
            for candidate_url in candidate_urls:
                try:
                    response = self.get_session().get(candidate_url, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        return None
                    if not looks_blocked_or_empty(response.text):
                        return response.text

                    last_error = "СЃС‚СЂР°РЅРёС†Р° РїРѕС…РѕР¶Р° РЅР° Р±Р»РѕРєРёСЂРѕРІРєСѓ РёР»Рё РїСѓСЃС‚РѕР№ JS-С€Р°Р±Р»РѕРЅ"
                    break
                except requests.RequestException as exc:
                    last_error = str(exc)
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {401, 403}:
                        continue
                    break
            if last_error == "СЃС‚СЂР°РЅРёС†Р° РїРѕС…РѕР¶Р° РЅР° Р±Р»РѕРєРёСЂРѕРІРєСѓ РёР»Рё РїСѓСЃС‚РѕР№ JS-С€Р°Р±Р»РѕРЅ":
                break
            if self.stop_signal.is_set():
                return None
            if attempt < MAX_RETRIES:
                time.sleep(min(attempt, 3))
        if last_error:
            self.log(f"requests РЅРµ СЃРјРѕРі Р·Р°РіСЂСѓР·РёС‚СЊ {url}: {last_error}", "warning")
        return None

    def fetch_by_method(self, url: str, method: str) -> Optional[str]:
        target_url = technopark_slash_url(url)
        if method == "requests":
            return self.fetch_with_requests(target_url)
        if method == "botasaurus-request":
            return fetch_with_botasaurus_request(target_url)
        if method == "botasaurus-browser":
            return fetch_with_botasaurus_browser(target_url, "google")
        if method == "botasaurus-browser-direct":
            return fetch_with_botasaurus_browser(target_url, "direct")
        if method == "botasaurus-visible":
            return fetch_with_botasaurus_visible_browser(target_url)
        if method == "crawl4ai":
            return fetch_with_crawl4ai(target_url)
        if method == "firecrawl":
            return fetch_with_firecrawl(target_url)
        if method == "scrapy":
            return fetch_with_scrapy(target_url)
        if method == "crawlee":
            return fetch_with_crawlee(target_url)
        return None

    def method_sequence(self, url: str = "") -> List[str]:
        if self.auto_connection_fallback and is_technopark_url(url):
            if self.connection_method == "botasaurus-visible":
                return ["botasaurus-visible"]

            preferred = ["botasaurus-visible", "requests"]
            if self.connection_method == "botasaurus-request":
                return preferred
            methods = [self.connection_method]
            methods.extend(method for method in preferred if method not in methods)
            return methods

        methods = [self.connection_method]
        if self.auto_connection_fallback:
            methods.extend(method for method in GENERIC_FALLBACK_METHODS if method not in methods)
        return methods

    def fetch(self, url: str) -> Optional[str]:
        last_method = ""
        for method in self.method_sequence(url):
            if self.stop_signal.is_set():
                return None
            last_method = method
            html = self.fetch_by_method(url, method)
            if html and not looks_blocked_or_empty(html):
                if method != self.connection_method:
                    self.log(f"РђРІС‚РѕРїРµСЂРµРєР»СЋС‡РµРЅРёРµ РїРѕРґРєР»СЋС‡РµРЅРёСЏ: {method} РґР»СЏ {url}", "warning")
                return html
            self.log(f"РњРµС‚РѕРґ РїРѕРґРєР»СЋС‡РµРЅРёСЏ {method} РЅРµ СЃСЂР°Р±РѕС‚Р°Р» РґР»СЏ {url}", "warning")

        self.update_state(error=f"РћР±С‹С‡РЅС‹Р№ Р·Р°РїСЂРѕСЃ РЅРµ СЃСЂР°Р±РѕС‚Р°Р» РґР»СЏ {url}. РџСЂРѕР±СѓСЋ Botasaurus...")
        self.update_state(
            error=(
                f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ {url}. РџРѕСЃР»РµРґРЅРёР№ РјРµС‚РѕРґ: {last_method}. "
                "РџСЂРѕРІРµСЂСЊС‚Рµ СЃРїРѕСЃРѕР± РїРѕРґРєР»СЋС‡РµРЅРёСЏ РёР»Рё РІРєР»СЋС‡РёС‚Рµ Р°РІС‚РѕРїРµСЂРµРєР»СЋС‡РµРЅРёРµ."
            ),
        )
        self.log(f"РќРµ СѓРґР°Р»РѕСЃСЊ Р·Р°РіСЂСѓР·РёС‚СЊ {url}. РџРѕСЃР»РµРґРЅРёР№ РјРµС‚РѕРґ: {last_method}", "error")
        return None

    def is_excluded(self, url: str) -> bool:
        patterns = self.exclusions

        matched = any(exclusion_matches(url, pattern) for pattern in patterns)
        if matched and url not in self.skipped_urls:
            with self.data_lock:
                self.skipped_urls.add(url)
                skipped_count = len(self.skipped_urls)
            self.update_state(skipped=skipped_count)
        return matched

    def is_product_allowed(self, url: str) -> bool:
        return product_url_matches_filters(url, self.product_url_filters)

    def remember_listing_price(self, product_url: str, price: str) -> None:
        with self.data_lock:
            if product_url and price:
                self.pending_prices[product_url] = price

    def get_listing_price(self, product_url: str) -> str:
        with self.data_lock:
            return self.pending_prices.get(product_url, "")

    def enqueue(self, url: Optional[str], force: bool = False) -> None:
        if not url or url in self.visited or url in self.queued or url in self.in_progress:
            return
        if is_probable_product_url(url) and not self.is_product_allowed(url):
            return
        with self.data_lock:
            if url in self.result_urls:
                return
        if not force and not should_follow_project_url(url, self.start_urls, self.root_netloc):
            return
        if force and (not same_site(url, self.root_netloc) or has_static_extension(url)):
            return
        if self.is_excluded(url):
            return
        self.queue.put(url)
        self.queued.add(url)

    def requeue_pending(self, pending_urls: Iterable[str]) -> None:
        with self.data_lock:
            for url in pending_urls:
                self.in_progress.discard(url)
        for url in pending_urls:
            self.enqueue(url, force=True)

    def extract_links(self, html: str, current_url: str) -> None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            normalized = normalize_url(link.get("href", ""), current_url)
            self.enqueue(normalized)

    def add_products(self, products: Iterable[Dict[str, str]]) -> int:
        added = 0
        with self.data_lock:
            for product in products:
                product_url = product.get("url", "")
                model = product.get("model", "")
                price = product.get("price", "")
                if product_url and not self.is_product_allowed(product_url):
                    continue
                if not product_url or not model or not price or product_url in self.result_urls:
                    continue
                self.result_urls.add(product_url)
                self.results.append(product)
                added += 1
        return added

    def snapshot_counts(self) -> Dict[str, int]:
        with self.data_lock:
            return {
                "visited": len(self.visited),
                "results": len(self.results),
                "skipped": len(self.skipped_urls),
            }

    def snapshot_results(self) -> List[Dict[str, str]]:
        with self.data_lock:
            return [dict(item) for item in self.results]

    def refresh_progress(self, current_url: str = "") -> None:
        remaining = self.queue.qsize()
        counts = self.snapshot_counts()
        processed = counts["visited"]
        total_known = processed + remaining
        percent = int((processed / total_known) * 100) if total_known else 0
        elapsed = self.elapsed_seconds()
        eta = None
        if processed > 0 and remaining > 0:
            eta = int((elapsed / processed) * remaining)
        self.update_state(
            percent=percent,
            currenturl=current_url,
            totalprocessed=processed,
            processed_products=counts["results"],
            found_products=counts["results"],
            skipped=counts["skipped"],
            thread_count=self.thread_count,
            elapsed_seconds=int(elapsed),
            eta_seconds=eta,
        )

    def elapsed_seconds(self) -> float:
        if self.started_at:
            return self.elapsed_before_resume + max(0.0, time.time() - self.started_at)
        return self.elapsed_before_resume

    def process_page(self, url: str, html: str) -> None:
        listing_products = extract_listing_products(url, html, self.extraction_rules)

        if not listing_products and (is_catalog_url(url) or not is_probable_product_url(url)) and not PRICE_RE.search(html):
            self.update_state(
                error=f"РќР° СЃС‚СЂР°РЅРёС†Рµ РєР°С‚Р°Р»РѕРіР° РЅРµС‚ С†РµРЅ РІ HTML. Р РµРЅРґРµСЂСЋ С‡РµСЂРµР· Botasaurus: {url}",
            )
            self.log(f"Р РµРЅРґРµСЂРёРЅРі РєР°С‚Р°Р»РѕРіР° С‡РµСЂРµР· Botasaurus: {url}", "warning")
            rendered_html = fetch_with_botasaurus_browser(url)
            if rendered_html and not looks_blocked_or_empty(rendered_html):
                html = rendered_html
                listing_products = extract_listing_products(url, html, self.extraction_rules)
                self.update_state(error="")

        if is_maunfeld_url(url):
            for product in listing_products:
                product_url = product.get("url", "")
                self.remember_listing_price(product_url, product.get("price", ""))
                self.enqueue(product_url, force=True)
        else:
            for product in listing_products:
                product_url = product.get("url", "")
                self.remember_listing_price(product_url, product.get("price", ""))
                self.enqueue(product_url, force=True)
            self.add_products(listing_products)

        product = extract_product_data(url, html, self.get_listing_price(url), self.extraction_rules)
        if product:
            self.add_products([product])

        if is_technopark_url(url):
            self.log(f"РЎС‚СЂР°РЅРёС†Р° РѕР±СЂР°Р±РѕС‚Р°РЅР°: {url}. РќР°Р№РґРµРЅРѕ С‚РѕРІР°СЂРѕРІ РЅР° СЃС‚СЂР°РЅРёС†Рµ: {len(listing_products)}", "info")

        if not is_probable_product_url(url):
            self.extract_links(html, url)

    def finish_with_excel(self, partial: bool = False) -> None:
        with self.data_lock:
            if self.excel_finalized:
                return
            self.excel_finalized = True

        rows = self.snapshot_results()
        counts = self.snapshot_counts()
        filename = create_export_file(rows, self.project)
        final_error = ""
        if partial:
            final_error = "РЎР±РѕСЂ РїСЂРёРѕСЃС‚Р°РЅРѕРІР»РµРЅ. CSV СЃС„РѕСЂРјРёСЂРѕРІР°РЅ РїРѕ СѓР¶Рµ РЅР°Р№РґРµРЅРЅС‹Рј С‚РѕРІР°СЂР°Рј."
        elif not self.results:
            final_error = (
                "РЎР±РѕСЂ Р·Р°РІРµСЂС€РµРЅ, РЅРѕ С‚РѕРІР°СЂС‹ РЅРµ РЅР°Р№РґРµРЅС‹. РџСЂРѕРІРµСЂСЊС‚Рµ СЃС‚Р°СЂС‚РѕРІС‹Р№ URL Рё РёСЃРєР»СЋС‡РµРЅРёСЏ; "
                "РґР»СЏ Р·Р°С‰РёС‰РµРЅРЅС‹С… СЃС‚СЂР°РЅРёС† СѓР±РµРґРёС‚РµСЃСЊ, С‡С‚Рѕ Botasaurus СѓСЃС‚Р°РЅРѕРІРёР»СЃСЏ С‡РµСЂРµР· run.ps1."
            )

        self.update_state(
            status="partial" if partial else "completed",
            percent=100 if not partial else int((self.project or {}).get("state", {}).get("percent", 0) or 0),
            currenturl="",
            totalprocessed=counts["visited"],
            processed_products=counts["results"],
            found_products=counts["results"],
            skipped=counts["skipped"],
            download_ready=True,
            download_url="/download",
            filename=filename.name,
            error=final_error,
            thread_count=self.thread_count,
            elapsed_seconds=int(self.elapsed_seconds()),
            eta_seconds=None,
            finished_at=now_iso() if not partial else "",
            paused_with_result=partial,
        )
        self.log(f"CSV СЃС„РѕСЂРјРёСЂРѕРІР°РЅ: {filename.name}. РўРѕРІР°СЂРѕРІ: {counts['results']}", "success")

    def run(self, resume: bool = False) -> None:
        if not self.started_at:
            self.started_at = time.time()
        self.update_state(
            status="running",
            thread_count=self.thread_count,
            started_at=(self.project or {}).get("state", {}).get("started_at") or now_iso(),
            paused_with_result=False,
        )
        self.log("РЎР±РѕСЂ РїСЂРѕРґРѕР»Р¶РµРЅ" if resume else "РЎР±РѕСЂ Р·Р°РїСѓС‰РµРЅ", "info")
        if not resume:
            for start_url in self.start_urls:
                self.enqueue(start_url)

        executor = ThreadPoolExecutor(max_workers=self.thread_count)
        pending = {}
        pending_urls_to_requeue = []

        try:
            while not self.stop_signal.is_set():
                while len(pending) < self.thread_count:
                    try:
                        url = self.queue.get_nowait()
                    except Empty:
                        break

                    self.queued.discard(url)
                    if url in self.visited or url in self.in_progress:
                        continue
                    with self.data_lock:
                        if url in self.result_urls and is_probable_product_url(url):
                            continue
                    self.in_progress.add(url)
                    self.update_state(currenturl=url)
                    pending[executor.submit(self.fetch, url)] = url
                    time.sleep(REQUEST_DELAY_SECONDS)

                if not pending:
                    if self.queue.empty():
                        break
                    continue

                done, _pending = wait(pending.keys(), timeout=0.5, return_when=FIRST_COMPLETED)
                if not done:
                    self.refresh_progress()
                    continue

                for future in done:
                    url = pending.pop(future)
                    with self.data_lock:
                        self.in_progress.discard(url)
                        self.visited.add(url)
                    html = None
                    try:
                        html = future.result()
                    except Exception as exc:  # noqa: BLE001 - РѕС€РёР±РєСѓ РїРѕРєР°Р·С‹РІР°РµРј РІ РёРЅС‚РµСЂС„РµР№СЃРµ.
                        self.update_state(error=f"РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё {url}: {exc}")
                        self.log(f"РћС€РёР±РєР° РѕР±СЂР°Р±РѕС‚РєРё {url}: {exc}", "error")

                    if html and not self.stop_signal.is_set():
                        self.process_page(url, html)
                    elif not self.stop_signal.is_set():
                        retry_count = self.failed_attempts.get(url, 0) + 1
                        self.failed_attempts[url] = retry_count
                        if retry_count <= 2:
                            with self.data_lock:
                                self.visited.discard(url)
                            self.enqueue(url, force=True)
                            self.log(f"РџРѕРІС‚РѕСЂРЅР°СЏ РїРѕРїС‹С‚РєР° Р·Р°РіСЂСѓР·РєРё {retry_count}/2: {url}", "warning")
                        else:
                            self.log(f"URL РїСЂРѕРїСѓС‰РµРЅ РїРѕСЃР»Рµ РїРѕРІС‚РѕСЂРЅС‹С… РїРѕРїС‹С‚РѕРє Р·Р°РіСЂСѓР·РєРё: {url}", "error")

                    self.refresh_progress(url)
        finally:
            if self.stop_signal.is_set():
                pending_urls_to_requeue = list(pending.values())
                self.requeue_pending(pending_urls_to_requeue)
            executor.shutdown(wait=False, cancel_futures=True)

        if self.stop_signal.is_set():
            self.elapsed_before_resume = self.elapsed_seconds()
            self.started_at = 0.0
            if self.finish_signal.is_set():
                self.finish_with_excel(partial=True)
            else:
                self.update_state(
                    status="paused",
                    currenturl="",
                    elapsed_seconds=int(self.elapsed_before_resume),
                    eta_seconds=None,
                    error="РЎР±РѕСЂ РЅР° РїР°СѓР·Рµ",
                )
                self.log("РЎР±РѕСЂ РїРѕСЃС‚Р°РІР»РµРЅ РЅР° РїР°СѓР·Сѓ", "warning")
            return

        self.elapsed_before_resume = self.elapsed_seconds()
        self.started_at = 0.0
        self.finish_with_excel()


def safe_filename(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z\u0400-\u04FF0-9_-]+", "_", value, flags=re.IGNORECASE).strip("_")
    return cleaned or "project"


def create_export_file(rows: List[Dict[str, str]], project: Optional[Dict[str, object]] = None) -> Path:
    if project:
        filename = f"{safe_filename(str(project.get('name') or 'project'))}_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.csv"
    else:
        filename = f"exportmaunfeld{datetime.now().strftime('%d-%m-%Y')}.csv"
    path = EXPORT_DIR / filename

    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(["URL С‚РѕРІР°СЂР°", "_MODEL_", "_PRICE_"])
        for row in rows:
            writer.writerow([row.get("url", ""), row.get("model", ""), row.get("price", "")])

    return path


class CollectOnlyCrawler(MaunfeldCrawler):
    def __init__(self, *args, progress_callback=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.progress_callback = progress_callback

    def update_state(self, **kwargs: object) -> None:
        if self.progress_callback:
            self.progress_callback(kwargs)

    def log(self, message: str, level: str = "info") -> None:
        return

    def finish_with_excel(self, partial: bool = False) -> None:
        with self.data_lock:
            self.excel_finalized = True


def text_by_selector(soup: BeautifulSoup, selector: str) -> str:
    if not selector:
        return ""
    try:
        return first_by_selector(soup, selector)
    except Exception:
        return ""


def image_by_selector(soup: BeautifulSoup, selector: str, base_url: str) -> str:
    if not selector:
        return ""
    try:
        node = soup.select_one(selector)
    except Exception:
        return ""
    if not node:
        return ""
    if node.name == "img":
        value = node.get("src") or node.get("data-src") or node.get("data-original") or ""
    else:
        image = node.select_one("img")
        value = image.get("src") or image.get("data-src") or image.get("data-original") if image else ""
    return normalize_url(value, base_url) or "" if value else ""


def extract_photo_url(soup: BeautifulSoup, base_url: str, selector: str = "") -> str:
    selected = image_by_selector(soup, selector, base_url)
    if selected:
        return selected
    meta = soup.select_one("meta[property='og:image'], meta[name='twitter:image'], link[itemprop='image']")
    if meta:
        value = meta.get("content") or meta.get("href") or ""
        normalized = normalize_url(value, base_url)
        if normalized:
            return normalized
    for image in soup.select("img[src], img[data-src], img[data-original]"):
        value = image.get("src") or image.get("data-src") or image.get("data-original") or ""
        normalized = normalize_url(value, base_url)
        if normalized and not has_static_extension(normalized.replace(".jpg", "")):
            return normalized
        if normalized:
            return normalized
    return ""


def extract_availability(soup: BeautifulSoup, selector: str = "") -> str:
    selected = text_by_selector(soup, selector)
    if selected:
        return selected
    page_text = clean_text(soup.get_text(" ", strip=True))
    patterns = [
        r"Р’ РЅР°Р»РёС‡РёРё",
        r"РќРµС‚ РІ РЅР°Р»РёС‡РёРё",
        r"РџРѕРґ Р·Р°РєР°Р·",
        r"РћР¶РёРґР°РµС‚СЃСЏ",
        r"РЎРѕРѕР±С‰РёС‚СЊ Рѕ РїРѕСЃС‚СѓРїР»РµРЅРёРё",
        r"available",
        r"out of stock",
        r"in stock",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))
    return ""


def extract_product_name(soup: BeautifulSoup, selector: str = "") -> str:
    selected = text_by_selector(soup, selector)
    if selected:
        return selected
    meta = soup.select_one("meta[property='og:title'], meta[name='twitter:title']")
    if meta and meta.get("content"):
        return clean_text(meta.get("content", ""))
    return first_text(soup, ["h1", "[itemprop='name']", ".product-title", ".product__title"])


def feed_source_key(url: str) -> str:
    hostname = urlparse(url).hostname or "feed"
    return safe_filename(hostname.lower().removeprefix("www."))


def feed_source_label(url: str) -> str:
    hostname = (urlparse(url).hostname or "").lower().removeprefix("www.")
    if "mega-kuhnya" in hostname:
        return "РњРµРіР°-РєСѓС…РЅСЏ"
    if "vsya-tehnika" in hostname:
        return "Р’СЃСЏ С‚РµС…РЅРёРєР°"
    return hostname or "Р¤РёРґ"


def source_feed_dir(source: str) -> Path:
    return FEED_DIR / safe_filename(source)


def local_feed_filename(kind: str, index: int, url: str) -> str:
    parsed = urlparse(url)
    raw_name = Path(parsed.path).name or kind
    stem = Path(raw_name).stem or kind
    suffix = Path(raw_name).suffix.lower()
    if suffix not in {".xml", ".yml"}:
        suffix = ".xml"
    return f"{index:02d}_{safe_filename(kind)}_{safe_filename(stem)}{suffix}"


def generation_file_url(url: str) -> str:
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query["cron"] = "file"
    return urlunparse(parsed._replace(query=urlencode(query)))


def clear_source_feeds(source: str) -> Path:
    feed_dir = source_feed_dir(source)
    if feed_dir.exists():
        for path in feed_dir.glob("*"):
            if path.is_file():
                path.unlink(missing_ok=True)
    feed_dir.mkdir(parents=True, exist_ok=True)
    return feed_dir


def download_feed_files() -> List[Dict[str, object]]:
    with news_lock:
        own_sites = own_sites_from_settings(news_settings)
        feed_urls = [site["feed_url"] for site in own_sites]
        generate_urls = [site["feed_generate_url"] for site in own_sites if site.get("feed_generate_url")]
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
    )
    downloaded: List[Dict[str, object]] = []
    with FEED_STORAGE_LOCK:
        expected_sources = {feed_source_key(url) for url in feed_urls}
        if FEED_DIR.exists():
            for child in FEED_DIR.iterdir():
                if child.is_dir() and child.name not in expected_sources:
                    shutil.rmtree(child, ignore_errors=True)
        for source in expected_sources:
            clear_source_feeds(source)
        for generate_url in generate_urls:
            try:
                response = session.get(generation_file_url(generate_url), timeout=60)
                response.raise_for_status()
            except Exception:
                pass
        for index, site in enumerate(own_sites, start=1):
            url = site["feed_url"]
            try:
                response = session.get(url, timeout=60)
                response.raise_for_status()
                source = feed_source_key(url)
                feed_dir = source_feed_dir(source)
                filename = local_feed_filename("feed", index, url)
                path = feed_dir / filename
                path.write_bytes(response.content)
                downloaded.append(
                    {
                        "kind": "feed",
                        "source": source,
                        "source_label": site.get("name") or feed_source_label(url),
                        "url": url,
                        "filename": filename,
                        "size": path.stat().st_size,
                        "downloaded_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                    }
                )
            except Exception:
                pass
    return downloaded


def fetch_existing_vendor_codes() -> tuple[Set[str], List[Dict[str, object]]]:
    codes, feeds, _feed_code_sets = fetch_existing_vendor_code_sets()
    return codes, feeds


def fetch_existing_vendor_code_sets() -> tuple[Set[str], List[Dict[str, object]], List[Dict[str, object]]]:
    downloaded_feeds = download_feed_files()
    codes: Set[str] = set()
    feeds: List[Dict[str, object]] = []
    feed_code_sets: List[Dict[str, object]] = []
    for feed in downloaded_feeds:
        filename = str(feed.get("filename") or "")
        path = source_feed_dir(str(feed.get("source") or "")) / filename
        try:
            feed_products = parse_feed_products_from_xml(path.read_bytes())
            feed_codes = {
                value
                for product in feed_products
                for value in (str(product.get("vendor_code") or ""), str(product.get("model_key") or ""))
                if value
            }
            codes.update(feed_codes)
            feeds.append({**feed, "codes_count": len(feed_codes)})
            feed_code_sets.append({**feed, "codes_count": len(feed_codes), "codes": feed_codes})
        except Exception as exc:
            feeds.append({**feed, "codes_count": 0, "error": str(exc)})
            feed_code_sets.append({**feed, "codes_count": 0, "codes": set(), "error": str(exc)})
    with news_lock:
        news_settings["feed_storage"] = feeds
        save_news_settings()
    save_logs()
    return codes, feeds, feed_code_sets


def product_compare_keys(product: Dict[str, str]) -> Set[str]:
    keys = {
        normalize_model_key(str(product.get("model", ""))),
        normalize_model_key(str(product.get("vendor_code", ""))),
    }
    keys.discard("")
    return keys


def build_missing_summary(new_items: List[Dict[str, str]], feed_code_sets: List[Dict[str, object]]) -> List[Dict[str, object]]:
    summary: List[Dict[str, object]] = []
    for feed in feed_code_sets:
        feed_codes = feed.get("codes", set())
        if not isinstance(feed_codes, set):
            feed_codes = set(feed_codes) if isinstance(feed_codes, list) else set()
        count = 0
        for item in new_items:
            keys = product_compare_keys(item)
            if keys and not (keys & feed_codes):
                count += 1
        summary.append(
            {
                "source": str(feed.get("source") or ""),
                "source_label": str(feed.get("source_label") or feed.get("url") or "Р¤РёРґ"),
                "url": str(feed.get("url") or ""),
                "count": count,
                "codes_count": int(feed.get("codes_count") or 0),
                "error": str(feed.get("error") or ""),
            }
        )
    return summary


def parse_vendor_codes_from_xml(content: bytes) -> Set[str]:
    return {
        value
        for product in parse_feed_products_from_xml(content)
        for value in (str(product.get("vendor_code") or ""), str(product.get("model_key") or ""))
        if value
    }


def parse_feed_products_from_xml(content: bytes) -> List[Dict[str, object]]:
    products: List[Dict[str, object]] = []
    root = ET.fromstring(content)
    for node in root.iter():
        children = list(node)
        if not children:
            continue
        values: Dict[str, str] = {}
        for child in children:
            key = str(child.tag).split("}")[-1].lower()
            values[key] = clean_text(child.text or "")
        vendor_code = normalize_model_key(values.get("vendorcode", ""))
        model = values.get("model") or values.get("name") or values.get("title") or vendor_code
        model_key = normalize_model_key(model)
        if not vendor_code and not model_key:
            continue
        products.append(
            {
                "vendor_code": vendor_code,
                "model_key": model_key,
                "name": values.get("name") or values.get("model") or values.get("title") or "",
                "url": values.get("url") or "",
                "raw": values,
            }
        )
    return products


def validate_monitor_selectors(monitor: Dict[str, object]) -> None:
    selector_fields = []
    rules = monitor.get("extraction_rules", {}) if isinstance(monitor.get("extraction_rules"), dict) else {}
    selectors = monitor.get("selector_settings", {}) if isinstance(monitor.get("selector_settings"), dict) else {}
    for key in ("product_card_selector", "product_url_selector", "model_selector", "price_selector"):
        if rules.get(key):
            selector_fields.append((key, str(rules[key])))
    for key in ("name_selector", "availability_selector", "photo_selector"):
        if selectors.get(key):
            selector_fields.append((key, str(selectors[key])))
    soup = BeautifulSoup("", "html.parser")
    for key, selector in selector_fields:
        try:
            soup.select(selector)
        except Exception as exc:
            raise ValueError(f"РћС€РёР±РєР° CSS-СЃРµР»РµРєС‚РѕСЂР° {key}: {selector}. {exc}") from exc


def update_news_monitor_state(monitor: Dict[str, object], **kwargs: object) -> None:
    with news_lock:
        state = dict(monitor.get("state", make_news_state()))
        state.update(kwargs)
        state = repair_mojibake(state)
        if state.get("started_at") and state.get("status") in {"running", "queued"}:
            try:
                started_at = datetime.fromisoformat(str(state.get("started_at")))
                if started_at.tzinfo is None:
                    started_at = started_at.replace(tzinfo=MSK_TZ)
                state["elapsed_seconds"] = int((datetime.now(MSK_TZ) - started_at).total_seconds())
            except ValueError:
                pass
        monitor["state"] = state
        monitor["brand_state"] = dict(state)
        group = clean_text(str(monitor.get("group") or ""))
        brand = clean_text(str(monitor.get("brand") or ""))
        for item in news_settings.get("monitors", []):
            if (
                isinstance(item, dict)
                and clean_text(str(item.get("group") or "")) == group
                and clean_text(str(item.get("brand") or "")) == brand
            ):
                item["state"] = dict(state)
                item["brand_state"] = dict(state)
        persist_news_monitor_state(monitor)


def persist_news_monitor_state(monitor: Dict[str, object], force: bool = False) -> None:
    monitor_id = str(monitor.get("id") or "").strip()
    if not monitor_id:
        return
    now = time.time()
    if not force and now - news_state_persisted_at.get(monitor_id, 0) < 1:
        return
    news_state_persisted_at[monitor_id] = now
    state = repair_mojibake({**make_news_state(), **(monitor.get("state") or {})})
    try:
        with session_scope() as session:
            donor = get_donor_row(session, monitor_id)
            if donor is None:
                return
            donor.updated_at = datetime.utcnow()
            if donor.brand:
                donor.brand.state = state
    except Exception as exc:
        print(f"Failed to persist news monitor state {monitor_id}: {exc}", flush=True)


def update_brand_scan_state(
    target_type: str,
    target_id: str,
    status: str,
    started_at: float,
    found_products: int = 0,
    new_count: int = 0,
    data: Optional[Dict[str, object]] = None,
) -> None:
    if target_type not in {"news", "donor"}:
        return
    state = {
        **make_news_state(),
        "status": status or "idle",
        "started_at": datetime.fromtimestamp(started_at, MSK_TZ).isoformat(timespec="seconds"),
        "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        "found_products": found_products,
        "new_count": new_count,
        "data": data or {},
    }
    state = repair_mojibake(state)
    with session_scope() as session:
        donor = get_donor_row(session, target_id)
        if donor and donor.brand:
            donor.brand.state = state
    with news_lock:
        monitor = next((item for item in news_settings.get("monitors", []) if str(item.get("id")) == str(target_id)), None)
        if monitor:
            group = clean_text(str(monitor.get("group") or ""))
            brand = clean_text(str(monitor.get("brand") or ""))
            for item in news_settings.get("monitors", []):
                if (
                    isinstance(item, dict)
                    and clean_text(str(item.get("group") or "")) == group
                    and clean_text(str(item.get("brand") or "")) == brand
                ):
                    item["brand_state"] = dict(state)
                    item["state"] = dict(state)


class NewsScanStopped(Exception):
    pass


def get_news_stop_event(monitor_id: str) -> threading.Event:
    with news_lock:
        event = news_stop_events.get(monitor_id)
        if not event:
            event = threading.Event()
            news_stop_events[monitor_id] = event
        return event


def request_news_stop(monitor_id: str, mode: str) -> threading.Event:
    event = get_news_stop_event(monitor_id)
    with news_lock:
        news_stop_modes[monitor_id] = mode
        monitor = get_news_monitor(monitor_id)
        if monitor:
            update_news_monitor_state(
                monitor,
                status="pausing" if mode == "pause" else "stopping",
                stage="Приостановка" if mode == "pause" else "Остановка",
                currenturl="",
            )
            persist_news_monitor_state(monitor, force=True)
    event.set()
    return event


def collect_products_for_monitor(monitor: Dict[str, object], stop_signal: threading.Event) -> List[Dict[str, str]]:
    finish_signal = threading.Event()

    def progress_callback(payload: Dict[str, object]) -> None:
        if stop_signal.is_set():
            return
        update_news_monitor_state(
            monitor,
            status="running",
            stage="РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ СЃР°Р№С‚Р°-РґРѕРЅРѕСЂР°",
            percent=min(85, int(payload.get("percent", 0) or 0)),
            currenturl=str(payload.get("currenturl", "")),
            processed=int(payload.get("totalprocessed", 0) or 0),
            found_products=int(payload.get("found_products", 0) or 0),
            skipped=int(payload.get("skipped", 0) or 0),
            error=str(payload.get("error", "") or ""),
        )

    crawler = CollectOnlyCrawler(
        list(monitor.get("start_urls", [])),
        int(time.time()),
        stop_signal,
        finish_signal,
        parse_thread_count(monitor.get("thread_count", 4)),
        project=None,
        exclusions=list(monitor.get("exclusions", DEFAULT_EXCLUSIONS)),
        product_url_filters=list(monitor.get("product_url_filters", [])),
        extraction_rules=normalize_extraction_rules(monitor.get("extraction_rules", {})),
        connection_method=normalize_connection_method(monitor.get("connection_method")),
        auto_connection_fallback=bool(monitor.get("auto_connection_fallback", True)),
        progress_callback=progress_callback,
    )
    crawler.run()
    return crawler.snapshot_results()


def enrich_news_product(product: Dict[str, str], monitor: Dict[str, object]) -> Dict[str, str]:
    url = product.get("url", "")
    selector_settings = monitor.get("selector_settings", {}) if isinstance(monitor.get("selector_settings"), dict) else {}
    extraction_rules = normalize_extraction_rules(monitor.get("extraction_rules", {}))
    details = {
        "date_found": datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S"),
        "group": str(monitor.get("group") or ""),
        "brand": str(monitor.get("brand") or ""),
        "name": product.get("model", ""),
        "model": product.get("model", ""),
        "price": product.get("price", ""),
        "availability": "",
        "photo_url": "",
        "url": url,
    }
    fetcher = CollectOnlyCrawler(
        [url],
        int(time.time()),
        threading.Event(),
        threading.Event(),
        1,
        connection_method=normalize_connection_method(monitor.get("connection_method")),
        auto_connection_fallback=bool(monitor.get("auto_connection_fallback", True)),
    )
    html = fetcher.fetch(url) if url else ""
    if not html:
        return details
    soup = BeautifulSoup(html, "html.parser")
    name = extract_product_name(soup, str(selector_settings.get("name_selector", "")))
    product_data = extract_product_data(url, html, product.get("price", ""), extraction_rules)
    if product_data:
        details["model"] = product_data.get("model", details["model"])
        details["price"] = product_data.get("price", details["price"])
    else:
        model_candidate = extract_model_by_markers(html, extraction_rules) or details["model"] or name
        prepared_model = prepare_rule_model(model_candidate, extraction_rules)
        if prepared_model:
            details["model"] = normalize_model(prepared_model, url)
    details["name"] = name or details["name"]
    details["availability"] = extract_availability(soup, str(selector_settings.get("availability_selector", "")))
    details["photo_url"] = extract_photo_url(soup, url, str(selector_settings.get("photo_selector", "")))
    return details


def create_news_csv(rows: List[Dict[str, str]], monitor: Dict[str, object], filename: str = "") -> Path:
    if not filename:
        filename = f"РќРѕРІРёРЅРєРё_{safe_filename(str(monitor.get('brand') or 'donor'))}_{datetime.now().strftime('%d-%m-%Y_%H-%M-%S')}.csv"
    path = EXPORT_DIR / filename
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(["Р”Р°С‚Р° РїРѕСЏРІР»РµРЅРёСЏ", "Р“СЂСѓРїРїР°", "РЎР°Р№С‚/Р±СЂРµРЅРґ", "РќР°РёРјРµРЅРѕРІР°РЅРёРµ", "РњРѕРґРµР»СЊ", "Р¦РµРЅР°", "РќР°Р»РёС‡РёРµ", "РќРµС‚ РЅР° СЃР°Р№С‚Р°С…", "URL С‚РѕРІР°СЂР°"])
        for row in rows:
            writer.writerow(
                [
                    row.get("date_found", ""),
                    row.get("group", ""),
                    row.get("brand", ""),
                    row.get("name", ""),
                    row.get("model", ""),
                    row.get("price", ""),
                    row.get("availability", ""),
                    row.get("missing_on", ""),
                    row.get("url", ""),
                ]
            )
    return path


def send_news_email(
    monitor: Optional[Dict[str, object]],
    new_count: int,
    test: bool = False,
    error_holder: Optional[List[str]] = None,
    missing_summary: Optional[List[Dict[str, object]]] = None,
) -> bool:
    with news_lock:
        smtp_config = dict(news_settings.get("smtp", {}))
    recipients = normalize_emails(smtp_config.get("recipients", []))
    username = str(smtp_config.get("username") or "").strip()
    password = str(smtp_config.get("password") or "").strip()
    sender_emails = normalize_emails(username)
    if not username or not password or not recipients:
        error_message = "Email РЅРµ РѕС‚РїСЂР°РІР»РµРЅ: Р·Р°РїРѕР»РЅРёС‚Рµ email-Р»РѕРіРёРЅ, РїР°СЂРѕР»СЊ РїСЂРёР»РѕР¶РµРЅРёСЏ Рё РїРѕР»СѓС‡Р°С‚РµР»РµР№ SMTP"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False
    if not sender_emails:
        error_message = "Email РЅРµ РѕС‚РїСЂР°РІР»РµРЅ: email-Р»РѕРіРёРЅ РґРѕР»Р¶РµРЅ Р±С‹С‚СЊ Р°РґСЂРµСЃРѕРј РїРѕС‡С‚С‹"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False
    sender_email = sender_emails[0]

    if test:
        subject = "РўРµСЃС‚ email-СѓРІРµРґРѕРјР»РµРЅРёР№"
        body = "РўРµСЃС‚РѕРІРѕРµ РїРёСЃСЊРјРѕ РѕС‚РїСЂР°РІР»РµРЅРѕ РёР· РјРѕРЅРёС‚РѕСЂРёРЅРіР° РЅРѕРІРёРЅРѕРє. SMTP-РЅР°СЃС‚СЂРѕР№РєРё СЂР°Р±РѕС‚Р°СЋС‚."
    else:
        brand = str((monitor or {}).get("brand") or "РґРѕРЅРѕСЂ")
        site_url = str((monitor or {}).get("site_url") or "")
        subject = f"РЈРІРµРґРѕРјР»РµРЅРёРµ Рѕ РЅРѕРІРёРЅРєР°С… РЅР° СЃР°Р№С‚Рµ {brand}"
        lines = [f"РќР° {site_url or brand} РЅР°Р№РґРµРЅРѕ РІСЃРµРіРѕ: {new_count}"]
        for item in missing_summary or []:
            count = int(item.get("count") or 0)
            label = str(item.get("source_label") or item.get("url") or "СЃР°Р№С‚")
            lines.append(f"РќР° СЃР°Р№С‚Рµ {label} РЅРµ Р±С‹Р»Рѕ РЅР°Р№РґРµРЅРѕ {count} РЅРѕРІРёРЅРѕРє.")
        body = "\n".join(lines)
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = ", ".join(recipients)
    message.set_content(body)

    host = str(smtp_config.get("host") or "smtp.yandex.ru")
    port = int(smtp_config.get("port") or 465)
    security_mode = str(smtp_config.get("security") or "ssl").lower()
    try:
        if security_mode == "tls":
            with smtplib.SMTP(host, port, timeout=30) as server:
                server.starttls(context=ssl.create_default_context())
                server.login(username, password)
                server.send_message(message, from_addr=sender_email, to_addrs=recipients)
        else:
            with smtplib.SMTP_SSL(host, port, context=ssl.create_default_context(), timeout=30) as server:
                server.login(username, password)
                server.send_message(message, from_addr=sender_email, to_addrs=recipients)
    except Exception as exc:
        error_message = f"РћС€РёР±РєР° РѕС‚РїСЂР°РІРєРё email: {exc}"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "error")
        return False
    add_news_log(monitor, "РўРµСЃС‚РѕРІРѕРµ email-СЃРѕРѕР±С‰РµРЅРёРµ РѕС‚РїСЂР°РІР»РµРЅРѕ" if test else f"Email-СѓРІРµРґРѕРјР»РµРЅРёРµ РѕС‚РїСЂР°РІР»РµРЅРѕ. РќРѕРІРёРЅРѕРє: {new_count}", "success")
    return True


def scan_news_monitor(monitor_id: str, manual: bool = False) -> None:
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return
    started = time.time()
    stop_event = get_news_stop_event(monitor_id)
    stop_event.clear()
    with news_lock:
        news_stop_modes.pop(monitor_id, None)
    new_items: List[Dict[str, str]] = []
    products: List[Dict[str, str]] = []
    local_feeds: List[Dict[str, object]] = []
    feed_code_sets: List[Dict[str, object]] = []
    missing_summary: List[Dict[str, object]] = []
    previous_csv = str(monitor.get("state", {}).get("last_csv") or "")

    def check_stopped() -> None:
        if stop_event.is_set():
            raise NewsScanStopped()

    with news_lock:
        monitor["state"] = {
            **make_news_state("running"),
            "stage": "РџРѕРґРіРѕС‚РѕРІРєР°",
            "started_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        }
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    add_news_log(monitor, "Р СѓС‡РЅРѕРµ СЃРєР°РЅРёСЂРѕРІР°РЅРёРµ РЅРѕРІРёРЅРѕРє Р·Р°РїСѓС‰РµРЅРѕ" if manual else "РџР»Р°РЅРѕРІРѕРµ СЃРєР°РЅРёСЂРѕРІР°РЅРёРµ РЅРѕРІРёРЅРѕРє Р·Р°РїСѓС‰РµРЅРѕ", "info")

    try:
        update_news_monitor_state(monitor, stage="РџРѕРґРіРѕС‚РѕРІРєР°", percent=2)
        validate_monitor_selectors(monitor)
        add_news_log(
            monitor,
            f"Scan settings: URL={', '.join(monitor.get('start_urls', []))}; "
            f"method={monitor.get('connection_method')}; threads={monitor.get('thread_count')}",
            "info",
        )
        update_news_monitor_state(monitor, stage="РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ СЃР°Р№С‚Р°-РґРѕРЅРѕСЂР°", percent=5)
        products = collect_products_for_monitor(monitor, stop_event)
        check_stopped()
        add_news_log(monitor, f"РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ СЃР°Р№С‚Р° Р·Р°РІРµСЂС€РµРЅРѕ. РќР°Р№РґРµРЅРѕ С‚РѕРІР°СЂРѕРІ: {len(products)}", "info")
        update_news_monitor_state(monitor, stage="Р“РµРЅРµСЂР°С†РёСЏ Рё Р·Р°РіСЂСѓР·РєР° С„РёРґРѕРІ РІР°С€РёС… СЃР°Р№С‚РѕРІ", percent=84, currenturl="")
        all_existing_codes, local_feeds, feed_code_sets = fetch_existing_vendor_code_sets()
        check_stopped()
        add_news_log(
            monitor,
            f"Р¤РёРґС‹ РѕР±РЅРѕРІР»РµРЅС‹ РїРѕСЃР»Рµ СЃР±РѕСЂР° РґРѕРЅРѕСЂР°: {len(local_feeds)}. РњРѕРґРµР»РµР№ РІСЃРµРіРѕ: {len(all_existing_codes)}",
            "info",
        )
        update_news_monitor_state(
            monitor,
            stage="РЎСЂР°РІРЅРµРЅРёРµ СЃ С„РёРґР°РјРё",
            percent=86,
            candidate_products=len(products),
            found_products=len(products),
            compared_products=0,
            currenturl="",
        )
        known = monitor.get("known_new_products", {}) if isinstance(monitor.get("known_new_products"), dict) else {}
        for index, product in enumerate(products, start=1):
            check_stopped()
            update_news_monitor_state(
                monitor,
                stage="РЎСЂР°РІРЅРµРЅРёРµ СЃ С„РёРґР°РјРё",
                percent=86 + int((index / max(1, len(products))) * 12),
                compared_products=index,
                currenturl=product.get("url", ""),
            )
            details = enrich_news_product(product, monitor)
            details["model"] = details.get("model") or product.get("model", "")
            detail_keys = product_compare_keys(details) | product_compare_keys(product)
            if not detail_keys:
                continue
            missing_feeds = []
            for feed in feed_code_sets:
                feed_codes = feed.get("codes", set())
                if not isinstance(feed_codes, set):
                    feed_codes = set(feed_codes) if isinstance(feed_codes, list) else set()
                if not (detail_keys & feed_codes):
                    missing_feeds.append(str(feed.get("source_label") or feed.get("url") or "Р¤РёРґ"))
            if not missing_feeds:
                continue
            model_key = sorted(detail_keys)[0]
            details["missing_on"] = ", ".join(missing_feeds)
            details["missing_on_count"] = len(missing_feeds)
            new_items.append(details)
            known[model_key] = details
        missing_summary = build_missing_summary(new_items, feed_code_sets)
        for item in missing_summary:
            add_news_log(
                monitor,
                f"РќРµС‚ РЅР° {item.get('source_label')}: {int(item.get('count') or 0)}",
                "info",
            )

        update_news_monitor_state(monitor, stage="Р¤РѕСЂРјРёСЂРѕРІР°РЅРёРµ CSV", percent=99, currenturl="")
        csv_path = create_news_csv(new_items, monitor, previous_csv)
        elapsed = int(time.time() - started)
        with news_lock:
            monitor["known_new_products"] = known
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "completed",
                "stage": "Р—Р°РІРµСЂС€РµРЅРѕ",
                "percent": 100,
                "processed": len(products),
                "found_products": len(products),
                "candidate_products": len(products),
                "compared_products": len(products),
                "new_count": len(new_items),
                "missing_by_feed": missing_summary,
                "last_scan_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "last_csv": csv_path.name,
                "error": "",
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "currenturl": "",
            }
            monitor["brand_state"] = dict(monitor["state"])
            monitor["next_run_at"] = "" if monitor.get("schedule_type") == "once" else compute_next_run_at(monitor)
            save_news_settings()
        add_news_log(monitor, f"РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ Р·Р°РІРµСЂС€РµРЅРѕ. РќР°Р№РґРµРЅРѕ РЅРѕРІРёРЅРѕРє: {len(new_items)}. CSV: {csv_path.name}", "success")
        update_brand_scan_state(
            "donor",
            monitor_id,
            "completed",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={"csv": csv_path.name, "feeds": local_feeds, "missing_by_feed": missing_summary},
        )
        if new_items:
            send_news_email(monitor, len(new_items), missing_summary=missing_summary)
    except NewsScanStopped:
        elapsed = int(time.time() - started)
        with news_lock:
            stop_mode = news_stop_modes.get(monitor_id, "stop")
        partial_csv = ""
        if stop_mode == "pause" and new_items:
            partial_csv = create_news_csv(new_items, monitor, previous_csv).name
        missing_summary = build_missing_summary(new_items, feed_code_sets) if feed_code_sets else []
        with news_lock:
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "partial" if stop_mode == "pause" else "stopped",
                "stage": "РџСЂРёРѕСЃС‚Р°РЅРѕРІР»РµРЅРѕ" if stop_mode == "pause" else "РћСЃС‚Р°РЅРѕРІР»РµРЅРѕ",
                "error": "",
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "currenturl": "",
                "last_csv": partial_csv or monitor.get("state", {}).get("last_csv", ""),
                "new_count": len(new_items),
                "missing_by_feed": missing_summary,
                "processed": len(products),
                "found_products": len(products),
            }
            monitor["brand_state"] = dict(monitor["state"])
            save_news_settings()
        add_news_log(
            monitor,
            f"РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ РЅРѕРІРёРЅРѕРє РїСЂРёРѕСЃС‚Р°РЅРѕРІР»РµРЅРѕ. CSV: {partial_csv}" if stop_mode == "pause" else "РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ РЅРѕРІРёРЅРѕРє РѕСЃС‚Р°РЅРѕРІР»РµРЅРѕ",
            "warning",
        )
        update_brand_scan_state(
            "donor",
            monitor_id,
            "partial" if stop_mode == "pause" else "stopped",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={"csv": partial_csv},
        )
    except Exception as exc:
        elapsed = int(time.time() - started)
        with news_lock:
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "error",
                "stage": "РћС€РёР±РєР°",
                "error": str(exc),
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
            }
            monitor["brand_state"] = dict(monitor["state"])
            save_news_settings()
        add_news_log(monitor, f"РћС€РёР±РєР° СЃРєР°РЅРёСЂРѕРІР°РЅРёСЏ РЅРѕРІРёРЅРѕРє: {exc}", "error")
        update_brand_scan_state(
            "donor",
            monitor_id,
            "error",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={"error": str(exc)},
        )
    finally:
        with news_lock:
            news_stop_modes.pop(monitor_id, None)
        stop_event.clear()


def parse_scan_time(value: object) -> datetime_time:
    text = str(value or "01:00")
    try:
        hour, minute = [int(part) for part in text[:5].split(":", 1)]
        return datetime_time(max(0, min(hour, 23)), max(0, min(minute, 59)), tzinfo=MSK_TZ)
    except Exception:
        return datetime_time(1, 0, tzinfo=MSK_TZ)


def compute_next_run_at(monitor: Dict[str, object]) -> str:
    now = datetime.now(MSK_TZ)
    schedule_type = str(monitor.get("schedule_type") or "daily")
    if schedule_type == "once":
        return str(monitor.get("next_run_at") or "")
    run_time = parse_scan_time(monitor.get("scan_time"))
    candidate = now.replace(hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)
    if schedule_type == "weekly":
        weekday = int(monitor.get("weekday", 0) or 0)
        days_ahead = (weekday - now.weekday()) % 7
        candidate = candidate + timedelta(days=days_ahead)
        if candidate <= now:
            candidate += timedelta(days=7)
    else:
        if candidate <= now:
            candidate += timedelta(days=1)
    return candidate.isoformat(timespec="minutes")


def is_monitor_due(monitor: Dict[str, object]) -> bool:
    if not monitor.get("enabled", True):
        return False
    if monitor.get("state", {}).get("status") == "running":
        return False
    now = datetime.now(MSK_TZ)
    schedule_type = str(monitor.get("schedule_type") or "daily")
    if schedule_type == "once":
        raw_next = str(monitor.get("next_run_at") or "")
        if not raw_next:
            return False
        try:
            due_at = datetime.fromisoformat(raw_next)
            if due_at.tzinfo is None:
                due_at = due_at.replace(tzinfo=MSK_TZ)
        except ValueError:
            return False
        return now >= due_at

    run_time = parse_scan_time(monitor.get("scan_time"))
    if now.hour != run_time.hour or now.minute != run_time.minute:
        return False
    if schedule_type == "weekly" and now.weekday() != int(monitor.get("weekday", 0) or 0):
        return False
    last_scan = str(monitor.get("state", {}).get("last_scan_at") or "")
    return not last_scan.startswith(now.date().isoformat())


def start_news_scheduler() -> None:
    global news_scheduler_thread
    if isinstance(news_scheduler_thread, threading.Thread) and news_scheduler_thread.is_alive():
        return

    def scheduler_loop() -> None:
        while True:
            try:
                load_news_settings()
                due_ids = []
                with news_lock:
                    for monitor in news_settings.get("monitors", []):
                        if is_monitor_due(monitor):
                            monitor["state"] = {**monitor.get("state", {}), "status": "queued"}
                            due_ids.append(str(monitor.get("id")))
                    if due_ids:
                        save_news_settings()
                for monitor_id in due_ids:
                    threading.Thread(target=scan_news_monitor, args=(monitor_id, False), daemon=True).start()
            except Exception:
                pass
            time.sleep(30)

    news_scheduler_thread = threading.Thread(target=scheduler_loop, daemon=True)
    news_scheduler_thread.start()


@app.route("/")
def index() -> str:
    ensure_storage()
    return render_template("index.html", default_start_url=DEFAULT_START_URL)


@app.get("/api/state")
def api_state():
    return jsonify(snapshot_state())


@app.get("/api/exclusions")
def api_exclusions():
    with exclusions_lock:
        return jsonify({"exclusions": load_exclusions()})


@app.get("/api/news")
def api_news():
    ensure_storage()
    return jsonify(public_news_settings())


@app.patch("/api/news/settings")
def api_update_news_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    with news_lock:
        if "own_sites" in payload and isinstance(payload.get("own_sites"), list):
            own_sites_payload = [item for item in payload.get("own_sites", []) if isinstance(item, dict)]
            own_sites = []
            for index, item in enumerate(own_sites_payload, start=1):
                feed_url = normalize_feed_url(str(item.get("feed_url") or "").strip())
                if not feed_url:
                    continue
                feed_generate_url = normalize_feed_url(str(item.get("feed_generate_url") or "").strip())
                own_sites.append(
                    {
                        "name": clean_text(str(item.get("name") or "")) or f"Р¤РёРґ {index}",
                        "feed_url": feed_url,
                        "feed_generate_url": feed_generate_url,
                    }
                )
            feed_urls = [
                item["feed_url"]
                for item in own_sites
            ]
            feed_generate_urls = [
                item["feed_generate_url"]
                for item in own_sites
                if item.get("feed_generate_url")
            ]
            feed_urls = feed_urls or [DEFAULT_FEED_URL]
            feed_generate_urls = feed_generate_urls or [DEFAULT_FEED_GENERATE_URL]
            news_settings["own_sites"] = own_sites or [{"name": feed_source_label(DEFAULT_FEED_URL), "feed_url": DEFAULT_FEED_URL, "feed_generate_url": DEFAULT_FEED_GENERATE_URL}]
            news_settings["feed_urls"] = feed_urls
            news_settings["feed_url"] = feed_urls[0] if feed_urls else DEFAULT_FEED_URL
            news_settings["feed_generate_urls"] = feed_generate_urls
            news_settings["feed_generate_url"] = feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL
        if "feed_url" in payload:
            news_settings["feed_url"] = str(payload.get("feed_url") or DEFAULT_FEED_URL).strip()
        if "feed_generate_url" in payload:
            news_settings["feed_generate_url"] = str(payload.get("feed_generate_url") or DEFAULT_FEED_GENERATE_URL).strip()
        if "feed_urls" in payload:
            feed_urls = normalize_feed_urls(payload.get("feed_urls") or DEFAULT_FEED_URL, DEFAULT_FEED_URL)
            news_settings["feed_urls"] = feed_urls
            news_settings["feed_url"] = feed_urls[0] if feed_urls else DEFAULT_FEED_URL
        if "feed_generate_urls" in payload:
            feed_generate_urls = normalize_feed_urls(payload.get("feed_generate_urls") or DEFAULT_FEED_GENERATE_URL, DEFAULT_FEED_GENERATE_URL)
            news_settings["feed_generate_urls"] = feed_generate_urls
            news_settings["feed_generate_url"] = feed_generate_urls[0] if feed_generate_urls else DEFAULT_FEED_GENERATE_URL
        if "auto_cleanup" in payload:
            news_settings["auto_cleanup"] = bool(payload.get("auto_cleanup"))
        if "smtp" in payload and isinstance(payload.get("smtp"), dict):
            smtp_payload = payload["smtp"]
            smtp = dict(news_settings.get("smtp", {}))
            smtp.pop("sender", None)
            for key in ("host", "security", "username"):
                if key in smtp_payload:
                    smtp[key] = str(smtp_payload.get(key) or "").strip()
            if "port" in smtp_payload:
                try:
                    smtp["port"] = int(smtp_payload.get("port") or 465)
                except (TypeError, ValueError):
                    smtp["port"] = 465
            if "password" in smtp_payload and str(smtp_payload.get("password") or "").strip():
                smtp["password"] = str(smtp_payload.get("password")).strip()
            if "recipients" in smtp_payload:
                smtp["recipients"] = normalize_emails(smtp_payload.get("recipients"))
            news_settings["smtp"] = smtp
        save_news_settings()
    return jsonify(public_news_settings())


@app.post("/api/news/email/test")
def api_test_news_email():
    ensure_storage()
    errors: List[str] = []
    if not send_news_email(None, 0, test=True, error_holder=errors):
        return jsonify({"error": errors[-1] if errors else "Email РЅРµ РѕС‚РїСЂР°РІР»РµРЅ. РџСЂРѕРІРµСЂСЊС‚Рµ SMTP-РЅР°СЃС‚СЂРѕР№РєРё Рё Р»РѕРіРё РјРѕРЅРёС‚РѕСЂРёРЅРіР°."}), 500
    return jsonify({"ok": True})


@app.patch("/api/news/monitors/<monitor_id>")
def api_update_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    payload = request.get_json(silent=True) or {}
    with news_lock:
        if "group" in payload:
            monitor["group"] = clean_text(str(payload.get("group") or monitor.get("group") or ""))
        if "brand" in payload:
            monitor["brand"] = clean_text(str(payload.get("brand") or monitor.get("brand") or ""))
        if "site_url" in payload:
            monitor["site_url"] = str(payload.get("site_url") or "").strip()
        if "start_urls" in payload:
            monitor["start_urls"] = normalize_start_urls(payload.get("start_urls"))
            monitor["site_url"] = monitor.get("site_url") or monitor["start_urls"][0]
        if "enabled" in payload:
            monitor["enabled"] = bool(payload.get("enabled"))
        if "schedule_type" in payload:
            schedule_type = str(payload.get("schedule_type") or "daily")
            monitor["schedule_type"] = schedule_type if schedule_type in {"daily", "weekly", "once"} else "daily"
        if "scan_time" in payload:
            monitor["scan_time"] = str(payload.get("scan_time") or "01:00")[:5]
        if "weekday" in payload:
            try:
                monitor["weekday"] = max(0, min(int(payload.get("weekday") or 0), 6))
            except (TypeError, ValueError):
                monitor["weekday"] = 0
        if "next_run_at" in payload:
            monitor["next_run_at"] = str(payload.get("next_run_at") or "")
        if "thread_count" in payload:
            monitor["thread_count"] = parse_thread_count(payload.get("thread_count"))
        if "connection_method" in payload:
            monitor["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            monitor["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        if "exclusions" in payload:
            exclusions = normalize_patterns(payload.get("exclusions"))
            monitor["exclusions"] = exclusions
            group = clean_text(str(monitor.get("group") or ""))
            brand = clean_text(str(monitor.get("brand") or ""))
            for item in news_settings.get("monitors", []):
                if (
                    isinstance(item, dict)
                    and clean_text(str(item.get("group") or "")) == group
                    and clean_text(str(item.get("brand") or "")) == brand
                ):
                    item["exclusions"] = list(exclusions)
        if "product_url_filters" in payload:
            monitor["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
        if "extraction_rules" in payload:
            monitor["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "selector_settings" in payload:
            monitor["selector_settings"] = normalize_selector_settings(payload.get("selector_settings"))
        if "collapsed" in payload:
            monitor["collapsed"] = bool(payload.get("collapsed"))
        monitor["next_run_at"] = compute_next_run_at(monitor) if monitor.get("schedule_type") != "once" else str(monitor.get("next_run_at") or "")
        save_news_settings()
    return jsonify({"monitor": dict(monitor)})


@app.post("/api/news/monitors/<monitor_id>/scan")
def api_scan_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    if monitor.get("state", {}).get("status") in {"running", "queued"}:
        return jsonify({"error": "РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ СѓР¶Рµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ"}), 409
    threading.Thread(target=scan_news_monitor, args=(monitor_id, True), daemon=True).start()
    with news_lock:
        monitor["state"] = {**monitor.get("state", {}), "status": "queued"}
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    return jsonify({"monitor": dict(monitor)})


@app.post("/api/news/monitors/<monitor_id>/stop")
def api_stop_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    request_news_stop(monitor_id, "stop")
    with news_lock:
        monitor["state"] = {
            **monitor.get("state", {}),
            "status": "stopping",
            "stage": "РћСЃС‚Р°РЅРѕРІРєР°",
        }
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    add_news_log(monitor, "Р—Р°РїСЂРѕС€РµРЅР° РѕСЃС‚Р°РЅРѕРІРєР° СЃРєР°РЅРёСЂРѕРІР°РЅРёСЏ РЅРѕРІРёРЅРѕРє", "warning")
    return jsonify({"monitor": dict(monitor)})


@app.post("/api/news/monitors/<monitor_id>/pause")
def api_pause_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    request_news_stop(monitor_id, "pause")
    with news_lock:
        monitor["state"] = {
            **monitor.get("state", {}),
            "status": "pausing",
            "stage": "РџСЂРёРѕСЃС‚Р°РЅРѕРІРєР°",
        }
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    add_news_log(monitor, "Р—Р°РїСЂРѕС€РµРЅР° РїСЂРёРѕСЃС‚Р°РЅРѕРІРєР° СЃРєР°РЅРёСЂРѕРІР°РЅРёСЏ РЅРѕРІРёРЅРѕРє СЃ СЃРѕС…СЂР°РЅРµРЅРёРµРј СЂРµР·СѓР»СЊС‚Р°С‚Р°", "warning")
    return jsonify({"monitor": dict(monitor)})


@app.post("/api/news/monitors/<monitor_id>/resume")
def api_resume_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    if monitor.get("state", {}).get("status") in {"running", "queued", "pausing", "stopping"}:
        return jsonify({"error": "РЎРєР°РЅРёСЂРѕРІР°РЅРёРµ СѓР¶Рµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ"}), 409
    threading.Thread(target=scan_news_monitor, args=(monitor_id, True), daemon=True).start()
    with news_lock:
        monitor["state"] = {**monitor.get("state", {}), "status": "queued", "stage": "РџСЂРѕРґРѕР»Р¶РµРЅРёРµ"}
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    add_news_log(monitor, "РџСЂРѕРґРѕР»Р¶РµРЅРёРµ СЃРєР°РЅРёСЂРѕРІР°РЅРёСЏ РЅРѕРІРёРЅРѕРє РїРѕСЃС‚Р°РІР»РµРЅРѕ РІ РѕС‡РµСЂРµРґСЊ", "info")
    return jsonify({"monitor": dict(monitor)})


@app.post("/api/news/monitors")
def api_create_news_monitor():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    urls = normalize_start_urls(payload.get("start_urls") or payload.get("site_url") or DEFAULT_START_URL)
    group = clean_text(str(payload.get("group") or "РњР°СЂР¶Р°"))
    brand = clean_text(str(payload.get("brand") or "РќРѕРІС‹Р№ РґРѕРЅРѕСЂ"))
    if payload.get("create_new_brand"):
        with news_lock:
            brand = unique_news_brand_name(group, brand if brand and brand != "РќРѕРІС‹Р№ РґРѕРЅРѕСЂ" else "РќРѕРІС‹Р№ Р±СЂРµРЅРґ")
    monitor = make_news_monitor(
        group,
        brand,
        urls,
    )
    with news_lock:
        news_settings.setdefault("monitors", []).append(monitor)
        save_news_settings()
    add_news_log(monitor, "РњРѕРЅРёС‚РѕСЂ РЅРѕРІРёРЅРѕРє СЃРѕР·РґР°РЅ", "success")
    return jsonify({"monitor": dict(monitor)})


@app.delete("/api/news/monitors/<monitor_id>")
def api_delete_news_monitor(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    if request.args.get("mode") != "brand":
        group = clean_text(str(monitor.get("group") or ""))
        brand = clean_text(str(monitor.get("brand") or ""))
        with news_lock:
            brand_monitors = [
                item
                for item in news_settings.get("monitors", [])
                if isinstance(item, dict)
                and clean_text(str(item.get("group") or "")) == group
                and clean_text(str(item.get("brand") or "")) == brand
            ]
        if len(brand_monitors) < 2:
            return jsonify({"error": "РќРµР»СЊР·СЏ СѓРґР°Р»РёС‚СЊ РµРґРёРЅСЃС‚РІРµРЅРЅРѕРіРѕ РґРѕРЅРѕСЂР° Р±СЂРµРЅРґР°"}), 409
    request_news_stop(monitor_id, "stop")
    with news_lock:
        monitors = news_settings.get("monitors", [])
        news_settings["monitors"] = [
            item
            for item in monitors
            if isinstance(item, dict) and str(item.get("id")) != monitor_id
        ]
        news_stop_events.pop(monitor_id, None)
        save_news_settings()
    add_news_log(monitor, "РњРѕРЅРёС‚РѕСЂ РЅРѕРІРёРЅРѕРє СѓРґР°Р»РµРЅ", "warning")
    return jsonify({"ok": True, "monitors": [dict(item) for item in news_settings.get("monitors", []) if isinstance(item, dict)]})


@app.get("/api/news/monitors/<monitor_id>/download")
def api_download_news_csv(monitor_id: str):
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return jsonify({"error": "РњРѕРЅРёС‚РѕСЂ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    filename = str(monitor.get("state", {}).get("last_csv") or "")
    path = EXPORT_DIR / filename
    if not filename or not path.exists():
        return jsonify({"error": "CSV РµС‰Рµ РЅРµ РіРѕС‚РѕРІ"}), 404
    return send_file(path, as_attachment=True, download_name=filename)


@app.get("/api/news/feeds/<source>/<path:filename>")
def api_download_news_feed(source: str, filename: str):
    ensure_storage()
    allowed_names = {
        str(feed.get("filename") or "")
        for feed in news_settings.get("feed_storage", [])
        if isinstance(feed, dict)
        and str(feed.get("source") or "") == source
    }
    if filename not in allowed_names:
        return jsonify({"error": "Р¤РёРґ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    feed_dir = source_feed_dir(source).resolve()
    path = (feed_dir / filename).resolve()
    if feed_dir not in path.parents or not path.exists():
        return jsonify({"error": "Р¤РёРґ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    return send_file(path, as_attachment=True, download_name=filename)


@app.get("/api/projects")
def api_projects():
    ensure_storage()
    with projects_lock:
        return jsonify({"projects": [public_project(project) for project in projects.values()]})


@app.post("/api/projects")
def api_create_project():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    name = str(payload.get("name") or f"РџСЂРѕРµРєС‚ {len(projects) + 1}").strip()
    start_urls = normalize_start_urls(payload.get("start_urls") or DEFAULT_START_URL)
    project = make_project(name, start_urls)
    with projects_lock:
        projects[project["id"]] = project
        save_projects()
    add_project_log(project, "РџСЂРѕРµРєС‚ СЃРѕР·РґР°РЅ", "success")
    return jsonify({"project": public_project(project)})


@app.patch("/api/projects/<project_id>")
def api_update_project(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404

    payload = request.get_json(silent=True) or {}
    with projects_lock:
        if "name" in payload:
            project["name"] = str(payload.get("name") or project["name"]).strip() or project["name"]
        if "start_urls" in payload:
            project["start_urls"] = normalize_start_urls(payload.get("start_urls"))
        if "product_url_filters" in payload:
            project["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
        if "extraction_rules" in payload:
            project["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "thread_count" in payload:
            thread_count = parse_thread_count(payload.get("thread_count"))
            project["thread_count"] = thread_count
            state = dict(project["state"])
            state["thread_count"] = thread_count
            project["state"] = state
        if "connection_method" in payload:
            project["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            project["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        if "auto_cleanup" in payload:
            project["auto_cleanup"] = bool(payload.get("auto_cleanup"))
        save_projects()
    return jsonify({"project": public_project(project)})


@app.delete("/api/projects/<project_id>")
def api_delete_project(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    with projects_lock:
        if len(projects) <= 1:
            return jsonify({"error": "РќРµР»СЊР·СЏ СѓРґР°Р»РёС‚СЊ РїРѕСЃР»РµРґРЅРёР№ РїСЂРѕРµРєС‚"}), 400
        stop_event = project.get("stop_event")
        if isinstance(stop_event, threading.Event):
            stop_event.set()
        projects.pop(project_id, None)
        save_projects()
    return jsonify({"ok": True})


@app.get("/api/projects/<project_id>/exclusions")
def api_project_exclusions(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    return jsonify({"exclusions": project.get("exclusions", [])})


@app.post("/api/projects/<project_id>/exclusions")
def api_project_add_exclusion(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "РџСѓСЃС‚РѕРµ РёСЃРєР»СЋС‡РµРЅРёРµ"}), 400
    with projects_lock:
        exclusions = project.setdefault("exclusions", [])
        if pattern not in exclusions:
            exclusions.append(pattern)
            save_projects()
    return jsonify({"exclusions": project.get("exclusions", [])})


@app.delete("/api/projects/<project_id>/exclusions/<int:index>")
def api_project_delete_exclusion(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    with projects_lock:
        exclusions = project.setdefault("exclusions", [])
        if index < 0 or index >= len(exclusions):
            return jsonify({"error": "РСЃРєР»СЋС‡РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ"}), 404
        exclusions.pop(index)
        save_projects()
    return jsonify({"exclusions": project.get("exclusions", [])})


@app.get("/api/projects/<project_id>/product-url-filters")
def api_project_product_url_filters(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})


@app.post("/api/projects/<project_id>/product-url-filters")
def api_project_add_product_url_filter(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "РџСѓСЃС‚РѕР№ С„РёР»СЊС‚СЂ СЃСЃС‹Р»РєРё"}), 400
    with projects_lock:
        filters = project.setdefault("product_url_filters", [])
        if pattern not in filters:
            filters.append(pattern)
            save_projects()
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})


@app.delete("/api/projects/<project_id>/product-url-filters/<int:index>")
def api_project_delete_product_url_filter(project_id: str, index: int):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    with projects_lock:
        filters = project.setdefault("product_url_filters", [])
        if index < 0 or index >= len(filters):
            return jsonify({"error": "Р¤РёР»СЊС‚СЂ СЃСЃС‹Р»РєРё РЅРµ РЅР°Р№РґРµРЅ"}), 404
        filters.pop(index)
        save_projects()
    return jsonify({"product_url_filters": project.get("product_url_filters", [])})


def start_project(project: Dict[str, object], resume: bool = False) -> Dict[str, object]:
    worker = project.get("worker_thread")
    state = project.get("state", {})
    if isinstance(worker, threading.Thread) and worker.is_alive():
        if state.get("status") == "running":
            raise RuntimeError("РЎР±РѕСЂ СѓР¶Рµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ")
        worker.join(timeout=2)
        if worker.is_alive():
            raise RuntimeError("РџСЂРµРґС‹РґСѓС‰РёР№ РїРѕС‚РѕРє РµС‰Рµ Р·Р°РІРµСЂС€Р°РµС‚СЃСЏ. РџРѕРІС‚РѕСЂРёС‚Рµ С‡РµСЂРµР· РЅРµСЃРєРѕР»СЊРєРѕ СЃРµРєСѓРЅРґ.")

    project["stop_event"] = threading.Event()
    project["finish_event"] = threading.Event()
    project["run_id"] = int(project.get("run_id", 0)) + 1

    crawler = project.get("crawler") if resume else None
    if crawler:
        crawler.run_id = int(project["run_id"])
        crawler.stop_signal = project["stop_event"]
        crawler.finish_signal = project["finish_event"]
        crawler.thread_count = parse_thread_count(project.get("thread_count", 4))
        crawler.exclusions = list(project.get("exclusions", DEFAULT_EXCLUSIONS))
        crawler.product_url_filters = normalize_patterns(project.get("product_url_filters", []))
        crawler.extraction_rules = normalize_extraction_rules(project.get("extraction_rules", {}))
        crawler.connection_method = normalize_connection_method(project.get("connection_method"))
        crawler.auto_connection_fallback = bool(project.get("auto_connection_fallback", True))
        crawler.excel_finalized = False
    else:
        reset_project_state(project, "running")
        crawler = MaunfeldCrawler(
            list(project.get("start_urls", [DEFAULT_START_URL])),
            int(project["run_id"]),
            project["stop_event"],
            project["finish_event"],
            parse_thread_count(project.get("thread_count", 4)),
            project=project,
            exclusions=list(project.get("exclusions", DEFAULT_EXCLUSIONS)),
            product_url_filters=list(project.get("product_url_filters", [])),
            extraction_rules=normalize_extraction_rules(project.get("extraction_rules", {})),
            connection_method=project.get("connection_method", "requests"),
            auto_connection_fallback=bool(project.get("auto_connection_fallback", True)),
        )
        project["crawler"] = crawler

    def target() -> None:
        try:
            crawler.run(resume=resume)
        except Exception as exc:  # noqa: BLE001
            update_project_state(project, status="error", error=str(exc), currenturl="", download_ready=False)
            add_project_log(project, f"РљСЂРёС‚РёС‡РµСЃРєР°СЏ РѕС€РёР±РєР°: {exc}", "error")

    worker_thread = threading.Thread(target=target, daemon=True)
    project["worker_thread"] = worker_thread
    worker_thread.start()
    add_project_log(project, "РџСЂРѕРґРѕР»Р¶РµРЅРёРµ РїРѕСЃС‚Р°РІР»РµРЅРѕ РІ РѕС‡РµСЂРµРґСЊ" if resume else "РЎР±РѕСЂ РїРѕСЃС‚Р°РІР»РµРЅ РІ РѕС‡РµСЂРµРґСЊ Р·Р°РїСѓСЃРєР°", "info")
    return project["state"]


@app.post("/api/projects/<project_id>/start")
def api_project_start(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404

    payload = request.get_json(silent=True) or {}
    with projects_lock:
        if "start_urls" in payload:
            project["start_urls"] = normalize_start_urls(payload.get("start_urls"))
        if "product_url_filters" in payload:
            project["product_url_filters"] = normalize_patterns(payload.get("product_url_filters"))
        if "extraction_rules" in payload:
            project["extraction_rules"] = normalize_extraction_rules(payload.get("extraction_rules"))
        if "thread_count" in payload:
            project["thread_count"] = parse_thread_count(payload.get("thread_count"))
        if "connection_method" in payload:
            project["connection_method"] = normalize_connection_method(payload.get("connection_method"))
        if "auto_connection_fallback" in payload:
            project["auto_connection_fallback"] = bool(payload.get("auto_connection_fallback"))
        save_projects()

    try:
        state = start_project(project)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)


@app.post("/api/projects/<project_id>/pause")
def api_project_pause(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    status = project.get("state", {}).get("status")
    if status not in {"running", "paused"}:
        return jsonify({"error": "РЎР±РѕСЂ РЅРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ"}), 409
    finish_event = project.get("finish_event")
    stop_event = project.get("stop_event")
    if isinstance(finish_event, threading.Event):
        finish_event.set()
    if status == "running" and isinstance(stop_event, threading.Event):
        stop_event.set()
    crawler = project.get("crawler")
    if crawler:
        crawler.finish_with_excel(partial=True)
    add_project_log(project, "РЎР±РѕСЂ РїСЂРёРѕСЃС‚Р°РЅРѕРІР»РµРЅ СЃ С„РѕСЂРјРёСЂРѕРІР°РЅРёРµРј CSV", "warning")
    return jsonify(project["state"])


@app.post("/api/projects/<project_id>/soft-pause")
def api_project_soft_pause(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    if project.get("state", {}).get("status") != "running":
        return jsonify({"error": "РЎР±РѕСЂ РЅРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ"}), 409
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    update_project_state(project, error="РЎС‚Р°РІР»СЋ СЃР±РѕСЂ РЅР° РїР°СѓР·Сѓ...", currenturl="")
    add_project_log(project, "Р—Р°РїСЂРѕС€РµРЅР° РѕР±С‹С‡РЅР°СЏ РїР°СѓР·Р°", "warning")
    return jsonify(project["state"])


@app.post("/api/projects/<project_id>/resume")
def api_project_resume(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    status = project.get("state", {}).get("status")
    if status not in {"paused", "partial"}:
        return jsonify({"error": "РџСЂРѕРґРѕР»Р¶РёС‚СЊ РјРѕР¶РЅРѕ С‚РѕР»СЊРєРѕ РїРѕСЃР»Рµ РїР°СѓР·С‹"}), 409
    try:
        state = start_project(project, resume=True)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)


@app.post("/api/projects/<project_id>/stop")
def api_project_stop(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    with projects_lock:
        project["run_id"] = int(project.get("run_id", 0)) + 1
        project["crawler"] = None
    reset_project_state(project, "idle")
    add_project_log(project, "РЎР±РѕСЂ РѕСЃС‚Р°РЅРѕРІР»РµРЅ", "warning")
    return jsonify(project["state"])


@app.post("/api/projects/<project_id>/restart")
def api_project_restart(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    stop_event = project.get("stop_event")
    if isinstance(stop_event, threading.Event):
        stop_event.set()
    worker = project.get("worker_thread")
    if isinstance(worker, threading.Thread) and worker.is_alive():
        with projects_lock:
            project["run_id"] = int(project.get("run_id", 0)) + 1
            project["crawler"] = None
        worker.join(timeout=3)
        if worker.is_alive():
            return jsonify({"error": "РџСЂРµРґС‹РґСѓС‰РёР№ СЃР±РѕСЂ РµС‰Рµ Р·Р°РІРµСЂС€Р°РµС‚СЃСЏ. РџРѕРІС‚РѕСЂРёС‚Рµ РїРµСЂРµР·Р°РїСѓСЃРє С‡РµСЂРµР· РЅРµСЃРєРѕР»СЊРєРѕ СЃРµРєСѓРЅРґ."}), 409
    try:
        state = start_project(project)
    except RuntimeError as exc:
        return jsonify({"error": str(exc)}), 409
    return jsonify(state)


@app.get("/api/logs")
def api_logs():
    ensure_storage()
    auto_cleanup = False
    with projects_lock:
        auto_cleanup = any(bool(project.get("auto_cleanup")) for project in projects.values())
    with news_lock:
        auto_cleanup = auto_cleanup or bool(news_settings.get("auto_cleanup"))

    all_logs = read_logs_file()
    if auto_cleanup:
        cutoff = time.time() - 7 * 24 * 60 * 60
        filtered_logs = [
            item
            for item in all_logs
            if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
        ]
        if len(filtered_logs) != len(all_logs):
            all_logs = filtered_logs
            write_logs_file(all_logs)
        with projects_lock:
            for project in projects.values():
                logs = project.get("logs", [])
                project["logs"] = [
                    item
                    for item in logs
                    if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
                ]
        with news_lock:
            logs = news_settings.get("logs", [])
            news_settings["logs"] = [
                item
                for item in logs
                if datetime.fromisoformat(item["time"]).timestamp() >= cutoff
            ]

    all_logs.sort(key=lambda item: item.get("time", ""))
    return jsonify(
        {
            "logs": all_logs,
            "auto_cleanup": auto_cleanup,
            "logs_signature": logs_signature(),
        }
    )

@app.delete("/api/logs")
def api_clear_logs():
    ensure_storage()
    with projects_lock:
        for project in projects.values():
            project["logs"] = []
    with news_lock:
        news_settings["logs"] = []
        save_news_settings()
    write_logs_file([])
    return jsonify({"ok": True})


@app.post("/api/logs/settings")
def api_logs_settings():
    ensure_storage()
    payload = request.get_json(silent=True) or {}
    auto_cleanup = bool(payload.get("auto_cleanup"))
    with projects_lock:
        for project in projects.values():
            project["auto_cleanup"] = auto_cleanup
        save_projects()
    with news_lock:
        news_settings["auto_cleanup"] = auto_cleanup
        save_news_settings()
    return jsonify({"auto_cleanup": auto_cleanup})


@app.post("/api/exclusions")
def add_exclusion():
    payload = request.get_json(silent=True) or {}
    pattern = str(payload.get("pattern", "")).strip()
    if not pattern:
        return jsonify({"error": "РџСѓСЃС‚РѕРµ РёСЃРєР»СЋС‡РµРЅРёРµ"}), 400

    with exclusions_lock:
        items = load_exclusions()
        if pattern not in items:
            items.append(pattern)
            save_exclusions(items)
    return jsonify({"exclusions": items})


@app.delete("/api/exclusions/<int:index>")
def delete_exclusion(index: int):
    with exclusions_lock:
        items = load_exclusions()
        if index < 0 or index >= len(items):
            return jsonify({"error": "РСЃРєР»СЋС‡РµРЅРёРµ РЅРµ РЅР°Р№РґРµРЅРѕ"}), 404
        items.pop(index)
        save_exclusions(items)
    return jsonify({"exclusions": items})


@app.post("/start")
def start_scan():
    global active_crawler, active_finish_event, active_run_id, active_stop_event, worker_thread

    current_status = snapshot_state()["status"]
    if current_status == "running" and worker_thread and worker_thread.is_alive():
        return jsonify({"error": "РЎР±РѕСЂ СѓР¶Рµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ"}), 409

    payload = request.get_json(silent=True) or {}
    start_url = str(payload.get("start_url") or DEFAULT_START_URL).strip()
    thread_count = parse_thread_count(payload.get("thread_count"))

    with state_lock:
        active_run_id += 1
        run_id = active_run_id
        active_stop_event = threading.Event()
        active_finish_event = threading.Event()
        stop_signal = active_stop_event
        finish_signal = active_finish_event

    reset_state("running", thread_count=thread_count)

    crawler = MaunfeldCrawler([start_url], run_id, stop_signal, finish_signal, thread_count)
    active_crawler = crawler

    def target() -> None:
        try:
            crawler.run()
        except Exception as exc:  # noqa: BLE001 - РїРѕРєР°Р·С‹РІР°РµРј РѕС€РёР±РєСѓ РїРѕР»СЊР·РѕРІР°С‚РµР»СЋ РІ РёРЅС‚РµСЂС„РµР№СЃРµ.
            update_state(run_id, status="error", error=str(exc), currenturl="", download_ready=False)

    worker_thread = threading.Thread(target=target, daemon=True)
    worker_thread.start()
    return jsonify(snapshot_state())


@app.post("/stop")
def stop_scan():
    global active_crawler, active_run_id

    active_stop_event.set()
    with state_lock:
        active_run_id += 1
        active_crawler = None
    reset_state("idle")
    return jsonify(snapshot_state())


@app.post("/pause")
def pause_scan_with_result():
    global active_crawler, active_run_id

    if snapshot_state()["status"] != "running":
        return jsonify({"error": "РЎР±РѕСЂ РЅРµ РІС‹РїРѕР»РЅСЏРµС‚СЃСЏ"}), 409

    active_finish_event.set()
    active_stop_event.set()
    crawler = active_crawler
    if crawler:
        crawler.finish_with_excel(partial=True)
        with state_lock:
            active_run_id += 1
            active_crawler = None
        return jsonify(snapshot_state())

    update_state(
        active_run_id,
        error="РћСЃС‚Р°РЅР°РІР»РёРІР°СЋ СЃР±РѕСЂ Рё С„РѕСЂРјРёСЂСѓСЋ Excel РїРѕ СѓР¶Рµ РЅР°Р№РґРµРЅРЅС‹Рј С‚РѕРІР°СЂР°Рј...",
        currenturl="",
    )
    return jsonify(snapshot_state())


@app.post("/restart")
def restart_scan():
    global active_crawler, active_run_id

    active_stop_event.set()
    with state_lock:
        active_run_id += 1
        active_crawler = None
    reset_state("idle")
    return start_scan()


@app.get("/progress")
def progress_stream():
    def stream():
        while True:
            ensure_storage()
            with projects_lock:
                data = json.dumps(
                    {
                        "projects": [public_project(project) for project in projects.values()],
                        "news": public_news_settings(),
                        "logs_signature": logs_signature(),
                    },
                    ensure_ascii=False,
                )
            yield f"event: progress\ndata: {data}\n\n"
            time.sleep(0.5)

    return Response(stream(), mimetype="text/event-stream")


@app.get("/download")
def download_excel():
    current_state = snapshot_state()
    filename = str(current_state.get("filename") or "")
    path = EXPORT_DIR / filename
    if not filename or not path.exists():
        return jsonify({"error": "Р¤Р°Р№Р» РµС‰Рµ РЅРµ РіРѕС‚РѕРІ"}), 404
    return send_file(path, as_attachment=True, download_name=filename)


@app.get("/api/projects/<project_id>/download")
def download_project_csv(project_id: str):
    project = get_project(project_id)
    if not project:
        return jsonify({"error": "РџСЂРѕРµРєС‚ РЅРµ РЅР°Р№РґРµРЅ"}), 404
    current_state = project.get("state", {})
    filename = str(current_state.get("filename") or "")
    path = EXPORT_DIR / filename
    if not filename or not path.exists():
        return jsonify({"error": "Р¤Р°Р№Р» РµС‰Рµ РЅРµ РіРѕС‚РѕРІ"}), 404
    return send_file(path, as_attachment=True, download_name=filename)


if __name__ == "__main__":
    ensure_storage()
    port = int(os.environ.get("PORT", "5000"))
    if os.environ.get("DEBUG_HANG_DUMP") == "1":
        faulthandler.dump_traceback_later(10, repeat=True)
    from socketserver import ThreadingMixIn
    from wsgiref.simple_server import WSGIRequestHandler, WSGIServer, make_server

    class ThreadingWSGIServer(ThreadingMixIn, WSGIServer):
        daemon_threads = True

    with make_server("127.0.0.1", port, app, server_class=ThreadingWSGIServer, handler_class=WSGIRequestHandler) as server:
        print(f"Serving on http://127.0.0.1:{port}", flush=True)
        server.serve_forever()
