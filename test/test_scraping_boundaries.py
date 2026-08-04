import unittest
import asyncio
import os
import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from config import botasaurus_browser_executable
from services.scraping import extract_product_data, normalize_url
from services.scraping.browser import (
    BotasaurusBrowserSession,
    BotasaurusDebugVisibleSession,
    BrowserMethodSession,
    PlaywrightBrowserSession,
)
from services.scraping.extraction import extract_listing_products
from services.scraping.fallback import ProductSiteCrawler
from services.scraping.http import looks_blocked_or_empty


class ScrapingBoundaryTests(unittest.TestCase):
    def test_url_normalization_drops_tracking_but_preserves_pagination(self) -> None:
        result = normalize_url(
            "/catalog/?page=2&utm_source=test",
            "https://Example.test/start/",
        )

        self.assertEqual(result, "https://example.test/catalog/?page=2")

    def test_selector_extraction_crosses_module_boundaries(self) -> None:
        html = """
        <html><body>
          <h1>Demo product</h1>
          <span class="model">ABC-123</span>
          <span class="price">12 990 руб.</span>
        </body></html>
        """

        product = extract_product_data(
            "https://example.test/product/abc-123",
            html,
            "",
            {"model_selector": ".model", "price_selector": ".price"},
            assume_product=True,
        )

        self.assertIsNotNone(product)
        self.assertEqual(product["model"], "ABC-123")

    def test_block_page_detection_is_available_without_circular_imports(self) -> None:
        self.assertTrue(looks_blocked_or_empty("<html><body>captcha</body></html>"))

    def test_listing_product_can_be_extracted_without_url_selector(self) -> None:
        html = """
        <div class="card"><span class="model">ABC-123</span><span class="price">12 990 руб.</span></div>
        <div class="card"><span class="model">XYZ-456</span><span class="price">19 990 руб.</span></div>
        """

        products = extract_listing_products(
            "https://example.test/catalog/",
            html,
            {
                "product_card_selector": ".card",
                "model_selector": ".model",
                "price_selector": ".price",
            },
        )

        self.assertEqual([product["url"] for product in products], ["", ""])
        self.assertEqual([product["model"] for product in products], ["ABC-123", "XYZ-456"])

    def test_missing_card_link_does_not_drop_product(self) -> None:
        products = extract_listing_products(
            "https://example.test/catalog/",
            '<div class="card"><span class="model">ABC-123</span><span class="price">12 990 руб.</span></div>',
            {
                "product_card_selector": ".card",
                "product_url_selector": "a.product-link",
                "model_selector": ".model",
                "price_selector": ".price",
            },
        )

        self.assertEqual(
            products,
            [{"url": "", "model": "ABC-123", "price": "12 990 руб."}],
        )

    def test_crawler_keeps_url_less_products_and_deduplicates_by_model(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="requests"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                extraction_rules={
                    "product_card_selector": ".card",
                    "model_selector": ".model",
                    "price_selector": ".price",
                },
            )
        html = """
        <div class="card"><span class="model">ABC-123</span><span class="price">12 990 руб.</span></div>
        <div class="card"><span class="model">XYZ-456</span><span class="price">19 990 руб.</span></div>
        """

        with patch.object(crawler, "current_connection_method", return_value="requests"):
            crawler.process_page("https://example.test/catalog/", html)
            crawler.process_page("https://example.test/catalog/page-2/", html)

        self.assertEqual(len(crawler.snapshot_results()), 2)
        self.assertEqual({item["url"] for item in crawler.snapshot_results()}, {""})

    def test_requests_collects_detail_when_catalog_cards_yield_nothing(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="requests"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                product_url_filters=["/goods_"],
                extraction_rules={
                    "product_card_selector": ".missing-card",
                    "model_selector": ".model",
                    "price_selector": ".price",
                },
                connection_method="requests",
            )

        with patch.object(crawler, "current_connection_method", return_value="requests"):
            crawler.process_page(
                "https://example.test/catalog/",
                '<a href="/goods_123/product.html">Product</a>',
            )

            product_url = crawler.queue.get_nowait()
            crawler.process_page(
                product_url,
                '<h1>Product</h1><span class="model">BDW 4026</span><span class="price">17 240 руб.</span>',
            )

        self.assertEqual(product_url, "https://example.test/goods_123/product.html")
        self.assertEqual(
            crawler.snapshot_results(),
            [{"url": product_url, "model": "BDW 4026", "price": "17 240 руб."}],
        )

    def test_url_less_listing_products_do_not_enqueue_their_detail_links(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="requests"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                product_url_filters=["/goods_"],
                extraction_rules={
                    "product_card_selector": ".card",
                    "model_selector": ".model",
                    "price_selector": ".price",
                },
                connection_method="requests",
            )
        html = """
        <div class="card">
          <a href="/goods_123/product.html">Product</a>
          <span class="model">ABC-123</span>
          <span class="price">12 990 руб.</span>
        </div>
        """

        with patch.object(crawler, "current_connection_method", return_value="requests"):
            crawler.process_page("https://example.test/catalog/", html)

        self.assertTrue(crawler.queue.empty())
        self.assertEqual(crawler.snapshot_results()[0]["url"], "")

    def test_disabled_auto_fallback_does_not_start_protected_browser(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="botasaurus-browser"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                extraction_rules={"product_card_selector": ".missing-card"},
                connection_method="botasaurus-browser",
                auto_connection_fallback=False,
            )

        with (
            patch.object(crawler, "current_connection_method", return_value="botasaurus-browser"),
            patch.object(crawler.browser_session, "fetch") as browser_fetch,
        ):
            crawler.process_page("https://example.test/catalog/", "<html><body>Catalog</body></html>")

        browser_fetch.assert_not_called()

    def test_catalog_processing_never_starts_a_different_browser_engine(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="botasaurus-browser"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                extraction_rules={"product_card_selector": ".missing-card"},
                connection_method="botasaurus-browser",
                auto_connection_fallback=True,
            )

        with (
            patch.object(crawler, "current_connection_method", return_value="botasaurus-browser"),
            patch.object(crawler.browser_session, "fetch") as browser_fetch,
        ):
            crawler.process_page("https://example.test/catalog/", "<html><body>Catalog</body></html>")

        browser_fetch.assert_not_called()

    def test_fallback_restarts_previous_session_before_trying_next_method(self) -> None:
        events = []

        class SharedBrowserSession:
            def restart(self, prefer_headless_shell=True, method=None):
                events.append(("restart", prefer_headless_shell, method))
                return True

        normalize = lambda value: str(value or "requests")
        with (
            patch("services.scraping.fallback.normalize_connection_method", side_effect=normalize),
            patch(
                "services.scraping.fallback.is_browser_render_method",
                side_effect=lambda method: method == "protected-site",
            ),
            patch("services.scraping.fallback.is_debug_visible_method", return_value=False),
        ):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                connection_method="botasaurus-browser",
                auto_connection_fallback=True,
                browser_session=SharedBrowserSession(),
                owns_browser_session=False,
            )

            def fetch_method(_url, method):
                events.append(("fetch", method))
                if method == "protected-site":
                    return "<html><body>Product</body></html>"
                return None

            with (
                patch.object(
                    crawler,
                    "fallback_method_sequence",
                    return_value=["botasaurus-browser", "requests", "protected-site"],
                ),
                patch.object(crawler, "fetch_with_connection_method", side_effect=fetch_method),
            ):
                result = crawler.fetch("https://example.test/catalog/")

        self.assertEqual(result, "<html><body>Product</body></html>")
        self.assertEqual(
            events,
            [
                ("fetch", "botasaurus-browser"),
                ("restart", True, "requests"),
                ("fetch", "requests"),
                ("restart", False, "protected-site"),
                ("fetch", "protected-site"),
                ("restart", True, "botasaurus-browser"),
            ],
        )
        self.assertEqual(crawler.connection_method_state["active_method"], "botasaurus-browser")

    def test_non_browser_fallback_becomes_active_after_previous_browser_stops(self) -> None:
        events = []

        class SharedBrowserSession:
            def restart(self, prefer_headless_shell=True, method=None):
                events.append(("restart", prefer_headless_shell, method))
                return True

        normalize = lambda value: str(value or "requests")
        with (
            patch("services.scraping.fallback.normalize_connection_method", side_effect=normalize),
            patch("services.scraping.fallback.is_browser_render_method", return_value=False),
            patch("services.scraping.fallback.is_debug_visible_method", return_value=False),
        ):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                connection_method="botasaurus-browser",
                auto_connection_fallback=True,
                browser_session=SharedBrowserSession(),
                owns_browser_session=False,
            )

            def fetch_method(_url, method):
                events.append(("fetch", method))
                return "<html><body>Catalog</body></html>" if method == "requests" else None

            with (
                patch.object(crawler, "fallback_method_sequence", return_value=["botasaurus-browser", "requests"]),
                patch.object(crawler, "fetch_with_connection_method", side_effect=fetch_method),
            ):
                result = crawler.fetch("https://example.test/catalog/")

        self.assertEqual(result, "<html><body>Catalog</body></html>")
        self.assertEqual(
            events,
            [
                ("fetch", "botasaurus-browser"),
                ("restart", True, "requests"),
                ("fetch", "requests"),
            ],
        )
        self.assertEqual(crawler.connection_method_state["active_method"], "requests")

    def test_browser_session_can_restart_after_full_shutdown(self) -> None:
        session = PlaywrightBrowserSession(threading.Event(), 1, prefer_headless_shell=True)
        previous_token = session._process_token

        restarted = session.restart(prefer_headless_shell=False)

        self.assertTrue(restarted)
        self.assertFalse(session._closed)
        self.assertFalse(session.prefer_headless_shell)
        self.assertNotEqual(session._process_token, previous_token)

    def test_thread_count_limits_parallel_browser_pages(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="requests"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                6,
            )

        self.assertEqual(crawler.thread_count, 6)
        self.assertEqual(crawler.browser_session.max_pages, 6)
        self.assertEqual(crawler.browser_session.botasaurus_session.max_pages, 6)
        self.assertEqual(crawler.browser_session.playwright_session.max_pages, 6)
        self.assertTrue(crawler.browser_session.prefer_headless_shell)

    def test_protected_site_keeps_full_chromium(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="protected-site"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                connection_method="protected-site",
            )

        self.assertFalse(crawler.browser_session.prefer_headless_shell)
        self.assertFalse(crawler.browser_session.playwright_session.prefer_headless_shell)

    def test_browser_session_resolves_executable_before_async_loop(self) -> None:
        with (
            patch("services.scraping.browser.env_str", return_value=""),
            patch(
                "services.scraping.browser.botasaurus_browser_executable",
                return_value="/ms-playwright/chromium_headless_shell/chrome-headless-shell",
            ) as executable_resolver,
        ):
            session = PlaywrightBrowserSession(prefer_headless_shell=True)

        executable_resolver.assert_called_once_with(prefer_headless_shell=True)
        self.assertEqual(
            session.executable_path,
            "/ms-playwright/chromium_headless_shell/chrome-headless-shell",
        )

    def test_playwright_headless_shell_executable_is_detected(self) -> None:
        with TemporaryDirectory() as directory:
            browser_root = Path(directory)
            chrome = browser_root / "chromium-123" / "chrome-linux64" / "chrome"
            shell = (
                browser_root
                / "chromium_headless_shell-123"
                / "chrome-headless-shell-linux64"
                / "chrome-headless-shell"
            )
            chrome.parent.mkdir(parents=True)
            shell.parent.mkdir(parents=True)
            chrome.write_bytes(b"")
            shell.write_bytes(b"")
            playwright = SimpleNamespace(
                chromium=SimpleNamespace(executable_path=str(chrome)),
                stop=lambda: None,
            )
            manager = SimpleNamespace(start=lambda: playwright)

            botasaurus_browser_executable.cache_clear()
            try:
                with (
                    patch.dict(os.environ, {"PLAYWRIGHT_BROWSER_EXECUTABLE": ""}),
                    patch("playwright.sync_api.sync_playwright", return_value=manager),
                ):
                    executable = botasaurus_browser_executable(prefer_headless_shell=True)
            finally:
                botasaurus_browser_executable.cache_clear()

        self.assertEqual(executable, str(shell))

    def test_browser_accepts_listing_html_without_product_url(self) -> None:
        session = PlaywrightBrowserSession(max_pages=3)
        html = '<div class="card"><span class="model">ABC-123</span><span class="price">12 990 руб.</span></div>'

        self.assertTrue(
            session._html_usable_for_parsing(
                "https://example.test/catalog/",
                html,
                {
                    "product_card_selector": ".card",
                    "model_selector": ".model",
                    "price_selector": ".price",
                },
                [],
                False,
            )
        )

    def test_browser_shutdown_closes_transport_before_cancelling_tasks(self) -> None:
        events = []
        session = PlaywrightBrowserSession()

        async def fake_close_browser() -> None:
            events.append("browser-closed")

        async def background_task() -> None:
            try:
                await asyncio.Event().wait()
            finally:
                events.append("task-cancelled")

        async def run_shutdown() -> None:
            task = asyncio.create_task(background_task())
            await asyncio.sleep(0)
            with patch.object(session, "_close_browser", side_effect=fake_close_browser):
                await session._shutdown_async()
            self.assertTrue(task.cancelled())

        asyncio.run(run_shutdown())
        self.assertEqual(events, ["browser-closed", "task-cancelled"])

    def test_browser_method_session_uses_native_botasaurus_only_for_botasaurus_codes(self) -> None:
        session = BrowserMethodSession(threading.Event(), 3, initial_method="botasaurus-browser")
        try:
            with (
                patch.object(session.botasaurus_session, "fetch", return_value="<html>botasaurus</html>") as botasaurus_fetch,
                patch.object(session.playwright_session, "fetch", return_value="<html>playwright</html>") as playwright_fetch,
            ):
                for method in ("botasaurus-browser", "botasaurus-browser-direct", "botasaurus-visible"):
                    self.assertEqual(session.fetch("https://example.test", method), "<html>botasaurus</html>")
                self.assertEqual(session.fetch("https://example.test", "playwright"), "<html>playwright</html>")
                self.assertEqual(session.fetch("https://example.test", "protected-site"), "<html>playwright</html>")

            self.assertEqual(
                [call.args[1] for call in botasaurus_fetch.call_args_list],
                ["botasaurus-browser", "botasaurus-browser-direct", "botasaurus-visible"],
            )
            self.assertEqual(
                [call.args[1] for call in playwright_fetch.call_args_list],
                ["playwright", "protected-site"],
            )
        finally:
            session.close()

    def test_native_botasaurus_session_rejects_playwright_method(self) -> None:
        with patch.object(BotasaurusBrowserSession, "_create_renderer", return_value=None):
            session = BotasaurusBrowserSession(threading.Event(), 2)
        self.assertIsNone(session.fetch("https://example.test", "playwright"))

    def test_debug_visible_botasaurus_uses_full_chrome_with_thread_tabs(self) -> None:
        with (
            patch.object(BotasaurusBrowserSession, "_create_renderer", return_value=None),
            patch(
                "services.scraping.browser.botasaurus_browser_executable",
                return_value="C:/chrome-for-testing/chrome.exe",
            ) as executable_resolver,
        ):
            session = BotasaurusDebugVisibleSession(
                threading.Event(),
                "debug-profile",
                max_pages=6,
            )

        executable_resolver.assert_called_once_with(prefer_headless_shell=False)
        self.assertEqual(session.executable_path, "C:/chrome-for-testing/chrome.exe")
        self.assertEqual(session.max_pages, 6)
        self.assertFalse(session.headless)
        self.assertEqual(session.allowed_methods, {"botasaurus-debug-visible"})

    def test_native_botasaurus_uses_one_renderer_with_bounded_tab_pool(self) -> None:
        renderer_calls = []
        active_lock = threading.Lock()
        active_tabs = set()
        max_active = 0

        class FakeTab:
            def __init__(self, number: int) -> None:
                self.number = number
                self.page_html = f"<html>{number}</html>"

            def run_js(self, _script: str) -> None:
                return None

        def fake_renderer(owner: BotasaurusBrowserSession) -> None:
            renderer_calls.append(owner)
            with owner._state_lock:
                owner._driver = object()
                for number in range(owner.max_pages):
                    owner._tabs.put_nowait(FakeTab(number))
            owner._ready.set()
            owner._close_requested.wait()

        def fake_navigate(tab: FakeTab, _url: str, _navigation: str) -> None:
            nonlocal max_active
            with active_lock:
                active_tabs.add(tab.number)
                max_active = max(max_active, len(active_tabs))
            threading.Event().wait(0.05)
            with active_lock:
                active_tabs.discard(tab.number)

        with patch.object(BotasaurusBrowserSession, "_create_renderer", return_value=fake_renderer):
            session = BotasaurusBrowserSession(threading.Event(), 4)
        try:
            with (
                patch.object(session, "_navigate_tab", side_effect=fake_navigate),
                patch("services.scraping.browser.time.sleep", return_value=None),
                patch("services.log_service.log_fetch_result"),
            ):
                with ThreadPoolExecutor(max_workers=8) as executor:
                    results = list(
                        executor.map(
                            lambda number: session.fetch(
                                f"https://example.test/{number}",
                                "botasaurus-browser-direct",
                            ),
                            range(8),
                        )
                    )
        finally:
            session.close()

        self.assertEqual(len(renderer_calls), 1)
        self.assertEqual(max_active, 4)
        self.assertTrue(all(result and result.startswith("<html>") for result in results))
        self.assertTrue(session._shutdown_complete.is_set())

    def test_every_connection_code_routes_to_its_named_engine(self) -> None:
        with patch("services.scraping.fallback.normalize_connection_method", return_value="requests"):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                2,
                connection_method="requests",
            )

        with (
            patch.object(crawler, "fetch_with_requests", return_value="requests"),
            patch("services.scraping.fallback.fetch_with_botasaurus_request", return_value="botasaurus-request"),
            patch.object(crawler.browser_session, "fetch", side_effect=lambda _url, method, *_args: method),
            patch.object(crawler.debug_visible_session, "fetch", return_value="botasaurus-debug-visible"),
            patch("services.scraping.fallback.fetch_with_crawl4ai", return_value="crawl4ai"),
            patch("services.scraping.fallback.fetch_with_scrapy", return_value="scrapy"),
            patch("services.scraping.fallback.fetch_with_crawlee", return_value="crawlee"),
            patch("services.scraping.fallback.fetch_with_scrapegraphai", return_value="scrapegraphai"),
        ):
            expected = {
                "requests": "requests",
                "botasaurus-request": "botasaurus-request",
                "botasaurus-browser": "botasaurus-browser",
                "botasaurus-browser-direct": "botasaurus-browser-direct",
                "botasaurus-visible": "botasaurus-visible",
                "botasaurus-debug-visible": "botasaurus-debug-visible",
                "playwright": "playwright",
                "protected-site": "protected-site",
                "crawl4ai": "crawl4ai",
                "scrapy": "scrapy",
                "crawlee": "crawlee",
                "scrapegraphai": "scrapegraphai",
            }
            for method, result in expected.items():
                with self.subTest(method=method):
                    self.assertEqual(crawler.fetch_by_method("https://example.test", method), result)


if __name__ == "__main__":
    unittest.main()
