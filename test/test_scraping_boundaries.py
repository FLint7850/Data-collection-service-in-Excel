import unittest
import asyncio
import os
import threading
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace
from unittest.mock import patch

from config import botasaurus_browser_executable
from services.scraping import extract_product_data, normalize_url
from services.scraping.browser import BotasaurusBrowserSession
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

    def test_browser_session_resolves_executable_before_async_loop(self) -> None:
        with (
            patch("services.scraping.browser.env_str", return_value=""),
            patch(
                "services.scraping.browser.botasaurus_browser_executable",
                return_value="/ms-playwright/chromium_headless_shell/chrome-headless-shell",
            ) as executable_resolver,
        ):
            session = BotasaurusBrowserSession(prefer_headless_shell=True)

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
        session = BotasaurusBrowserSession(max_pages=3)
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
        session = BotasaurusBrowserSession()

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


if __name__ == "__main__":
    unittest.main()
