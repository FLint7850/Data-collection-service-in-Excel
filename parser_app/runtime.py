"""Общая конфигурация и разделяемое состояние приложения.

Бизнес-логика находится в services/, HTTP-маршруты — в routes/.
Этот модуль не должен содержать обработчики API и код парсинга.
"""

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

from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait

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

from flask import Flask, Response, g, jsonify as flask_jsonify, redirect, render_template, request, send_file, session, url_for

from sqlalchemy import delete, select

from werkzeug.security import check_password_hash, generate_password_hash


BASE_DIR = Path(__file__).resolve().parent.parent

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
                os.environ[key] = value
    except OSError:
        return

load_local_env()

os.environ["PYTHON_DOTENV_DISABLED"] = "1"

# Database imports intentionally happen after .env is loaded so DATABASE_PATH
# and other deployment settings are available during engine creation.
from db import SessionLocal, init_db, session_scope  # noqa: E402
from models import AppSetting, Brand, ConnectionMethod, Donor, FileImport, OwnSite, Project, User  # noqa: E402

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

LOG_DIR = env_path("LOG_DIR", "logs")

FEED_DIR = env_path("FEED_DIR", "feeds")

LOGS_FILE = env_path("LOGS_FILE", str(LOG_DIR / "logs.json"))

UNIFIED_LOG_FILE = env_path("UNIFIED_LOG_FILE", str(LOG_DIR / "app.log"))

EXPORT_DIR = env_path("EXPORT_DIR", "exports")

FILE_IMPORT_DIR = env_path("FILE_IMPORT_DIR", "storage/file-import")

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

NEWS_ENRICH_WORKER_COUNT = env_int("NEWS_ENRICH_WORKER_COUNT", 8, minimum=1, maximum=16)

NEWS_MAX_CONCURRENT_SCANS = env_int("NEWS_MAX_CONCURRENT_SCANS", 3, minimum=1, maximum=16)

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

app = Flask(
    __name__,
    template_folder=str(BASE_DIR / "templates"),
    static_folder=str(BASE_DIR / "static"),
)

app.secret_key = env_str("FLASK_SECRET_KEY", "change-this-secret-key")

app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE=env_str("SESSION_COOKIE_SAMESITE", "Lax"),
    SESSION_COOKIE_SECURE=env_str("SESSION_COOKIE_SECURE", "0") == "1",
    MAX_CONTENT_LENGTH=env_int("MAX_UPLOAD_MB", 100, minimum=1) * 1024 * 1024,
)

state_lock = threading.RLock()

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

HEADLESS_BROWSER_SEMAPHORE = threading.BoundedSemaphore(1)

FEED_STORAGE_LOCK = threading.Lock()

UNIFIED_LOG_LOCK = threading.Lock()

connection_method_cache_lock = threading.Lock()

connection_method_cache: Dict[str, object] = {"loaded_at": 0.0, "codes": []}

news_stop_events: Dict[str, threading.Event] = {}

news_stop_modes: Dict[str, str] = {}

news_scan_threads: Dict[str, threading.Thread] = {}

news_scan_queue: Queue = Queue()

news_queued_scan_ids: Set[str] = set()

news_active_scan_ids: Set[str] = set()

news_scan_dispatch_event = threading.Event()

news_scan_dispatcher_thread: Optional[threading.Thread] = None

news_state_persisted_at: Dict[str, float] = {}

NEWS_TRANSITION_TIMEOUT_SECONDS = 180

BROWSER_RENDER_METHODS = {
    "botasaurus-browser",
    "botasaurus-browser-direct",
    "botasaurus-visible",
    "botasaurus-debug-visible",
    "crawl4ai",
    "playwright",
    "scrapegraphai",
}

DEBUG_VISIBLE_METHODS = {"botasaurus-debug-visible"}

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

UNIFIED_LOG_RE = re.compile(r"^(?P<time>\S+) \[(?P<level>[^\]]+)\] (?P<project_name>.*?): (?P<message>.*)$")

LOG_TAIL_LINES = 2000

MODEL_BRAND_CACHE_SECONDS = 60

model_brand_cache_lock = threading.Lock()

model_brand_cache: Dict[str, object] = {"loaded_at": 0.0, "brands": set()}

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
    "ЧЕРНЫЙ",
    "ЧЁРНЫЙ",
    "БЕЛЫЙ",
    "СЕРЫЙ",
    "СЕРЕБРИСТЫЙ",
    "ЗОЛОТОЙ",
    "КРАСНЫЙ",
    "СИНИЙ",
    "ЗЕЛЕНЫЙ",
    "ЗЕЛЁНЫЙ",
    "РОЗОВЫЙ",
    "БЕЖЕВЫЙ",
    "КОРИЧНЕВЫЙ",
}

