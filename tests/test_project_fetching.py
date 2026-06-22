import threading

from parser_app.services import crawler as crawler_module
from parser_app.services import fetching


def make_crawler(monkeypatch) -> crawler_module.ProductSiteCrawler:
    monkeypatch.setattr(crawler_module, "normalize_connection_method", lambda value: str(value or "requests"))
    return crawler_module.ProductSiteCrawler(
        start_urls=["https://shop.test/catalog/category"],
        run_id=1,
        stop_signal=threading.Event(),
        finish_signal=threading.Event(),
        thread_count=1,
        product_url_filters=["/catalog/category/"],
        connection_method="requests",
    )


def test_catalog_html_without_products_is_not_accepted(monkeypatch) -> None:
    crawler = make_crawler(monkeypatch)
    navigation = " ".join(f'<a href="/info/{index}">Раздел {index}</a>' for index in range(12))
    html = f"<html><body><p>{'Обычный информационный текст. ' * 30}</p>{navigation}</body></html>"

    assert crawler.html_has_expected_content(crawler.start_url, html) is False


def test_catalog_html_with_product_link_is_accepted(monkeypatch) -> None:
    crawler = make_crawler(monkeypatch)
    html = """
        <html><body>
            <a href="/catalog/category/model-123">Модель 123</a>
            <p>Каталог продукции с подробным описанием и характеристиками.</p>
        </body></html>
    """

    assert crawler.html_has_expected_content(crawler.start_url, html) is True


def test_fallback_continues_after_unusable_nonempty_html(monkeypatch) -> None:
    crawler = make_crawler(monkeypatch)
    unusable = (
        "<html><body>"
        + "<p>Навигационная оболочка без каталога. " * 30
        + "".join(f'<a href="/info/{index}">Ссылка</a>' for index in range(12))
        + "</body></html>"
    )
    usable = """
        <html><body>
            <article class="product-card">
                <a href="/catalog/category/model-123">Модель 123</a>
                <span class="price">49 990 ₽</span>
            </article>
        </body></html>
    """
    calls: list[str] = []

    def fake_fetch(_url: str, method: str):
        calls.append(method)
        return {"requests": unusable, "crawl4ai": unusable, "playwright": usable}.get(method)

    monkeypatch.setattr(crawler, "fetch_by_method_with_timeout", fake_fetch)
    monkeypatch.setattr(crawler, "fallback_method_sequence", lambda: ["requests", "crawl4ai", "playwright"])

    result = crawler.fetch(crawler.start_url)

    assert result == usable
    assert calls == ["requests", "crawl4ai", "playwright"]
    assert crawler.current_connection_method() == "playwright"


def test_botasaurus_request_runner_result_is_normalized(monkeypatch) -> None:
    class FakeTasks:
        @staticmethod
        def request_html(url: str):
            return [{"content_type": "text/html; charset=utf-8", "text": f"<html>{url}</html>"}]

    monkeypatch.setattr(fetching, "_load_botasaurus_tasks", lambda: FakeTasks)

    assert fetching.fetch_with_botasaurus_request("https://shop.test/") == (
        "<html>https://shop.test/</html>"
    )
