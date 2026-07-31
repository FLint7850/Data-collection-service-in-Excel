"""URL normalization, extraction rules and HTTP/browser scraping engines."""

from services.core_service import (
    BASE_DIR,
    BLOCKED_BROWSER_RESOURCE_TYPES,
    BLOCKED_BROWSER_URL_PARTS,
    BLOCKED_PAGE_MARKERS,
    BeautifulSoup,
    Brand,
    CONNECTION_METHOD_TIMEOUT_SECONDS,
    DEFAULT_EXCLUSIONS,
    Dict,
    Empty,
    FIRST_COMPLETED,
    Iterable,
    List,
    MAX_RETRIES,
    NEWS_SCAN_STALL_TIMEOUT,
    Optional,
    PRICE_RE,
    Path,
    Queue,
    REQUEST_DELAY_SECONDS,
    REQUEST_TIMEOUT,
    SESSION_BROWSER_METHODS,
    STANDALONE_BROWSER_SEMAPHORE,
    Set,
    ThreadPoolExecutor,
    VISIBLE_BROWSER_LOCK,
    base64,
    botasaurus_browser_executable,
    env_str,
    fnmatch,
    html_lib,
    is_browser_render_method,
    is_debug_visible_method,
    normalize_connection_method,
    normalize_extraction_rules,
    normalize_patterns,
    normalize_start_urls,
    now_iso,
    ordered_db_connection_methods,
    parse_qsl,
    re,
    requests,
    reset_state,
    select,
    session_scope,
    subprocess,
    sys,
    threading,
    time,
    update_state,
    urldefrag,
    urlencode,
    urljoin,
    urlparse,
    urlunparse,
    wait,
)

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


def is_domain_url(url: str, domain: str) -> bool:
    return urlparse(url).netloc.lower().removeprefix("www.").endswith(domain.lower().removeprefix("www."))


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
    text = clean_text(soup.get_text(" ", strip=True))
    links_count = len(soup.select("a[href]"))
    if PRICE_RE.search(html):
        return False
    if PRICE_RE.search(text) and links_count > 10:
        return False
    if any(marker in lowered for marker in BLOCKED_PAGE_MARKERS):
        return len(text) < 1200 or links_count < 10
    return len(text) < 250 and links_count < 5


def should_follow_url(url: str, start_url: str, root_netloc: str) -> bool:
    """Ограничивает обход страницами сайта, полезными для поиска товаров."""
    if not same_site(url, root_netloc) or has_static_extension(url):
        return False

    path = urlparse(url).path or "/"
    start_path = urlparse(start_url).path or "/"
    normalized_start_path = start_path.rstrip("/") or "/"

    if normalized_start_path not in {"/", "/catalog"}:
        return path == normalized_start_path or path.startswith(normalized_start_path + "/")

    if path == "/" or path == "/catalog" or path.startswith("/catalog/"):
        return True

    return False


def should_follow_project_url(url: str, start_urls: List[str], root_netloc: str) -> bool:
    if has_static_extension(url):
        return False

    path = urlparse(url).path or "/"
    if is_obvious_service_path(path):
        return False
    allowed_domain = False
    for start_url in start_urls:
        start_netloc = urlparse(start_url).netloc
        if not same_site(url, start_netloc or root_netloc):
            continue
        allowed_domain = True
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


def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ").replace("\u2009", " ")).strip()


def split_text_lines(value: str) -> List[str]:
    return [clean_text(line) for line in re.split(r"[\n\r]+", value) if clean_text(line)]


MODEL_BRAND_CACHE_SECONDS = 60


model_brand_cache_lock = threading.Lock()


model_brand_cache: Dict[str, object] = {"loaded_at": 0.0, "brands": set()}


def model_brand_names(force_refresh: bool = False) -> Set[str]:
    """Возвращает бренды из БД только для fallback-очистки модели из названия."""
    now = time.time()
    with model_brand_cache_lock:
        cached = set(model_brand_cache.get("brands") or set())
        loaded_at = float(model_brand_cache.get("loaded_at") or 0.0)
        if cached and not force_refresh and now - loaded_at < MODEL_BRAND_CACHE_SECONDS:
            return cached

    brands: Set[str] = set()
    try:
        with session_scope() as session:
            rows = session.execute(select(Brand.name)).scalars().all()
        for name in rows:
            text = clean_text(str(name or "")).upper()
            if text:
                brands.add(text)
    except Exception:
        brands = set()

    with model_brand_cache_lock:
        model_brand_cache["brands"] = set(brands)
        model_brand_cache["loaded_at"] = now
    return brands


def known_brand_regex() -> str:
    return "|".join(re.escape(brand.lower()) for brand in sorted(model_brand_names(), key=len, reverse=True))


