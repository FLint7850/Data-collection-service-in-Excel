"""Environment parsing and immutable application configuration."""

import os
import re
from datetime import timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Iterable, List, Optional


BASE_DIR = Path(__file__).resolve().parent


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
            if key:
                os.environ.setdefault(key, value.strip().strip('"').strip("'"))
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
    path = Path(env_str(name, default))
    return path if path.is_absolute() else BASE_DIR / path


@lru_cache(maxsize=2)
def botasaurus_browser_executable(prefer_headless_shell: bool = True) -> Optional[str]:
    configured = env_str("PLAYWRIGHT_BROWSER_EXECUTABLE")
    if configured and Path(configured).is_file():
        return configured
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
            for shell_dir in sorted(browser_root.glob("chromium_headless_shell-*"), reverse=True):
                for shell_name in (
                    "chrome-headless-shell.exe",
                    "chrome-headless-shell",
                    "headless_shell.exe",
                    "headless_shell",
                ):
                    matches = list(shell_dir.rglob(shell_name))
                    if matches:
                        return str(matches[0])
        return str(executable) if executable.is_file() else None
    except Exception:
        return None


FEED_DIR = env_path("FEED_DIR", "feeds")
EXPORT_DIR = env_path("EXPORT_DIR", "exports")
FILE_IMPORT_DIR = env_path("FILE_IMPORT_DIR", "storage/file-import")
SCRAPE_CHECKPOINT_DIR = env_path("SCRAPE_CHECKPOINT_DIR", "storage/checkpoints")
PROJECT_PROFILE_DIR = BASE_DIR / "profiles" / "projects"

DEFAULT_START_URL = env_str("DEFAULT_START_URL", "")
DEFAULT_FEED_URL = env_str("DEFAULT_FEED_URL", "https://mega-kuhnya.ru/price/last_modified.xml")
DEFAULT_FEED_GENERATE_URL = env_str(
    "DEFAULT_FEED_GENERATE_URL",
    "https://mega-kuhnya.ru/index.php?route=extension/feed/unixml/new_product",
)
DEFAULT_EXCLUSIONS = env_list(
    "DEFAULT_EXCLUSIONS",
    ["/catalog/rasprodazha/", "/catalog/utsenka/", "/about/", "/contacts/"],
)

MSK_TZ = timezone(timedelta(hours=env_int("APP_TIMEZONE_OFFSET_HOURS", 3)))
REQUEST_TIMEOUT = env_int("REQUEST_TIMEOUT", 20, minimum=1)
CONNECTION_METHOD_TIMEOUT_SECONDS = env_int("CONNECTION_METHOD_TIMEOUT_SECONDS", 60, minimum=1)
REQUEST_DELAY_SECONDS = env_float("REQUEST_DELAY_SECONDS", 0.05, minimum=0.0)
MAX_RETRIES = env_int("MAX_RETRIES", 3, minimum=1)
MAX_DOWNLOAD_BYTES = env_int("MAX_DOWNLOAD_BYTES", 200 * 1024 * 1024, minimum=1024 * 1024)
MAX_ARCHIVE_UNCOMPRESSED_BYTES = env_int(
    "MAX_ARCHIVE_UNCOMPRESSED_BYTES", 512 * 1024 * 1024, minimum=10 * 1024 * 1024
)
MAX_ARCHIVE_MEMBERS = env_int("MAX_ARCHIVE_MEMBERS", 10_000, minimum=100, maximum=100_000)
FEED_WORKER_COUNT = env_int("FEED_WORKER_COUNT", 6, minimum=1, maximum=12)
FEED_SNAPSHOT_CACHE_SECONDS = env_int("FEED_SNAPSHOT_CACHE_SECONDS", 120, minimum=0, maximum=3600)
FEED_SNAPSHOT_RETAIN = env_int("FEED_SNAPSHOT_RETAIN", 3, minimum=2, maximum=10)
NEWS_SCAN_STALL_TIMEOUT = env_int("NEWS_SCAN_STALL_TIMEOUT", 180, minimum=1)
SCHEDULE_DUE_GRACE_SECONDS = env_int("SCHEDULE_DUE_GRACE_SECONDS", 90, minimum=0)
CONNECTION_METHOD_CACHE_SECONDS = env_int("CONNECTION_METHOD_CACHE_SECONDS", 30, minimum=1)
NEWS_TRANSITION_TIMEOUT_SECONDS = env_int("NEWS_TRANSITION_TIMEOUT_SECONDS", 180, minimum=30)
FEED_COMPARISON_PROGRESS_COMMIT_INTERVAL_SECONDS = env_float(
    "FEED_COMPARISON_PROGRESS_COMMIT_INTERVAL_SECONDS", 2.0, minimum=0.5, maximum=30.0
)

PRICE_RE = re.compile(r"\d[\d\s\u2009\xa0]{1,}(?:\u20bd|\u0440\u0443\u0431\.?)", re.IGNORECASE)
BLOCKED_PAGE_MARKERS = tuple(
    env_list(
        "BLOCKED_PAGE_MARKERS",
        [
            "cloudflare", "captcha", "access denied", "http 403", "__qrator",
            "qauth.js", "qrator", "доступ ограничен", "проверяем ваш браузер", "enable javascript",
        ],
    )
)
BLOCKED_BROWSER_RESOURCE_TYPES = {"image", "media", "font", "stylesheet"}
BLOCKED_BROWSER_URL_PARTS = (
    "google-analytics", "googletagmanager", "doubleclick", "adservice", "adsystem",
    "yandex.ru/metrika", "mc.yandex", "metrika", "analytics", "counter",
    "facebook.net", "vk.com/rtrg", "top-fwz1.mail.ru", "mail.ru/counter",
)
SESSION_BROWSER_METHODS = {"protected-site"}
BOTASAURUS_HEADLESS_METHODS = {"botasaurus-browser", "botasaurus-browser-direct", "botasaurus-visible"}
DEBUG_VISIBLE_METHODS = {"botasaurus-debug-visible"}
STATIC_BROWSER_RENDER_METHODS = {
    *SESSION_BROWSER_METHODS, *BOTASAURUS_HEADLESS_METHODS, *DEBUG_VISIBLE_METHODS,
    "crawl4ai", "playwright", "scrapegraphai",
}

FILE_IMPORT_ALLOWED_SUFFIXES = {".csv", ".xlsx", ".xls"}
FILE_IMPORT_ACTIVE_STATUSES = {"queued", "running"}
FILE_IMPORT_RESULT_FIELDS = ["row", "name", "price", "brand", "model_candidates", "selected_model", "missing_on"]
FEED_COMPARISON_ACTIVE_STATUSES = {"queued", "running"}
FEED_COMPARISON_RESULT_FIELDS = list(FILE_IMPORT_RESULT_FIELDS)
VISUAL_MODEL_TRANSLATION = str.maketrans(
    {
        "А": "A", "В": "B", "Е": "E", "К": "K", "М": "M", "Н": "H",
        "О": "O", "Р": "P", "С": "C", "Т": "T", "Х": "X",
        "а": "A", "в": "B", "е": "E", "к": "K", "м": "M", "н": "H",
        "о": "O", "р": "P", "с": "C", "т": "T", "х": "X",
    }
)
