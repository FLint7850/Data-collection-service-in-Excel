"""URL normalization, extraction rules and HTTP/browser scraping engines."""

import base64
from importlib.util import find_spec
import os
import signal
import subprocess
import sys
import threading
import time
import uuid
from config import BASE_DIR, BLOCKED_BROWSER_RESOURCE_TYPES, BLOCKED_BROWSER_URL_PARTS, REQUEST_TIMEOUT, botasaurus_browser_executable, env_str
from pathlib import Path
from queue import Empty, Queue
from runtime.state import STANDALONE_BROWSER_SEMAPHORE
from typing import Dict, Iterable, List, Optional, Set

from services.scraping.extraction import extract_listing_products, extract_product_data
from services.scraping.http import is_product_url_for_filters

from services.scraping.http import looks_blocked_or_empty

def fetch_with_botasaurus_browser(url: str, navigation: str = "direct") -> Optional[str]:
    """Fallback через Botasaurus Browser для страниц, которым нужен настоящий рендеринг."""
    from services.log_service import log_fetch_exception, log_fetch_result
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError:
        return None

    chrome_executable_path = botasaurus_browser_executable(prefer_headless_shell=True)

    @browser(
        headless=True,
        chrome_executable_path=chrome_executable_path,
        add_arguments=[
            "--headless=new",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-sync",
            "--blink-settings=imagesEnabled=false",
        ],
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
        time.sleep(2)
        for _ in range(4):
            try:
                driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            time.sleep(0.8)
        return driver.page_html

    try:
        started = time.time()
        with STANDALONE_BROWSER_SEMAPHORE:
            result = _render_html(url)
    except Exception as error:
        log_fetch_exception(f"botasaurus-browser:{navigation}", url, error)
        return None

    if isinstance(result, list):
        result = result[0] if result else None
    if result:
        log_fetch_result(f"botasaurus-browser:{navigation}", url, result, time.time() - started)
    return result if isinstance(result, str) and result.strip() else None


class BotasaurusBrowserSession:
    """One hidden full Chromium session owned by one project/news scan.

    thread_count still controls parallel open pages, but every page now uses a
    selector-driven fast path and closes as soon as the needed DOM appears.
    """

    def __init__(
        self,
        stop_signal: Optional[threading.Event] = None,
        max_pages: int = 1,
        profile_dir: Optional[Path] = None,
        prefer_headless_shell: bool = True,
    ) -> None:
        from services.projects import parse_thread_count
        self.stop_signal = stop_signal
        self.max_pages = max(1, parse_thread_count(max_pages))
        self.profile_dir = profile_dir
        self.prefer_headless_shell = bool(prefer_headless_shell)
        self.executable_path = env_str("PLAYWRIGHT_BROWSER_EXECUTABLE") or botasaurus_browser_executable(
            prefer_headless_shell=self.prefer_headless_shell,
        )
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._semaphore = None
        self._closed = False
        self._start_error: Optional[BaseException] = None
        self._process_token = f"parser-browser-session-{uuid.uuid4().hex}"
        self._shutdown_complete = threading.Event()

    def _ensure_started(self) -> bool:
        with self._state_lock:
            if self._closed:
                return False
            if self._thread is None or not self._thread.is_alive():
                self._start_error = None
                self._ready.clear()
                self._thread = threading.Thread(target=self._run_loop, name="project-browser-session", daemon=True)
                self._thread.start()
        if not self._ready.wait(timeout=30):
            return False
        return self._start_error is None and self._loop is not None

    def _run_loop(self) -> None:
        from services.log_service import fetch_debug_log
        import asyncio

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_browser())
            self._ready.set()
            with self._state_lock:
                closed = self._closed
            if not closed:
                self._loop.run_forever()
        except BaseException as error:  # noqa: BLE001
            self._start_error = error
            fetch_debug_log(f"browser-session start failed: {type(error).__name__}: {error}", "warning")
            self._ready.set()
        finally:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._shutdown_async())
            except BaseException as error:  # noqa: BLE001
                fetch_debug_log(f"browser-session shutdown failed: {type(error).__name__}: {error}", "warning")
            finally:
                if not self._loop.is_closed():
                    self._loop.close()
                self._loop = None
                self._shutdown_complete.set()

    async def _start_browser(self) -> None:
        import asyncio
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        launch_options = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled",
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-sync",
                "--no-sandbox",
                "--blink-settings=imagesEnabled=false",
                "--disable-renderer-backgrounding",
                "--disable-background-timer-throttling",
                f"--{self._process_token}",
            ],
        }
        if self.executable_path:
            launch_options["executable_path"] = self.executable_path
        context_options = dict(
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
            ),
            locale="ru-RU",
            viewport={"width": 1366, "height": 900},
            extra_http_headers={
                "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
            },
        )
        if self.profile_dir is not None:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            self._context = await self._playwright.chromium.launch_persistent_context(
                str(self.profile_dir),
                **launch_options,
                **context_options,
            )
            self._browser = self._context.browser
        else:
            self._browser = await self._playwright.chromium.launch(**launch_options)
            self._context = await self._browser.new_context(**context_options)
        try:
            await self._context.add_init_script(
                """
                Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
                Object.defineProperty(navigator, 'languages', { get: () => ['ru-RU', 'ru', 'en-US', 'en'] });
                Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
                window.chrome = window.chrome || { runtime: {} };
                """
            )
        except Exception:
            pass
        self._semaphore = asyncio.Semaphore(self.max_pages)

    async def _close_browser(self) -> None:
        import asyncio
        from services.log_service import fetch_debug_log

        async def close_component(name: str, awaitable) -> None:
            try:
                await asyncio.wait_for(awaitable, timeout=8)
            except BaseException as error:  # noqa: BLE001
                fetch_debug_log(
                    f"browser-session {name} close failed: {type(error).__name__}: {error}",
                    "warning",
                )

        if self._context is not None:
            await close_component("context", self._context.close())
        if self._browser is not None:
            await close_component("browser", self._browser.close())
        if self._playwright is not None:
            await close_component("playwright", self._playwright.stop())
        self._context = None
        self._browser = None
        self._playwright = None
        self._semaphore = None

    async def _shutdown_async(self) -> None:
        import asyncio

        # Сначала корректно закрываем страницы, контекст, браузер и Playwright.
        # Если отменить все задачи раньше, отменяется и внутренний transport
        # Playwright, после чего context.close() уже не способен завершить Chromium.
        await self._close_browser()
        current_task = asyncio.current_task()
        tasks = [
            task
            for task in asyncio.all_tasks()
            if task is not current_task and not task.done()
        ]
        for task in tasks:
            task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _force_terminate_owned_processes(self) -> None:
        """Добивает только Chromium-процессы этой сессии после graceful shutdown."""
        if os.name != "posix" or not Path("/proc").is_dir():
            return
        token = f"--{self._process_token}".encode()
        parent_by_pid: Dict[int, int] = {}
        roots: Set[int] = set()
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                cmdline = (entry / "cmdline").read_bytes()
                stat = (entry / "stat").read_text(encoding="utf-8")
                parent_by_pid[pid] = int(stat.rsplit(")", 1)[1].split()[1])
                if token in cmdline:
                    roots.add(pid)
            except (OSError, ValueError, IndexError):
                continue
        if not roots:
            return

        owned = set(roots)
        current_pid = os.getpid()
        for root_pid in roots:
            parent_pid = parent_by_pid.get(root_pid, 0)
            while parent_pid not in {0, 1, current_pid} and parent_pid not in owned:
                owned.add(parent_pid)
                parent_pid = parent_by_pid.get(parent_pid, 0)
        changed = True
        while changed:
            changed = False
            for pid, parent_pid in parent_by_pid.items():
                if parent_pid in owned and pid not in owned:
                    owned.add(pid)
                    changed = True

        owned.discard(current_pid)
        if not owned:
            return
        from services.log_service import fetch_debug_log
        fetch_debug_log(f"browser-session force cleanup: processes={len(owned)}", "warning")
        for sig in (signal.SIGTERM, signal.SIGKILL):
            for pid in sorted(owned, reverse=True):
                try:
                    os.kill(pid, sig)
                except (ProcessLookupError, PermissionError):
                    continue
            if sig == signal.SIGTERM:
                time.sleep(0.25)

    @staticmethod
    def _profiles_for_method(method: str) -> List[Dict[str, object]]:
        method = str(method or "")
        if method == "protected-site":
            return [
                {"name": "protected_direct", "block_stylesheet": False, "selector_timeout": 9000, "referer": ""},
                {"name": "protected_google_referrer", "block_stylesheet": False, "selector_timeout": 9000, "referer": "https://www.google.com/"},
            ]
        if method == "botasaurus-browser-direct":
            referer = ""
        elif method == "botasaurus-browser":
            referer = "https://www.google.com/"
        else:
            referer = ""
        return [
            {"name": "fast_full_browser", "block_stylesheet": True, "selector_timeout": 2500, "referer": referer},
            {"name": "compatible_full_browser", "block_stylesheet": False, "selector_timeout": 5500, "referer": referer},
        ]

    @staticmethod
    def _selector_list(rules: Optional[Dict[str, str]], allow_empty_price: bool = False) -> List[str]:
        rules = rules or {}
        selectors: List[str] = []
        for key in ("product_card_selector", "product_url_selector", "model_selector"):
            value = str(rules.get(key) or "").strip()
            if value and value not in selectors:
                selectors.append(value)
        price_selector = str(rules.get("price_selector") or "").strip()
        if price_selector and (not allow_empty_price or not selectors):
            selectors.append(price_selector)
        return selectors

    @staticmethod
    async def _count_locator(page, selector: str) -> int:
        try:
            return await page.locator(selector).count()
        except Exception:
            return 0

    async def _count_ready_nodes(self, page, rules: Optional[Dict[str, str]], allow_empty_price: bool = False) -> int:
        total = 0
        for selector in self._selector_list(rules, allow_empty_price):
            total += await self._count_locator(page, selector)
        return total

    async def _wait_for_ready_selectors(self, page, rules: Optional[Dict[str, str]], allow_empty_price: bool, timeout_ms: int) -> bool:
        for selector in self._selector_list(rules, allow_empty_price):
            try:
                await page.wait_for_selector(selector, state="attached", timeout=timeout_ms)
                return True
            except Exception:
                continue
        return False

    def _html_usable_for_parsing(
        self,
        url: str,
        html: str,
        rules: Optional[Dict[str, str]],
        product_url_filters: Optional[Iterable[str]],
        allow_empty_price: bool,
    ) -> bool:
        if not html or looks_blocked_or_empty(html):
            return False
        try:
            if extract_listing_products(url, html, rules or {}, product_url_filters or []):
                return True
        except Exception:
            pass
        try:
            product = extract_product_data(
                url,
                html,
                "",
                rules or {},
                assume_product=is_product_url_for_filters(url, product_url_filters or []),
                allow_empty_price=allow_empty_price,
            )
            if product:
                return True
        except Exception:
            pass
        return False

    async def _fetch_once(
        self,
        url: str,
        method: str,
        profile: Dict[str, object],
        rules: Optional[Dict[str, str]],
        product_url_filters: Optional[Iterable[str]],
        allow_empty_price: bool,
    ) -> Optional[str]:
        from services.log_service import log_fetch_exception, log_fetch_result
        if self._context is None:
            return None
        page = await self._context.new_page()
        profile_name = str(profile.get("name") or "browser")
        block_stylesheet = bool(profile.get("block_stylesheet"))
        selector_timeout = int(profile.get("selector_timeout") or 2500)
        started = time.time()
        scroll_count = 0
        try:
            referer = str(profile.get("referer") or "")
            if referer:
                await page.set_extra_http_headers({"Referer": referer})

            async def route_handler(route, request):
                if self._should_block_resource(request, block_stylesheet=block_stylesheet):
                    await route.abort()
                else:
                    await route.continue_()

            await page.route("**/*", route_handler)
            timeout_ms = REQUEST_TIMEOUT * 1000
            await page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
            selector_found = await self._wait_for_ready_selectors(page, rules, allow_empty_price, selector_timeout)

            last_count = await self._count_ready_nodes(page, rules, allow_empty_price)
            stable_rounds = 0
            # Скроллим только до стабилизации DOM, а не фиксированное количество раз.
            for _ in range(5):
                if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                    return None
                await page.mouse.wheel(0, 1400)
                scroll_count += 1
                await page.wait_for_timeout(350)
                current_count = await self._count_ready_nodes(page, rules, allow_empty_price)
                if current_count <= last_count:
                    stable_rounds += 1
                else:
                    stable_rounds = 0
                    last_count = current_count
                if selector_found and stable_rounds >= 1:
                    break
                if stable_rounds >= 2:
                    break

            try:
                await page.evaluate("window.stop()")
            except Exception:
                pass
            html = await page.content()
            usable = self._html_usable_for_parsing(url, html, rules, product_url_filters, allow_empty_price)
            log_fetch_result(
                f"{method}:{profile_name}",
                url,
                html,
                time.time() - started,
                extra=f"selector_found={selector_found}; scroll_count={scroll_count}; usable={usable}",
            )
            return html if isinstance(html, str) and html.strip() else None
        except Exception as error:
            log_fetch_exception(f"{method}:{profile_name}", url, error)
            return None
        finally:
            try:
                await page.close()
            except Exception:
                pass

    async def _fetch_async(
        self,
        url: str,
        method: str,
        rules: Optional[Dict[str, str]] = None,
        product_url_filters: Optional[Iterable[str]] = None,
        allow_empty_price: bool = False,
    ) -> Optional[str]:
        if self._context is None or self._semaphore is None:
            return None

        async with self._semaphore:
            if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                return None
            best_html = ""
            for profile in self._profiles_for_method(method):
                html = await self._fetch_once(url, method, profile, rules, product_url_filters, allow_empty_price)
                if html and not best_html:
                    best_html = html
                if html and self._html_usable_for_parsing(url, html, rules, product_url_filters, allow_empty_price):
                    return html
            return best_html or None

    @staticmethod
    def _should_block_resource(request, block_stylesheet: bool = True) -> bool:
        resource_type = getattr(request, "resource_type", "")
        if resource_type in {"image", "media", "font"}:
            return True
        if block_stylesheet and resource_type == "stylesheet":
            return True
        request_url = str(getattr(request, "url", "") or "").lower()
        return any(part in request_url for part in BLOCKED_BROWSER_URL_PARTS)

    def fetch(
        self,
        url: str,
        method: str,
        rules: Optional[Dict[str, str]] = None,
        product_url_filters: Optional[Iterable[str]] = None,
        allow_empty_price: bool = False,
    ) -> Optional[str]:
        from services.log_service import log_fetch_exception
        if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
            return None
        with self._state_lock:
            if self._closed:
                return None
        if not self._ensure_started():
            return None
        future = None
        try:
            import asyncio

            future = asyncio.run_coroutine_threadsafe(
                self._fetch_async(url, method, rules, product_url_filters, allow_empty_price),
                self._loop,
            )
            result = future.result(timeout=REQUEST_TIMEOUT + 35)
        except Exception as error:
            if future is not None:
                future.cancel()
                try:
                    future.result(timeout=2)
                except Exception:
                    pass
            log_fetch_exception(method, url, error)
            return None
        return result if isinstance(result, str) and result.strip() else None

    def close(self) -> None:
        import asyncio
        from services.log_service import fetch_debug_log

        with self._lifecycle_lock:
            thread = None
            loop = None
            with self._state_lock:
                self._closed = True
                thread = self._thread
                loop = self._loop
            if loop is not None and loop.is_running():
                try:
                    shutdown = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
                    shutdown.result(timeout=20)
                except BaseException as error:  # noqa: BLE001
                    fetch_debug_log(f"browser-session close failed: {type(error).__name__}: {error}", "warning")
                try:
                    loop.call_soon_threadsafe(loop.stop)
                except BaseException as error:  # noqa: BLE001
                    fetch_debug_log(f"browser-session loop stop failed: {type(error).__name__}: {error}", "warning")
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=20)
                if thread.is_alive():
                    fetch_debug_log("browser-session thread did not stop in 20 seconds", "warning")
            self._force_terminate_owned_processes()
            if thread is not None and thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=5)

    def restart(self, prefer_headless_shell: Optional[bool] = None) -> bool:
        """Fully stops the owned browser process and makes this shared object reusable."""
        from services.log_service import fetch_debug_log

        with self._lifecycle_lock:
            self.close()
            thread = self._thread
            if thread is not None and thread.is_alive():
                fetch_debug_log("browser-session restart aborted: previous thread is still alive", "warning")
                return False

            if prefer_headless_shell is not None:
                self.prefer_headless_shell = bool(prefer_headless_shell)
            self.executable_path = env_str("PLAYWRIGHT_BROWSER_EXECUTABLE") or botasaurus_browser_executable(
                prefer_headless_shell=self.prefer_headless_shell,
            )
            with self._state_lock:
                self._ready = threading.Event()
                self._thread = None
                self._loop = None
                self._playwright = None
                self._browser = None
                self._context = None
                self._semaphore = None
                self._closed = False
                self._start_error = None
                self._process_token = f"parser-browser-session-{uuid.uuid4().hex}"
                self._shutdown_complete = threading.Event()
            return True


