"""Extracted application service module."""

from datetime import time as datetime_time
import csv
import io
import os
import re
import requests
import shutil
import smtplib
import ssl
import threading
import time
import uuid
import xml.etree.ElementTree as ET
from bs4 import BeautifulSoup
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, as_completed, wait
from config import DEFAULT_EXCLUSIONS, EXPORT_DIR, FEED_DIR, FEED_SNAPSHOT_CACHE_SECONDS, FEED_SNAPSHOT_RETAIN, FEED_WORKER_COUNT, MSK_TZ, NEWS_TRANSITION_TIMEOUT_SECONDS, PROJECT_PROFILE_DIR, SCHEDULE_DUE_GRACE_SECONDS
from database.session import session_scope
from datetime import datetime, timedelta
from email.message import EmailMessage
from models import Brand, utc_now
from pathlib import Path
from runtime import state as runtime_state
from runtime.state import FEED_STORAGE_LOCK, NEWS_PROGRESS_FIELDS, feed_snapshot_cache, news_browser_sessions, news_crawlers, news_lock, news_scan_threads, news_settings, news_state_persisted_at, news_stop_events, news_stop_modes
from services.connections import get_donor_row, normalize_connection_method
from services.normalization import datetime_to_input_value, normalize_emails, normalize_extraction_rules, normalize_model_key, normalize_patterns, normalize_start_urls, output_text, parse_db_int, repair_mojibake, repair_mojibake_text, safe_filename
from services.outbound_proxy import outbound_requests_session
from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from typing import Dict, List, Optional, Set
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse
from services.scraping import (
    BrowserMethodSession,
    ProductSiteCrawler,
    clean_text,
    extract_model_by_markers,
    extract_product_data,
    finalize_scraped_model,
    first_by_selector,
    first_text,
    product_url_filter_patterns,
)
from services.scraping.checkpoints import delete_scrape_checkpoint, load_scrape_checkpoint, save_scrape_checkpoint
from sqlalchemy import and_, or_
from sqlalchemy.orm import selectinload


class CollectOnlyCrawler(ProductSiteCrawler):
    def __init__(self, *args, progress_callback=None, **kwargs):
        kwargs.setdefault("allow_empty_price", True)
        super().__init__(*args, **kwargs)
        self.progress_callback = progress_callback

    def update_state(self, **kwargs: object) -> None:
        if self.progress_callback:
            self.progress_callback(kwargs)

    def log(self, message: str, level: str = "info") -> None:
        if self.progress_callback:
            self.progress_callback(
                {
                    "log_message": message,
                    "log_level": level,
                }
            )

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


def extract_availability(soup: BeautifulSoup, selector: str = "") -> str:
    selected = text_by_selector(soup, selector)
    if selected:
        return selected
    page_text = clean_text(soup.get_text(" ", strip=True))
    patterns = [
        r"В наличии",
        r"Нет в наличии",
        r"Под заказ",
        r"Ожидается",
        r"Сообщить о поступлении",
        r"available",
        r"out of stock",
        r"in stock",
    ]
    for pattern in patterns:
        match = re.search(pattern, page_text, flags=re.IGNORECASE)
        if match:
            return clean_text(match.group(0))
    return ""


def availability_is_excluded(availability: str, rules: object) -> bool:
    """Проверяет статус наличия по построчным правилам исключения до сравнения с фидами."""
    status = clean_text(availability).lower()
    if not status:
        return False
    for rule in normalize_patterns(rules):
        normalized_rule = clean_text(rule).lower()
        if normalized_rule and normalized_rule in status:
            return True
    return False


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
        return "Мега-кухня"
    if "vsya-tehnika" in hostname:
        return "Вся техника"
    return hostname or "Фид"


def source_feed_dir(source: str) -> Path:
    return FEED_DIR / safe_filename(source)


def feed_snapshots_dir() -> Path:
    return FEED_DIR / ".snapshots"


def feed_snapshot_path(feed: Dict[str, object]) -> Optional[Path]:
    snapshot_value = str(feed.get("snapshot") or "").strip()
    source_value = str(feed.get("source") or "").strip()
    filename = Path(str(feed.get("filename") or "")).name
    if not source_value or not filename:
        return None
    if not snapshot_value:
        # Backward compatibility for feed metadata written before snapshots.
        legacy_root = source_feed_dir(source_value).resolve()
        legacy_path = (legacy_root / filename).resolve()
        return legacy_path if legacy_root in legacy_path.parents else None
    snapshot = safe_filename(snapshot_value)
    source = safe_filename(source_value)
    path = (feed_snapshots_dir() / snapshot / source / filename).resolve()
    snapshot_root = (feed_snapshots_dir() / snapshot).resolve()
    return path if snapshot_root in path.parents else None


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


def make_feed_session() -> requests.Session:
    session = outbound_requests_session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            )
        }
    )
    return session


def trigger_feed_generation(generate_url: str) -> None:
    try:
        with make_feed_session().get(generation_file_url(generate_url), timeout=60) as response:
            response.raise_for_status()
    except Exception:
        pass


