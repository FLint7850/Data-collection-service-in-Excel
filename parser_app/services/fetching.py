"""HTTP and browser fetching engines."""



from parser_app.runtime import *  # noqa: F401,F403



def fetch_with_botasaurus_request(url: str) -> Optional[str]:
    """Fallback через Botasaurus Request: браузероподобный HTTP-запрос с Google Referrer."""
    try:
        from botasaurus.request import Request
        from botasaurus.request import request as botasaurus_request
    except ImportError:
        return None

    @botasaurus_request(max_retry=MAX_RETRIES, output=None, create_error_logs=False)
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
    """Fallback через Botasaurus Browser для страниц, которым нужен настоящий рендеринг."""
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError:
        return None

    @browser(
        headless=True,
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
    """Совместимый скрытый вариант старого botasaurus-visible для автопереключения."""
    return fetch_with_botasaurus_browser(url, "direct")

def fetch_with_botasaurus_debug_visible_browser(url: str) -> Optional[str]:
    """Ручной диагностический режим: открывает видимый браузер только при явном выборе."""
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError:
        return None

    @browser(
        headless=False,
        profile="protected_sites_debug_visible",
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
            result = _render_html(url)
    except Exception:
        return None

    if isinstance(result, list):
        result = result[0] if result else None
    return result if isinstance(result, str) and result.strip() else None

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
        with HEADLESS_BROWSER_SEMAPHORE:
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

class PlaywrightHeadlessRenderer:
    """Один скрытый Chromium внутри сервиса; на каждый URL открывается только новая page."""

    def __init__(self) -> None:
        self.jobs: Queue = Queue()
        self.thread: Optional[threading.Thread] = None
        self.lock = threading.Lock()

    def ensure_started(self) -> None:
        with self.lock:
            if self.thread and self.thread.is_alive():
                return
            self.thread = threading.Thread(target=self._worker, name="playwright-headless-renderer", daemon=True)
            self.thread.start()

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

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(
                headless=True,
                args=[
                    "--disable-blink-features=AutomationControlled",
                    "--disable-gpu",
                    "--disable-dev-shm-usage",
                    "--disable-background-networking",
                    "--disable-sync",
                    "--no-sandbox",
                    "--blink-settings=imagesEnabled=false",
                ],
            )
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
    try:
        completed = subprocess.run(
            [sys.executable, "-c", script, url, str(timeout_seconds), ENGINE_OUTPUT_MARKER],
            cwd=str(BASE_DIR),
            capture_output=True,
            timeout=timeout_seconds + 10,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except Exception as error:
        raise RuntimeError(f"{engine_name}: не удалось запустить процесс: {error}") from error

    stdout = completed.stdout.decode("utf-8", "replace")
    stderr = completed.stderr.decode("utf-8", "replace")

    if completed.returncode != 0:
        details = (stderr or stdout or "").strip()
        if len(details) > 1200:
            details = details[-1200:]
        raise RuntimeError(f"{engine_name}: процесс завершился с кодом {completed.returncode}: {details}")

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
    try:
        import scrapy  # noqa: F401
    except ImportError:
        return None
    return fetch_with_python_engine(SCRAPY_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "Scrapy")

def fetch_with_crawlee(url: str) -> Optional[str]:
    try:
        import crawlee  # noqa: F401
    except ImportError:
        return None
    return fetch_with_python_engine(CRAWLEE_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "Crawlee")

def fetch_with_playwright(url: str) -> Optional[str]:
    try:
        import playwright  # noqa: F401
    except ImportError:
        return None
    with HEADLESS_BROWSER_SEMAPHORE:
        return playwright_headless_renderer.fetch(url, REQUEST_TIMEOUT)

def fetch_with_scrapegraphai(url: str) -> Optional[str]:
    try:
        import scrapegraphai  # noqa: F401
    except ImportError:
        return None
    with HEADLESS_BROWSER_SEMAPHORE:
        return fetch_with_python_engine(SCRAPEGRAPHAI_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "ScrapeGraphAI")
