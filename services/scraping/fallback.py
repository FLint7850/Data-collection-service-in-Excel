"""URL normalization, extraction rules and HTTP/browser scraping engines."""

import requests
import threading
import time
from bs4 import BeautifulSoup
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from config import (
    BOTASAURUS_HEADLESS_METHODS,
    CONNECTION_METHOD_TIMEOUT_SECONDS,
    DEFAULT_EXCLUSIONS,
    MAX_RETRIES,
    NEWS_SCAN_STALL_TIMEOUT,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT,
    SESSION_BROWSER_METHODS,
)
from pathlib import Path
from queue import Empty, Queue
from runtime.state import reset_state, update_state
from services.connections import is_browser_render_method, is_debug_visible_method, normalize_connection_method, ordered_db_connection_methods
from services.normalization import normalize_extraction_rules, normalize_patterns, normalize_start_urls, now_iso
from services.outbound_proxy import outbound_requests_session
from typing import Dict, Iterable, List, Optional, Set
from urllib.parse import urlparse

from services.scraping.browser import (
    BrowserMethodSession,
    fetch_with_crawlee,
    fetch_with_scrapy,
)
from services.scraping.extraction import (
    extract_listing_products,
    extract_product_data,
    has_explicit_model_rules,
)
from services.scraping.http import (
    canonicalize_product_url_by_filters,
    exclusion_matches,
    fetch_with_botasaurus_request,
    has_static_extension,
    is_product_url_for_filters,
    looks_blocked_or_empty,
    normalize_url,
    product_url_filter_patterns,
    product_url_matches_any,
    product_url_matches_filters,
    same_site,
    should_follow_project_url,
)