def download_feed_site(index: int, site: Dict[str, str], snapshot_dir: Path, snapshot: str) -> Optional[Dict[str, object]]:
    from services.file_validation import write_limited_response
    url = site["feed_url"]
    temporary_path: Optional[Path] = None
    try:
        with make_feed_session().get(url, timeout=60, stream=True) as response:
            response.raise_for_status()
            source = feed_source_key(url)
            feed_dir = snapshot_dir / source
            feed_dir.mkdir(parents=True, exist_ok=True)
            filename = local_feed_filename("feed", index, url)
            path = feed_dir / filename
            temporary_path = path.with_suffix(path.suffix + ".part")
            write_limited_response(response, temporary_path)
        os.replace(temporary_path, path)
        return {
            "kind": "feed",
            "source": source,
            "source_label": site.get("name") or feed_source_label(url),
            "url": url,
            "filename": filename,
            "snapshot": snapshot,
            "size": path.stat().st_size,
            "downloaded_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        }
    except Exception:
        if temporary_path:
            temporary_path.unlink(missing_ok=True)
        return None


def cleanup_feed_snapshots() -> None:
    snapshots_dir = feed_snapshots_dir()
    if not snapshots_dir.exists():
        return
    try:
        snapshots = sorted(
            [path for path in snapshots_dir.iterdir() if path.is_dir()],
            key=lambda path: path.stat().st_mtime,
            reverse=True,
        )
    except OSError:
        return
    for path in snapshots[FEED_SNAPSHOT_RETAIN:]:
        try:
            shutil.rmtree(path)
        except OSError:
            # Windows can keep a file open while it is being downloaded. Keep this
            # old immutable snapshot and retry cleanup after a future refresh.
            continue


def wait_feed_futures(futures, stop_event: Optional[threading.Event]) -> List[object]:
    from services.file_import_service import stop_file_import_if_requested
    pending = set(futures)
    results: List[object] = []
    while pending:
        stop_file_import_if_requested(stop_event)
        completed, pending = wait(pending, timeout=0.5, return_when=FIRST_COMPLETED)
        if not completed:
            continue
        for future in completed:
            results.append(future.result())
    return results


def download_feed_files(stop_event: Optional[threading.Event] = None) -> List[Dict[str, object]]:
    from services.file_import_service import FileImportStopped, stop_file_import_if_requested
    from services.news import own_sites_from_settings
    with news_lock:
        own_sites = own_sites_from_settings(news_settings)
        generate_urls = [site["feed_generate_url"] for site in own_sites if site.get("feed_generate_url")]
    signature = tuple((site["feed_url"], site.get("feed_generate_url", "")) for site in own_sites)
    with FEED_STORAGE_LOCK:
        cache_feeds = feed_snapshot_cache.get("feeds")
        cache_age = time.time() - float(feed_snapshot_cache.get("created_at") or 0.0)
        if (
            signature == feed_snapshot_cache.get("signature")
            and cache_age <= FEED_SNAPSHOT_CACHE_SECONDS
            and isinstance(cache_feeds, list)
            and cache_feeds
            and all((path := feed_snapshot_path(feed)) and path.exists() for feed in cache_feeds if isinstance(feed, dict))
        ):
            return [dict(feed) for feed in cache_feeds if isinstance(feed, dict)]

        stop_file_import_if_requested(stop_event)
        if generate_urls:
            executor = ThreadPoolExecutor(max_workers=min(FEED_WORKER_COUNT, len(generate_urls)))
            try:
                wait_feed_futures([executor.submit(trigger_feed_generation, url) for url in generate_urls], stop_event)
            except FileImportStopped:
                executor.shutdown(wait=False, cancel_futures=True)
                raise
            else:
                executor.shutdown(wait=True)

        snapshot = f"{int(time.time() * 1000)}_{uuid.uuid4().hex[:8]}"
        snapshot_dir = feed_snapshots_dir() / snapshot
        snapshot_dir.mkdir(parents=True, exist_ok=False)
        downloaded: List[Dict[str, object]] = []
        if own_sites:
            executor = ThreadPoolExecutor(max_workers=min(FEED_WORKER_COUNT, len(own_sites)))
            try:
                futures = [
                    executor.submit(download_feed_site, index, site, snapshot_dir, snapshot)
                    for index, site in enumerate(own_sites, start=1)
                ]
                for feed in wait_feed_futures(futures, stop_event):
                    if feed:
                        downloaded.append(feed)
            except FileImportStopped:
                executor.shutdown(wait=False, cancel_futures=True)
                try:
                    shutil.rmtree(snapshot_dir)
                except OSError:
                    pass
                raise
            else:
                executor.shutdown(wait=True)
        if not downloaded:
            try:
                shutil.rmtree(snapshot_dir)
            except OSError:
                pass
            return []

        feed_snapshot_cache.update(
            {"signature": signature, "created_at": time.time(), "feeds": [dict(feed) for feed in downloaded]}
        )
        cleanup_feed_snapshots()
        return downloaded


def fetch_existing_vendor_code_sets() -> tuple[Set[str], List[Dict[str, object]], List[Dict[str, object]]]:
    from services.news import save_news_configuration
    downloaded_feeds = download_feed_files()
    codes: Set[str] = set()
    feeds: List[Dict[str, object]] = []
    feed_code_sets: List[Dict[str, object]] = []
    for feed in downloaded_feeds:
        path = feed_snapshot_path(feed)
        try:
            if path is None:
                raise FileNotFoundError("Не задан путь к snapshot фида")
            feed_codes = parse_vendor_codes_from_xml(path.read_bytes())
            codes.update(feed_codes)
            feeds.append({**feed, "codes_count": len(feed_codes)})
            feed_code_sets.append({**feed, "codes_count": len(feed_codes), "codes": feed_codes})
        except Exception as exc:
            feeds.append({**feed, "codes_count": 0, "error": str(exc)})
            feed_code_sets.append({**feed, "codes_count": 0, "codes": set(), "error": str(exc)})
    with news_lock:
        news_settings["feed_storage"] = feeds
        save_news_configuration()
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
                "source_label": str(feed.get("source_label") or feed.get("url") or "Фид"),
                "url": str(feed.get("url") or ""),
                "count": count,
                "codes_count": int(feed.get("codes_count") or 0),
                "error": str(feed.get("error") or ""),
            }
        )
    return summary


def parse_vendor_codes_from_xml(content: bytes) -> Set[str]:
    codes: Set[str] = set()
    try:
        for _event, node in ET.iterparse(io.BytesIO(content), events=("end",)):
            children = list(node)
            if children:
                values: Dict[str, str] = {}
                for child in children:
                    key = str(child.tag).split("}")[-1].lower()
                    if key in {"vendorcode", "model", "name", "title"}:
                        values[key] = clean_text(child.text or "")
                vendor_code = normalize_model_key(values.get("vendorcode", ""))
                model = values.get("model") or values.get("name") or values.get("title") or vendor_code
                model_key = normalize_model_key(model)
                if vendor_code:
                    codes.add(vendor_code)
                if model_key:
                    codes.add(model_key)
                node.clear()
    except ET.ParseError:
        raise
    return codes


def validate_monitor_selectors(monitor: Dict[str, object]) -> None:
    selector_fields = []
    rules = monitor.get("extraction_rules", {}) if isinstance(monitor.get("extraction_rules"), dict) else {}
    selectors = monitor.get("selector_settings", {}) if isinstance(monitor.get("selector_settings"), dict) else {}
    for key in ("product_card_selector", "product_url_selector", "model_selector", "price_selector"):
        if rules.get(key):
            selector_fields.append((key, str(rules[key])))
    for key in ("name_selector", "availability_selector"):
        if selectors.get(key):
            selector_fields.append((key, str(selectors[key])))
    soup = BeautifulSoup("", "html.parser")
    for key, selector in selector_fields:
        try:
            soup.select(selector)
        except Exception as exc:
            raise ValueError(f"Ошибка CSS-селектора {key}: {selector}. {exc}") from exc


def update_news_monitor_state(monitor: Dict[str, object], persist: bool = True, **kwargs: object) -> None:
    from services.news import make_news_state
    from services.progress_service import has_positive_progress_value, is_active_status, merge_stable_progress_state, publish_news_monitor_progress
    with news_lock:
        previous_state = dict(monitor.get("state", make_news_state()))
        state = dict(previous_state)
        current_status = str(state.get("status") or "")
        terminal_statuses = {"completed", "error", "partial", "idle", "stopped"}
        if state.get("finished_at") and current_status in terminal_statuses and kwargs.get("status") != current_status:
            return
        state.update(kwargs)
        previous_progress = monitor.get("_last_progress_state")
        state = merge_stable_progress_state(
            state,
            previous_progress if isinstance(previous_progress, dict) else previous_state,
            NEWS_PROGRESS_FIELDS,
        )
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
        if is_active_status(state.get("status")):
            if has_positive_progress_value(state, NEWS_PROGRESS_FIELDS) or str(state.get("currenturl") or "").strip():
                monitor["_last_progress_state"] = dict(state)
        else:
            monitor.pop("_last_progress_state", None)
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
                publish_news_monitor_progress(item)
    if persist:
        persist_news_monitor_state(monitor)


