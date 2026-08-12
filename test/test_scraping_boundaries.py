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
    ScrapeGraphAISession,
    _ensure_botasaurus_debugging_address_compatibility,
)
from services.outbound_proxy import OutboundProxy
from services.scraping.extraction import extract_listing_products
from services.scraping.fallback import ProductSiteCrawler
from services.scraping.http import looks_blocked_or_empty
from services.scraping.checkpoints import delete_scrape_checkpoint, load_scrape_checkpoint, save_scrape_checkpoint


class ScrapingBoundaryTests(unittest.TestCase):
    def test_playwright_uses_native_proxy_settings(self) -> None:
        proxy = OutboundProxy(
            "http://user:pass@198.51.100.10:6584",
            "http",
            "198.51.100.10",
            6584,
            "user",
            "pass",
        )
        session = PlaywrightBrowserSession(max_pages=1)
        async def add_init_script(_script):
            return None

        fake_context = SimpleNamespace(add_init_script=add_init_script)

        launches = []
        async def new_context(**_kwargs):
            return fake_context

        browser = SimpleNamespace(new_context=new_context)

        async def launch(**kwargs):
            launches.append(kwargs)
            return browser

        chromium = SimpleNamespace(launch=launch)
        playwright = SimpleNamespace(chromium=chromium)

        class FakePlaywrightManager:
            async def start(self):
                return playwright

        with (
            patch("services.scraping.browser.configured_outbound_proxy", return_value=proxy),
            patch("playwright.async_api.async_playwright", return_value=FakePlaywrightManager()),
        ):
            asyncio.run(session._start_browser())

        self.assertEqual(launches[0]["proxy"], proxy.playwright())

    def make_recording_crawler(self):
        class FakeBrowserSession:
            def close(self):
                return None

        class RecordingCrawler(ProductSiteCrawler):
            def __init__(self):
                super().__init__(
                    ["https://example.test/catalog/"],
                    1,
                    threading.Event(),
                    threading.Event(),
                    1,
                    browser_session=FakeBrowserSession(),
                )
                self.state_updates = []
                self.finished_partials = []

            def update_state(self, **kwargs):
                self.state_updates.append(kwargs)

            def log(self, _message, _level="info"):
                return None

            def finish_with_excel(self, partial=False):
                self.finished_partials.append(partial)

        # These crawler-boundary tests do not exercise the database-backed
        # connection-method catalog.  Keep them independent from application
        # bootstrap so they also run in a clean Docker build without app.db.
        with patch("services.scraping.fallback.normalize_connection_method", return_value="requests"):
            return RecordingCrawler()

    def test_failed_url_is_deferred_and_auto_pauses_with_partial_result(self) -> None:
        crawler = self.make_recording_crawler()

        with (
            patch.object(crawler, "fetch", return_value=None) as fetch,
            patch("services.scraping.fallback.REQUEST_DELAY_SECONDS", 0),
        ):
            crawler.run()

        self.assertEqual(fetch.call_count, 3)
        self.assertEqual(crawler.deferred_urls, {"https://example.test/catalog/"})
        self.assertTrue(crawler.stop_signal.is_set())
        self.assertTrue(crawler.recovery_pause_reason)
        self.assertEqual(crawler.finished_partials, [True])
        self.assertTrue(any(state.get("status") == "pausing" for state in crawler.state_updates))

    def test_resume_retries_deferred_url_without_rescanning_visited_urls(self) -> None:
        crawler = self.make_recording_crawler()
        crawler.deferred_urls.add("https://example.test/catalog/")
        crawler.visited.update(
            {
                "https://example.test/catalog/",
                "https://example.test/already-done/",
            }
        )
        crawler.failed_attempts["https://example.test/catalog/"] = 3
        crawler.stop_signal = threading.Event()
        crawler.finish_signal = threading.Event()

        with (
            patch.object(crawler, "fetch", return_value="<html><body>ok</body></html>") as fetch,
            patch.object(crawler, "process_page"),
            patch("services.scraping.fallback.REQUEST_DELAY_SECONDS", 0),
        ):
            crawler.run(resume=True)

        self.assertEqual(
            [call.args[0] for call in fetch.call_args_list],
            ["https://example.test/catalog/"],
        )
        self.assertNotIn("https://example.test/catalog/", crawler.deferred_urls)
        self.assertIn("https://example.test/already-done/", crawler.visited)
        self.assertEqual(crawler.finished_partials, [False])

    def test_stall_requests_recoverable_pause_instead_of_fatal_error(self) -> None:
        crawler = self.make_recording_crawler()

        crawler.mark_stalled(["https://example.test/slow/"])

        self.assertTrue(crawler.stop_signal.is_set())
        self.assertTrue(crawler.recovery_pause_reason)
        self.assertEqual(crawler.fatal_error, "")
        self.assertTrue(any(state.get("status") == "pausing" for state in crawler.state_updates))

    def test_crawler_checkpoint_round_trip_preserves_resume_queue_and_results(self) -> None:
        crawler = self.make_recording_crawler()
        crawler.enqueue("https://example.test/pending/", force=True)
        crawler.deferred_urls.add("https://example.test/retry/")
        crawler.visited.add("https://example.test/done/")
        crawler.results.append(
            {"url": "https://example.test/product/1", "model": "ABC-1", "price": "100"}
        )
        crawler.result_urls.add("https://example.test/product/1")
        payload = crawler.checkpoint_payload()

        restored = self.make_recording_crawler()

        self.assertTrue(restored.restore_checkpoint(payload))
        self.assertEqual(restored.deferred_urls, {"https://example.test/retry/"})
        self.assertIn("https://example.test/done/", restored.visited)
        self.assertEqual(restored.snapshot_results(), crawler.snapshot_results())
        self.assertEqual(restored.queue.get_nowait(), "https://example.test/pending/")

    def test_scrape_checkpoint_file_is_atomic_and_removable(self) -> None:
        with TemporaryDirectory() as directory:
            root = Path(directory)
            with patch("services.scraping.checkpoints.SCRAPE_CHECKPOINT_DIR", root):
                path = save_scrape_checkpoint(
                    "news",
                    "42",
                    {"queued_urls": ["https://example.test/retry/"]},
                )
                loaded = load_scrape_checkpoint("news", "42")
                delete_scrape_checkpoint("news", "42")

        self.assertEqual(loaded["queued_urls"], ["https://example.test/retry/"])
        self.assertFalse(path.exists())

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

    def test_successful_browser_fallback_stays_active_for_next_urls(self) -> None:
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
            ],
        )
        self.assertEqual(crawler.connection_method_state["active_method"], "protected-site")

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
        self.assertEqual(crawler.browser_session.debug_visible_session.max_pages, 6)
        self.assertEqual(crawler.browser_session.crawl4ai_session.max_pages, 6)
        self.assertEqual(crawler.browser_session.playwright_session.max_pages, 6)
        self.assertTrue(crawler.browser_session.prefer_headless_shell)

    def test_shared_news_worker_does_not_close_browser_manager(self) -> None:
        manager = BrowserMethodSession(
            threading.Event(),
            4,
            initial_method="botasaurus-browser-direct",
        )
        with patch(
            "services.scraping.fallback.normalize_connection_method",
            return_value="botasaurus-browser-direct",
        ):
            crawler = ProductSiteCrawler(
                ["https://example.test/catalog/"],
                1,
                threading.Event(),
                threading.Event(),
                1,
                browser_session=manager,
                owns_browser_session=False,
            )

        crawler.close_browser_sessions()

        self.assertFalse(manager._closed)
        manager.close()

    def test_profiles_and_debug_mode_keep_configured_thread_count(self) -> None:
        from services.projects import project_runtime_thread_count

        self.assertEqual(
            project_runtime_thread_count(
                {
                    "thread_count": 10,
                    "persist_profile": True,
                    "connection_method": "protected-site",
                }
            ),
            10,
        )
        self.assertEqual(
            project_runtime_thread_count(
                {
                    "thread_count": 10,
                    "persist_profile": False,
                    "connection_method": "botasaurus-debug-visible",
                }
            ),
            10,
        )

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

    def test_browser_method_session_routes_each_browser_code_to_its_native_engine(self) -> None:
        session = BrowserMethodSession(threading.Event(), 3, initial_method="botasaurus-browser")
        try:
            with (
                patch.object(session.botasaurus_session, "fetch", return_value="<html>botasaurus</html>") as botasaurus_fetch,
                patch.object(session.debug_visible_session, "fetch", return_value="<html>debug</html>") as debug_fetch,
                patch.object(session.crawl4ai_session, "fetch", return_value="<html>crawl4ai</html>") as crawl4ai_fetch,
                patch.object(session.scrapegraphai_session, "fetch", return_value="<html>scrapegraphai</html>") as scrapegraphai_fetch,
                patch.object(session.playwright_session, "fetch", return_value="<html>playwright</html>") as playwright_fetch,
            ):
                for method in ("botasaurus-browser", "botasaurus-browser-direct", "botasaurus-visible"):
                    self.assertEqual(session.fetch("https://example.test", method), "<html>botasaurus</html>")
                self.assertEqual(session.fetch("https://example.test", "playwright"), "<html>playwright</html>")
                self.assertEqual(session.fetch("https://example.test", "protected-site"), "<html>playwright</html>")
                self.assertEqual(session.fetch("https://example.test", "botasaurus-debug-visible"), "<html>debug</html>")
                self.assertEqual(session.fetch("https://example.test", "crawl4ai"), "<html>crawl4ai</html>")
                self.assertEqual(session.fetch("https://example.test", "scrapegraphai"), "<html>scrapegraphai</html>")

            self.assertEqual(
                [call.args[1] for call in botasaurus_fetch.call_args_list],
                ["botasaurus-browser", "botasaurus-browser-direct", "botasaurus-visible"],
            )
            self.assertEqual(
                [call.args[1] for call in playwright_fetch.call_args_list],
                ["playwright", "protected-site"],
            )
            debug_fetch.assert_called_once()
            crawl4ai_fetch.assert_called_once_with("https://example.test")
            scrapegraphai_fetch.assert_called_once_with("https://example.test")
        finally:
            session.close()

    def test_native_botasaurus_session_rejects_playwright_method(self) -> None:
        with patch.object(BotasaurusBrowserSession, "_create_renderer", return_value=None):
            session = BotasaurusBrowserSession(threading.Event(), 2)
        self.assertIsNone(session.fetch("https://example.test", "playwright"))

    def test_botasaurus_omits_remote_debugging_host_for_headless_shell(self) -> None:
        from botasaurus_driver.core.config import Config

        _ensure_botasaurus_debugging_address_compatibility()
        config = Config(
            headless=True,
            port=59123,
            chrome_executable_path=botasaurus_browser_executable(prefer_headless_shell=True),
        )

        arguments = config()

        self.assertNotIn("--remote-debugging-host=127.0.0.1", arguments)
        self.assertIn("--remote-debugging-port=59123", arguments)

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

    def test_scrapegraphai_serializes_its_internal_full_browser_per_scan(self) -> None:
        session = ScrapeGraphAISession(threading.Event())
        active = 0
        max_active = 0
        lock = threading.Lock()

        def fake_fetch(*_args, **_kwargs):
            nonlocal active, max_active
            with lock:
                active += 1
                max_active = max(max_active, active)
            threading.Event().wait(0.03)
            with lock:
                active -= 1
            return "<html>scrapegraphai</html>"

        with patch("services.scraping.browser.fetch_with_python_engine", side_effect=fake_fetch):
            with ThreadPoolExecutor(max_workers=4) as executor:
                results = list(executor.map(session.fetch, [f"https://example.test/{i}" for i in range(4)]))
        session.close()

        self.assertEqual(max_active, 1)
        self.assertEqual(results, ["<html>scrapegraphai</html>"] * 4)

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
            patch.object(crawler.browser_session.debug_visible_session, "fetch", return_value="botasaurus-debug-visible"),
            patch("services.scraping.fallback.fetch_with_scrapy", return_value="scrapy"),
            patch("services.scraping.fallback.fetch_with_crawlee", return_value="crawlee"),
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