class BotasaurusDebugVisibleSession:
    """One visible Botasaurus browser with a persistent project profile."""

    def __init__(self, stop_signal: Optional[threading.Event] = None, profile: str = "protected_sites_debug_visible") -> None:
        self.stop_signal = stop_signal
        self.profile = profile or "protected_sites_debug_visible"
        self._lock = threading.Lock()
        self._closed = False
        self._renderer = self._create_renderer()

    def _create_renderer(self):
        try:
            from botasaurus.browser import Driver
            from botasaurus.browser import browser
        except ImportError:
            return None

        chrome_executable_path = botasaurus_browser_executable(prefer_headless_shell=False)

        @browser(
            headless=False,
            chrome_executable_path=chrome_executable_path,
            profile=self.profile,
            window_size=[1280, 720],
            add_arguments=["--window-position=40,40"],
            block_images_and_css=False,
            wait_for_complete_page_load=True,
            reuse_driver=True,
            output=None,
            close_on_crash=True,
            create_error_logs=False,
            max_retry=1,
        )
        def _render_html(driver: Driver, target_url: str):
            driver.get(target_url)
            time.sleep(8)
            for _ in range(3):
                try:
                    driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    break
                time.sleep(0.8)
            return driver.page_html

        return _render_html

    def fetch(self, url: str, method: str) -> Optional[str]:
        if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
            return None
        if self._renderer is None:
            return None
        with self._lock:
            if self._closed:
                return None
            try:
                result = self._renderer(url)
            except Exception:
                return None
        if isinstance(result, list):
            result = result[0] if result else None
        return result if isinstance(result, str) and result.strip() else None

    def close(self) -> None:
        with self._lock:
            self._closed = True
            renderer = self._renderer
            if renderer is not None and hasattr(renderer, "close"):
                try:
                    renderer.close()
                except Exception:
                    pass