def persist_news_monitor_state(monitor: Dict[str, object], force: bool = False) -> None:
    from services.news import normalize_news_state
    from services.progress_service import publish_news_brand_progress
    monitor_id = str(monitor.get("id") or "").strip()
    if not monitor_id:
        return
    publish_news_brand_progress(monitor)
    now = time.time()
    if not force and now - news_state_persisted_at.get(monitor_id, 0) < 1:
        return
    news_state_persisted_at[monitor_id] = now
    state = normalize_news_state(monitor.get("state"))
    for attempt in range(4):
        try:
            with session_scope() as session:
                donor = get_donor_row(session, monitor_id)
                if donor is None:
                    return
                donor.updated_at = utc_now()
                if donor.brand:
                    donor.brand.state = state
            return
        except OperationalError as exc:
            if "database is locked" not in str(exc).lower() or attempt == 3:
                print(f"Failed to persist news monitor state {monitor_id}: {exc}", flush=True)
                return
            time.sleep(0.25 * (attempt + 1))
        except Exception as exc:
            print(f"Failed to persist news monitor state {monitor_id}: {exc}", flush=True)
            return


def news_monitor_thread_alive(monitor_id: object) -> bool:
    thread = news_scan_threads.get(str(monitor_id))
    return isinstance(thread, threading.Thread) and thread.is_alive()


def start_news_scan(monitor_id: str, manual: bool, resume: bool = False) -> bool:
    monitor_id = str(monitor_id)

    def run() -> None:
        try:
            from services.news import get_news_monitor
            monitor = get_news_monitor(monitor_id)
            state = monitor.get("state", {}) if monitor else {}
            if monitor and state.get("status") == "queued":
                if resume:
                    scan_news_monitor(monitor_id, manual, resume=True)
                else:
                    scan_news_monitor(monitor_id, manual)
        finally:
            with news_lock:
                if news_scan_threads.get(monitor_id) is threading.current_thread():
                    news_scan_threads.pop(monitor_id, None)

    with news_lock:
        current = news_scan_threads.get(monitor_id)
        if isinstance(current, threading.Thread) and current.is_alive():
            return False
        thread = threading.Thread(
            target=run,
            name=f"news-scan-{monitor_id}",
            daemon=True,
        )
        news_scan_threads[monitor_id] = thread
    try:
        thread.start()
    except Exception:
        with news_lock:
            if news_scan_threads.get(monitor_id) is thread:
                news_scan_threads.pop(monitor_id, None)
        raise
    return True


def transition_requested_at(monitor: Dict[str, object]) -> Optional[datetime]:
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    for key in ("stop_requested_at", "finished_at", "started_at"):
        parsed = parse_schedule_datetime(state.get(key))
        if parsed:
            return parsed
    return None


def is_stale_news_transition(monitor: Dict[str, object]) -> bool:
    state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    status = str(state.get("status") or "")
    if status not in {"pausing", "stopping"}:
        return False
    requested_at = transition_requested_at(monitor)
    timed_out = bool(requested_at and (datetime.now(MSK_TZ) - requested_at).total_seconds() >= NEWS_TRANSITION_TIMEOUT_SECONDS)
    return timed_out or not news_monitor_thread_alive(monitor.get("id"))


def finalize_stale_news_transition(monitor: Dict[str, object]) -> bool:
    if not is_stale_news_transition(monitor):
        return False
    state = dict(monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {})
    was_pausing = state.get("status") == "pausing"
    state.update(
        {
            "status": "partial" if was_pausing else "stopped",
            "stage": "Приостановлено" if was_pausing else "Остановлено",
            "error": "",
            "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
            "currenturl": "",
            "queue_size": 0,
            "active_tasks": 0,
            "active_urls": [],
        }
    )
    with news_lock:
        monitor["state"] = state
        monitor["brand_state"] = dict(state)
    return True


def cleanup_stale_news_transitions() -> None:
    changed: List[Dict[str, object]] = []
    with news_lock:
        monitors = [item for item in news_settings.get("monitors", []) if isinstance(item, dict)]
    for monitor in monitors:
        if finalize_stale_news_transition(monitor):
            changed.append(monitor)
    for monitor in changed:
        threading.Thread(target=persist_news_monitor_state, args=(monitor, True), daemon=True).start()


def update_brand_scan_state(
    target_type: str,
    target_id: str,
    status: str,
    started_at: float,
    found_products: int = 0,
    new_count: int = 0,
    data: Optional[Dict[str, object]] = None,
) -> None:
    from services.news import make_news_state, normalize_news_state
    from services.progress_service import progress_int
    if target_type not in {"news", "donor"}:
        return
    data = data or {}
    existing_state: Dict[str, object] = {}
    with news_lock:
        monitor = next((item for item in news_settings.get("monitors", []) if str(item.get("id")) == str(target_id)), None)
        if monitor and isinstance(monitor.get("state"), dict):
            existing_state = dict(monitor.get("state") or {})
    finished_at = datetime.now(MSK_TZ).isoformat(timespec="seconds")
    state = {
        **make_news_state(),
        **existing_state,
        "status": status or "idle",
        "started_at": existing_state.get("started_at") or datetime.fromtimestamp(started_at, MSK_TZ).isoformat(timespec="seconds"),
        "finished_at": finished_at,
        "last_scan_at": existing_state.get("last_scan_at") or finished_at,
        "found_products": found_products,
        "new_count": new_count,
    }
    if data.get("csv"):
        state["last_csv"] = str(data.get("csv") or "")
    if isinstance(data.get("missing_by_feed"), list):
        state["missing_by_feed"] = data["missing_by_feed"]
    if data.get("availability_skipped") is not None:
        state["availability_skipped"] = progress_int(data.get("availability_skipped"))
    if data.get("error"):
        state["error"] = str(data.get("error") or "")
    state = normalize_news_state(state)
    with session_scope() as session:
        donor = get_donor_row(session, target_id)
        if donor and donor.brand:
            donor.brand.state = state
    with news_lock:
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
    from services.news import get_news_monitor
    event = get_news_stop_event(monitor_id)
    monitor: Optional[Dict[str, object]] = None
    with news_lock:
        news_stop_modes[monitor_id] = mode
    monitor = get_news_monitor(monitor_id)
    if monitor:
        update_news_monitor_state(
            monitor,
            persist=False,
            status="pausing" if mode == "pause" else "stopping",
            stage="Приостановка" if mode == "pause" else "Остановка",
            currenturl="",
            stop_requested_at=datetime.now(MSK_TZ).isoformat(timespec="seconds"),
        )
    event.set()
    with news_lock:
        browser_session = news_browser_sessions.get(monitor_id)
    if isinstance(browser_session, BrowserMethodSession):
        browser_session.close()
    if monitor:
        threading.Thread(target=persist_news_monitor_state, args=(monitor, True), daemon=True).start()
    return event


