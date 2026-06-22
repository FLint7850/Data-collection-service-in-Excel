"""HTML/JSON-LD product extraction and replacement rules."""



from parser_app.runtime import *  # noqa: F401,F403



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

def jsonld_items(soup: BeautifulSoup) -> Iterable[Any]:
    for script in soup.select("script[type='application/ld+json']"):
        raw = script.string or script.get_text("", strip=True)
        if not raw:
            continue
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            continue
        if isinstance(data, list):
            for item in data:
                yield item
        else:
            yield data

def iter_json_nodes(value: Any) -> Iterable[Dict[str, Any]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from iter_json_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from iter_json_nodes(child)

def type_contains(value: Any, expected: str) -> bool:
    if isinstance(value, str):
        return value.lower() == expected.lower()
    if isinstance(value, list):
        return any(type_contains(item, expected) for item in value)
    return False

def extract_offer_price(offers: Any) -> str:
    for offer in iter_json_nodes(offers):
        for key in ("price", "lowPrice", "highPrice"):
            price = normalize_price_value(offer.get(key))
            if price:
                return price
    return ""

def extract_schema_product(
    soup: BeautifulSoup,
    url: str,
    fallback_price: str = "",
    allow_empty_price: bool = False,
) -> Optional[Dict[str, str]]:
    for item in jsonld_items(soup):
        for node in iter_json_nodes(item):
            if not type_contains(node.get("@type"), "Product"):
                continue
            model = clean_text(str(node.get("model") or node.get("sku") or node.get("name") or ""))
            price = extract_offer_price(node.get("offers")) or fallback_price
            item_url = normalize_url(str(node.get("url") or ""), url) or url
            if model and (price or allow_empty_price):
                return {"url": item_url, "model": normalize_model(model, item_url), "price": price}
    return None

def extract_schema_listing_products(soup: BeautifulSoup, current_url: str) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    seen_urls: Set[str] = set()
    for item in jsonld_items(soup):
        for node in iter_json_nodes(item):
            if not type_contains(node.get("@type"), "Product"):
                continue
            product_url = normalize_url(str(node.get("url") or ""), current_url) or ""
            if product_url and not is_probable_product_url(product_url):
                product_url = ""
            model = clean_text(str(node.get("model") or node.get("sku") or node.get("name") or ""))
            price = extract_offer_price(node.get("offers"))
            if not product_url or not model or not price or product_url in seen_urls:
                continue
            seen_urls.add(product_url)
            products.append({"url": product_url, "model": normalize_model(model, product_url), "price": price})
    return products

def find_labeled_value(soup: BeautifulSoup, labels: Iterable[str]) -> str:
    """Ищет значение рядом с подписью вроде 'Артикул' или 'Модель'."""
    label_regex = re.compile("|".join(re.escape(label) for label in labels), re.IGNORECASE)

    for row in soup.select("tr, li, .row, .item, .chars__item, .characteristics__item"):
        row_text = clean_text(row.get_text(" ", strip=True))
        if not label_regex.search(row_text):
            continue

        value_node = row.select_one(".val, .value, td:last-child, span:last-child, div:last-child")
        if value_node:
            value = clean_text(value_node.get_text(" ", strip=True))
            value = label_regex.sub("", value).strip(" :—-")
            if value:
                return value

        value = label_regex.sub("", row_text).strip(" :—-")
        if value:
            return value

    page_text = clean_text(soup.get_text(" ", strip=True))
    match = re.search(r"(?:Артикул|Модель|Art:)\s*[:\-]?\s*([A-Za-z\u0400-\u04FF0-9][^|]{1,80})", page_text)
    if match:
        return clean_text(match.group(1)).split(" В наличии")[0].strip()

    return ""

def extract_labeled_model_value(soup: BeautifulSoup) -> str:
    """Ищет модель/артикул в характеристиках без привязки к конкретному бренду."""
    labels = (
        "модель",
        "артикул",
        "sku",
        "код модели",
        "model",
        "article",
        "art.",
    )
    label_regex = re.compile(r"^(?:" + "|".join(re.escape(label) for label in labels) + r")\b", re.IGNORECASE)

    for row in soup.select("li, tr, .item, .features-grid__item, .characteristics__item, .chars__item, .row"):
        name_node = row.select_one(".name, .label, .title, td:first-child, th:first-child")
        value_node = row.select_one(".val, .value, td:last-child, span:last-child, div:last-child")
        if name_node and value_node:
            name = clean_text(name_node.get_text(" ", strip=True)).strip(" :—-")
            value = clean_text(value_node.get_text(" ", strip=True)).strip(" :—-")
            if label_regex.search(name) and value and not PRICE_RE.search(value):
                return value

        row_text = clean_text(row.get_text(" ", strip=True))
        if not label_regex.search(row_text):
            continue

        value = label_regex.sub("", row_text).strip(" :—-")
        if value and not PRICE_RE.search(value):
            return value

    page_lines = split_text_lines(soup.get_text("\n", strip=True))
    for line in page_lines:
        if label_regex.search(line):
            value = label_regex.sub("", line).strip(" :—-")
            if value and not PRICE_RE.search(value):
                return value

    return ""

def extract_price(soup: BeautifulSoup, allow_page_fallback: bool = True) -> str:
    meta_price = soup.select_one(
        '[itemprop="price"], meta[property="product:price:amount"], meta[property="og:price:amount"]'
    )
    if meta_price:
        value = meta_price.get("content") or meta_price.get("value") or meta_price.get_text(" ", strip=True)
        if value:
            return normalize_price_value(value)

    price = first_text(
        soup,
        [
            "span.price--detail .nobr",
            ".price--detail .nobr",
            ".price.price--detail",
            ".product-detail .price",
            ".detail .price",
            ".product-price",
            ".price-current",
            "[class*='current-price']",
            "[class*='product-price']",
            "[class*='price--detail']",
        ],
    )
    if price:
        match = PRICE_RE.search(price)
        return clean_text(match.group(0) if match else price)

    if not allow_page_fallback:
        return ""

    page_text = clean_text(soup.get_text(" ", strip=True))
    match = PRICE_RE.search(page_text)
    return clean_text(match.group(0)) if match else ""

def is_probable_product_url(url: str) -> bool:
    return looks_like_product_path(urlparse(url).path)

def find_card_container(price_node, current_url: str) -> Optional[object]:
    """Находит ближайший контейнер карточки товара вокруг цены."""
    node = price_node if hasattr(price_node, "select") else price_node.parent
    best = None
    for _ in range(10):
        if not node or getattr(node, "name", None) in {"body", "html"}:
            break

        text = clean_text(node.get_text(" ", strip=True))
        links = node.select("a[href]") if hasattr(node, "select") else []
        images = node.select("img") if hasattr(node, "select") else []
        product_links = [
            link
            for link in links
            if is_probable_product_url(normalize_url(link.get("href", ""), current_url) or "")
        ]

        if len(text) <= 1800 and (product_links or images):
            best = node
            if product_links:
                break
        node = node.parent
    return best

def extract_model_from_card(card, price: str) -> str:
    title_selectors = [
        "[class*='name']",
        "[class*='title']",
        "[class*='product'] a",
        "a[href*='/catalog/']",
    ]
    for selector in title_selectors:
        for node in card.select(selector):
            text = clean_text(node.get_text(" ", strip=True))
            if is_good_model_text(text):
                return text

    ignored = {
        "онлайн",
        "распродажа",
        "новинка",
        "сделано в европе",
        "кухонным студиям",
        "в наличии",
        "нет в наличии",
        "по умолчанию",
        "по популярности",
    }
    lines = split_text_lines(card.get_text("\n", strip=True))
    lines = [
        line
        for line in lines
        if line.lower() not in ignored and not PRICE_RE.search(line) and line != price
    ]

    for line in lines:
        if is_good_model_text(line):
            return line

    return ""

def is_good_model_text(text: str) -> bool:
    text = clean_text(text)
    if len(text) < 8 or len(text) > 180:
        return False
    lowered = text.lower()
    if lowered in {
        "в наличии",
        "нет в наличии",
        "онлайн",
        "распродажа",
        "новинка",
        "купить",
        "подробнее",
    }:
        return False
    if PRICE_RE.search(text):
        return False
    return bool(re.search(r"[A-Z\u0400-\u04FF]{2,}[\w.\-/]*\d", text, re.IGNORECASE))

def extract_product_url_from_card(card, current_url: str, product_url_filters: Optional[Iterable[str]] = None) -> str:
    filters = list(product_url_filters or [])
    for link in card.select("a[href]"):
        normalized = canonicalize_product_url_by_filters(normalize_url(link.get("href", ""), current_url), filters)
        if normalized and is_product_url_for_filters(normalized, filters):
            return normalized
    return current_url

def find_card_container_from_link(link, current_url: str, product_url_filters: Optional[Iterable[str]] = None) -> Optional[object]:
    node = link
    best = None
    filters = list(product_url_filters or [])
    target_url = canonicalize_product_url_by_filters(normalize_url(link.get("href", ""), current_url), filters)
    for _ in range(10):
        if not node or getattr(node, "name", None) in {"body", "html"}:
            break
        if not hasattr(node, "select"):
            node = node.parent
            continue

        text = clean_text(node.get_text(" ", strip=True))
        links = [
            item
            for item in node.select("a[href]")
            if is_product_url_for_filters(
                canonicalize_product_url_by_filters(normalize_url(item.get("href", ""), current_url), filters),
                filters,
            )
        ]
        same_product_links = [
            item
            for item in links
            if canonicalize_product_url_by_filters(normalize_url(item.get("href", ""), current_url), filters) == target_url
        ]
        class_text = " ".join(node.get("class", [])) if hasattr(node, "get") else ""
        if same_product_links and (getattr(node, "name", None) == "article" or "product-card" in class_text):
            return node
        if extract_price_from_container(node) and len(text) <= 2200 and links:
            best = node
            if same_product_links and len({normalize_url(item.get("href", ""), current_url) for item in links}) <= 3:
                break
        node = node.parent
    return best

def extract_listing_products_from_links(
    soup: BeautifulSoup,
    current_url: str,
    seen_urls: Set[str],
    product_url_filters: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    filters = list(product_url_filters or [])
    products: List[Dict[str, str]] = []
    for link in soup.select("a[href]"):
        product_url = canonicalize_product_url_by_filters(normalize_url(link.get("href", ""), current_url), filters)
        if not product_url or not is_product_url_for_filters(product_url, filters) or product_url in seen_urls:
            continue

        card = find_card_container_from_link(link, current_url, filters)
        if not card:
            continue
        price = extract_price_from_container(card)
        if not price:
            continue
        model_source = clean_text(link.get_text(" ", strip=True)) or extract_model_from_card(card, price)
        model = normalize_model(model_source, product_url)
        if not model:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})

    return products

