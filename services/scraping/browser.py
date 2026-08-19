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
from config import (
    BASE_DIR,
    BLOCKED_BROWSER_URL_PARTS,
    BOTASAURUS_HEADLESS_METHODS,
    REQUEST_TIMEOUT,
    SESSION_BROWSER_METHODS,
    botasaurus_browser_executable,
    env_str,
)
from pathlib import Path
from queue import Empty, Queue
from typing import Dict, Iterable, List, Optional, Set

from services.scraping.extraction import extract_listing_products, extract_product_data
from services.scraping.http import is_product_url_for_filters

from services.scraping.http import looks_blocked_or_empty


_BOTASAURUS_CONFIG_PATCH_LOCK = threading.Lock()


def _ensure_botasaurus_debugging_address_compatibility() -> None:
    """Removes Botasaurus' host flag, which crashes current Headless Shell."""
    from botasaurus_driver.core.config import Config

    with _BOTASAURUS_CONFIG_PATCH_LOCK:
        if getattr(Config, "_parser_debugging_address_compat", False):
            return
        original_call = Config.__call__

        def compatible_call(config):
            arguments = original_call(config)
            return [
                argument
                for argument in arguments
                if not argument.startswith("--remote-debugging-host=")
            ]

        Config.__call__ = compatible_call
        Config._parser_debugging_address_compat = True


def _force_terminate_token_processes(process_token: str, known_root_pid: Optional[int] = None) -> None:
    """Terminates only the browser tree carrying this session's unique token."""
    try:
        import psutil
    except ImportError:
        return

    marker = f"--{process_token}"
    roots = []
    for process in psutil.process_iter(["pid", "cmdline"]):
        try:
            if marker in (process.info.get("cmdline") or []):
                roots.append(process)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue

    if known_root_pid and not roots:
        try:
            candidate = psutil.Process(int(known_root_pid))
            if marker in (candidate.cmdline() or []):
                roots.append(candidate)
        except (psutil.NoSuchProcess, psutil.AccessDenied, ValueError):
            pass
    if not roots:
        return

    owned = {}
    for root in roots:
        try:
            owned[root.pid] = root
            for child in root.children(recursive=True):
                owned[child.pid] = child
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    owned.pop(os.getpid(), None)
    processes = list(owned.values())
    for process in reversed(processes):
        try:
            process.terminate()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    _gone, alive = psutil.wait_procs(processes, timeout=1.5)
    for process in alive:
        try:
            process.kill()
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    if alive:
        psutil.wait_procs(alive, timeout=1.5)


def _terminate_subprocess_tree(process: subprocess.Popen) -> None:
    """Stops an isolated parser subprocess together with browser descendants."""
    if process.poll() is not None:
        return
    if os.name == "nt":
        try:
            subprocess.run(
                ["taskkill", "/PID", str(process.pid), "/T", "/F"],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
                check=False,
                timeout=10,
            )
        except (OSError, subprocess.SubprocessError):
            process.kill()
        return
    try:
        os.killpg(process.pid, signal.SIGTERM)
    except ProcessLookupError:
        return


def _ensure_botasaurus_initial_tab(driver) -> None:
    """Chrome Headless Shell starts without a page; Botasaurus expects one."""
    try:
        browser = getattr(driver, "_browser", None)
        tabs = list(getattr(browser, "tabs", []) or [])
    except Exception:
        tabs = []
    if not tabs and hasattr(driver, "open_link_in_new_tab"):
        driver.open_link_in_new_tab("about:blank")