def collect_products_for_monitor(
    monitor: Dict[str, object],
    stop_signal: threading.Event,
    browser_session: BrowserMethodSession,
    connection_method_state: Optional[Dict[str, object]] = None,
    resume: bool = False,
) -> List[Dict[str, str]]:
    from services.projects import parse_thread_count
    finish_signal = threading.Event()
    start_urls = normalize_start_urls(monitor.get("start_urls") or "", allow_empty=True)
    if not start_urls:
        raise RuntimeError("У донора не указаны стартовые URL для сканирования.")

    def progress_callback(payload: Dict[str, object]) -> None:
        from services.news import add_news_log
        log_message = str(payload.get("log_message") or "").strip()
        log_level = str(payload.get("log_level") or "info").strip() or "info"
        if log_message:
            add_news_log(monitor, log_message, log_level)
            if stop_signal.is_set():
                return
            event_state = {"last_event": log_message}
            if log_level == "warning":
                event_state["last_warning"] = log_message
            elif log_level == "error":
                event_state["error"] = log_message
            update_news_monitor_state(monitor, **event_state)
            if not any(key in payload for key in ("percent", "currenturl", "totalprocessed", "found_products")):
                return
        if stop_signal.is_set():
            return
        update_news_monitor_state(
            monitor,
            status=str(payload.get("status") or "running"),
            stage="Сканирование сайта-донора",
            percent=min(85, int(payload.get("percent", 0) or 0)),
            currenturl=str(payload.get("currenturl", "")),
            processed=int(payload.get("totalprocessed", 0) or 0),
            found_products=int(payload.get("found_products", 0) or 0),
            in_memory_products=int(payload.get("in_memory_products", payload.get("found_products", 0)) or 0),
            queue_size=int(payload.get("queue_size", 0) or 0),
            active_tasks=int(payload.get("active_tasks", 0) or 0),
            active_urls=list(payload.get("active_urls", []) or [])[:8],
            failed_pages=int(payload.get("failed_pages", 0) or 0),
            stall_seconds=int(payload.get("stall_seconds", 0) or 0),
            skipped=int(payload.get("skipped", 0) or 0),
            error=str(payload.get("error", "") or ""),
            last_warning=str(payload.get("last_warning", "") or ""),
        )

    monitor_id = str(monitor.get("id") or "")
    with news_lock:
        existing = news_crawlers.get(monitor_id) if resume else None
    crawler = existing if isinstance(existing, CollectOnlyCrawler) else None
    resume_with_state = crawler is not None
    checkpoint = load_scrape_checkpoint("news", monitor_id) if resume and crawler is None else None

    if crawler is None:
        crawler = CollectOnlyCrawler(
            start_urls,
            int(time.time()),
            stop_signal,
            finish_signal,
            parse_thread_count(monitor.get("thread_count", 4)),
            project=None,
            exclusions=list(monitor.get("exclusions", DEFAULT_EXCLUSIONS)),
            product_url_filters=list(monitor.get("product_url_filters", [])),
            product_url_exclusions=list(monitor.get("product_url_exclusions", [])),
            extraction_rules=normalize_extraction_rules(monitor.get("extraction_rules", {})),
            connection_method=normalize_connection_method(monitor.get("connection_method")),
            auto_connection_fallback=bool(monitor.get("auto_connection_fallback", True)),
            connection_method_state=connection_method_state,
            allow_empty_price=True,
            browser_session=browser_session,
            owns_browser_session=False,
            progress_callback=progress_callback,
        )
        if checkpoint:
            resume_with_state = crawler.restore_checkpoint(checkpoint)
    else:
        crawler.stop_signal = stop_signal
        crawler.finish_signal = finish_signal
        crawler.thread_count = parse_thread_count(monitor.get("thread_count", 4))
        crawler.exclusions = list(monitor.get("exclusions", DEFAULT_EXCLUSIONS))
        crawler.extraction_rules = normalize_extraction_rules(monitor.get("extraction_rules", {}))
        crawler.product_url_filters = product_url_filter_patterns(
            list(monitor.get("product_url_filters", [])),
            crawler.extraction_rules,
        )
        crawler.product_url_exclusions = normalize_patterns(monitor.get("product_url_exclusions", []))
        crawler.connection_method = normalize_connection_method(monitor.get("connection_method"))
        crawler.auto_connection_fallback = bool(monitor.get("auto_connection_fallback", True))
        crawler.connection_method_state = connection_method_state or crawler.connection_method_state
        crawler.active_connection_method = crawler.connection_method
        crawler.browser_session = browser_session
        crawler.owns_browser_session = False
        crawler.progress_callback = progress_callback
        crawler.excel_finalized = False

    with news_lock:
        news_crawlers[monitor_id] = crawler
    if resume and not resume_with_state:
        from services.news import add_news_log
        add_news_log(monitor, "Checkpoint продолжения не найден; сканирование будет запущено заново", "warning")
    crawler.run(resume=resume_with_state)
    products = crawler.snapshot_results()
    if crawler.recovery_pause_reason:
        with news_lock:
            news_stop_modes[monitor_id] = "pause"
        update_news_monitor_state(
            monitor,
            status="pausing",
            error="",
            last_warning=crawler.recovery_pause_reason,
            found_products=len(products),
            in_memory_products=len(products),
            currenturl="",
        )
    return products


def enrich_news_product(
    product: Dict[str, str],
    monitor: Dict[str, object],
    stop_signal: threading.Event,
    browser_session: BrowserMethodSession,
    connection_method_state: Optional[Dict[str, object]] = None,
) -> Dict[str, str]:
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
        "url": url,
    }
    fetcher = CollectOnlyCrawler(
        [url],
        int(time.time()),
        stop_signal,
        threading.Event(),
        1,
        connection_method=normalize_connection_method(monitor.get("connection_method")),
        auto_connection_fallback=bool(monitor.get("auto_connection_fallback", True)),
        connection_method_state=connection_method_state,
        allow_empty_price=True,
        browser_session=browser_session,
        owns_browser_session=False,
    )
    try:
        html = fetcher.fetch(url) if url else ""
    finally:
        # The browser manager belongs to the whole news scan. This worker does
        # not close any of the shared Botasaurus/Playwright sessions.
        fetcher.close_browser_sessions()
    if not html:
        return details
    soup = BeautifulSoup(html, "html.parser")
    name = extract_product_name(soup, str(selector_settings.get("name_selector", "")))
    product_data = extract_product_data(
        url,
        html,
        product.get("price", ""),
        extraction_rules,
        allow_empty_price=True,
    )
    if product_data:
        details["model"] = product_data.get("model", details["model"])
        details["price"] = product_data.get("price", details["price"])
    else:
        marker_model = extract_model_by_markers(html, extraction_rules)
        model_candidate = marker_model or details["model"] or name
        prepared_model = finalize_scraped_model(
            model_candidate,
            url,
            extraction_rules,
            preserve_configured_model=bool(marker_model),
        )
        if prepared_model:
            details["model"] = prepared_model
    details["name"] = name or details["name"]
    details["availability"] = extract_availability(soup, str(selector_settings.get("availability_selector", "")))
    return details


def create_news_csv(rows: List[Dict[str, str]], monitor: Dict[str, object], filename: str = "") -> Path:
    from services.news import news_csv_filename
    if not filename:
        filename = news_csv_filename(monitor)
    filename = output_text(filename)
    path = EXPORT_DIR / filename
    with path.open("w", encoding="utf-8-sig", newline="") as csv_file:
        writer = csv.writer(csv_file, delimiter=";")
        writer.writerow(
            [
                "Дата появления",
                "Группа",
                "Сайт/бренд",
                "Наименование",
                "Модель",
                "Цена",
                "Наличие",
                "Нет на сайтах",
                "URL товара",
            ]
        )
        for row in rows:
            writer.writerow(
                [
                    output_text(row.get("date_found", "")),
                    output_text(row.get("group", "")),
                    output_text(row.get("brand", "")),
                    output_text(row.get("name", "")),
                    output_text(row.get("model", "")),
                    output_text(row.get("price", "")),
                    output_text(row.get("availability", "")),
                    output_text(row.get("missing_on", "")),
                    output_text(row.get("url", "")),
                ]
            )
    return path


