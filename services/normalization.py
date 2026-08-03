"""Shared input normalization and serialization helpers."""

import re
from datetime import datetime
from typing import Dict, List, Optional
from urllib.parse import urldefrag, urlparse, urlunparse

from flask import jsonify as flask_jsonify

from config import DEFAULT_START_URL, MSK_TZ

def normalize_start_urls(value: object, allow_empty: bool = False) -> List[str]:
    from services.scraping import normalize_url
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
    if urls or allow_empty:
        return urls
    return [DEFAULT_START_URL] if DEFAULT_START_URL else []


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
    from services.scraping import clean_text
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
    from services.scraping import clean_text
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