def normalize_model(value: str, product_url: str = "") -> str:
    """Возвращает маркировку модели без полного товарного названия."""
    text = clean_text(value)

    if not text:
        return ""

    # Сохраняем регистр и разделители моделей, которые уже выглядят как готовая модель.
    mixed_case_model = text.replace("\\", "/")
    mixed_case_model = re.sub(r"[–—]", "-", mixed_case_model)
    mixed_case_model = re.sub(r"\s*([/_.+])\s*", r"\1", mixed_case_model)
    mixed_case_model = re.sub(r"\s+-\s+", " - ", mixed_case_model)
    mixed_case_model = re.sub(r"\s{2,}", " ", mixed_case_model).strip()
    mixed_case_model = mixed_case_model.rstrip(".")
    text = mixed_case_model

    if (
        re.fullmatch(
            r"[A-Za-z0-9./_@-]+(?:\s+-\s+|\s+[A-Za-z0-9./_@-]+){0,8}",
            mixed_case_model,
        )
        and any(char.isdigit() for char in mixed_case_model)
        and any(char.isalpha() for char in mixed_case_model)
        and any(char.islower() for char in mixed_case_model)
    ):
        return mixed_case_model

    # Частый случай: "Бренд ABC123" -> "ABC123".
    brands_regex = known_brand_regex()
    if brands_regex:
        brand_match = re.search(
            rf"\b(?:{brands_regex})\b\s+([A-Z0-9][A-Z0-9./_@\\-]{{2,}})",
            text,
            re.IGNORECASE,
        )
        if brand_match:
            return brand_match.group(1).strip(" .,/\\_-").replace("\\", "/").upper()

    latin_model_text = text.replace("\\", "/")
    latin_model_tokens = re.findall(r"[A-Za-z0-9./_@-]+", latin_model_text)
    if (
        latin_model_tokens
        and " ".join(latin_model_tokens).strip() == re.sub(r"\s+", " ", latin_model_text).strip()
        and 1 <= len(latin_model_tokens) <= 6
        and any(any(char.isdigit() for char in token) for token in latin_model_tokens)
        and any(any(char.isalpha() for char in token) for token in latin_model_tokens)
        and latin_model_tokens[0].upper() not in {"SERIE", "SERIES"}
        and latin_model_tokens[0].upper() not in model_brand_names()
    ):
        return " ".join(token.strip(" .,/\\_-").upper() for token in latin_model_tokens if token.strip(" .,/\\_-"))

    ascii_tokens = re.findall(r"[A-Za-z0-9]+(?:[./_@-][A-Za-z0-9]+)*", text)
    for start_index in range(max(0, len(ascii_tokens) - 6), len(ascii_tokens)):
        candidate_tokens = [token.strip(" .,/\\_-") for token in ascii_tokens[start_index:] if token.strip(" .,/\\_-")]
        if not (2 <= len(candidate_tokens) <= 6):
            continue
        if not any(any(char.isdigit() for char in token) for token in candidate_tokens):
            continue
        if not all(re.fullmatch(r"[A-Z0-9./_@-]+", token) for token in candidate_tokens):
            continue
        if candidate_tokens[0].upper() in model_brand_names() or candidate_tokens[0].upper() in {"SERIE", "SERIES"}:
            continue
        return " ".join(candidate_tokens).upper()

    ignored_tokens = {*model_brand_names()}
    code_tokens = []
    for token in re.findall(r"[A-Z\u0400-\u04FF0-9][A-Z\u0400-\u04FF0-9./_@\\-]{2,}", text, flags=re.IGNORECASE):
        cleaned = token.strip(" .,/\\_-")
        if cleaned.upper() in ignored_tokens:
            continue
        has_digit = any(char.isdigit() for char in cleaned)
        has_letter = any(char.isalpha() for char in cleaned)
        if has_digit and has_letter:
            code_tokens.append(cleaned)

    if code_tokens:
        return code_tokens[-1].replace("\\", "/").upper()

    return text


def first_text(soup: BeautifulSoup, selectors: Iterable[str]) -> str:
    for selector in selectors:
        node = soup.select_one(selector)
        if node:
            text = clean_text(node.get_text(" ", strip=True))
            if text:
                return text
    return ""


def normalize_price_value(value: object) -> str:
    text = clean_text(str(value or ""))
    if not text:
        return ""
    match = PRICE_RE.search(text)
    if match:
        return clean_text(match.group(0))
    if not re.fullmatch(r"[^\w\u0400-\u04FF]*\d[\d\s\u2009\xa0.,]*[^\w\u0400-\u04FF]*", text):
        return ""
    digits = re.sub(r"[^\d]", "", text)
    if digits and len(digits) >= 2:
        return f"{int(digits):,}".replace(",", " ") + " \u20bd"
    return ""


def apply_extract_regex(value: str, pattern: str) -> str:
    text = clean_text(value)
    if not pattern:
        return text
    try:
        match = re.search(pattern, text, flags=re.IGNORECASE)
    except re.error:
        return text
    if not match:
        return text
    return clean_text(match.group(1) if match.groups() else match.group(0))


def replacement_flags(flag_text: str) -> int:
    flags = 0
    flags_text = flag_text.lower()
    if "i" in flags_text:
        flags |= re.IGNORECASE
    if "m" in flags_text:
        flags |= re.MULTILINE
    if "s" in flags_text:
        flags |= re.DOTALL
    return flags


def wildcard_rule_to_regex(pattern: str) -> str:
    result = []
    index = 0
    while index < len(pattern):
        if pattern.startswith("{skip}", index):
            result.append(".*?")
            index += len("{skip}")
        elif pattern.startswith("{.}", index):
            result.append(".")
            index += len("{.}")
        else:
            result.append(re.escape(pattern[index]))
            index += 1
    return "".join(result)


def apply_replace_rules(value: str, rules_text: str) -> str:
    text = html_lib.unescape(value or "")
    if not rules_text:
        return text

    for raw_line in rules_text.splitlines():
        line = raw_line.strip()
        if not line or "|" not in line:
            continue
        pattern, replacement = line.split("|", 1)
        pattern = pattern.strip()
        replacement = replacement.strip()

        try:
            if pattern == "{br}":
                text = re.sub(r"\r\n|\r|\n", replacement, text)
                continue

            regex_match = re.fullmatch(r"\{reg\[#(.*)#([a-zA-Z]*)\]\}", pattern)
            if regex_match:
                regex_pattern, flags_text = regex_match.groups()
                text = re.sub(regex_pattern, replacement, text, flags=replacement_flags(flags_text))
                continue

            if "{skip}" in pattern or "{.}" in pattern:
                text = re.sub(wildcard_rule_to_regex(pattern), replacement, text, flags=re.DOTALL)
                continue

            text = text.replace(pattern, replacement)
        except re.error:
            continue

    return text


def strip_html_to_text(value: str) -> str:
    raw = html_lib.unescape(value or "")
    if "<" in raw and ">" in raw:
        return BeautifulSoup(raw, "html.parser").get_text(" ", strip=True)
    return raw


def extract_between_markers(source: str, start_marker: str, end_marker: str) -> str:
    if not start_marker and not end_marker:
        return ""

    text = source or ""
    start_index = 0
    if start_marker:
        found_start = text.find(start_marker)
        if found_start < 0:
            return ""
        start_index = found_start + len(start_marker)

    end_index = len(text)
    if end_marker:
        found_end = text.find(end_marker, start_index)
        if found_end < 0:
            return ""
        end_index = found_end

    return text[start_index:end_index]


def extract_model_by_markers(source: str, rules: Dict[str, str]) -> str:
    return extract_between_markers(
        source,
        str(rules.get("model_start_marker", "")),
        str(rules.get("model_end_marker", "")),
    )


def prepare_rule_model(value: str, rules: Dict[str, str]) -> str:
    text = apply_replace_rules(value, str(rules.get("model_replace_rules", "")))
    text = strip_html_to_text(text)
    return clean_text(text)


def has_explicit_model_rules(rules: Optional[Dict[str, str]]) -> bool:
    if not rules:
        return False
    return any(
        str(rules.get(key, "")).strip()
        for key in ("model_selector", "model_start_marker", "model_end_marker", "model_replace_rules")
    )


def has_configured_model_source(rules: Optional[Dict[str, str]]) -> bool:
    if not rules:
        return False
    return any(
        str(rules.get(key, "")).strip()
        for key in ("model_selector", "model_start_marker", "model_end_marker")
    )