def build_email_message(
    sender_email: str,
    recipient: str,
    subject: str,
    body: str,
    csv_path: Optional[Path] = None,
) -> EmailMessage:
    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender_email
    message["To"] = recipient
    message.set_content(body)
    if csv_path:
        message.add_attachment(
            csv_path.read_bytes(),
            maintype="text",
            subtype="csv",
            filename=str(repair_mojibake_text(csv_path.name) or csv_path.name),
        )
    return message


def send_messages_to_recipients(
    host: str,
    port: int,
    security_mode: str,
    username: str,
    password: str,
    sender_email: str,
    recipients: List[str],
    subject: str,
    body: str,
    csv_path: Optional[Path] = None,
) -> None:
    context = ssl.create_default_context()
    failures: List[str] = []
    if security_mode == "tls":
        with smtplib.SMTP(host, port, timeout=30) as server:
            server.starttls(context=context)
            server.login(username, password)
            for recipient in recipients:
                try:
                    server.send_message(
                        build_email_message(sender_email, recipient, subject, body, csv_path),
                        from_addr=sender_email,
                        to_addrs=[recipient],
                    )
                except Exception as exc:
                    failures.append(f"{recipient}: {exc}")
    else:
        with smtplib.SMTP_SSL(host, port, context=context, timeout=30) as server:
            server.login(username, password)
            for recipient in recipients:
                try:
                    server.send_message(
                        build_email_message(sender_email, recipient, subject, body, csv_path),
                        from_addr=sender_email,
                        to_addrs=[recipient],
                    )
                except Exception as exc:
                    failures.append(f"{recipient}: {exc}")
    if failures:
        raise RuntimeError("Не удалось отправить на: " + "; ".join(failures))


def feed_missing_labels(keys: Set[str], feed_code_sets: List[Dict[str, object]]) -> List[str]:
    if not keys:
        return []
    missing_feeds = []
    for feed in feed_code_sets:
        feed_codes = feed.get("codes", set())
        if not isinstance(feed_codes, set):
            feed_codes = set(feed_codes) if isinstance(feed_codes, list) else set()
        if not (keys & feed_codes):
            missing_feeds.append(str(feed.get("source_label") or feed.get("url") or "Фид"))
    return missing_feeds


def build_partial_news_items(
    products: List[Dict[str, str]],
    monitor: Dict[str, object],
    feed_code_sets: List[Dict[str, object]],
) -> List[Dict[str, str]]:
    """Build a valid best-effort news result without making more page requests."""
    rows: List[Dict[str, str]] = []
    seen_models: Set[str] = set()
    for product in products:
        keys = product_compare_keys(product)
        if not keys:
            continue
        missing_feeds = feed_missing_labels(keys, feed_code_sets)
        if not missing_feeds:
            continue
        model = str(product.get("model") or "").strip()
        dedupe_key = model.casefold() or str(product.get("url") or "").strip()
        if not dedupe_key or dedupe_key in seen_models:
            continue
        seen_models.add(dedupe_key)
        rows.append(
            {
                "date_found": datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S"),
                "group": str(monitor.get("group") or ""),
                "brand": str(monitor.get("brand") or ""),
                "name": str(product.get("name") or model),
                "model": model,
                "price": str(product.get("price") or ""),
                "availability": str(product.get("availability") or ""),
                "missing_on": ", ".join(missing_feeds),
                "missing_on_count": str(len(missing_feeds)),
                "url": str(product.get("url") or ""),
            }
        )
    return rows


def news_monitor_profile_storage_dir(monitor: Dict[str, object]) -> Path:
    monitor_id = safe_filename(str(monitor.get("id") or monitor.get("brand") or "monitor"))
    return PROJECT_PROFILE_DIR / "news" / monitor_id


def news_monitor_should_keep_browser_profile(monitor: Dict[str, object]) -> bool:
    method = normalize_connection_method(monitor.get("connection_method"))
    return method == "protected-site" or bool(monitor.get("auto_connection_fallback", True))


def enrich_news_candidates(
    products: List[Dict[str, str]],
    monitor: Dict[str, object],
    feed_code_sets: List[Dict[str, object]],
    stop_signal: threading.Event,
    browser_session: BrowserMethodSession,
    progress_callback,
    connection_method_state: Optional[Dict[str, object]] = None,
) -> List[Dict[str, str]]:
    from services.projects import parse_thread_count
    candidates: List[tuple[int, Dict[str, str]]] = []
    resolved: List[Optional[Dict[str, str]]] = [None] * len(products)

    for index, product in enumerate(products):
        keys = product_compare_keys(product)
        if not keys:
            candidates.append((index, product))
            continue
        missing_feeds = feed_missing_labels(keys, feed_code_sets)
        if not missing_feeds:
            details = {
                "date_found": datetime.now(MSK_TZ).strftime("%d.%m.%Y %H:%M:%S"),
                "group": str(monitor.get("group") or ""),
                "brand": str(monitor.get("brand") or ""),
                "name": product.get("model", ""),
                "model": product.get("model", ""),
                "price": product.get("price", ""),
                "availability": "",
                        "url": product.get("url", ""),
            }
            resolved[index] = details
            progress_callback(index + 1, details.get("url", ""))
        else:
            candidates.append((index, product))

    if candidates and not stop_signal.is_set():
        max_workers = min(parse_thread_count(monitor.get("thread_count", 4)), len(candidates))
        if connection_method_state is None:
            initial_method = normalize_connection_method(monitor.get("connection_method"))
            connection_method_state = {
                "active_method": initial_method,
                "resource_method": initial_method,
                "resource_generation": 0,
                "lock": threading.Lock(),
                "transition_lock": threading.Lock(),
            }
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            future_to_index = {
                executor.submit(
                    enrich_news_product,
                    product,
                    monitor,
                    stop_signal,
                    browser_session,
                    connection_method_state,
                ): (index, product)
                for index, product in candidates
            }
            completed = len(products) - len(candidates)
            for future in as_completed(future_to_index):
                if stop_signal.is_set():
                    raise NewsScanStopped()
                index, product = future_to_index[future]
                details = future.result()
                details["model"] = details.get("model") or product.get("model", "")
                resolved[index] = details
                completed += 1
                progress_callback(completed, details.get("url", product.get("url", "")))

    return [item for item in resolved if item]


