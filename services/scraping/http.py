"""URL normalization, extraction rules and HTTP/browser scraping engines."""

import re
from bs4 import BeautifulSoup
from config import BLOCKED_PAGE_MARKERS, MAX_RETRIES, PRICE_RE
from fnmatch import fnmatch
from services.normalization import normalize_patterns
from typing import Dict, Iterable, List, Optional
from urllib.parse import parse_qsl, urldefrag, urlencode, urljoin, urlparse, urlunparse

def normalize_url(raw_url: str, base_url: str) -> Optional[str]:
    """Приводит ссылку к каноническому виду внутри сайта."""
    if not raw_url:
        return None
    raw_url = raw_url.strip()
    if raw_url.startswith(("mailto:", "tel:", "javascript:")):
        return None

    absolute_url = urljoin(base_url, raw_url)
    absolute_url, _fragment = urldefrag(absolute_url)
    parsed = urlparse(absolute_url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        return None

    path = re.sub(r"/{2,}", "/", parsed.path or "/")

# Важно: не удаляем завершающий слэш.
# Для Bitrix/каталогов URL вида /catalog/category/ и /catalog/category
# могут обрабатываться сайтом по-разному. Например ZUGEL требует слэш.

    # Сохраняем пагинацию и обязательные параметры товарных страниц OpenCart.
    # Остальные параметры обычно создают дубликаты: сортировки, UTM-метки,
    # сравнение и фильтры с теми же товарами.
    query_params = parse_qsl(parsed.query, keep_blank_values=False)
    route = next(
        (value for key, value in query_params if key.lower() == "route"),
        "",
    ).strip("/").lower()
    has_product_id = any(key.lower() == "product_id" and value for key, value in query_params)
    is_opencart_product = route == "product/product" and has_product_id

    preserved_params = []
    for key, value in query_params:
        key_lower = key.lower()
        if key_lower == "page" or key_lower.startswith("pagen_"):
            preserved_params.append((key, value))
        elif is_opencart_product and key_lower in {"route", "path", "product_id"}:
            preserved_params.append((key, value))
    query = urlencode(preserved_params, safe="/")

    result = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))
    return result