def has_model_replace_rules(rules: Optional[Dict[str, str]]) -> bool:
    return bool(rules and str(rules.get("model_replace_rules", "")).strip())


def finalize_scraped_model(
    value: str,
    product_url: str,
    rules: Optional[Dict[str, str]] = None,
    preserve_configured_model: bool = False,
) -> str:
    prepared = prepare_rule_model(value, rules or {})
    if not prepared:
        return ""
    if preserve_configured_model or has_model_replace_rules(rules):
        return prepared
    return normalize_model(prepared, product_url)


def first_by_selector(root, selector: str) -> str:
    if not selector or not hasattr(root, "select"):
        return ""
    try:
        node = root.select_one(selector)
    except Exception:
        return ""
    if not node:
        return ""
    return clean_text(node.get("content") or node.get("value") or node.get_text(" ", strip=True))


def extract_prices(value: str) -> List[str]:
    return [clean_text(match.group(0)) for match in PRICE_RE.finditer(value or "")]


def extract_price_from_container(container, selector: str = "") -> str:
    if not container or not hasattr(container, "select"):
        return ""
    if not selector:
        return ""
    selected = first_by_selector(container, selector)
    selected_price = (extract_prices(selected) or [normalize_price_value(selected)])[0]
    return selected_price or ""


def extract_listing_products_by_rules(
    soup: BeautifulSoup,
    current_url: str,
    rules: Dict[str, str],
    seen_urls: Set[str],
    product_url_filters: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    card_selector = rules.get("product_card_selector", "")
    if not card_selector:
        return []
    filters = list(product_url_filters or [])
    products: List[Dict[str, str]] = []
    try:
        cards = soup.select(card_selector)
    except Exception:
        return []
    url_selector = rules.get("product_url_selector", "")
    for card in cards:
        link_node = None
        if url_selector and not product_url_filter_patterns([], {"product_url_selector": url_selector}):
            try:
                link_node = card.select_one(url_selector)
            except Exception:
                link_node = None
        product_url = canonicalize_product_url_by_filters(normalize_url(link_node.get("href", "") if link_node else "", current_url), filters)
        if not product_url or product_url in seen_urls or not product_url_matches_filters(product_url, filters):
            continue

        model = extract_model_by_markers(str(card), rules)
        model_from_config = bool(model)
        if not model:
            model = first_by_selector(card, rules.get("model_selector", ""))
            model_from_config = bool(model)
        if has_configured_model_source(rules) and not model_from_config:
            continue
        model = finalize_scraped_model(model, product_url, rules, model_from_config)

        price = extract_price_from_container(card, rules.get("price_selector", ""))
        if not model or not price:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})
    return products


def extract_listing_products(
    current_url: str,
    html: str,
    rules: Optional[Dict[str, str]] = None,
    product_url_filters: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    """Собирает товары прямо со страницы категории/каталога."""
    soup = BeautifulSoup(html, "html.parser")
    products: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()
    rules = normalize_extraction_rules(rules or {})
    filters = product_url_filter_patterns(product_url_filters or [], rules)
    configured_card_source = bool(str(rules.get("product_card_selector", "")).strip())

    if configured_card_source:
        products.extend(extract_listing_products_by_rules(soup, current_url, rules, seen_urls, filters))
        seen_urls.update(product["url"] for product in products if product.get("url"))

    return products


def should_accept_extracted_product(
    url: str,
    soup: BeautifulSoup,
    model: str,
    price: str,
    h1: str,
    page_text: str,
    model_from_labeled_value: bool,
    rules: Optional[Dict[str, str]] = None,
    assume_product: bool = False,
    allow_empty_price: bool = False,
) -> bool:
    """Решает, можно ли сохранить страницу как товар.

    Важно: здесь нет проверок вида `is_maunfeld_url()` или `is_kuppersberg_url()`.
    Новый бренд должен работать через URL-фильтры, селекторы, schema.org и общие признаки товара.
    """
    if not model:
        return False
    if not price and not allow_empty_price:
        return False
    if assume_product:
        return True
    return bool(
        rules
        and any(
            str(rules.get(key, "")).strip()
            for key in ("model_selector", "price_selector", "model_start_marker", "model_end_marker")
        )
    )


def extract_product_data_by_rules(
    url: str,
    html: str,
    soup: BeautifulSoup,
    rules: Dict[str, str],
    fallback_price: str = "",
    assume_product: bool = False,
    allow_empty_price: bool = False,
) -> Optional[Dict[str, str]]:
    if not rules:
        return None
    model = extract_model_by_markers(html, rules)
    if not model:
        model = first_by_selector(soup, rules.get("model_selector", ""))
    price = first_by_selector(soup, rules.get("price_selector", ""))
    model = finalize_scraped_model(model, url, rules, True)
    prices = extract_prices(price)
    if prices:
        price = prices[-1]
    else:
        price = normalize_price_value(price or fallback_price)
    page_text = clean_text(soup.get_text(" ", strip=True))
    h1 = first_text(soup, ["h1"])
    if should_accept_extracted_product(
        url=url,
        soup=soup,
        model=model,
        price=price,
        h1=h1,
        page_text=page_text,
        model_from_labeled_value=False,
        rules=rules,
        assume_product=assume_product,
        allow_empty_price=allow_empty_price,
    ):
        return {"url": url, "model": model, "price": price}
    return None


def extract_product_data(
    url: str,
    html: str,
    fallback_price: str = "",
    rules: Optional[Dict[str, str]] = None,
    assume_product: bool = False,
    allow_empty_price: bool = False,
) -> Optional[Dict[str, str]]:
    soup = BeautifulSoup(html, "html.parser")
    rules = rules or {}
    ruled_product = extract_product_data_by_rules(
        url,
        html,
        soup,
        rules,
        fallback_price,
        assume_product,
        allow_empty_price=allow_empty_price,
    )
    if ruled_product:
        return ruled_product
    return None


def fetch_with_botasaurus_request(url: str) -> Optional[str]:
    """Fallback через Botasaurus Request: браузероподобный HTTP-запрос с Google Referrer."""
    from services.log_service import log_fetch_exception
    try:
        from botasaurus.request import Request
        from botasaurus.request import request as botasaurus_request
    except ImportError as error:
        log_fetch_exception("botasaurus-request:import", url, error)
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


def fetch_with_botasaurus_browser(url: str, navigation: str = "direct") -> Optional[str]:
    """Fallback через Botasaurus Browser для страниц, которым нужен настоящий рендеринг."""
    from services.log_service import log_fetch_exception, log_fetch_result
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError:
        return None

    chrome_executable_path = botasaurus_browser_executable(prefer_headless_shell=False)

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


def fetch_with_botasaurus_visible_browser(url: str) -> Optional[str]:
    """Совместимый скрытый вариант старого botasaurus-visible для автопереключения."""
    return fetch_with_botasaurus_browser(url, "direct")


def fetch_with_botasaurus_debug_visible_browser(url: str) -> Optional[str]:
    """Ручной диагностический режим: открывает видимый браузер только при явном выборе."""
    from services.log_service import log_fetch_exception
    try:
        from botasaurus.browser import Driver
        from botasaurus.browser import browser
    except ImportError as error:
        log_fetch_exception("botasaurus-debug-visible:import", url, error)
        return None

    chrome_executable_path = botasaurus_browser_executable(prefer_headless_shell=False)

    @browser(
        headless=False,
        chrome_executable_path=chrome_executable_path,
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
        time.sleep(8)
        for _ in range(3):
            try:
                driver.run_js("window.scrollTo(0, document.body.scrollHeight)")
            except Exception:
                break
            time.sleep(0.8)
        return driver.page_html

    try:
        with VISIBLE_BROWSER_LOCK:
            result = _render_html(url)
    except Exception as error:
        log_fetch_exception("botasaurus-debug-visible", url, error)
        return None

    if isinstance(result, list):
        result = result[0] if result else None
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
    ) -> None:
        from services.project_service import parse_thread_count
        self.stop_signal = stop_signal
        self.max_pages = max(1, parse_thread_count(max_pages))
        self.profile_dir = profile_dir
        self._state_lock = threading.Lock()
        self._ready = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self._loop = None
        self._playwright = None
        self._browser = None
        self._context = None
        self._semaphore = None
        self._closed = False
        self._start_error: Optional[BaseException] = None

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
        except BaseException as error:  # noqa: BLE001
            self._start_error = error
            fetch_debug_log(f"browser-session start failed: {type(error).__name__}: {error}", "warning")
            self._ready.set()
            return
        self._ready.set()
        try:
            self._loop.run_forever()
        finally:
            if not self._loop.is_closed():
                self._loop.run_until_complete(self._shutdown_async())
                self._loop.close()

    async def _start_browser(self) -> None:
        import asyncio
        from playwright.async_api import async_playwright

        self._playwright = await async_playwright().start()
        # Используем полноценный Chromium, а нагрузку снижаем ранней остановкой
        # страницы после появления нужных селекторов.
        executable_path = env_str("PLAYWRIGHT_BROWSER_EXECUTABLE") or botasaurus_browser_executable(prefer_headless_shell=False)
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
            ],
        }
        if executable_path:
            launch_options["executable_path"] = executable_path
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
        if self._context is not None:
            try:
                await self._context.close()
            except Exception:
                pass
        if self.profile_dir is None and self._browser is not None:
            try:
                await self._browser.close()
            except Exception:
                pass
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception:
                pass
        self._context = None
        self._browser = None
        self._playwright = None
        self._semaphore = None

    async def _shutdown_async(self) -> None:
        import asyncio

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
        await self._close_browser()

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

        thread = None
        loop = None
        with self._state_lock:
            if self._closed:
                return
            self._closed = True
            thread = self._thread
            loop = self._loop
        if loop is not None:
            try:
                shutdown = asyncio.run_coroutine_threadsafe(self._shutdown_async(), loop)
                shutdown.result(timeout=10)
            except Exception:
                pass
            try:
                loop.call_soon_threadsafe(loop.stop)
            except Exception:
                pass
        if thread is not None and thread is not threading.current_thread():
            thread.join(timeout=10)


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

        with sync_playwright() as playwright:
            executable_path = botasaurus_browser_executable(prefer_headless_shell=True)
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
    with STANDALONE_BROWSER_SEMAPHORE:
        return playwright_headless_renderer.fetch(url, REQUEST_TIMEOUT)