def send_news_email(
    monitor: Optional[Dict[str, object]],
    new_count: int,
    test: bool = False,
    error_holder: Optional[List[str]] = None,
    missing_summary: Optional[List[Dict[str, object]]] = None,
) -> bool:
    from services.news import add_news_log, default_smtp_settings, resolve_export_file
    with news_lock:
        smtp_config = dict(news_settings.get("smtp", {}))
    recipients = normalize_emails(smtp_config.get("recipients", []))
    username = str(smtp_config.get("username") or "").strip()
    password = str(smtp_config.get("password") or "").strip()
    sender_emails = normalize_emails(username)
    if not username or not password or not recipients:
        error_message = "Email не отправлен: заполните email-логин, пароль приложения и получателей SMTP"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False
    if not sender_emails:
        error_message = "Email не отправлен: email-логин должен быть адресом почты"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "warning")
        return False

    sender_email = sender_emails[0]
    csv_path: Optional[Path] = None
    if test:
        subject = "Тест email-уведомления"
        body = "Тестовое письмо отправлено из мониторинга новинок. SMTP-настройки работают."
    else:
        brand = str(repair_mojibake_text((monitor or {}).get("brand") or "донор"))
        site_url = str((monitor or {}).get("site_url") or "")
        subject = f"Уведомление о новинках на сайте {brand}"
        lines = [f"На {site_url or brand} найдено всего: {new_count}"]
        for item in missing_summary or []:
            count = int(item.get("count") or 0)
            label = str(repair_mojibake_text(item.get("source_label") or item.get("url") or "сайт"))
            lines.append(f"На сайте {label} не было найдено {count} новинок.")
        body = "\n".join(lines)

        state = (monitor or {}).get("state", {}) if isinstance((monitor or {}).get("state"), dict) else {}
        state_data = state.get("data", {}) if isinstance(state.get("data"), dict) else {}
        csv_filename = str(state.get("last_csv") or state_data.get("csv") or "")
        csv_path = resolve_export_file(csv_filename)

    smtp_defaults = default_smtp_settings()
    host = str(smtp_config.get("host") or smtp_defaults["host"])
    port = int(smtp_config.get("port") or smtp_defaults["port"])
    security_mode = str(smtp_config.get("security") or smtp_defaults["security"]).lower()
    try:
        send_messages_to_recipients(host, port, security_mode, username, password, sender_email, recipients, subject, body, csv_path)
    except Exception as exc:
        error_message = f"Ошибка отправки email: {exc}"
        if error_holder is not None:
            error_holder.append(error_message)
        add_news_log(monitor, error_message, "error")
        return False

    add_news_log(
        monitor,
        "Тестовое email-сообщение отправлено" if test else f"Email-уведомление отправлено. Новинок: {new_count}",
        "success",
    )
    return True