ENGINE_OUTPUT_MARKER = "__PARSER_ENGINE_HTML_BASE64__:"

SCRAPY_FETCH_SCRIPT = r"""
import base64
import sys

import scrapy
from scrapy.crawler import CrawlerProcess

url = sys.argv[1]
timeout = int(float(sys.argv[2]))
marker = sys.argv[3]


class SinglePageSpider(scrapy.Spider):
    name = "single_page_fetch"
    body = b""
    handle_httpstatus_all = True
    custom_settings = {
        "LOG_ENABLED": False,
        "ROBOTSTXT_OBEY": False,
        "DOWNLOAD_TIMEOUT": timeout,
        "RETRY_ENABLED": False,
        "COOKIES_ENABLED": True,
        "HTTPERROR_ALLOW_ALL": True,
        "USER_AGENT": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        "DEFAULT_REQUEST_HEADERS": {
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        },
        "TELNETCONSOLE_ENABLED": False,
        "WARN_ON_GENERATOR_RETURN_VALUE": False,
    }

    async def start(self):
        yield scrapy.Request(url, dont_filter=True)

    def parse(self, response):
        SinglePageSpider.body = bytes(response.body or b"")


process = CrawlerProcess(settings=SinglePageSpider.custom_settings)
process.crawl(SinglePageSpider)
process.start(stop_after_crawl=True)
print(marker + base64.b64encode(SinglePageSpider.body).decode("ascii"))
"""

CRAWLEE_FETCH_SCRIPT = r"""
import asyncio
import base64
import sys
from datetime import timedelta

from crawlee.crawlers._http import HttpCrawler

url = sys.argv[1]
timeout = int(float(sys.argv[2]))
marker = sys.argv[3]


async def main():
    result = {"body": b""}
    crawler = HttpCrawler(
        max_requests_per_crawl=1,
        max_request_retries=0,
        request_handler_timeout=timedelta(seconds=timeout),
        configure_logging=False,
        ignore_http_error_status_codes=list(range(300, 600)),
    )

    @crawler.router.default_handler
    async def handler(context):
        result["body"] = await context.http_response.read()

    await crawler.run([url])
    print(marker + base64.b64encode(result["body"]).decode("ascii"))


asyncio.run(main())
"""

PLAYWRIGHT_FETCH_SCRIPT = r"""
import base64
import sys

from playwright.sync_api import sync_playwright

url = sys.argv[1]
timeout = int(float(sys.argv[2])) * 1000
marker = sys.argv[3]
blocked_resource_types = {"image", "media", "font", "stylesheet"}
blocked_url_parts = (
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


def should_block(request):
    if request.resource_type in blocked_resource_types:
        return True
    request_url = (request.url or "").lower()
    return any(part in request_url for part in blocked_url_parts)

with sync_playwright() as p:
    browser = p.chromium.launch(
        headless=True,
        args=[
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            "--no-sandbox",
        ],
    )
    context = browser.new_context(
        user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        locale="ru-RU",
        viewport={"width": 1366, "height": 900},
    )
    page = context.new_page()
    page.route("**/*", lambda route, request: route.abort() if should_block(request) else route.continue_())
    page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try:
        page.wait_for_load_state("networkidle", timeout=min(timeout, 15000))
    except Exception:
        pass
    for _ in range(3):
        try:
            page.mouse.wheel(0, 1600)
            page.wait_for_timeout(500)
        except Exception:
            break
    html = page.content()
    browser.close()
    print(marker + base64.b64encode(html.encode("utf-8", "replace")).decode("ascii"))
"""

SCRAPEGRAPHAI_FETCH_SCRIPT = r"""
import base64
import sys

from scrapegraphai.nodes.fetch_node import FetchNode

url = sys.argv[1]
timeout = int(float(sys.argv[2]))
marker = sys.argv[3]

node = FetchNode(
    input="url",
    output=["doc"],
    node_config={
        "headless": True,
        "timeout": timeout,
        "use_soup": False,
        "cut": False,
        "loader_kwargs": {
            "timeout": timeout,
            "requires_js_support": True,
            "load_state": "networkidle",
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--no-sandbox",
            ],
        },
    },
)
state = node.execute({"url": url})
documents = state.get("doc") or []
html = ""
if documents:
    html = getattr(documents[0], "page_content", "") or ""
if not html:
    compressed = state.get("doc") or state.get("document") or []
    if compressed:
        html = getattr(compressed[0], "page_content", "") or ""
print(marker + base64.b64encode(str(html).encode("utf-8", "replace")).decode("ascii"))
"""

FILE_IMPORT_ALLOWED_SUFFIXES = {".csv", ".xlsx"}

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
