import unittest
import asyncio
import threading
from unittest.mock import patch

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

    def test_configured_url_selector_still_requires_card_link(self) -> None:
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

        self.assertEqual(products, [])

    def test_crawler_keeps_url_less_products_and_deduplicates_by_model(self) -> None:
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

        crawler.process_page("https://example.test/catalog/", html)
        crawler.process_page("https://example.test/catalog/page-2/", html)

        self.assertEqual(len(crawler.snapshot_results()), 2)
        self.assertEqual({item["url"] for item in crawler.snapshot_results()}, {""})

    def test_thread_count_limits_parallel_browser_pages(self) -> None:
        crawler = ProductSiteCrawler(
            ["https://example.test/catalog/"],
            1,
            threading.Event(),
            threading.Event(),
            6,
        )

        self.assertEqual(crawler.thread_count, 6)
        self.assertEqual(crawler.browser_session.max_pages, 6)

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