def decode_script_text(value: str) -> str:
    text = html_lib.unescape(value or "")
    text = text.replace("\\/", "/").replace("\\u002F", "/").replace("\\u002f", "/")
    if "\\u" in text:
        try:
            text = text.encode("utf-8", errors="ignore").decode("unicode_escape", errors="ignore")
        except UnicodeError:
            pass
    return text

def extract_price_near_text(value: str) -> str:
    price_match = PRICE_RE.search(value)
    if price_match:
        return clean_text(price_match.group(0))

    for key in ("price", "currentPrice", "actualPrice", "value"):
        match = re.search(rf'"{key}"\s*:\s*"?(\d{{3,9}})"?', value, re.IGNORECASE)
        if match:
            return normalize_price_value(match.group(1))
    return ""

def extract_name_near_text(value: str) -> str:
    for key in ("name", "title", "productName"):
        matches = re.findall(rf'"{key}"\s*:\s*"([^"]{{3,220}})"', value, flags=re.IGNORECASE)
        for match in matches:
            text = clean_text(html_lib.unescape(match))
            if is_good_model_text(text) or normalize_model(text):
                return text
    return ""

def extract_listing_products_from_scripts(
    soup: BeautifulSoup,
    current_url: str,
    seen_urls: Set[str],
    product_url_filters: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    filters = list(product_url_filters or [])
    product_url_re = re.compile(
        r'(?:https?://[^"\'<>\s]+)?/[^"\'<>\s]+(?:goods?_\d+|[a-z0-9][a-z0-9_-]*\d[a-z0-9_-]*)(?:\.html)?/?',
        re.IGNORECASE,
    )

    for script in soup.select("script"):
        raw = script.string or script.get_text("", strip=False)
        if not raw:
            continue
        text = decode_script_text(raw)
        if not text or "price" not in text.lower():
            continue

        for match in product_url_re.finditer(text):
            product_url = normalize_url(match.group(0), current_url)
            product_url = canonicalize_product_url_by_filters(product_url or "", filters)
            if not product_url or not is_product_url_for_filters(product_url, filters) or product_url in seen_urls:
                continue

            left = max(0, match.start() - 2500)
            right = min(len(text), match.end() + 2500)
            window = text[left:right]
            price = extract_price_near_text(window)
            name = extract_name_near_text(window)
            model = normalize_model(name, product_url)
            if not price or not model:
                continue

            seen_urls.add(product_url)
            products.append({"url": product_url, "model": model, "price": price})

    return products

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
    if selector:
        selected = first_by_selector(container, selector)
        selected_price = (extract_prices(selected) or [normalize_price_value(selected)])[0]
        if selected_price:
            return selected_price

    for node in container.select("[class*='price'], [class*='cost'], [itemprop='price']"):
        text = clean_text(node.get("content") or node.get("value") or node.get_text(" ", strip=True))
        if not text or len(text) > 120:
            continue
        price = (extract_prices(text) or [normalize_price_value(text)])[0]
        if price:
            return price

    prices = extract_prices(container.get_text(" ", strip=True))
    return prices[-1] if prices else ""

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
    use_url_selector = bool(url_selector) and not product_url_filter_patterns([], {"product_url_selector": url_selector})
    for card in cards:
        link_node = None
        if use_url_selector:
            try:
                link_node = card.select_one(url_selector)
            except Exception:
                link_node = None
        if not link_node:
            link_node = card.select_one("a[href]")
        product_url = canonicalize_product_url_by_filters(normalize_url(link_node.get("href", "") if link_node else "", current_url), filters)
        if not product_url or product_url in seen_urls or not is_product_url_for_filters(product_url, filters):
            continue
        card_product_urls = {
            canonicalize_product_url_by_filters(normalize_url(link.get("href", ""), current_url), filters)
            for link in card.select("a[href]")
        }
        card_product_urls = {
            item for item in card_product_urls if item and is_product_url_for_filters(item, filters)
        }
        if len(card_product_urls) > 1:
            continue

        model = extract_model_by_markers(str(card), rules)
        if not model:
            model = first_by_selector(card, rules.get("model_selector", ""))
        if not model:
            model = extract_model_from_card(card, "")
        model = prepare_rule_model(model, rules)
        model = normalize_model(model, product_url)

        price = extract_price_from_container(card, rules.get("price_selector", ""))
        if not model or not price:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})
    return products