def same_site(url: str, root_netloc: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    root = root_netloc.lower()
    return netloc == root or netloc.endswith("." + root)


def has_static_extension(url: str) -> bool:
    return bool(
        re.search(
            r"\.(?:jpg|jpeg|png|gif|svg|webp|pdf|doc|docx|xls|xlsx|zip|rar|mp4|avi|css|js)$",
            urlparse(url).path,
            flags=re.IGNORECASE,
        )
    )


def is_obvious_service_path(path: str) -> bool:
    first = next((part.lower() for part in path.split("/") if part), "")
    return first in {
        "articles",
        "reviews",
        "delivery-and-payment",
        "services",
        "credit",
        "guarantee",
        "contacts",
        "favorites",
        "compare",
        "cart",
        "login",
        "personal",
        "search",
        "upload",
        "bitrix",
        "ajax",
    }


def looks_blocked_or_empty(html: str) -> bool:
    """Определяет страницы блокировки или почти пустые HTML-оболочки."""
    lowered = html.lower()
    soup = BeautifulSoup(html, "html.parser")
    text = re.sub(r"\s+", " ", soup.get_text(" ", strip=True)).strip()
    links_count = len(soup.select("a[href]"))
    if PRICE_RE.search(html):
        return False
    if PRICE_RE.search(text) and links_count > 10:
        return False
    if any(marker in lowered for marker in BLOCKED_PAGE_MARKERS):
        return len(text) < 1200 or links_count < 10
    return len(text) < 250 and links_count < 5


def should_follow_project_url(url: str, start_urls: List[str], root_netloc: str) -> bool:
    if has_static_extension(url):
        return False

    path = urlparse(url).path or "/"
    if is_obvious_service_path(path):
        return False
    for start_url in start_urls:
        start_netloc = urlparse(start_url).netloc
        if not same_site(url, start_netloc or root_netloc):
            continue
        start_path = (urlparse(start_url).path or "/").rstrip("/") or "/"
        if start_path in {"/", "/catalog"}:
            return True
        if path == start_path or path.startswith(start_path + "/"):
            return True

    return False


def is_catalog_url(url: str) -> bool:
    path = urlparse(url).path or "/"
    return path == "/catalog" or path.startswith("/catalog/")


def exclusion_matches(url: str, pattern: str) -> bool:
    """Проверяет URL по пользовательскому шаблону исключения."""
    pattern = pattern.strip()
    if not pattern:
        return False

    parsed = urlparse(url)
    full_url = url.rstrip("/") + "/"
    path = (parsed.path or "/").rstrip("/") + "/"
    normalized_pattern = pattern.rstrip("/") + "/"

    if "*" in pattern or "?" in pattern:
        return fnmatch(full_url, pattern) or fnmatch(path, pattern)

    if pattern.startswith(("http://", "https://")):
        return full_url.startswith(normalized_pattern)

    return path.startswith(normalized_pattern) or pattern in parsed.path


def product_url_matches_filters(url: str, filters: Iterable[str]) -> bool:
    patterns = [str(pattern).strip().lower() for pattern in filters if str(pattern).strip()]
    if not patterns:
        return True

    parsed = urlparse(url)
    haystack = f"{url} {parsed.path}".lower()
    return any(pattern in haystack or fnmatch(haystack, pattern) for pattern in patterns)


def product_url_matches_any(url: str, patterns: Iterable[str]) -> bool:
    normalized_patterns = [str(pattern).strip().lower() for pattern in patterns if str(pattern).strip()]
    if not normalized_patterns:
        return False

    parsed = urlparse(url)
    haystack = f"{url} {parsed.path}".lower()
    return any(pattern in haystack or fnmatch(haystack, pattern) for pattern in normalized_patterns)


def product_url_filter_patterns(
    product_url_filters: Optional[Iterable[str]],
    rules: Optional[Dict[str, str]] = None,
) -> List[str]:
    patterns = normalize_patterns(product_url_filters or [])
    rules = rules or {}
    selector_value = str(rules.get("product_url_selector", "") or "").strip()
    if selector_value and (selector_value.startswith(("http://", "https://", "/")) or "://" in selector_value):
        if selector_value not in patterns:
            patterns.append(selector_value)
    return patterns


def canonicalize_product_url_by_filters(url: str, filters: Iterable[str]) -> str:
    if not url:
        return ""
    parsed = urlparse(url)
    path = parsed.path or "/"
    product_anchor = re.search(r"/goods?_\d+", path, flags=re.IGNORECASE)
    if product_anchor and product_anchor.start() > 0:
        path = path[product_anchor.start():]
    return urlunparse((parsed.scheme, parsed.netloc, path, "", parsed.query, ""))


def is_product_url_for_filters(url: str, filters: Iterable[str]) -> bool:
    return bool([pattern for pattern in filters if str(pattern).strip()]) and product_url_matches_filters(url, filters)

def fetch_with_botasaurus_request(url: str) -> Optional[str]:
    """Fallback через Botasaurus Request: браузероподобный HTTP-запрос с Google Referrer."""
    from services.log_service import log_fetch_exception
    try:
        from botasaurus.request import Request
        from botasaurus.request import request as botasaurus_request
    except ImportError as error:
        log_fetch_exception("botasaurus-request:import", url, error)
        return None

    from services.outbound_proxy import proxy_for_external_url

    outbound_proxy = proxy_for_external_url(url)

    @botasaurus_request(
        max_retry=MAX_RETRIES,
        output=None,
        create_error_logs=False,
        proxy=outbound_proxy.url if outbound_proxy is not None else None,
    )
    def _fetch_html(request_client: Request, target_url: str):
        response = request_client.get(target_url)
        response.raise_for_status()
        return {
            "content_type": response.headers.get("content-type", ""),
            "text": response.text,
        }

    try:
        result = _fetch_html(url)
    except Exception as error:
        log_fetch_exception("botasaurus-request", url, error)
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