class PlaywrightBrowserSession:
    """One Playwright Chromium session owned by one project/news scan.

    thread_count still controls parallel open pages, but every page now uses a
    selector-driven fast path and closes as soon as the needed DOM appears.
    """

    def __init__(
        self,
        stop_signal: Optional[threading.Event] = None,
        max_pages: int = 1,
        profile_dir: Optional[Path] = None,
        prefer_headless_shell: bool = True,
        request_url_validator=None,
    ) -> None:
        from services.projects import parse_thread_count
        self.stop_signal = stop_signal
        self.max_pages = max(1, parse_thread_count(max_pages))
        self.profile_dir = profile_dir
        self.prefer_headless_shell = bool(prefer_headless_shell)
        self.request_url_validator = request_url_validator
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
        _force_terminate_token_processes(self._process_token)

    @staticmethod
    def _profiles_for_method(method: str) -> List[Dict[str, object]]:
        method = str(method or "")
        if method == "protected-site":
            return [
                {"name": "protected_direct", "block_stylesheet": False, "selector_timeout": 9000, "referer": ""},
                {"name": "protected_google_referrer", "block_stylesheet": False, "selector_timeout": 9000, "referer": "https://www.google.com/"},
            ]
        return [
            {"name": "fast_playwright", "block_stylesheet": True, "selector_timeout": 2500, "referer": ""},
            {"name": "compatible_playwright", "block_stylesheet": False, "selector_timeout": 5500, "referer": ""},
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
                request_url = str(getattr(request, "url", "") or "")
                validator = self.request_url_validator
                allowed = True
                if validator is not None and request_url.lower().startswith(("http://", "https://")):
                    try:
                        allowed = bool(validator(request_url))
                    except Exception:
                        allowed = False
                if not allowed or self._should_block_resource(request, block_stylesheet=block_stylesheet):
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


class BotasaurusBrowserSession:
    """One native Botasaurus browser with a bounded pool of tabs.

    ``max_pages`` is the number of tabs inside one Chrome process, not the
    number of independent browser instances. The Botasaurus decorator owns the
    single Driver for the whole scan and closes it when the session stops or
    switches to another connection method.
    """

    prefer_headless_shell = True
    headless = True
    block_images_and_css = True
    wait_for_complete_page_load = False
    initial_wait_seconds = 1.0
    scroll_count = 4
    scroll_wait_seconds = 0.5
    allowed_methods = frozenset(BOTASAURUS_HEADLESS_METHODS)

    def __init__(
        self,
        stop_signal: Optional[threading.Event] = None,
        max_pages: int = 1,
        profile: Optional[str] = None,
    ) -> None:
        from services.projects import parse_thread_count

        self.stop_signal = stop_signal
        self.max_pages = max(1, parse_thread_count(max_pages))
        self.profile = profile
        self.executable_path = botasaurus_browser_executable(
            prefer_headless_shell=self.prefer_headless_shell
        )
        self._tabs: Queue = Queue(maxsize=self.max_pages)
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._tab_admin_lock = threading.Lock()
        self._closed = False
        self._active_calls = 0
        self._process_token = f"parser-botasaurus-session-{uuid.uuid4().hex}"
        self._browser_pid: Optional[int] = None
        self._driver = None
        self._thread: Optional[threading.Thread] = None
        self._ready = threading.Event()
        self._close_requested = threading.Event()
        self._shutdown_complete = threading.Event()
        self._start_error: Optional[BaseException] = None
        self._renderer = self._create_renderer()

    def _create_renderer(self):
        _ensure_botasaurus_debugging_address_compatibility()
        try:
            from botasaurus.browser import Driver
            from botasaurus.browser import browser
        except ImportError:
            return None

        process_argument = f"--{self._process_token}"

        browser_arguments = [
            "--no-sandbox",
            "--disable-gpu",
            "--disable-dev-shm-usage",
            "--disable-background-networking",
            "--disable-sync",
            "--blink-settings=imagesEnabled=false",
            process_argument,
        ]
        if self.headless:
            browser_arguments.insert(0, "--headless=new")
        else:
            browser_arguments.insert(0, "--window-position=40,40")

        @browser(
            headless=self.headless,
            chrome_executable_path=self.executable_path,
            profile=self.profile,
            add_arguments=browser_arguments,
            window_size=[1280, 720],
            block_images_and_css=self.block_images_and_css,
            wait_for_complete_page_load=self.wait_for_complete_page_load,
            # Page retries are controlled by ProductSiteCrawler. Retrying the
            # whole Driver here would launch another browser behind its back.
            max_retry=0,
            output=None,
            close_on_crash=True,
            create_error_logs=False,
            raise_exception=True,
        )
        def _serve_tabs(driver: Driver, _session: "BotasaurusBrowserSession"):
            self._serve_driver(driver)

        return _serve_tabs

    @staticmethod
    def _make_browser_tab(driver, raw_tab):
        from botasaurus_driver.driver import BrowserTab

        return BrowserTab(driver.config, raw_tab, driver, driver, driver._browser)

    def _new_browser_tab(self, driver):
        with self._tab_admin_lock:
            raw_tab = driver._browser.get("about:blank", new_tab=True)
        return self._make_browser_tab(driver, raw_tab)

    def _serve_driver(self, driver) -> None:
        try:
            _ensure_botasaurus_initial_tab(driver)
            raw_tabs = list(driver._browser.tabs)
            while len(raw_tabs) < self.max_pages:
                self._new_browser_tab(driver)
                raw_tabs = list(driver._browser.tabs)

            with self._state_lock:
                if self._closed:
                    return
                self._driver = driver
                self._browser_pid = int(getattr(driver._browser, "_process_pid", 0) or 0) or None
                for raw_tab in raw_tabs[: self.max_pages]:
                    self._tabs.put_nowait(self._make_browser_tab(driver, raw_tab))
            self._ready.set()

            while not self._close_requested.wait(0.25):
                if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                    break

            # Give active tab calls a short chance to finish normally. The
            # decorator closes the single Driver immediately afterwards.
            deadline = time.time() + 2
            while time.time() < deadline:
                with self._state_lock:
                    if self._active_calls == 0:
                        break
                time.sleep(0.05)
        finally:
            self._ready.set()

    def _run_renderer(self) -> None:
        try:
            renderer = self._renderer
            if renderer is not None:
                renderer(self)
        except BaseException as error:  # noqa: BLE001
            self._start_error = error
        finally:
            with self._state_lock:
                self._driver = None
            self._ready.set()
            self._shutdown_complete.set()

    def _ensure_started(self) -> bool:
        with self._lifecycle_lock:
            with self._state_lock:
                if self._closed or self._renderer is None:
                    return False
                thread = self._thread
                if thread is None:
                    self._thread = threading.Thread(
                        target=self._run_renderer,
                        name=f"botasaurus-tab-session-{self._process_token[-8:]}",
                        daemon=True,
                    )
                    self._thread.start()
        if not self._ready.wait(timeout=REQUEST_TIMEOUT + 10):
            return False
        with self._state_lock:
            return not self._closed and self._driver is not None and self._start_error is None

    def _acquire_tab(self):
        while True:
            if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                return None
            with self._state_lock:
                if self._closed:
                    return None
            try:
                tab = self._tabs.get(timeout=0.25)
            except Empty:
                continue
            with self._state_lock:
                if self._closed:
                    return None
                self._active_calls += 1
            return tab

    def _navigate_tab(self, tab, url: str, navigation: str) -> None:
        from botasaurus_driver import cdp
        from botasaurus_driver.solve_cloudflare_captcha import wait_till_document_is_ready

        referer = "https://www.google.com/" if navigation == "google" else None
        frame_id, *_ = tab._tab.send(cdp.page.navigate(url, referrer=referer))
        tab._tab.frame_id = frame_id
        time.sleep(0.25)
        wait_till_document_is_ready(
            tab._tab,
            self.wait_for_complete_page_load,
            timeout=REQUEST_TIMEOUT,
        )

    def _replace_failed_tab(self, tab):
        try:
            tab._tab.close()
        except Exception:
            pass
        with self._state_lock:
            driver = self._driver
            closed = self._closed
        if driver is None or closed:
            return None
        try:
            return self._new_browser_tab(driver)
        except Exception:
            return None

    def fetch(
        self,
        url: str,
        method: str,
        rules: Optional[Dict[str, str]] = None,
        product_url_filters: Optional[Iterable[str]] = None,
        allow_empty_price: bool = False,
    ) -> Optional[str]:
        del rules, product_url_filters, allow_empty_price
        from services.log_service import log_fetch_exception, log_fetch_result

        if method not in self.allowed_methods or not self._ensure_started():
            return None
        tab = self._acquire_tab()
        if tab is None:
            return None

        started = time.time()
        reusable_tab = tab
        try:
            navigation = "google" if method == "botasaurus-browser" else "direct"
            self._navigate_tab(tab, url, navigation)
            time.sleep(self.initial_wait_seconds)
            for _ in range(self.scroll_count):
                if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                    return None
                try:
                    tab.run_js("window.scrollTo(0, document.body.scrollHeight)")
                except Exception:
                    break
                time.sleep(self.scroll_wait_seconds)
            result = tab.page_html
            if result:
                log_fetch_result(method, url, result, time.time() - started, extra="engine=botasaurus")
            return result if isinstance(result, str) and result.strip() else None
        except Exception as error:
            log_fetch_exception(method, url, error)
            reusable_tab = self._replace_failed_tab(tab)
            return None
        finally:
            with self._state_lock:
                self._active_calls = max(0, self._active_calls - 1)
                closed = self._closed
            if reusable_tab is not None and not closed:
                self._tabs.put(reusable_tab)

    def _force_terminate_owned_processes(self) -> None:
        _force_terminate_token_processes(self._process_token, self._browser_pid)

    def close(self) -> None:
        with self._lifecycle_lock:
            with self._state_lock:
                self._closed = True
                thread = self._thread
            self._close_requested.set()
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=15)
            self._force_terminate_owned_processes()
            if thread is not None and thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=5)