def scan_news_monitor(monitor_id: str, manual: bool = False, resume: bool = False) -> None:
    from services.news import add_news_log, delete_news_csv_for_monitor, get_news_monitor, make_news_state, save_news_monitor
    from services.projects import parse_thread_count
    monitor = get_news_monitor(monitor_id)
    if not monitor:
        return
    refresh_monitor_schedule_from_brand(monitor)
    started = time.time()
    previous_state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
    resume_elapsed = int(previous_state.get("elapsed_seconds", 0) or 0) if resume else 0
    if not resume:
        with news_lock:
            news_crawlers.pop(str(monitor_id), None)
        delete_scrape_checkpoint("news", monitor_id)
    stop_event = get_news_stop_event(monitor_id)
    stop_event.clear()
    with news_lock:
        news_stop_modes.pop(monitor_id, None)
    new_items: List[Dict[str, str]] = []
    products: List[Dict[str, str]] = []
    local_feeds: List[Dict[str, object]] = []
    feed_code_sets: List[Dict[str, object]] = []
    missing_summary: List[Dict[str, object]] = []
    availability_skipped = 0
    profile_dir = news_monitor_profile_storage_dir(monitor) if news_monitor_should_keep_browser_profile(monitor) else None
    initial_connection_method = normalize_connection_method(monitor.get("connection_method"))
    browser_session = BrowserMethodSession(
        stop_event,
        parse_thread_count(monitor.get("thread_count", 4)),
        profile_dir=profile_dir,
        initial_method=initial_connection_method,
    )
    with news_lock:
        news_browser_sessions[monitor_id] = browser_session
    connection_method_state = {
        "active_method": initial_connection_method,
        "resource_method": initial_connection_method,
        "resource_generation": 0,
        "lock": threading.Lock(),
        "transition_lock": threading.Lock(),
    }

    def check_stop_requested() -> None:
        if stop_event.is_set():
            raise NewsScanStopped()

    with news_lock:
        monitor["state"] = {
            **make_news_state("running"),
            "stage": "Подготовка",
            "started_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
            "elapsed_seconds": resume_elapsed,
            "run_monitor_id": str(monitor_id),
        }
        monitor["brand_state"] = dict(monitor["state"])
        persist_news_monitor_state(monitor, force=True)
    add_news_log(monitor, "Ручное сканирование новинок запущено" if manual else "Плановое сканирование новинок запущено", "info")
    add_news_log(monitor, "Начал сбор", "info")

    try:
        update_news_monitor_state(monitor, stage="Подготовка", percent=2)
        validate_monitor_selectors(monitor)
        add_news_log(
            monitor,
            f"Scan settings: URL={', '.join(monitor.get('start_urls', []))}; "
            f"method={monitor.get('connection_method')}; threads={monitor.get('thread_count')}",
            "info",
        )
        update_news_monitor_state(monitor, stage="Сканирование сайта-донора", percent=5)
        products = collect_products_for_monitor(
            monitor,
            stop_event,
            browser_session,
            connection_method_state,
            resume=resume,
        )
        check_stop_requested()
        add_news_log(monitor, "Сбор закончил", "info")
        add_news_log(monitor, f"Сканирование сайта завершено. Найдено товаров: {len(products)}", "info")
        update_news_monitor_state(monitor, stage="Генерация и загрузка фидов ваших сайтов", percent=84, currenturl="")
        add_news_log(monitor, "Скачивание фида", "info")
        all_existing_codes, local_feeds, feed_code_sets = fetch_existing_vendor_code_sets()
        check_stop_requested()
        add_news_log(monitor, "Фид скачался", "info")
        add_news_log(
            monitor,
            f"Фиды обновлены после сбора донора: {len(local_feeds)}. Моделей всего: {len(all_existing_codes)}",
            "info",
        )
        update_news_monitor_state(
            monitor,
            stage="Сравнение с фидами",
            percent=86,
            candidate_products=len(products),
            found_products=len(products),
            compared_products=0,
            currenturl="",
        )
        add_news_log(monitor, "Началось сравнение", "info")
        known = monitor.get("known_new_products", {}) if isinstance(monitor.get("known_new_products"), dict) else {}
        def update_compare_progress(index: int, current_url: str = "") -> None:
            check_stop_requested()
            update_news_monitor_state(
                monitor,
                stage="Сравнение с фидами",
                percent=86 + int((index / max(1, len(products))) * 12),
                compared_products=index,
                currenturl=current_url,
            )

        enriched_products = enrich_news_candidates(
            products,
            monitor,
            feed_code_sets,
            stop_event,
            browser_session,
            update_compare_progress,
            connection_method_state,
        )
        availability_exclusions = normalize_patterns((monitor.get("selector_settings") or {}).get("availability_exclusions", []))
        for details, product in zip(enriched_products, products):
            check_stop_requested()
            details["model"] = details.get("model") or product.get("model", "")
            if availability_is_excluded(details.get("availability", ""), availability_exclusions):
                availability_skipped += 1
                continue
            detail_keys = product_compare_keys(details) | product_compare_keys(product)
            if not detail_keys:
                continue
            missing_feeds = feed_missing_labels(detail_keys, feed_code_sets)
            if not missing_feeds:
                continue
            model_key = sorted(detail_keys)[0]
            details["missing_on"] = ", ".join(missing_feeds)
            details["missing_on_count"] = len(missing_feeds)
            new_items.append(details)
            known[model_key] = details
        missing_summary = build_missing_summary(new_items, feed_code_sets)
        add_news_log(monitor, "Сравнение закончилось", "info")
        if availability_skipped:
            add_news_log(monitor, f"Исключено по статусу наличия: {availability_skipped}", "info")
        for item in missing_summary:
            add_news_log(
                monitor,
                f"Нет на {item.get('source_label')}: {int(item.get('count') or 0)}",
                "info",
            )

        update_news_monitor_state(monitor, stage="Формирование CSV", percent=99, currenturl="")
        csv_path = create_news_csv(new_items, monitor)
        delete_news_csv_for_monitor(monitor, keep_filename=csv_path.name)
        elapsed = resume_elapsed + int(time.time() - started)
        with news_lock:
            monitor["known_new_products"] = known
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "completed",
                "stage": "Завершено",
                "percent": 100,
                "processed": len(products),
                "found_products": len(products),
                "candidate_products": len(products),
                "compared_products": len(products),
                "in_memory_products": len(products),
                "availability_skipped": availability_skipped,
                "queue_size": 0,
                "active_tasks": 0,
                "active_urls": [],
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
            if normalize_schedule_type(monitor.get("schedule_type")) != "once":
                monitor["next_run_at"] = update_brand_next_run_at(monitor.get("brand_id"))
            save_news_monitor(monitor)
        delete_scrape_checkpoint("news", monitor_id)
        with news_lock:
            news_crawlers.pop(str(monitor_id), None)
        add_news_log(monitor, f"Сканирование завершено. Найдено новинок: {len(new_items)}. CSV: {csv_path.name}", "success")
        update_brand_scan_state(
            "donor",
            monitor_id,
            "completed",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={
                "csv": csv_path.name,
                "feeds": local_feeds,
                "missing_by_feed": missing_summary,
                "availability_skipped": availability_skipped,
            },
        )
        if new_items:
            send_news_email(monitor, len(new_items), missing_summary=missing_summary)
    except NewsScanStopped:
        elapsed = resume_elapsed + int(time.time() - started)
        with news_lock:
            stop_mode = news_stop_modes.get(monitor_id, "stop")
            crawler = news_crawlers.get(str(monitor_id))
        partial_csv = ""
        recovery_reason = (
            crawler.recovery_pause_reason
            if isinstance(crawler, CollectOnlyCrawler) and crawler.recovery_pause_reason
            else "Сканирование приостановлено с сохранением промежуточного результата."
        )
        if stop_mode == "pause" and isinstance(crawler, CollectOnlyCrawler):
            save_scrape_checkpoint("news", monitor_id, crawler.checkpoint_payload())
        if stop_mode == "pause" and products:
            try:
                if not feed_code_sets:
                    _all_codes, local_feeds, feed_code_sets = fetch_existing_vendor_code_sets()
                new_items = build_partial_news_items(products, monitor, feed_code_sets)
            except Exception as partial_error:
                add_news_log(monitor, f"Не удалось полностью сравнить промежуточный результат: {partial_error}", "warning")
        if stop_mode == "pause":
            partial_path = create_news_csv(new_items, monitor)
            partial_csv = partial_path.name
            delete_news_csv_for_monitor(monitor, keep_filename=partial_csv)
        else:
            delete_scrape_checkpoint("news", monitor_id)
            with news_lock:
                news_crawlers.pop(str(monitor_id), None)
        missing_summary = build_missing_summary(new_items, feed_code_sets) if feed_code_sets else []
        outstanding = 0
        if isinstance(crawler, CollectOnlyCrawler):
            outstanding = crawler.queue.qsize() + len(crawler.deferred_urls)
        with news_lock:
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "partial" if stop_mode == "pause" else "idle",
                "stage": "Приостановлено" if stop_mode == "pause" else "Ожидание",
                "error": "",
                "last_warning": recovery_reason if stop_mode == "pause" else "",
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "currenturl": "",
                "last_csv": partial_csv or monitor.get("state", {}).get("last_csv", ""),
                "new_count": len(new_items),
                "missing_by_feed": missing_summary,
                "processed": len(products),
                "found_products": len(products),
                "in_memory_products": len(products),
                "availability_skipped": availability_skipped,
                "queue_size": outstanding if stop_mode == "pause" else 0,
                "active_tasks": 0,
                "active_urls": [],
            }
            monitor["brand_state"] = dict(monitor["state"])
            save_news_monitor(monitor)
        add_news_log(
            monitor,
            f"Сканирование новинок приостановлено. CSV: {partial_csv}" if stop_mode == "pause" else "Сканирование новинок остановлено",
            "warning",
        )
        update_brand_scan_state(
            "donor",
            monitor_id,
            "partial" if stop_mode == "pause" else "idle",
            started,
            found_products=len(products),
            new_count=len(new_items),
            data={"csv": partial_csv, "availability_skipped": availability_skipped},
        )
    except Exception as exc:
        elapsed = resume_elapsed + int(time.time() - started)
        delete_scrape_checkpoint("news", monitor_id)
        with news_lock:
            news_crawlers.pop(str(monitor_id), None)
        with news_lock:
            monitor["state"] = {
                **monitor.get("state", {}),
                "status": "error",
                "stage": "Ошибка",
                "error": str(exc),
                "finished_at": datetime.now(MSK_TZ).isoformat(timespec="seconds"),
                "elapsed_seconds": elapsed,
                "found_products": len(products),
                "in_memory_products": len(products),
                "availability_skipped": availability_skipped,
                "active_tasks": 0,
                "active_urls": [],
            }
            monitor["brand_state"] = dict(monitor["state"])
            save_news_monitor(monitor)
        add_news_log(monitor, f"Ошибка сканирования новинок: {exc}", "error")
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
        browser_session.close()
        with news_lock:
            if news_browser_sessions.get(monitor_id) is browser_session:
                news_browser_sessions.pop(monitor_id, None)
            news_stop_modes.pop(monitor_id, None)
            thread = news_scan_threads.get(monitor_id)
            if thread is threading.current_thread():
                news_scan_threads.pop(monitor_id, None)
            state = monitor.get("state", {}) if isinstance(monitor.get("state"), dict) else {}
            if state.get("status") != "partial":
                news_crawlers.pop(str(monitor_id), None)
        stop_event.clear()


def parse_scan_time(value: object) -> datetime_time:
    text = str(value or "01:00")
    try:
        hour, minute = [int(part) for part in text[:5].split(":", 1)]
        return datetime_time(max(0, min(hour, 23)), max(0, min(minute, 59)), tzinfo=MSK_TZ)
    except Exception:
        return datetime_time(1, 0, tzinfo=MSK_TZ)


def parse_schedule_datetime(value: object) -> Optional[datetime]:
    if isinstance(value, datetime):
        return value.astimezone(MSK_TZ) if value.tzinfo else value.replace(tzinfo=MSK_TZ)
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    return parsed.astimezone(MSK_TZ) if parsed.tzinfo else parsed.replace(tzinfo=MSK_TZ)


def normalize_schedule_type(value: object) -> str:
    schedule_type = str(value or "daily")
    return schedule_type if schedule_type in {"daily", "weekly", "once"} else "daily"


def normalize_weekday(value: object) -> int:
    try:
        return max(0, min(int(value or 0), 6))
    except (TypeError, ValueError):
        return 0