def fetch_with_crawl4ai(url: str) -> Optional[str]:
    try:
        import asyncio
        from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
    except ImportError:
        return None

    async def _fetch() -> Optional[str]:
        browser_config = BrowserConfig(
            browser_type="chromium",
            headless=True,
            channel="chromium",
            text_mode=True,
            light_mode=True,
            avoid_ads=True,
            avoid_css=True,
            viewport_width=1366,
            viewport_height=900,
            user_agent=(
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
            ),
            extra_args=[
                "--disable-gpu",
                "--disable-dev-shm-usage",
                "--disable-background-networking",
                "--disable-sync",
                "--blink-settings=imagesEnabled=false",
            ],
            verbose=False,
        )
        run_config = CrawlerRunConfig(
            wait_until="domcontentloaded",
            page_timeout=REQUEST_TIMEOUT * 1000,
            wait_for_images=False,
            delay_before_return_html=0.2,
            exclude_all_images=True,
            excluded_tags=["img", "picture", "source", "video", "audio", "svg", "style"],
            exclude_domains=list(BLOCKED_BROWSER_URL_PARTS),
            log_console=False,
            capture_network_requests=False,
            max_retries=0,
            verbose=False,
        )
        async with AsyncWebCrawler(config=browser_config) as crawler:
            result = await asyncio.wait_for(
                crawler.arun(url=url, config=run_config),
                timeout=REQUEST_TIMEOUT + 10,
            )
            html = getattr(result, "html", "") or getattr(result, "cleaned_html", "")
            return html if isinstance(html, str) else None

    try:
        with STANDALONE_BROWSER_SEMAPHORE:
            return asyncio.run(_fetch())
    except Exception:
        return None


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
import os
import shutil
import sys
import tempfile
import uuid
from datetime import timedelta