def fetch_with_scrapegraphai(url: str) -> Optional[str]:
    try:
        import scrapegraphai  # noqa: F401
    except ImportError:
        return None
    with STANDALONE_BROWSER_SEMAPHORE:
        return fetch_with_python_engine(SCRAPEGRAPHAI_FETCH_SCRIPT, url, REQUEST_TIMEOUT, "ScrapeGraphAI")


class ProductSiteCrawler:
    def __init__(
        self,
        start_urls: List[str],
        run_id: int,
        stop_signal: threading.Event,
        finish_signal: threading.Event,
        thread_count: int,
        project: Optional[Dict[str, object]] = None,
        exclusions: Optional[List[str]] = None,
        product_url_filters: Optional[List[str]] = None,
        product_url_exclusions: Optional[List[str]] = None,
        extraction_rules: Optional[Dict[str, str]] = None,
        connection_method: str = "requests",
        auto_connection_fallback: bool = True,
        connection_method_state: Optional[Dict[str, object]] = None,
        allow_empty_price: bool = False,
        browser_session: Optional[BotasaurusBrowserSession] = None,
        owns_browser_session: bool = True,
        profile_dir: Optional[Path] = None,
    ):
        from services.project_service import parse_thread_count
        self.run_id = run_id
        self.stop_signal = stop_signal
        self.finish_signal = finish_signal
        self.thread_count = parse_thread_count(thread_count)
        self.start_urls = normalize_start_urls(start_urls)
        self.start_url = self.start_urls[0]
        self.root_netloc = urlparse(self.start_url).netloc
        self.project = project
        self.exclusions = exclusions if exclusions is not None else DEFAULT_EXCLUSIONS.copy()
        self.extraction_rules = normalize_extraction_rules(extraction_rules or {})
        self.product_url_filters = product_url_filter_patterns(product_url_filters or [], self.extraction_rules)
        self.product_url_exclusions = normalize_patterns(product_url_exclusions or [])
        self.connection_method = normalize_connection_method(connection_method)
        self.auto_connection_fallback = bool(auto_connection_fallback)
        self.allow_empty_price = bool(allow_empty_price)
        self.profile_dir = profile_dir
        if connection_method_state is None:
            connection_method_state = {
                "active_method": self.connection_method,
                "lock": threading.Lock(),
            }
        else:
            connection_method_state.setdefault("active_method", self.connection_method)
            connection_method_state.setdefault("lock", threading.Lock())
        self.connection_method_state = connection_method_state
        self.active_connection_method = str(connection_method_state.get("active_method") or self.connection_method)
        debug_profile = str(profile_dir) if profile_dir is not None else "protected_sites_debug_visible"
        self.browser_session = browser_session or BotasaurusBrowserSession(
            self.stop_signal,
            self.thread_count,
            profile_dir=self.profile_dir,
        )
        self.debug_visible_session = BotasaurusDebugVisibleSession(self.stop_signal, debug_profile)
        self.owns_browser_session = owns_browser_session
        self.browser_sessions_lock = threading.Lock()
        self.browser_sessions: List[object] = []
        self.thread_local = threading.local()
        self.headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/124.0 Safari/537.36"
            ),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.8",
        }
        self.queue: Queue[str] = Queue()
        self.queued: Set[str] = set()
        self.in_progress: Set[str] = set()
        self.visited: Set[str] = set()
        self.skipped_urls: Set[str] = set()
        self.result_urls: Set[str] = set()
        self.pending_prices: Dict[str, str] = {}
        self.results: List[Dict[str, str]] = []
        self.failed_attempts: Dict[str, int] = {}
        self.permanent_failures: Set[str] = set()
        self.data_lock = threading.Lock()
        self.excel_finalized = False
        self.started_at = 0.0
        self.elapsed_before_resume = 0.0
        self.last_progress_at = time.time()
        self.last_progress_signature: tuple = ()
        self.fatal_error = ""

    def update_state(self, **kwargs: object) -> None:
        from services.project_service import update_project_state
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            update_project_state(self.project, **kwargs)
        else:
            update_state(self.run_id, **kwargs)

    def reset_state(self, status: str = "idle") -> None:
        from services.project_service import reset_project_state
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            reset_project_state(self.project, status)
        else:
            reset_state(status, self.run_id, self.thread_count)

    def log(self, message: str, level: str = "info") -> None:
        from services.project_service import add_project_log
        if self.project is not None:
            if self.run_id != int(self.project.get("run_id", self.run_id)):
                return
            add_project_log(self.project, message, level)

    def get_session(self) -> requests.Session:
        session = getattr(self.thread_local, "session", None)
        if session is None:
            session = requests.Session()
            session.headers.update(self.headers)
            self.thread_local.session = session
        return session

    def browser_session_for_worker(self) -> BotasaurusBrowserSession:
        return self.browser_session

    def debug_visible_session_for_worker(self) -> BotasaurusDebugVisibleSession:
        return self.debug_visible_session

    def close_browser_sessions(self) -> None:
        sessions: List[object] = []
        with self.browser_sessions_lock:
            for session in self.browser_sessions:
                if session not in sessions:
                    sessions.append(session)
            self.browser_sessions.clear()
        if self.owns_browser_session:
            if self.browser_session not in sessions:
                sessions.append(self.browser_session)
            if self.debug_visible_session not in sessions:
                sessions.append(self.debug_visible_session)
        for session in sessions:
            session.close()

    def fetch_with_requests(self, url: str) -> Optional[str]:
        last_error = ""
        candidate_urls = [url]
        for attempt in range(1, MAX_RETRIES + 1):
            if self.stop_signal.is_set():
                return None
            for candidate_url in candidate_urls:
                try:
                    response = self.get_session().get(candidate_url, timeout=REQUEST_TIMEOUT)
                    response.raise_for_status()
                    content_type = response.headers.get("content-type", "")
                    if "text/html" not in content_type and "application/xhtml" not in content_type:
                        return None
                    if not looks_blocked_or_empty(response.text):
                        return response.text

                    last_error = "страница похожа на блокировку или пустой JS-шаблон"
                    break
                except requests.RequestException as exc:
                    last_error = str(exc)
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {404, 410}:
                        with self.data_lock:
                            self.permanent_failures.add(url)
                        self.log(f"URL пропущен: страница вернула {exc.response.status_code}: {url}", "warning")
                        return None
                    if isinstance(exc, requests.HTTPError) and exc.response is not None and exc.response.status_code in {401, 403}:
                        continue
                    break
            if last_error == "страница похожа на блокировку или пустой JS-шаблон":
                break
            if self.stop_signal.is_set():
                return None
            if attempt < MAX_RETRIES:
                time.sleep(min(attempt, 3))
        if last_error:
            self.log(f"requests не смог загрузить {url}: {last_error}", "warning")
        return None

    def fetch_by_method(self, url: str, method: str) -> Optional[str]:
        target_url = url
        if method == "requests":
            return self.fetch_with_requests(target_url)
        if method == "botasaurus-request":
            return fetch_with_botasaurus_request(target_url)
        if method in {"botasaurus-browser", "botasaurus-browser-direct", "botasaurus-visible", "playwright"}:
            return self.browser_session_for_worker().fetch(
                target_url,
                method,
                self.extraction_rules,
                self.product_url_filters,
                self.allow_empty_price,
            )
        if method == "botasaurus-debug-visible":
            return self.debug_visible_session_for_worker().fetch(target_url, method)
        if method in SESSION_BROWSER_METHODS:
            return self.browser_session_for_worker().fetch(
                target_url,
                method,
                self.extraction_rules,
                self.product_url_filters,
                self.allow_empty_price,
            )
        if method == "crawl4ai":
            return fetch_with_crawl4ai(target_url)
        if method == "scrapegraphai":
            return fetch_with_scrapegraphai(target_url)
        if method == "scrapy":
            return fetch_with_scrapy(target_url)
        if method == "crawlee":
            return fetch_with_crawlee(target_url)
        return None

    def fetch_by_method_with_timeout(self, url: str, method: str) -> Optional[str]:
        if is_browser_render_method(method) or is_debug_visible_method(method):
            try:
                return self.fetch_by_method(url, method)
            except Exception as error:
                self.log(f"Метод подключения {method} завершился ошибкой для {url}: {error}", "warning")
                return None

        result_queue: Queue = Queue(maxsize=1)

        def run_method() -> None:
            try:
                result_queue.put(("ok", self.fetch_by_method(url, method)), block=False)
            except Exception as error:
                result_queue.put(("error", error), block=False)

        thread = threading.Thread(target=run_method, daemon=True)
        thread.start()
        try:
            status, value = result_queue.get(timeout=CONNECTION_METHOD_TIMEOUT_SECONDS)
        except Empty:
            self.log(
                f"Метод подключения {method} превысил таймаут {CONNECTION_METHOD_TIMEOUT_SECONDS} сек. для {url}",
                "warning",
            )
            return None
        if status == "error":
            self.log(f"Метод подключения {method} завершился ошибкой для {url}: {value}", "warning")
            return None
        return value if isinstance(value, str) else None

    def fallback_method_sequence(self) -> List[str]:
        """Возвращает fallback-методы из БД без схлопывания разных браузерных движков."""
        methods: List[str] = []
        for method in ordered_db_connection_methods():
            # Видимый debug-браузер не запускаем автоматически, только если выбран явно.
            if is_debug_visible_method(method) and method != self.connection_method:
                continue
            if method not in methods:
                methods.append(method)
        return methods

    def current_connection_method(self) -> str:
        lock = self.connection_method_state["lock"]
        with lock:
            current = normalize_connection_method(self.connection_method_state.get("active_method"))
            self.connection_method_state["active_method"] = current
            self.active_connection_method = current
            return current

    def set_active_connection_method(self, method: str) -> None:
        previous = self.active_connection_method
        lock = self.connection_method_state["lock"]
        with lock:
            current = normalize_connection_method(method)
            self.connection_method_state["active_method"] = current
            self.active_connection_method = current
        if current != previous and self.owns_browser_session:
            self.close_browser_sessions()
            self.browser_session = BotasaurusBrowserSession(
                self.stop_signal,
                self.thread_count,
                profile_dir=self.profile_dir,
            )
            self.debug_visible_session = BotasaurusDebugVisibleSession(
                self.stop_signal,
                str(self.profile_dir) if self.profile_dir is not None else "protected_sites_debug_visible",
            )

    def fetch_with_connection_method(self, url: str, method: str) -> Optional[str]:
        from services.log_service import log_fetch_result
        self.last_progress_at = time.time()
        self.log(f"Пробую метод подключения {method} для {url}", "info")
        started = time.time()
        html = self.fetch_by_method_with_timeout(url, method)
        self.last_progress_at = time.time()
        if html:
            log_fetch_result(method, url, html, time.time() - started)
        if html and not looks_blocked_or_empty(html):
            return html
        self.log(f"Метод подключения {method} не сработал для {url}", "warning")
        return None

    def fetch(self, url: str) -> Optional[str]:
        current_method = self.current_connection_method()
        last_method = current_method

        if self.stop_signal.is_set():
            return None

        html = self.fetch_with_connection_method(url, current_method)
        if html:
            return html

        with self.data_lock:
            if url in self.permanent_failures:
                return None

        if not self.auto_connection_fallback:
            self.update_state(
                error=(
                    f"Не удалось загрузить {url}. Последний метод: {last_method}. "
                    "Проверьте способ подключения или включите автопереключение."
                ),
            )
            self.log(f"Не удалось загрузить {url}. Последний метод: {last_method}", "error")
            return None

        for method in self.fallback_method_sequence():
            if self.stop_signal.is_set():
                return None
            if method == current_method:
                continue
            last_method = method
            html = self.fetch_with_connection_method(url, method)
            if html:
                if method != current_method:
                    self.set_active_connection_method(method)
                    self.log(f"Автопереключение подключения: {method} для {url}", "warning")
                return html
            with self.data_lock:
                if url in self.permanent_failures:
                    break

        self.update_state(
            error=(
                f"Не удалось загрузить {url}. Последний метод: {last_method}. "
                "Проверьте способ подключения или включите автопереключение."
            ),
        )
        self.log(f"Не удалось загрузить {url}. Последний метод: {last_method}", "error")
        return None

    def is_excluded(self, url: str) -> bool:
        patterns = self.exclusions

        matched = any(exclusion_matches(url, pattern) for pattern in patterns)
        if matched and url not in self.skipped_urls:
            with self.data_lock:
                self.skipped_urls.add(url)
                skipped_count = len(self.skipped_urls)
            self.update_state(skipped=skipped_count)
        return matched

    def is_product_allowed(self, url: str) -> bool:
        return product_url_matches_filters(url, self.product_url_filters) and not product_url_matches_any(url, self.product_url_exclusions)

    def is_filter_marked_product(self, url: str) -> bool:
        return bool(self.product_url_filters) and self.is_product_allowed(url)

    def is_product_url(self, url: str) -> bool:
        return is_product_url_for_filters(url, self.product_url_filters)

    def is_start_url_path(self, url: str) -> bool:
        parsed = urlparse(url)
        normalized_path = (parsed.path or "/").rstrip("/") or "/"
        for start_url in self.start_urls:
            start_parsed = urlparse(start_url)
            if not same_site(url, start_parsed.netloc or self.root_netloc):
                continue
            start_path = (start_parsed.path or "/").rstrip("/") or "/"
            if normalized_path == start_path:
                return True
        return False

    def is_current_product_page(self, url: str) -> bool:
        return self.is_product_url(url) and self.is_product_allowed(url) and not self.is_start_url_path(url)

    def remember_listing_price(self, product_url: str, price: str) -> None:
        product_url = canonicalize_product_url_by_filters(product_url, self.product_url_filters)
        with self.data_lock:
            if product_url and price:
                self.pending_prices[product_url] = price

    def get_listing_price(self, product_url: str) -> str:
        product_url = canonicalize_product_url_by_filters(product_url, self.product_url_filters)
        with self.data_lock:
            return self.pending_prices.get(product_url, "")

    def enqueue(self, url: Optional[str], force: bool = False) -> None:
        url = canonicalize_product_url_by_filters(url or "", self.product_url_filters)
        if not url or url in self.visited or url in self.queued or url in self.in_progress:
            return
        is_product = self.is_product_url(url)
        if is_product and not self.is_product_allowed(url):
            return
        with self.data_lock:
            if url in self.result_urls:
                return
        if not force:
            if is_product:
                if not same_site(url, self.root_netloc) or has_static_extension(url):
                    return
            elif not should_follow_project_url(url, self.start_urls, self.root_netloc):
                return
        if force and (not same_site(url, self.root_netloc) or has_static_extension(url)):
            return
        if self.is_excluded(url):
            return
        self.queue.put(url)
        self.queued.add(url)

    def requeue_pending(self, pending_urls: Iterable[str]) -> None:
        with self.data_lock:
            for url in pending_urls:
                self.in_progress.discard(url)
        for url in pending_urls:
            self.enqueue(url, force=True)

    def extract_links(self, html: str, current_url: str) -> None:
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.select("a[href]"):
            normalized = normalize_url(link.get("href", ""), current_url)
            self.enqueue(normalized)

    def add_products(self, products: Iterable[Dict[str, str]]) -> int:
        added = 0
        with self.data_lock:
            for product in products:
                product_url = canonicalize_product_url_by_filters(product.get("url", ""), self.product_url_filters)
                model = product.get("model", "")
                price = product.get("price", "")
                if product_url and not self.is_product_allowed(product_url):
                    continue
                if not product_url or not model or (not price and not self.allow_empty_price) or product_url in self.result_urls:
                    continue
                product["url"] = product_url
                self.result_urls.add(product_url)
                self.results.append(product)
                added += 1
        return added

    def snapshot_counts(self) -> Dict[str, int]:
        with self.data_lock:
            return {
                "visited": len(self.visited),
                "results": len(self.results),
                "skipped": len(self.skipped_urls),
                "queued": self.queue.qsize(),
                "active": len(self.in_progress),
                "failed": len(self.failed_attempts),
            }

    def snapshot_results(self) -> List[Dict[str, str]]:
        with self.data_lock:
            return [dict(item) for item in self.results]

    def refresh_progress(self, current_url: str = "") -> None:
        remaining = self.queue.qsize()
        counts = self.snapshot_counts()
        processed = counts["visited"]
        total_known = processed + remaining
        percent = int((processed / total_known) * 100) if total_known else 0
        elapsed = self.elapsed_seconds()
        self.update_state(
            percent=percent,
            currenturl=current_url,
            totalprocessed=processed,
            processed_products=counts["results"],
            found_products=counts["results"],
            in_memory_products=counts["results"],
            queue_size=remaining,
            active_tasks=counts["active"],
            active_urls=sorted(self.in_progress)[:8],
            failed_pages=counts["failed"],
            stall_seconds=max(0, int(time.time() - self.last_progress_at)),
            skipped=counts["skipped"],
            thread_count=self.thread_count,
            elapsed_seconds=int(elapsed),
        )

    def progress_signature(self, pending_urls: Iterable[str]) -> tuple:
        counts = self.snapshot_counts()
        return (
            counts["visited"],
            counts["results"],
            counts["skipped"],
            self.queue.qsize(),
            tuple(sorted(pending_urls)),
        )

    def note_progress_activity(self, pending_urls: Iterable[str]) -> None:
        signature = self.progress_signature(pending_urls)
        if signature != self.last_progress_signature:
            self.last_progress_signature = signature
            self.last_progress_at = time.time()

    def mark_stalled(self, pending_urls: Iterable[str]) -> None:
        active_urls = list(pending_urls)
        counts = self.snapshot_counts()
        message = (
            f"Сбор не двигается {NEWS_SCAN_STALL_TIMEOUT} секунд. "
            f"Активных задач: {len(active_urls)}; очередь: {self.queue.qsize()}; "
            f"товаров в памяти: {counts['results']}. "
            f"Активные URL: {', '.join(active_urls[:5])}"
        )
        self.fatal_error = message
        self.update_state(
            status="error",
            error=message,
            currenturl=active_urls[0] if active_urls else "",
            active_urls=active_urls[:8],
            active_tasks=len(active_urls),
            queue_size=self.queue.qsize(),
            in_memory_products=counts["results"],
            stall_seconds=NEWS_SCAN_STALL_TIMEOUT,
        )
        self.log(message, "error")
        self.stop_signal.set()

    def elapsed_seconds(self) -> float:
        if self.started_at:
            return self.elapsed_before_resume + max(0.0, time.time() - self.started_at)
        return self.elapsed_before_resume

    def process_page(self, url: str, html: str) -> None:
        current_is_product = self.is_current_product_page(url)
        listing_products: List[Dict[str, str]] = []
        listing_price = self.get_listing_price(url)

        if current_is_product:
            product = extract_product_data(
                url,
                html,
                listing_price,
                self.extraction_rules,
                assume_product=True,
                allow_empty_price=self.allow_empty_price,
            )
            if product:
                self.add_products([product])
                return

            current_is_product = False

        listing_products = extract_listing_products(url, html, self.extraction_rules, self.product_url_filters)

        if (
            self.current_connection_method() != "requests"
            and not current_is_product
            and not listing_products
            and (is_catalog_url(url) or not self.is_product_url(url))
        ):
            self.update_state(
                error=f"На странице каталога не извлечены товары. Рендерю через браузер: {url}",
            )
            self.log(f"Рендеринг каталога через браузер: {url}", "warning")
            rendered_html = self.browser_session.fetch(
                url,
                "protected-site",
                self.extraction_rules,
                self.product_url_filters,
                self.allow_empty_price,
            )
            if rendered_html and not looks_blocked_or_empty(rendered_html):
                html = rendered_html
                listing_products = extract_listing_products(url, html, self.extraction_rules, self.product_url_filters)
                self.update_state(error="")

        for product in listing_products:
            product_url = canonicalize_product_url_by_filters(product.get("url", ""), self.product_url_filters)
            if product_url and not self.is_product_allowed(product_url):
                continue
            product["url"] = product_url
            self.remember_listing_price(product_url, product.get("price", ""))
            self.enqueue(product_url, force=True)
        if not self.product_url_filters and not has_explicit_model_rules(self.extraction_rules):
            self.add_products(listing_products)

        should_extract_current_product = (
            not self.is_start_url_path(url)
            and (not listing_products or bool(self.get_listing_price(url)))
        )
        product = None if not should_extract_current_product else extract_product_data(
            url,
            html,
            self.get_listing_price(url),
            self.extraction_rules,
            assume_product=self.is_product_url(url),
            allow_empty_price=self.allow_empty_price,
        )
        if product:
            self.add_products([product])

        if not current_is_product:
            self.extract_links(html, url)

    def finish_with_excel(self, partial: bool = False) -> None:
        from services.project_service import create_export_file, delete_project_csv_for_project, save_projects
        with self.data_lock:
            if self.excel_finalized:
                return
            self.excel_finalized = True

        rows = self.snapshot_results()
        counts = self.snapshot_counts()
        filename = create_export_file(rows, self.project)
        if self.project is not None:
            delete_project_csv_for_project(self.project, keep_filename=filename.name)
        final_error = ""
        if partial:
            final_error = "Сбор приостановлен. CSV сформирован по уже найденным товарам."
        elif not self.results:
            final_error = (
                "Сбор завершен, но товары не найдены. Проверьте стартовый URL и исключения; "
                "для защищенных страниц убедитесь, что Botasaurus установился через run.ps1."
            )

        self.update_state(
            status="partial" if partial else "completed",
            percent=100 if not partial else int((self.project or {}).get("state", {}).get("percent", 0) or 0),
            currenturl="",
            totalprocessed=counts["visited"],
            processed_products=counts["results"],
            found_products=counts["results"],
            skipped=counts["skipped"],
            download_ready=True,
            download_url="/download",
            filename=filename.name,
            error=final_error,
            thread_count=self.thread_count,
            elapsed_seconds=int(self.elapsed_seconds()),
            finished_at=now_iso() if not partial else "",
            paused_with_result=partial,
        )
        self.log(f"CSV сформирован: {filename.name}. Товаров: {counts['results']}", "success")
        if self.project is not None:
            save_projects()

    def run(self, resume: bool = False) -> None:
        if not self.started_at:
            self.started_at = time.time()
        self.update_state(
            status="running",
            thread_count=self.thread_count,
            started_at=(self.project or {}).get("state", {}).get("started_at") or now_iso(),
            paused_with_result=False,
        )
        self.log("Сбор продолжен" if resume else "Сбор запущен", "info")
        if not resume:
            for start_url in self.start_urls:
                self.enqueue(start_url)

        executor = ThreadPoolExecutor(max_workers=self.thread_count)
        pending = {}
        pending_urls_to_requeue = []
        self.note_progress_activity([])

        try:
            while not self.stop_signal.is_set():
                while len(pending) < self.thread_count:
                    try:
                        url = self.queue.get_nowait()
                    except Empty:
                        break

                    self.queued.discard(url)
                    if url in self.visited or url in self.in_progress:
                        continue
                    with self.data_lock:
                        if url in self.result_urls and self.is_product_url(url):
                            continue
                    self.in_progress.add(url)
                    self.update_state(
                        currenturl=url,
                        active_urls=sorted(self.in_progress)[:8],
                        active_tasks=len(self.in_progress),
                        queue_size=self.queue.qsize(),
                    )
                    pending[executor.submit(self.fetch, url)] = url
                    self.note_progress_activity(pending.values())
                    time.sleep(REQUEST_DELAY_SECONDS)

                if not pending:
                    if self.queue.empty():
                        break
                    continue

                done, _pending = wait(pending.keys(), timeout=0.5, return_when=FIRST_COMPLETED)
                if not done:
                    self.refresh_progress()
                    self.note_progress_activity(pending.values())
                    if pending and time.time() - self.last_progress_at >= NEWS_SCAN_STALL_TIMEOUT:
                        self.mark_stalled(pending.values())
                    continue

                for future in done:
                    url = pending.pop(future)
                    self.note_progress_activity(pending.values())
                    with self.data_lock:
                        self.in_progress.discard(url)
                        self.visited.add(url)
                    html = None
                    try:
                        html = future.result()
                    except Exception as exc:  # noqa: BLE001 - ошибку показываем в интерфейсе.
                        self.update_state(error=f"Ошибка обработки {url}: {exc}")
                        self.log(f"Ошибка обработки {url}: {exc}", "error")

                    if html and not self.stop_signal.is_set():
                        self.process_page(url, html)
                    elif not self.stop_signal.is_set():
                        with self.data_lock:
                            permanent_failure = url in self.permanent_failures
                        if permanent_failure:
                            self.log(f"URL пропущен без повторов: {url}", "warning")
                            self.refresh_progress(url)
                            continue
                        retry_count = self.failed_attempts.get(url, 0) + 1
                        self.failed_attempts[url] = retry_count
                        if retry_count <= 2:
                            with self.data_lock:
                                self.visited.discard(url)
                            self.enqueue(url, force=True)
                            self.log(f"Повторная попытка загрузки {retry_count}/2: {url}", "warning")
                        else:
                            self.log(f"URL пропущен после повторных попыток загрузки: {url}", "error")

                    self.refresh_progress(url)
        finally:
            if self.stop_signal.is_set():
                pending_urls_to_requeue = list(pending.values())
                self.requeue_pending(pending_urls_to_requeue)
            executor.shutdown(wait=False, cancel_futures=True)
            self.close_browser_sessions()

        if self.stop_signal.is_set():
            self.elapsed_before_resume = self.elapsed_seconds()
            self.started_at = 0.0
            if self.fatal_error:
                self.update_state(
                    status="error",
                    currenturl="",
                    active_urls=[],
                    active_tasks=0,
                    queue_size=self.queue.qsize(),
                    elapsed_seconds=int(self.elapsed_before_resume),
                    error=self.fatal_error,
                )
                return
            stop_mode = str((self.project or {}).get("stop_mode") or "")
            if self.finish_signal.is_set():
                self.finish_with_excel(partial=True)
            elif stop_mode == "pause":
                self.update_state(
                    status="paused",
                    currenturl="",
                    elapsed_seconds=int(self.elapsed_before_resume),
                    error="Сбор на паузе",
                )
                if (self.project or {}).get("state", {}).get("status") == "paused":
                    self.log("Сбор поставлен на паузу", "warning")
            else:
                self.update_state(
                    status="idle",
                    currenturl="",
                    active_urls=[],
                    active_tasks=0,
                    queue_size=0,
                    elapsed_seconds=int(self.elapsed_before_resume),
                    error="",
                    paused_with_result=False,
                )
                if stop_mode == "stop":
                    self.log("Сбор остановлен", "warning")
            return

        self.elapsed_before_resume = self.elapsed_seconds()
        self.started_at = 0.0
        self.finish_with_excel()