def extract_listing_products_from_common_cards(
    soup: BeautifulSoup,
    current_url: str,
    rules: Dict[str, str],
    seen_urls: Set[str],
    product_url_filters: Optional[Iterable[str]] = None,
) -> List[Dict[str, str]]:
    products: List[Dict[str, str]] = []
    filters = list(product_url_filters or [])
    card_selectors = [
        ".catalog-card.js-ecom_product-item",
        ".js-ecom_product-item",
        "[class*='product-item']",
        "[class*='product-card']",
    ]
    cards = []
    seen_card_ids: Set[int] = set()
    for selector in card_selectors:
        for card in soup.select(selector):
            if id(card) in seen_card_ids:
                continue
            seen_card_ids.add(id(card))
            cards.append(card)

    for card in cards:
        product_url = extract_product_url_from_card(card, current_url, filters)
        if not product_url or product_url in seen_urls or not is_product_url_for_filters(product_url, filters):
            continue

        price = extract_price_from_container(card, rules.get("price_selector", ""))
        if not price:
            continue

        model = extract_model_by_markers(str(card), rules)
        if not model:
            model = first_by_selector(card, rules.get("model_selector", ""))
        if not model:
            title_link = None
            for link in card.select("a[title][href]"):
                if normalize_url(link.get("href", ""), current_url) == product_url:
                    title_link = link
                    break
            if title_link is None:
                title_link = card.select_one("a[title][href]")
            model = title_link.get("title", "") if title_link else ""
        if not model:
            model = extract_model_from_card(card, price)
        model = prepare_rule_model(model, rules)
        model = normalize_model(model, product_url)
        if not model:
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
    products: List[Dict[str, str]] = extract_schema_listing_products(soup, current_url)
    price_sources = []
    seen_urls: Set[str] = {product["url"] for product in products}
    seen_source_ids: Set[int] = set()
    rules = normalize_extraction_rules(rules or {})
    filters = product_url_filter_patterns(product_url_filters or [], rules)

    products.extend(extract_listing_products_from_common_cards(soup, current_url, rules, seen_urls, filters))

    for price_node in soup.find_all(string=PRICE_RE):
        price_sources.append(price_node)

    for node in soup.select("[class*='price'], [itemprop='price']"):
        text = clean_text(node.get_text(" ", strip=True) or node.get("content", "") or "")
        if PRICE_RE.search(text) and id(node) not in seen_source_ids:
            seen_source_ids.add(id(node))
            price_sources.append(node)

    for price_node in price_sources:
        if hasattr(price_node, "get_text"):
            source_text = price_node.get_text(" ", strip=True)
        else:
            source_text = str(price_node)
        price_match = PRICE_RE.search(source_text)
        if not price_match:
            continue

        price = clean_text(price_match.group(0))
        card = find_card_container(price_node, current_url)
        if not card:
            continue
        card_prices = extract_prices(card.get_text(" ", strip=True))
        if len(card_prices) > 1:
            price = card_prices[-1]

        product_url = extract_product_url_from_card(card, current_url, filters)
        if product_url == current_url and not is_product_url_for_filters(current_url, filters):
            continue
        model = normalize_model(extract_model_from_card(card, price), product_url)

        if not model or product_url in seen_urls:
            continue

        seen_urls.add(product_url)
        products.append({"url": product_url, "model": model, "price": price})

    products.extend(extract_listing_products_from_links(soup, current_url, seen_urls, filters))
    products.extend(extract_listing_products_from_scripts(soup, current_url, seen_urls, filters))
    if rules:
        products.extend(extract_listing_products_by_rules(soup, current_url, rules, seen_urls, filters))
    return products