def compute_schedule_run_at(
    schedule_type: object,
    scan_time: object,
    weekday: object = 0,
    once_at: object = None,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    now = now or datetime.now(MSK_TZ)
    schedule = normalize_schedule_type(schedule_type)
    if schedule == "once":
        return parse_schedule_datetime(once_at)
    run_time = parse_scan_time(scan_time)
    candidate = now.replace(hour=run_time.hour, minute=run_time.minute, second=0, microsecond=0)
    if schedule == "weekly":
        candidate += timedelta(days=normalize_weekday(weekday) - now.weekday())
    return candidate


def compute_next_schedule_at(
    schedule_type: object,
    scan_time: object,
    weekday: object = 0,
    once_at: object = None,
    now: Optional[datetime] = None,
) -> Optional[datetime]:
    now = now or datetime.now(MSK_TZ)
    schedule = normalize_schedule_type(schedule_type)
    if schedule == "once":
        return parse_schedule_datetime(once_at)
    candidate = compute_schedule_run_at(schedule, scan_time, weekday, now=now)
    if candidate is None:
        return None
    if schedule == "weekly":
        if candidate <= now:
            candidate += timedelta(days=7)
    elif candidate <= now:
        candidate += timedelta(days=1)
    return candidate


def brand_schedule_fields(brand: Brand) -> Dict[str, object]:
    return {
        "enabled": bool(brand.enabled),
        "schedule_type": normalize_schedule_type(brand.schedule_type),
        "scan_time": str(brand.scan_time or "01:00")[:5],
        "weekday": normalize_weekday(brand.weekday),
        "next_run_at": datetime_to_input_value(brand.next_run_at),
        "primary_donor_id": str(brand.primary_donor_id) if brand.primary_donor_id else "",
    }


def is_brand_due(brand: Brand, now: Optional[datetime] = None) -> bool:
    if not bool(brand.enabled):
        return False
    state = brand.state if isinstance(brand.state, dict) else {}
    if state.get("status") in {"running", "queued", "pausing", "stopping"}:
        return False
    now = now or datetime.now(MSK_TZ)
    schedule_type = normalize_schedule_type(brand.schedule_type)
    due_at = compute_schedule_run_at(schedule_type, brand.scan_time, brand.weekday, brand.next_run_at, now)
    if not due_at:
        return False
    if schedule_type in {"daily", "weekly"}:
        seconds_after_due = (now - due_at).total_seconds()
        if seconds_after_due < 0 or seconds_after_due >= SCHEDULE_DUE_GRACE_SECONDS:
            return False
    elif now < due_at:
        return False
    last_scan = str(state.get("last_scan_at") or "")
    if last_scan:
        last_scan_at = parse_schedule_datetime(last_scan)
        if last_scan_at and last_scan_at >= due_at:
            return False
    return True


def update_brand_next_run_at(brand_id: object) -> str:
    with session_scope() as session:
        brand = session.get(Brand, parse_db_int(brand_id))
        if not brand:
            return ""
        next_at = compute_next_schedule_at(brand.schedule_type, brand.scan_time, brand.weekday, brand.next_run_at)
        if normalize_schedule_type(brand.schedule_type) != "once":
            brand.next_run_at = next_at.replace(tzinfo=None) if next_at else None
        return datetime_to_input_value(brand.next_run_at)


def refresh_monitor_schedule_from_brand(monitor: Dict[str, object]) -> None:
    brand_id = parse_db_int(monitor.get("brand_id"))
    if not brand_id:
        return
    with session_scope() as session:
        brand = session.get(Brand, brand_id)
        if not brand:
            return
        monitor.update(brand_schedule_fields(brand))


def scheduled_brand_candidates(now: Optional[datetime] = None) -> List[Brand]:
    """Load only brands whose schedule can be due in the current grace window."""
    now = now or datetime.now(MSK_TZ)
    window_start = now - timedelta(seconds=SCHEDULE_DUE_GRACE_SECONDS)
    minute_pairs = {
        (window_start.weekday(), window_start.strftime("%H:%M")),
        (now.weekday(), now.strftime("%H:%M")),
    }
    schedule_conditions = [
        and_(
            Brand.schedule_type == "once",
            Brand.next_run_at.is_not(None),
            Brand.next_run_at <= now.replace(tzinfo=None),
        )
    ]
    for weekday, scan_time in minute_pairs:
        schedule_conditions.extend(
            [
                and_(Brand.schedule_type == "daily", Brand.scan_time == scan_time),
                and_(Brand.schedule_type == "weekly", Brand.weekday == weekday, Brand.scan_time == scan_time),
            ]
        )
    with session_scope() as session:
        rows = session.scalars(
            select(Brand)
            .options(selectinload(Brand.donors))
            .where(
                Brand.enabled.is_(True),
                Brand.donors.any(),
                or_(*schedule_conditions),
            )
            .order_by(Brand.id)
        ).all()
        return [brand for brand in rows if is_brand_due(brand, now)]


def start_news_scheduler() -> None:
    if (
        isinstance(runtime_state.news_scheduler_thread, threading.Thread)
        and runtime_state.news_scheduler_thread.is_alive()
    ):
        return

    def scheduler_loop() -> None:
        from services.news import add_news_log, save_news_monitor, sync_brand_runtime_fields
        while True:
            try:
                due_ids: List[str] = []
                with news_lock:
                    # Deletion uses this lock too, so the database candidates and
                    # the process-local donor list belong to the same snapshot.
                    due_brands = scheduled_brand_candidates()
                    monitor_by_id = {
                        str(monitor.get("id")): monitor
                        for monitor in news_settings.get("monitors", [])
                        if isinstance(monitor, dict)
                    }
                    due_brand_data = [
                        {
                            "brand_id": brand.id,
                            "brand_name": brand.name,
                            "primary_id": brand.primary_donor_id,
                            "schedule": brand_schedule_fields(brand),
                            "donor_ids": [donor.id for donor in brand.donors],
                        }
                        for brand in due_brands
                    ]
                    for brand_data in due_brand_data:
                        primary_id = str(brand_data.get("primary_id") or "")
                        selected = monitor_by_id.get(primary_id)
                        if selected is None:
                            fallback_id = next((str(donor_id) for donor_id in brand_data.get("donor_ids", []) if str(donor_id) in monitor_by_id), "")
                            selected = monitor_by_id.get(fallback_id)
                        if selected is None:
                            add_news_log(
                                None,
                                f"Плановый запуск пропущен: основной донор бренда {brand_data.get('brand_name')} не найден.",
                                "warning",
                            )
                            continue
                        selected.update(brand_data["schedule"])
                        selected["state"] = {**selected.get("state", {}), "status": "queued"}
                        selected["brand_state"] = dict(selected["state"])
                        sync_brand_runtime_fields(selected)
                        save_news_monitor(selected)
                        due_ids.append(str(selected.get("id")))
                for monitor_id in due_ids:
                    start_news_scan(monitor_id, manual=False)
            except Exception as error:
                try:
                    add_news_log(None, f"Ошибка планировщика новинок: {error}", "error")
                except Exception:
                    print(f"News scheduler error: {error}", flush=True)
            time.sleep(30)

    runtime_state.news_scheduler_thread = threading.Thread(
        target=scheduler_loop,
        name="news-scheduler",
        daemon=True,
    )
    runtime_state.news_scheduler_thread.start()