__all__ = ['BotasaurusBrowserSession', 'BotasaurusDebugVisibleSession', 'PlaywrightHeadlessRenderer', 'ProductSiteCrawler', 'apply_extract_regex', 'apply_replace_rules', 'canonicalize_product_url_by_filters', 'clean_text', 'exclusion_matches', 'extract_between_markers', 'extract_listing_products', 'extract_listing_products_by_rules', 'extract_model_by_markers', 'extract_price_from_container', 'extract_prices', 'extract_product_data', 'extract_product_data_by_rules', 'fetch_with_botasaurus_browser', 'fetch_with_botasaurus_debug_visible_browser', 'fetch_with_botasaurus_request', 'fetch_with_botasaurus_visible_browser', 'fetch_with_crawl4ai', 'fetch_with_crawlee', 'fetch_with_playwright', 'fetch_with_python_engine', 'fetch_with_scrapegraphai', 'fetch_with_scrapy', 'finalize_scraped_model', 'first_by_selector', 'first_text', 'has_configured_model_source', 'has_explicit_model_rules', 'has_model_replace_rules', 'has_static_extension', 'is_catalog_url', 'is_domain_url', 'is_obvious_service_path', 'is_product_url_for_filters', 'known_brand_regex', 'looks_blocked_or_empty', 'model_brand_names', 'normalize_model', 'normalize_price_value', 'normalize_url', 'prepare_rule_model', 'product_url_filter_patterns', 'product_url_matches_any', 'product_url_matches_filters', 'replacement_flags', 'same_site', 'should_accept_extracted_product', 'should_follow_project_url', 'should_follow_url', 'split_text_lines', 'strip_html_to_text', 'wildcard_rule_to_regex']