class Crawl4AIBrowserSession:
    """One native Crawl4AI crawler with thread_count bounded concurrent pages."""

    def __init__(
        self,
        stop_signal: Optional[threading.Event] = None,
        max_pages: int = 1,
    ) -> None:
        from services.projects import parse_thread_count

        self.stop_signal = stop_signal
        self.max_pages = max(1, parse_thread_count(max_pages))
        self._state_lock = threading.Lock()
        self._lifecycle_lock = threading.RLock()
        self._ready = threading.Event()
        self._close_requested = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop = None
        self._crawler = None
        self._semaphore = None
        self._closed = False
        self._start_error: Optional[BaseException] = None
        self._process_token = f"parser-crawl4ai-session-{uuid.uuid4().hex}"

    def _ensure_started(self) -> bool:
        with self._state_lock:
            if self._closed:
                return False
            if self._thread is None or not self._thread.is_alive():
                self._start_error = None
                self._ready.clear()
                self._close_requested.clear()
                self._thread = threading.Thread(
                    target=self._run_loop,
                    name="crawl4ai-browser-session",
                    daemon=True,
                )
                self._thread.start()
        if not self._ready.wait(timeout=40):
            return False
        return self._start_error is None and self._loop is not None and self._crawler is not None

    def _run_loop(self) -> None:
        import asyncio
        from services.log_service import fetch_debug_log

        self._loop = asyncio.new_event_loop()
        asyncio.set_event_loop(self._loop)
        try:
            self._loop.run_until_complete(self._start_crawler())
            self._ready.set()
            with self._state_lock:
                closed = self._closed
            if not closed:
                self._loop.run_forever()
        except BaseException as error:  # noqa: BLE001
            self._start_error = error
            fetch_debug_log(f"crawl4ai-session start failed: {type(error).__name__}: {error}", "warning")
            self._ready.set()
        finally:
            try:
                if not self._loop.is_closed():
                    self._loop.run_until_complete(self._shutdown_async())
            except BaseException as error:  # noqa: BLE001
                fetch_debug_log(f"crawl4ai-session shutdown failed: {type(error).__name__}: {error}", "warning")
            finally:
                if not self._loop.is_closed():
                    self._loop.close()
                self._loop = None

    async def _start_crawler(self) -> None:
        import asyncio

        crawl4ai_storage = BASE_DIR / "runtime" / "crawl4ai"
        crawl4ai_storage.mkdir(parents=True, exist_ok=True)
        # Crawl4AI creates its global cache manager during import, so the
        # writable base must be configured before importing the package.
        os.environ["CRAWL4_AI_BASE_DIRECTORY"] = str(crawl4ai_storage)
        from crawl4ai import AsyncWebCrawler, BrowserConfig

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
                f"--{self._process_token}",
            ],
            verbose=False,
        )
        self._crawler = AsyncWebCrawler(
            config=browser_config,
            base_directory=str(crawl4ai_storage),
            thread_safe=False,
        )
        await self._crawler.start()
        self._semaphore = asyncio.Semaphore(self.max_pages)

    @staticmethod
    def _run_config():
        from crawl4ai import CacheMode, CrawlerRunConfig

        return CrawlerRunConfig(
            cache_mode=CacheMode.BYPASS,
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

    async def _fetch_async(self, url: str) -> Optional[str]:
        import asyncio

        if self._crawler is None or self._semaphore is None:
            return None
        async with self._semaphore:
            if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                return None
            result = await asyncio.wait_for(
                self._crawler.arun(url=url, config=self._run_config()),
                timeout=REQUEST_TIMEOUT + 10,
            )
            html = getattr(result, "html", "") or getattr(result, "cleaned_html", "")
            return html if isinstance(html, str) and html.strip() else None

    def fetch(self, url: str) -> Optional[str]:
        from services.log_service import log_fetch_exception

        if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
            return None
        if not self._ensure_started():
            return None
        future = None
        try:
            import asyncio

            future = asyncio.run_coroutine_threadsafe(self._fetch_async(url), self._loop)
            return future.result(timeout=REQUEST_TIMEOUT + 20)
        except Exception as error:
            if future is not None:
                future.cancel()
            log_fetch_exception("crawl4ai", url, error)
            return None

    async def _shutdown_async(self) -> None:
        import asyncio

        if self._crawler is not None:
            try:
                await asyncio.wait_for(self._crawler.close(), timeout=10)
            except BaseException:  # noqa: BLE001
                pass
        self._crawler = None
        self._semaphore = None
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

    def close(self) -> None:
        with self._lifecycle_lock:
            with self._state_lock:
                self._closed = True
                thread = self._thread
                loop = self._loop
            if loop is not None and loop.is_running():
                loop.call_soon_threadsafe(loop.stop)
            if thread is not None and thread is not threading.current_thread():
                thread.join(timeout=15)
            _force_terminate_token_processes(self._process_token)
            if thread is not None and thread is not threading.current_thread() and thread.is_alive():
                thread.join(timeout=5)


class ScrapeGraphAISession:
    """Per-scan ScrapeGraphAI Chromium lifecycle without a server-wide lock."""

    def __init__(self, stop_signal: Optional[threading.Event] = None) -> None:
        self.stop_signal = stop_signal
        # FetchNode creates and owns its Chromium internally and cannot accept
        # a shared context. Serialize only this scan so thread_count does not
        # turn into thread_count independent full browsers.
        self._slot = threading.BoundedSemaphore(1)
        self._state_lock = threading.Lock()
        self._active_processes: Set[subprocess.Popen] = set()
        self._closed = False

    def _register_process(self, process: subprocess.Popen) -> None:
        with self._state_lock:
            if self._closed:
                _terminate_subprocess_tree(process)
                return
            self._active_processes.add(process)

    def _unregister_process(self, process: subprocess.Popen) -> None:
        with self._state_lock:
            self._active_processes.discard(process)

    def fetch(self, url: str) -> Optional[str]:
        while True:
            with self._state_lock:
                if self._closed:
                    return None
            if isinstance(self.stop_signal, threading.Event) and self.stop_signal.is_set():
                return None
            if self._slot.acquire(timeout=0.25):
                break
        try:
            with self._state_lock:
                if self._closed:
                    return None
            return fetch_with_python_engine(
                SCRAPEGRAPHAI_FETCH_SCRIPT,
                url,
                REQUEST_TIMEOUT,
                "ScrapeGraphAI",
                process_started=self._register_process,
                process_finished=self._unregister_process,
            )
        finally:
            self._slot.release()

    def close(self) -> None:
        with self._state_lock:
            self._closed = True
            processes = list(self._active_processes)
        for process in processes:
            _terminate_subprocess_tree(process)


class BrowserMethodSession:
    """Routes browser method codes to their matching native engine."""

    def __init__(
        self,
        stop_signal: Optional[threading.Event] = None,
        max_pages: int = 1,
        profile_dir: Optional[Path] = None,
        initial_method: str = "playwright",
    ) -> None:
        from services.projects import parse_thread_count

        self.stop_signal = stop_signal
        self.max_pages = max(1, parse_thread_count(max_pages))
        self.profile_dir = profile_dir
        self.initial_method = str(initial_method or "playwright")
        self.prefer_headless_shell = self.initial_method != "protected-site"
        self._lifecycle_lock = threading.RLock()
        self._closed = False
        self.playwright_session = self._new_playwright_session()
        self.botasaurus_session = BotasaurusBrowserSession(self.stop_signal, self.max_pages)
        self.debug_visible_session = self._new_debug_visible_session()
        self.crawl4ai_session = Crawl4AIBrowserSession(self.stop_signal, self.max_pages)
        self.scrapegraphai_session = ScrapeGraphAISession(self.stop_signal)

    def _new_playwright_session(self) -> PlaywrightBrowserSession:
        return PlaywrightBrowserSession(
            self.stop_signal,
            self.max_pages,
            profile_dir=self.profile_dir,
            prefer_headless_shell=self.prefer_headless_shell,
        )

    def _new_debug_visible_session(self) -> "BotasaurusDebugVisibleSession":
        return BotasaurusDebugVisibleSession(
            self.stop_signal,
            profile=(
                str(self.profile_dir)
                if self.profile_dir is not None
                else "protected_sites_debug_visible"
            ),
            max_pages=self.max_pages,
        )

    def fetch(
        self,
        url: str,
        method: str,
        rules: Optional[Dict[str, str]] = None,
        product_url_filters: Optional[Iterable[str]] = None,
        allow_empty_price: bool = False,
    ) -> Optional[str]:
        with self._lifecycle_lock:
            if self._closed:
                return None
            if method in BOTASAURUS_HEADLESS_METHODS:
                session = self.botasaurus_session
            elif method == "botasaurus-debug-visible":
                session = self.debug_visible_session
            elif method == "crawl4ai":
                session = self.crawl4ai_session
            elif method == "scrapegraphai":
                session = self.scrapegraphai_session
            elif method == "playwright" or method in SESSION_BROWSER_METHODS:
                session = self.playwright_session
            else:
                return None
        if method in {"crawl4ai", "scrapegraphai"}:
            return session.fetch(url)
        return session.fetch(url, method, rules, product_url_filters, allow_empty_price)

    def close(self) -> None:
        with self._lifecycle_lock:
            self._closed = True
            self.botasaurus_session.close()
            self.debug_visible_session.close()
            self.crawl4ai_session.close()
            self.scrapegraphai_session.close()
            self.playwright_session.close()

    def restart(
        self,
        prefer_headless_shell: Optional[bool] = None,
        method: Optional[str] = None,
    ) -> bool:
        with self._lifecycle_lock:
            self.botasaurus_session.close()
            self.debug_visible_session.close()
            self.crawl4ai_session.close()
            self.scrapegraphai_session.close()
            self.playwright_session.close()
            if method:
                self.initial_method = str(method)
            if prefer_headless_shell is not None:
                self.prefer_headless_shell = bool(prefer_headless_shell)
            else:
                self.prefer_headless_shell = self.initial_method != "protected-site"
            self.playwright_session = self._new_playwright_session()
            self.botasaurus_session = BotasaurusBrowserSession(self.stop_signal, self.max_pages)
            self.debug_visible_session = self._new_debug_visible_session()
            self.crawl4ai_session = Crawl4AIBrowserSession(self.stop_signal, self.max_pages)
            self.scrapegraphai_session = ScrapeGraphAISession(self.stop_signal)
            self._closed = False
            return True


class BotasaurusDebugVisibleSession(BotasaurusBrowserSession):
    """One visible Botasaurus Chrome for Testing with a bounded tab pool."""

    prefer_headless_shell = False
    headless = False
    block_images_and_css = False
    wait_for_complete_page_load = True
    initial_wait_seconds = 8.0
    scroll_count = 3
    scroll_wait_seconds = 0.8
    allowed_methods = frozenset({"botasaurus-debug-visible"})

    def __init__(
        self,
        stop_signal: Optional[threading.Event] = None,
        profile: str = "protected_sites_debug_visible",
        max_pages: int = 1,
    ) -> None:
        super().__init__(
            stop_signal,
            max_pages=max_pages,
            profile=profile or "protected_sites_debug_visible",
        )


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


def fetch_with_python_engine(
    script: str,
    url: str,
    timeout_seconds: int,
    engine_name: str = "engine",
    process_started=None,
    process_finished=None,
) -> Optional[str]:
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
        if process_started is not None:
            process_started(process)
        try:
            stdout_bytes, stderr_bytes = process.communicate(timeout=timeout_seconds + 10)
        except subprocess.TimeoutExpired as error:
            _terminate_subprocess_tree(process)
            try:
                stdout_bytes, stderr_bytes = process.communicate(timeout=3)
            except subprocess.TimeoutExpired:
                if os.name == "posix":
                    try:
                        os.killpg(process.pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass
                elif process.poll() is None:
                    process.kill()
                stdout_bytes, stderr_bytes = process.communicate()
            raise RuntimeError(
                f"{engine_name}: процесс превысил таймаут {timeout_seconds + 10} сек."
            ) from error
    except Exception as error:
        if isinstance(error, RuntimeError) and str(error).startswith(f"{engine_name}:"):
            raise
        raise RuntimeError(f"{engine_name}: не удалось запустить процесс: {error}") from error
    finally:
        if "process" in locals() and process_finished is not None:
            process_finished(process)

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