storage_dir = os.path.join(tempfile.gettempdir(), "parser-crawlee", uuid.uuid4().hex)
os.environ["CRAWLEE_STORAGE_DIR"] = storage_dir

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


try:
    asyncio.run(main())
finally:
    shutil.rmtree(storage_dir, ignore_errors=True)
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

try:
    import langchain_community.chat_models as community_chat_models
    from langchain_ollama import ChatOllama

    if not hasattr(community_chat_models, "ChatOllama"):
        community_chat_models.ChatOllama = ChatOllama
except Exception:
    pass

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
state = node.execute({"url": url}) or {}
documents = state.get("doc") or state.get("document") or []
html = ""
if isinstance(documents, list) and documents:
    html = getattr(documents[0], "page_content", "") or str(documents[0] or "")
elif isinstance(documents, str):
    html = documents
print(marker + base64.b64encode(str(html).encode("utf-8", "replace")).decode("ascii"))
"""


class PlaywrightHeadlessRenderer:
    """Small pool of isolated Chromium workers for fallback rendering."""

    def __init__(self) -> None:
        self.jobs: Queue = Queue()
        self.threads: List[threading.Thread] = []
        self.lock = threading.Lock()

    def ensure_started(self) -> None:
        with self.lock:
            self.threads = [thread for thread in self.threads if thread.is_alive()]
            while len(self.threads) < 1:
                worker_number = len(self.threads) + 1
                thread = threading.Thread(
                    target=self._worker,
                    name=f"playwright-headless-renderer-{worker_number}",
                    daemon=True,
                )
                self.threads.append(thread)
                thread.start()

    def fetch(self, url: str, timeout_seconds: int) -> Optional[str]:
        self.ensure_started()
        result_queue: Queue = Queue(maxsize=1)
        self.jobs.put((url, timeout_seconds, result_queue))
        try:
            status, value = result_queue.get(timeout=timeout_seconds + 35)
        except Empty as error:
            raise RuntimeError("Playwright: внутренний headless browser не ответил вовремя") from error
        if status == "error":
            raise RuntimeError(f"Playwright: {value}")
        return value if isinstance(value, str) and value.strip() else None

    def _worker(self) -> None:
        from playwright.sync_api import sync_playwright

        def should_block_resource(request) -> bool:
            resource_type = getattr(request, "resource_type", "")
            if resource_type in BLOCKED_BROWSER_RESOURCE_TYPES:
                return True
            request_url = str(getattr(request, "url", "") or "").lower()
            return any(part in request_url for part in BLOCKED_BROWSER_URL_PARTS)

        executable_path = botasaurus_browser_executable(prefer_headless_shell=True)
        with sync_playwright() as playwright:
            launch_options = {
                "headless": True,
                "args": [
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--no-sandbox",
                    "--blink-settings=imagesEnabled=false",
                ],
            }
            if executable_path:
                launch_options["executable_path"] = executable_path
            browser = playwright.chromium.launch(**launch_options)
            context = browser.new_context(
                user_agent=(
                    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"
                ),
                locale="ru-RU",
                viewport={"width": 1366, "height": 900},
            )
            try:
                while True:
                    url, timeout_seconds, result_queue = self.jobs.get()
                    page = None
                    try:
                        page = context.new_page()
                        page.route(
                            "**/*",
                            lambda route, request: route.abort()
                            if should_block_resource(request)
                            else route.continue_(),
                        )
                        timeout_ms = int(float(timeout_seconds)) * 1000
                        page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
                        try:
                            page.wait_for_load_state("networkidle", timeout=min(timeout_ms, 10000))
                        except Exception:
                            pass
                        for _ in range(3):
                            page.mouse.wheel(0, 1600)
                            page.wait_for_timeout(350)
                        html = page.content()
                        result_queue.put(("ok", html), block=False)
                    except Exception as error:
                        result_queue.put(("error", error), block=False)
                    finally:
                        if page is not None:
                            try:
                                page.close()
                            except Exception:
                                pass
            finally:
                context.close()
                browser.close()


playwright_headless_renderer = PlaywrightHeadlessRenderer()


def fetch_with_python_engine(script: str, url: str, timeout_seconds: int, engine_name: str = "engine") -> Optional[str]:
    command = [sys.executable, "-c", script, url, str(timeout_seconds), ENGINE_OUTPUT_MARKER]
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    if os.name == "nt":
        creationflags |= getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        process = subprocess.Popen(
            command,
            cwd=str(BASE_DIR),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            start_new_session=os.name == "posix",
            creationflags=creationflags,
        )
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds + 10)
        except subprocess.TimeoutExpired as error:
            if os.name == "posix":
                try:
                    os.killpg(process.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
            else:
                process.terminate()
            try:
                stdout_bytes, stderr_bytes = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                else:
                    process.kill()
                stdout_bytes, stderr_bytes = process.communicate()
            raise RuntimeError(
                f"{engine_name}: процесс превысил таймаут {timeout_seconds + 10} сек."
            ) from error
    except Exception as error:
        if isinstance(error, RuntimeError) and str(error).startswith(f"{engine_name}:"):
            raise
        raise RuntimeError(f"{engine_name}: не удалось запустить процесс: {error}") from error

    stdout = stdout_bytes.decode("utf-8", "replace")
    stderr = stderr_bytes.decode("utf-8", "replace")

    if process.returncode != 0:
        details = (stderr or stdout or "").strip()
        if len(details) > 1200:
            details = details[-1200:]
        raise RuntimeError(f"{engine_name}: процесс завершился с кодом {process.returncode}: {details}")

    for line in reversed(stdout.splitlines()):
        if ENGINE_OUTPUT_MARKER not in line:
            continue

        payload = line.split(ENGINE_OUTPUT_MARKER, 1)[1].strip()

        if not payload:
            raise RuntimeError(f"{engine_name}: движок вернул пустой HTML")

        try:
            html_bytes = base64.b64decode(payload)
        except Exception as error:
            raise RuntimeError(f"{engine_name}: не удалось декодировать HTML: {error}") from error

        html = html_bytes.decode("utf-8", "replace").strip()
        return html or None

    details = (stderr or stdout or "").strip()
    if len(details) > 1200:
        details = details[-1200:]
    raise RuntimeError(f"{engine_name}: движок не вернул HTML. Вывод: {details}")


def fetch_with_scrapy(url: str) -> Optional[str]:
    if find_spec("scrapy") is None:
        return None
    return fetch_with_python_engine(SCRAPY_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "Scrapy")


def fetch_with_crawlee(url: str) -> Optional[str]:
    if find_spec("crawlee") is None:
        return None
    return fetch_with_python_engine(CRAWLEE_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "Crawlee")


def fetch_with_playwright(url: str) -> Optional[str]:
    if find_spec("playwright") is None:
        return None
    with STANDALONE_BROWSER_SEMAPHORE:
        return playwright_headless_renderer.fetch(url, REQUEST_TIMEOUT)


def fetch_with_scrapegraphai(url: str) -> Optional[str]:
    if find_spec("scrapegraphai") is None:
        return None
    with STANDALONE_BROWSER_SEMAPHORE:
        return fetch_with_python_engine(SCRAPEGRAPHAI_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "ScrapeGraphAI")