class ProductSiteCrawler:
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
        product_url_exclusions: Optional[List[str]] = None,
        extraction_rules: Optional[Dict[str, str]] = None,
        connection_method: str = "requests",
        auto_connection_fallback: bool = True,
        connection_method_state: Optional[Dict[str, object]] = None,
        allow_empty_price: bool = False,
        browser_session: Optional[BrowserMethodSession] = None,
        owns_browser_session: bool = True,
        profile_dir: Optional[Path] = None,
    ):
        from services.projects import parse_thread_count
        self.run_id = run_id
        self.stop_signal = stop_signal
        self.finish_signal = finish_signal
        self.thread_count = parse_thread_count(thread_count)
        self.start_urls = normalize_start_urls(start_urls)
        self.start_url = self.start_urls[0]
        self.root_netloc = urlparse(self.start_url).netloc
        self.project = project
        self.exclusions = exclusions if exclusions is not None else DEFAULT_EXCLUSIONS.copy()
        self.extraction_rules = normalize_extraction_rules(extraction_rules or {})
        self.product_url_filters = product_url_filter_patterns(product_url_filters or [], self.extraction_rules)
        self.product_url_exclusions = normalize_patterns(product_url_exclusions or [])
        self.connection_method = normalize_connection_method(connection_method)
        self.auto_connection_fallback = bool(auto_connection_fallback)
        self.allow_empty_price = bool(allow_empty_price)
        self.profile_dir = profile_dir
        if connection_method_state is None:
            connection_method_state = {
                "active_method": self.connection_method,
                "lock": threading.Lock(),
                "transition_lock": threading.Lock(),
                "resource_method": self.connection_method,
                "resource_generation": 0,
            }
        else:
            connection_method_state.setdefault("active_method", self.connection_method)
            connection_method_state.setdefault("lock", threading.Lock())
            connection_method_state.setdefault("transition_lock", threading.Lock())
            connection_method_state.setdefault(
                "resource_method",
                str(connection_method_state.get("active_method") or self.connection_method),
            )
            connection_method_state.setdefault("resource_generation", 0)
        self.connection_method_state = connection_method_state
        self.active_connection_method = str(connection_method_state.get("active_method") or self.connection_method)
        self.browser_session = browser_session or BrowserMethodSession(
            self.stop_signal,
            self.thread_count,
            profile_dir=self.profile_dir,
            initial_method=self.connection_method,
        )
        self.owns_browser_session = owns_browser_session
        self.browser_sessions_lock = threading.Lock()
        self.browser_sessions: List[object] = []
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
        self.result_models: Set[str] = set()
        self.pending_prices: Dict[str, str] = {}
        self.results: List[Dict[str, str]] = []
        self.failed_attempts: Dict[str, int] = {}
        self.deferred_urls: Set[str] = set()
        self.permanent_failures: Set[str] = set()
        self.data_lock = threading.Lock()
        self.excel_finalized = False
        self.started_at = 0.0
        self.elapsed_before_resume = 0.0
        self.last_progress_at = time.time()
        self.last_progress_signature: tuple = ()
        self.fatal_error = ""
        self.recovery_pause_reason = ""

    def update_state(self, **kwargs: object) -> None:
        from services.projects import update_project_state
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            update_project_state(self.project, **kwargs)
        else:
            update_state(self.run_id, **kwargs)

    def reset_state(self, status: str = "idle") -> None:
        from services.projects import reset_project_state
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            reset_project_state(self.project, status)
        else:
            reset_state(status, self.run_id, self.thread_count)

    def log(self, message: str, level: str = "info") -> None:
        from services.projects import add_project_log
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            add_project_log(self.project, message, level)

    def get_session(self) -> requests.Session:
        session = getattr(self.thread_local, "session", None)
        if session is None:
            session = outbound_requests_session()
            session.headers.update(self.headers)
            self.thread_local.session = session
        return session

    def browser_session_for_worker(self) -> BrowserMethodSession:
        return self.browser_session

    def close_browser_sessions(self) -> None:
        sessions: List[object] = []
        with self.browser_sessions_lock:
            for session in self.browser_sessions:
                if session not in sessions:
                    sessions.append(session)
            self.browser_sessions.clear()
        if self.owns_browser_session:
            if self.browser_session not in sessions:
                sessions.append(self.browser_session)
        for session in sessions:
            session.close()

    def checkpoint_payload(self) -> Dict[str, object]:
        """Return the durable state needed to resume without rescanning successful URLs."""
        with self.data_lock:
            with self.queue.mutex:
                queued_urls = list(self.queue.queue)
            return {
                "start_urls": list(self.start_urls),
                "queued_urls": queued_urls,
                "deferred_urls": sorted(self.deferred_urls),
                "visited_urls": sorted(self.visited),
                "skipped_urls": sorted(self.skipped_urls),
                "permanent_failures": sorted(self.permanent_failures),
                "failed_attempts": dict(self.failed_attempts),
                "pending_prices": dict(self.pending_prices),
                "results": [dict(item) for item in self.results],
                "result_urls": sorted(self.result_urls),
                "result_models": sorted(self.result_models),
                "elapsed_seconds": float(self.elapsed_seconds()),
            }

    def restore_checkpoint(self, payload: object) -> bool:
        if not isinstance(payload, dict):
            return False

        def strings(key: str) -> List[str]:
            value = payload.get(key, [])
            if not isinstance(value, list):
                return []
            return [str(item).strip() for item in value if str(item).strip()]

        checkpoint_start_urls = strings("start_urls")
        if checkpoint_start_urls and checkpoint_start_urls != self.start_urls:
            return False

        raw_results = payload.get("results", [])
        results = [
            {str(key): str(value or "") for key, value in item.items()}
            for item in raw_results
            if isinstance(item, dict)
        ] if isinstance(raw_results, list) else []
        raw_attempts = payload.get("failed_attempts", {})
        failed_attempts: Dict[str, int] = {}
        if isinstance(raw_attempts, dict):
            for url, count in raw_attempts.items():
                if not str(url).strip():
                    continue
                try:
                    failed_attempts[str(url)] = max(0, int(count or 0))
                except (TypeError, ValueError):
                    continue
        raw_prices = payload.get("pending_prices", {})
        pending_prices = {
            str(url): str(price or "")
            for url, price in raw_prices.items()
            if str(url).strip()
        } if isinstance(raw_prices, dict) else {}

        with self.data_lock:
            self.queue = Queue()
            self.queued = set()
            self.in_progress = set()
            self.visited = set(strings("visited_urls"))
            self.skipped_urls = set(strings("skipped_urls"))
            self.deferred_urls = set(strings("deferred_urls"))
            self.permanent_failures = set(strings("permanent_failures"))
            self.failed_attempts = failed_attempts
            self.pending_prices = pending_prices
            self.results = results
            self.result_urls = set(strings("result_urls"))
            self.result_models = set(strings("result_models"))
            if not self.result_urls:
                self.result_urls = {
                    str(item.get("url") or "")
                    for item in results
                    if str(item.get("url") or "").strip()
                }
            if not self.result_models:
                self.result_models = {
                    str(item.get("model") or "").strip().casefold()
                    for item in results
                    if not str(item.get("url") or "").strip()
                    and str(item.get("model") or "").strip()
                }
            for url in strings("queued_urls"):
                if url not in self.permanent_failures and url not in self.queued:
                    self.queue.put(url)
                    self.queued.add(url)
        try:
            self.elapsed_before_resume = max(0.0, float(payload.get("elapsed_seconds", 0) or 0))
        except (TypeError, ValueError):
            self.elapsed_before_resume = 0.0
        self.started_at = 0.0
        self.excel_finalized = False
        self.fatal_error = ""
        self.recovery_pause_reason = ""
        return True

    def save_project_checkpoint(self) -> None:
        if self.project is None:
            return
        from services.scraping.checkpoints import save_scrape_checkpoint
        save_scrape_checkpoint("projects", self.project.get("id"), self.checkpoint_payload())

    def delete_project_checkpoint(self) -> None:
        if self.project is None:
            return
        from services.scraping.checkpoints import delete_scrape_checkpoint
        delete_scrape_checkpoint("projects", self.project.get("id"))

    def prepare_resume_queue(self) -> None:
        with self.data_lock:
            retry_urls = sorted(self.deferred_urls)
            for url in retry_urls:
                self.visited.discard(url)
                self.failed_attempts.pop(url, None)
            self.deferred_urls.clear()
        for url in retry_urls:
            self.enqueue(url, force=True)

    def request_recovery_pause(self, message: str, active_urls: Optional[Iterable[str]] = None) -> None:
        if self.recovery_pause_reason:
            return
        urls = [str(url) for url in (active_urls or []) if str(url)]
        self.recovery_pause_reason = message
        self.update_state(
            status="pausing",
            error="",
            last_warning=message,
            currenturl=urls[0] if urls else "",
            active_urls=urls[:8],
            active_tasks=len(urls),
            queue_size=self.queue.qsize() + len(self.deferred_urls),
        )
        self.log(message, "warning")
        self.stop_signal.set()

    def fetch_with_requests(self, url: str) -> Optional[str]:
        last_error = ""
        candidate_urls = [url]
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

                    last_error = "страница похожа на блокировку или пустой JS-шаблон"
                    break
                except requests.RequestException as exc:
                    last_error = str(exc)
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {404, 410}:
                        with self.data_lock:
                            self.permanent_failures.add(url)
                        self.log(f"URL пропущен: страница вернула {exc.response.status_code}: {url}", "warning")
                        return None
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {401, 403}:
                        continue
                    break
            if last_error == "страница похожа на блокировку или пустой JS-шаблон":
                break
            if self.stop_signal.is_set():
                return None
            if attempt < MAX_RETRIES:
                time.sleep(min(attempt, 3))
        if last_error:
            self.log(f"requests не смог загрузить {url}: {last_error}", "warning")
        return None

    def fetch_by_method(self, url: str, method: str) -> Optional[str]:
        target_url = url
        if method == "requests":
            return self.fetch_with_requests(target_url)
        if method == "botasaurus-request":
            return fetch_with_botasaurus_request(target_url)
        if method in BOTASAURUS_HEADLESS_METHODS or method == "playwright":
            return self.browser_session_for_worker().fetch(
                target_url,
                method,
                self.extraction_rules,
                self.product_url_filters,
                self.allow_empty_price,
            )
        if method == "botasaurus-debug-visible":
            return self.browser_session_for_worker().fetch(target_url, method)
        if method in SESSION_BROWSER_METHODS:
            return self.browser_session_for_worker().fetch(
                target_url,
                method,
                self.extraction_rules,
                self.product_url_filters,
                self.allow_empty_price,
            )
        if method == "crawl4ai":
            return self.browser_session_for_worker().fetch(target_url, method)
        if method == "scrapegraphai":
            return self.browser_session_for_worker().fetch(target_url, method)
        if method == "scrapy":
            return fetch_with_scrapy(target_url)
        if method == "crawlee":
            return fetch_with_crawlee(target_url)
        return None

    def fetch_by_method_with_timeout(self, url: str, method: str) -> Optional[str]:
        if is_browser_render_method(method) or is_debug_visible_method(method):
            try:
                return self.fetch_by_method(url, method)
            except Exception as error:
                self.log(f"Метод подключения {method} завершился ошибкой для {url}: {error}", "warning")
                return None

        result_queue: Queue = Queue(maxsize=1)

        def run_method() -> None:
            try:
                result_queue.put(("ok", self.fetch_by_method(url, method)), block=False)
            except Exception as error:
                result_queue.put(("error", error), block=False)

        thread = threading.Thread(target=run_method, daemon=True)
        thread.start()
        try:
            status, value = result_queue.get(timeout=CONNECTION_METHOD_TIMEOUT_SECONDS)
        except Empty:
            self.log(
                f"Метод подключения {method} превысил таймаут {CONNECTION_METHOD_TIMEOUT_SECONDS} сек. для {url}",
                "warning",
            )
            return None
        if status == "error":
            self.log(f"Метод подключения {method} завершился ошибкой для {url}: {value}", "warning")
            return None
        return value if isinstance(value, str) else None

    def fallback_method_sequence(self) -> List[str]:
        """Возвращает fallback-методы из БД без схлопывания разных браузерных движков."""
        methods: List[str] = []
        for method in ordered_db_connection_methods():
            # Видимый debug-браузер не запускаем автоматически, только если выбран явно.
            if is_debug_visible_method(method) and method != self.connection_method:
                continue
            if method not in methods:
                methods.append(method)
        return methods

    def current_connection_method(self) -> str:
        lock = self.connection_method_state["lock"]
        with lock:
            current = normalize_connection_method(self.connection_method_state.get("active_method"))
            self.connection_method_state["active_method"] = current
            self.active_connection_method = current
            return current

    def prepare_connection_method(self, method: str, activate: bool = True) -> str:
        """Stops resources from the previous method before enabling the next one."""
        current = normalize_connection_method(method)
        lock = self.connection_method_state["lock"]
        with lock:
            previous_resource = normalize_connection_method(
                self.connection_method_state.get("resource_method")
            )
            if activate:
                self.connection_method_state["active_method"] = current
                self.active_connection_method = current
            self.connection_method_state["resource_method"] = current
            if current != previous_resource:
                self.connection_method_state["resource_generation"] = (
                    int(self.connection_method_state.get("resource_generation", 0)) + 1
                )

        if current == previous_resource:
            return current

        # The shared session object is also used by news enrichment workers.
        # Restart it in place so every owner sees the replacement session and
        # the old Chromium/Playwright process is gone before the next method.
        self.browser_session.restart(
            prefer_headless_shell=current != "protected-site",
            method=current,
        )

        return current

    def set_active_connection_method(self, method: str) -> None:
        self.prepare_connection_method(method)

    def fetch_with_connection_method(self, url: str, method: str) -> Optional[str]:
        from services.log_service import log_fetch_result
        self.last_progress_at = time.time()
        self.log(f"Пробую метод подключения {method} для {url}", "info")
        started = time.time()
        html = self.fetch_by_method_with_timeout(url, method)
        self.last_progress_at = time.time()
        if html:
            log_fetch_result(method, url, html, time.time() - started)
        if html and not looks_blocked_or_empty(html):
            return html
        self.log(f"Метод подключения {method} не сработал для {url}", "warning")
        return None

    def fetch(self, url: str) -> Optional[str]:
        transition_lock = self.connection_method_state["transition_lock"]
        # Do not start a new URL while another worker is replacing the shared
        # browser process. Existing requests may finish or be cancelled by the
        # session shutdown, but no new work enters the previous method.
        with transition_lock:
            current_method = self.current_connection_method()
            resource_generation = int(self.connection_method_state.get("resource_generation", 0))
        last_method = current_method

        if self.stop_signal.is_set():
            return None

        html = self.fetch_with_connection_method(url, current_method)
        if html:
            return html

        with self.data_lock:
            if url in self.permanent_failures:
                return None

        if not self.auto_connection_fallback:
            self.update_state(
                error=(
                    f"Не удалось загрузить {url}. Последний метод: {last_method}. "
                    "Проверьте способ подключения или включите автопереключение."
                ),
            )
            self.log(f"Не удалось загрузить {url}. Последний метод: {last_method}", "error")
            return None

        with transition_lock:
            # Another worker may have completed the transition while this URL
            # was failing on the old method. Reuse that method instead of
            # starting a second, competing fallback chain.
            latest_method = self.current_connection_method()
            latest_generation = int(self.connection_method_state.get("resource_generation", 0))
            if latest_method != current_method or latest_generation != resource_generation:
                return self.fetch_with_connection_method(url, latest_method)

            for method in self.fallback_method_sequence():
                if self.stop_signal.is_set():
                    return None
                if method == current_method:
                    continue
                last_method = method
                self.prepare_connection_method(method, activate=False)
                html = self.fetch_with_connection_method(url, method)
                if html:
                    # Keep the successful engine for the remaining URLs.
                    # Recreating a browser after every URL causes process/CPU
                    # churn and races the other workers sharing this manager.
                    self.set_active_connection_method(method)
                    self.log(f"Автопереключение подключения: {method} для {url}", "warning")
                    return html
                with self.data_lock:
                    if url in self.permanent_failures:
                        break

            # Every candidate failed. Stop the final candidate process and
            # leave the original method ready for the next retry/URL.
            self.prepare_connection_method(current_method, activate=False)

        self.update_state(
            error=(
                f"Не удалось загрузить {url}. Последний метод: {last_method}. "
                "Проверьте способ подключения или включите автопереключение."
            ),
        )
        self.log(f"Не удалось загрузить {url}. Последний метод: {last_method}", "error")
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
        return product_url_matches_filters(url, self.product_url_filters) and not product_url_matches_any(url, self.product_url_exclusions)

    def is_filter_marked_product(self, url: str) -> bool:
        return bool(self.product_url_filters) and self.is_product_allowed(url)

    def is_product_url(self, url: str) -> bool:
        return is_product_url_for_filters(url, self.product_url_filters)

    def is_start_url_path(self, url: str) -> bool:
        parsed = urlparse(url)
        normalized_path = (parsed.path or "/").rstrip("/") or "/"
        for start_url in self.start_urls:
            start_parsed = urlparse(start_url)
            if not same_site(url, start_parsed.netloc or self.root_netloc):
                continue
            start_path = (start_parsed.path or "/").rstrip("/") or "/"
            if normalized_path == start_path:
                return True
        return False

    def is_current_product_page(self, url: str) -> bool:
        return self.is_product_url(url) and self.is_product_allowed(url) and not self.is_start_url_path(url)

    def remember_listing_price(self, product_url: str, price: str) -> None:
        product_url = canonicalize_product_url_by_filters(product_url, self.product_url_filters)
        with self.data_lock:
            if product_url and price:
                self.pending_prices[product_url] = price

    def get_listing_price(self, product_url: str) -> str:
        product_url = canonicalize_product_url_by_filters(product_url, self.product_url_filters)
        with self.data_lock:
            return self.pending_prices.get(product_url, "")

    def enqueue(self, url: Optional[str], force: bool = False) -> None:
        url = canonicalize_product_url_by_filters(url or "", self.product_url_filters)
        if not url or url in self.visited or url in self.queued or url in self.in_progress:
            return
        is_product = self.is_product_url(url)
        if is_product and not self.is_product_allowed(url):
            return
        with self.data_lock:
            if url in self.result_urls:
                return
        if not force:
            if is_product:
                if not same_site(url, self.root_netloc) or has_static_extension(url):
                    return
            elif not should_follow_project_url(url, self.start_urls, self.root_netloc):
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

    def extract_links(self, html: str, current_url: str, include_product_urls: bool = True) -> None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            normalized = normalize_url(link.get("href", ""), current_url)
            if not include_product_urls and self.is_product_url(normalized):
                continue
            self.enqueue(normalized)

    def add_products(self, products: Iterable[Dict[str, str]]) -> int:
        added = 0
        with self.data_lock:
            for product in products:
                product_url = canonicalize_product_url_by_filters(product.get("url", ""), self.product_url_filters)
                model = str(product.get("model", "") or "").strip()
                model_key = model.casefold()
                price = product.get("price", "")
                if product_url and not self.is_product_allowed(product_url):
                    continue
                if (
                    not model
                    or (not price and not self.allow_empty_price)
                    or (product_url and product_url in self.result_urls)
                    or model_key in self.result_models
                ):
                    continue
                product["url"] = product_url
                if product_url:
                    self.result_urls.add(product_url)
                else:
                    self.result_models.add(model_key)
                self.results.append(product)
                added += 1
        return added

    def snapshot_counts(self) -> Dict[str, int]:
        with self.data_lock:
            return {
                "visited": len(self.visited),
                "results": len(self.results),
                "skipped": len(self.skipped_urls),
                "queued": self.queue.qsize(),
                "active": len(self.in_progress),
                "failed": len(self.failed_attempts),
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
        self.update_state(
            percent=percent,
            currenturl=current_url,
            totalprocessed=processed,
            processed_products=counts["results"],
            found_products=counts["results"],
            in_memory_products=counts["results"],
            queue_size=remaining,
            active_tasks=counts["active"],
            active_urls=sorted(self.in_progress)[:8],
            failed_pages=counts["failed"],
            stall_seconds=max(0, int(time.time() - self.last_progress_at)),
            skipped=counts["skipped"],
            thread_count=self.thread_count,
            elapsed_seconds=int(elapsed),
        )

    def progress_signature(self, pending_urls: Iterable[str]) -> tuple:
        counts = self.snapshot_counts()
        return (
            counts["visited"],
            counts["results"],
            counts["skipped"],
            self.queue.qsize(),
            tuple(sorted(pending_urls)),
        )

    def note_progress_activity(self, pending_urls: Iterable[str]) -> None:
        signature = self.progress_signature(pending_urls)
        if signature != self.last_progress_signature:
            self.last_progress_signature = signature
            self.last_progress_at = time.time()

    def mark_stalled(self, pending_urls: Iterable[str]) -> None:
        active_urls = list(pending_urls)
        counts = self.snapshot_counts()
        message = (
            f"Сбор не двигается {NEWS_SCAN_STALL_TIMEOUT} секунд. "
            f"Активных задач: {len(active_urls)}; очередь: {self.queue.qsize()}; "
            f"товаров в памяти: {counts['results']}. "
            f"Активные URL: {', '.join(active_urls[:5])}"
        )
        self.update_state(
            in_memory_products=counts["results"],
            stall_seconds=NEWS_SCAN_STALL_TIMEOUT,
        )
        self.request_recovery_pause(message, active_urls)

    def elapsed_seconds(self) -> float:
        if self.started_at:
            return self.elapsed_before_resume + max(0.0, time.time() - self.started_at)
        return self.elapsed_before_resume

    def process_page(self, url: str, html: str) -> None:
        current_is_product = self.is_current_product_page(url)
        listing_products: List[Dict[str, str]] = []
        listing_price = self.get_listing_price(url)

        if current_is_product:
            product = extract_product_data(
                url,
                html,
                listing_price,
                self.extraction_rules,
                assume_product=True,
                allow_empty_price=self.allow_empty_price,
            )
            if product:
                self.add_products([product])
                return

            current_is_product = False

        listing_products = extract_listing_products(url, html, self.extraction_rules, self.product_url_filters)

        for product in listing_products:
            product_url = canonicalize_product_url_by_filters(product.get("url", ""), self.product_url_filters)
            if product_url and not self.is_product_allowed(product_url):
                continue
            product["url"] = product_url
            if product_url:
                self.remember_listing_price(product_url, product.get("price", ""))
                self.enqueue(product_url, force=True)
        url_less_listing_products = [product for product in listing_products if not product.get("url")]
        collected_only_url_less_listing_products = bool(listing_products) and len(url_less_listing_products) == len(listing_products)
        if url_less_listing_products:
            self.add_products(url_less_listing_products)
        if not self.product_url_filters and not has_explicit_model_rules(self.extraction_rules):
            self.add_products(listing_products)

        should_extract_current_product = (
            not self.is_start_url_path(url)
            and (not listing_products or bool(self.get_listing_price(url)))
        )
        product = None if not should_extract_current_product else extract_product_data(
            url,
            html,
            self.get_listing_price(url),
            self.extraction_rules,
            assume_product=self.is_product_url(url),
            allow_empty_price=self.allow_empty_price,
        )
        if product:
            self.add_products([product])

        if not current_is_product:
            self.extract_links(html, url, include_product_urls=not collected_only_url_less_listing_products)

    def finish_with_excel(self, partial: bool = False) -> None:
        from services.projects import create_export_file, delete_project_csv_for_project, save_project
        with self.data_lock:
            if self.excel_finalized:
                return
            self.excel_finalized = True

        rows = self.snapshot_results()
        counts = self.snapshot_counts()
        filename = create_export_file(rows, self.project)
        if self.project is not None:
            delete_project_csv_for_project(self.project, keep_filename=filename.name)
        final_error = ""
        if partial:
            final_error = "" if self.recovery_pause_reason else "Сбор приостановлен. CSV сформирован по уже найденным товарам."
        elif not self.results:
            final_error = (
                "Сбор завершен, но товары не найдены. Проверьте стартовый URL и исключения; "
                "для защищенных страниц убедитесь, что Botasaurus установился через run.ps1."
            )

        self.update_state(
            status="partial" if partial else "completed",
            percent=100 if not partial else int((self.project or {}).get("state", {}).get("percent", 0) or 0),
            currenturl="",
            active_urls=[],
            active_tasks=0,
            queue_size=self.queue.qsize() + len(self.deferred_urls),
            totalprocessed=counts["visited"],
            processed_products=counts["results"],
            found_products=counts["results"],
            skipped=counts["skipped"],
            download_ready=True,
            download_url="/download",
            filename=filename.name,
            error=final_error,
            last_warning=self.recovery_pause_reason,
            thread_count=self.thread_count,
            elapsed_seconds=int(self.elapsed_seconds()),
            finished_at=now_iso() if not partial else "",
            paused_with_result=partial,
        )
        self.log(f"CSV сформирован: {filename.name}. Товаров: {counts['results']}", "success")
        if self.project is not None and self.run_id == int(self.project.get("run_id", self.run_id)):
            save_project(self.project)

    def run(self, resume: bool = False) -> None:
        if not self.started_at:
            self.started_at = time.time()
        self.fatal_error = ""
        self.recovery_pause_reason = ""
        if resume:
            self.prepare_resume_queue()
        self.update_state(
            status="running",
            thread_count=self.thread_count,
            started_at=(self.project or {}).get("state", {}).get("started_at") or now_iso(),
            paused_with_result=False,
        )
        self.log("Сбор продолжен" if resume else "Сбор запущен", "info")
        if not resume:
            for start_url in self.start_urls:
                self.enqueue(start_url)

        executor = ThreadPoolExecutor(max_workers=self.thread_count)
        pending = {}
        pending_urls_to_requeue = []
        self.note_progress_activity([])

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
                        if url in self.result_urls and self.is_product_url(url):
                            continue
                    self.in_progress.add(url)
                    self.update_state(
                        currenturl=url,
                        active_urls=sorted(self.in_progress)[:8],
                        active_tasks=len(self.in_progress),
                        queue_size=self.queue.qsize(),
                    )
                    pending[executor.submit(self.fetch, url)] = url
                    self.note_progress_activity(pending.values())
                    time.sleep(REQUEST_DELAY_SECONDS)

                if not pending:
                    if self.queue.empty():
                        if self.deferred_urls:
                            self.request_recovery_pause(
                                f"Не удалось загрузить URL после повторных попыток: {len(self.deferred_urls)}. "
                                "Сбор приостановлен; нажмите «Продолжить», чтобы повторить эти ссылки.",
                                sorted(self.deferred_urls)[:8],
                            )
                        break
                    continue

                done, _pending = wait(pending.keys(), timeout=0.5, return_when=FIRST_COMPLETED)
                if not done:
                    self.refresh_progress()
                    self.note_progress_activity(pending.values())
                    if pending and time.time() - self.last_progress_at >= NEWS_SCAN_STALL_TIMEOUT:
                        self.mark_stalled(pending.values())
                    continue

                for future in done:
                    url = pending.pop(future)
                    self.note_progress_activity(pending.values())
                    with self.data_lock:
                        self.in_progress.discard(url)
                        self.visited.add(url)
                    html = None
                    try:
                        html = future.result()
                    except Exception as exc:  # noqa: BLE001 - ошибку показываем в интерфейсе.
                        self.update_state(error=f"Ошибка обработки {url}: {exc}")
                        self.log(f"Ошибка обработки {url}: {exc}", "error")

                    if html and not self.stop_signal.is_set():
                        with self.data_lock:
                            self.failed_attempts.pop(url, None)
                            self.deferred_urls.discard(url)
                        self.process_page(url, html)
                    elif not self.stop_signal.is_set():
                        with self.data_lock:
                            permanent_failure = url in self.permanent_failures
                        if permanent_failure:
                            self.log(f"URL пропущен без повторов: {url}", "warning")
                            self.refresh_progress(url)
                            continue
                        retry_count = self.failed_attempts.get(url, 0) + 1
                        self.failed_attempts[url] = retry_count
                        if retry_count <= 2:
                            with self.data_lock:
                                self.visited.discard(url)
                            self.enqueue(url, force=True)
                            self.log(f"Повторная попытка загрузки {retry_count}/2: {url}", "warning")
                        else:
                            with self.data_lock:
                                self.deferred_urls.add(url)
                            self.log(f"URL отложен до продолжения после повторных попыток загрузки: {url}", "warning")

                    self.refresh_progress(url)
        finally:
            if self.stop_signal.is_set():
                pending_urls_to_requeue = list(pending.values())
                self.requeue_pending(pending_urls_to_requeue)
            executor.shutdown(wait=False, cancel_futures=True)
            self.close_browser_sessions()

        if self.stop_signal.is_set():
            self.elapsed_before_resume = self.elapsed_seconds()
            self.started_at = 0.0
            if self.fatal_error:
                self.delete_project_checkpoint()
                self.update_state(
                    status="error",
                    currenturl="",
                    active_urls=[],
                    active_tasks=0,
                    queue_size=self.queue.qsize(),
                    elapsed_seconds=int(self.elapsed_before_resume),
                    error=self.fatal_error,
                )
                return
            if self.recovery_pause_reason:
                self.save_project_checkpoint()
                self.finish_with_excel(partial=True)
                return
            stop_mode = str((self.project or {}).get("stop_mode") or "")
            if self.finish_signal.is_set():
                self.save_project_checkpoint()
                self.finish_with_excel(partial=True)
            elif stop_mode == "pause":
                self.save_project_checkpoint()
                self.update_state(
                    status="paused",
                    currenturl="",
                    elapsed_seconds=int(self.elapsed_before_resume),
                    error="Сбор на паузе",
                )
                if (self.project or {}).get("state", {}).get("status") == "paused":
                    self.log("Сбор поставлен на паузу", "warning")
                if self.project is not None:
                    from services.projects import save_project
                    save_project(self.project)
            else:
                self.delete_project_checkpoint()
                self.update_state(
                    status="idle",
                    currenturl="",
                    active_urls=[],
                    active_tasks=0,
                    queue_size=0,
                    elapsed_seconds=int(self.elapsed_before_resume),
                    error="",
                    paused_with_result=False,
                )
                if stop_mode == "stop":
                    self.log("Сбор остановлен", "warning")
            return

        self.elapsed_before_resume = self.elapsed_seconds()
        self.started_at = 0.0
        self.delete_project_checkpoint()
        self.finish_with_excel()
