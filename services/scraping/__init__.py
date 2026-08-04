"""Stable public API for scraping services."""

from services.scraping.browser import (
    BotasaurusBrowserSession,
    BotasaurusDebugVisibleSession,
    BrowserMethodSession,
    PlaywrightBrowserSession,
)
from services.scraping.extraction import (
    clean_text,
    extract_model_by_markers,
    extract_product_data,
    finalize_scraped_model,
    first_by_selector,
    first_text,
    prepare_rule_model,
)
from services.scraping.fallback import ProductSiteCrawler
from services.scraping.http import normalize_url, product_url_filter_patterns

__all__ = [
    "BotasaurusBrowserSession",
    "BotasaurusDebugVisibleSession",
    "BrowserMethodSession",
    "PlaywrightBrowserSession",
    "ProductSiteCrawler",
    "clean_text",
    "extract_model_by_markers",
    "extract_product_data",
    "finalize_scraped_model",
    "first_by_selector",
    "first_text",
    "normalize_url",
    "prepare_rule_model",
    "product_url_filter_patterns",
]