def has_generic_product_signal(
    soup: BeautifulSoup,
    page_text: str,
    h1: str,
    price: str,
    model_from_labeled_value: bool,
    rules: Optional[Dict[str, str]] = None,
) -> bool:
    """Универсальные признаки товарной страницы без привязки к бренду или домену."""
    if soup.select_one("[itemtype*='Product'], [itemprop='price'], [itemprop='sku'], [itemprop='model'], script[type='application/ld+json']"):
        return True

    if rules and (str(rules.get("model_selector", "")).strip() or str(rules.get("price_selector", "")).strip()):
        return True

    if model_from_labeled_value:
        return True

    product_signals = (
        "Код товара",
        "Артикул",
        "Модель",
        "Характеристики",
        "В корзину",
        "Купить",
        "Ваша цена",
        "Сообщить о поступлении",
        "Нет в наличии",
        "Наличие",
    )
    if any(signal.lower() in page_text.lower() for signal in product_signals):
        return True

    return bool(h1 and (price or re.search(r"[A-Z\u0400-\u04FF]{2,}[\w.\-/]*\d", h1, re.IGNORECASE)))

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
    if rules and any(str(rules.get(key, "")).strip() for key in ("product_card_selector", "product_url_selector", "model_selector", "price_selector", "model_start_marker")):
        return True
    if not is_probable_product_url(url):
        return False
    return has_generic_product_signal(soup, page_text, h1, price, model_from_labeled_value, rules)

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
    model = prepare_rule_model(model, rules)
    prices = extract_prices(price)
    if prices:
        price = prices[-1]
    else:
        price = normalize_price_value(price or fallback_price)
    if not price and not allow_empty_price:
        prices = extract_prices(soup.get_text(" ", strip=True))
        price = prices[-1] if prices else ""
    model = normalize_model(model, url)
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

    h1 = first_text(soup, ["h1"])
    price = fallback_price or extract_price(soup, allow_page_fallback=not allow_empty_price)

    schema_product = extract_schema_product(soup, url, price, allow_empty_price=allow_empty_price)
    if schema_product and (schema_product.get("price") or allow_empty_price):
        return schema_product

    model = find_labeled_value(soup, ["Модель", "Артикул", "SKU", "Код модели", "Art:", "Model", "Article"])
    model_from_labeled_value = bool(model)

    if not model:
        model = extract_labeled_model_value(soup)
        model_from_labeled_value = bool(model)

    if not model:
        model = first_text(
            soup,
            [
                "[itemprop='model']",
                "[itemprop='sku']",
                "meta[itemprop='sku']",
                ".product-description__subtitle",
                ".sku",
                ".article",
                ".articul",
            ],
        )
        model_from_labeled_value = bool(model)

    if not model and h1:
        model = h1

    if rules:
        model = prepare_rule_model(model, rules)
    model = normalize_model(model, url)

    page_text = clean_text(soup.get_text(" ", strip=True))
    if should_accept_extracted_product(
        url=url,
        soup=soup,
        model=model,
        price=price,
        h1=h1,
        page_text=page_text,
        model_from_labeled_value=model_from_labeled_value,
        rules=rules,
        assume_product=assume_product,
        allow_empty_price=allow_empty_price,
    ):
        return {"url": url, "model": model, "price": price}

    return None
