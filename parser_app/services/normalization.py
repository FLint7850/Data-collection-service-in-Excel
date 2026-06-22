"""URL, text and product-model normalization."""



from parser_app.runtime import *  # noqa: F401,F403



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

    # Сохраняем только пагинацию. Остальные параметры обычно создают дубликаты:
    # сортировки, UTM-метки, сравнение, фильтры с теми же товарами.
    pagination_params = []
    for key, value in parse_qsl(parsed.query, keep_blank_values=False):
        key_lower = key.lower()
        if key_lower == "page" or key_lower.startswith("pagen_"):
            pagination_params.append((key, value))
    query = urlencode(pagination_params)

    result = urlunparse((parsed.scheme.lower(), parsed.netloc.lower(), path, "", query, ""))
    return result

def same_site(url: str, root_netloc: str) -> bool:
    netloc = urlparse(url).netloc.lower()
    root = root_netloc.lower()
    return netloc == root or netloc.endswith("." + root)

def is_domain_url(url: str, domain: str) -> bool:
    return urlparse(url).netloc.lower().removeprefix("www.").endswith(domain.lower().removeprefix("www."))

def is_technopark_url(url: str) -> bool:
    return urlparse(url).netloc.lower().endswith("technopark.ru")

def has_static_extension(url: str) -> bool:
    return bool(
        re.search(
            r"\.(?:jpg|jpeg|png|gif|svg|webp|pdf|doc|docx|xls|xlsx|zip|rar|mp4|avi|css|js)$",
            urlparse(url).path,
            flags=re.IGNORECASE,
        )
    )

def looks_like_product_path(path: str) -> bool:
    path_parts = [part for part in path.split("/") if part]
    if not path_parts:
        return False
    slug = path_parts[-1]
    service_prefixes = {
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
        "support",
        "about",
        "action",
        "brand",
    }
    if path_parts[0].lower() in service_prefixes:
        return False
    if re.search(r"(?:^|/)goods?_\d+", path, flags=re.IGNORECASE):
        return True
    if len(path_parts) >= 3 and path_parts[0] == "catalog":
        return "-" in slug or any(char.isdigit() for char in slug)
    if len(path_parts) >= 2 and slug.lower().endswith(".html"):
        product_slug = slug.rsplit(".", 1)[0]
        return "-" in product_slug and any(char.isdigit() for char in product_slug)
    if len(path_parts) <= 3:
        product_slug = slug.rsplit(".", 1)[0]
        return "-" in product_slug and any(char.isdigit() for char in product_slug)
    return False

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
    links = soup.select("a[href]")
    links_count = len(links)
    product_links_count = 0
    for link in links:
        href = normalize_url(link.get("href", ""), "https://placeholder.local/") or ""
        if href and is_probable_product_url(href):
            product_links_count += 1
            if product_links_count >= 2:
                break
    has_product_markup = bool(
        soup.select_one(
            "[itemtype*='Product'], [itemprop='price'], script[type='application/ld+json'], "
            ".catalog-card, .js-ecom_product-item, [class*='product-card'], [class*='product-item'], "
            "[class*='price'], [class*='cost']"
        )
    )
    if product_links_count or has_product_markup or PRICE_RE.search(html):
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

    if allowed_domain and is_probable_product_url(url):
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
    return is_probable_product_url(url) or (
        bool([pattern for pattern in filters if str(pattern).strip()])
        and product_url_matches_filters(url, filters)
    )

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ").replace("\u2009", " ")).strip()

def split_text_lines(value: str) -> List[str]:
    return [clean_text(line) for line in re.split(r"[\n\r]+", value) if clean_text(line)]

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

    brand_regex = "|".join(re.escape(brand.lower()) for brand in sorted(brands, key=len, reverse=True))
    with model_brand_cache_lock:
        model_brand_cache["brands"] = set(brands)
        model_brand_cache["brand_regex"] = brand_regex
        model_brand_cache["loaded_at"] = now
    return brands

def known_brand_regex() -> str:
    model_brand_names()
    with model_brand_cache_lock:
        return str(model_brand_cache.get("brand_regex") or "")

def model_tokens_after_brand(value: str, brands: Optional[Set[str]] = None) -> str:
    """Extract a multi-token code after a configured or title-level Latin brand."""
    tokens = re.findall(r"[A-Za-z\u0400-\u04FF0-9]+(?:[./_-][A-Za-z\u0400-\u04FF0-9]+)*", clean_text(value))
    if not tokens:
        return ""
    brands = set(brands or model_brand_names())

    for index, token in enumerate(tokens):
        is_configured_brand = token.upper() in brands
        # A donor title can contain a brand that has not been added locally.
        is_title_brand = bool(re.fullmatch(r"[A-Za-z]{2,}", token))
        if not is_configured_brand and not is_title_brand:
            continue

        model_parts = []
        for candidate in tokens[index + 1 : index + 6]:
            candidate_clean = candidate.strip(" .,/\\_-")
            candidate_upper = candidate_clean.upper()
            if not candidate_clean or candidate_upper in MODEL_COLOR_WORDS:
                break
            if not re.search(r"[A-Za-z0-9]", candidate_clean):
                break
            normalized_candidate = candidate_clean.translate(VISUAL_MODEL_TRANSLATION)
            if any(char.isdigit() for char in normalized_candidate) or model_parts:
                model_parts.append(normalized_candidate)
                continue
            if re.fullmatch(r"[A-Za-z]{1,5}", candidate_clean):
                model_parts.append(normalized_candidate)
                continue
            break

        if model_parts and any(any(char.isdigit() for char in part) for part in model_parts):
            return " ".join(model_parts).upper()

    return ""

def model_from_url_slug(product_url: str) -> str:
    slug = urlparse(product_url).path.rstrip("/").split("/")[-1].lower()
    match = re.search(r"-([a-z0-9][a-z0-9-]*?[a-z][a-z0-9-]*\d[a-z0-9-]*)(?:-\d{5,})?$", slug)
    if not match:
        return ""

    model = match.group(1).replace("-", " ").strip()
    return model.upper()

def normalize_model(value: str, product_url: str = "") -> str:
    """Возвращает маркировку модели без полного товарного названия."""
    text = clean_text(value)

    if not text:
        return ""

    # Сохраняем регистр и разделители моделей, которые уже выглядят как готовая модель.
    mixed_case_model = text.replace("\\", "/")
    mixed_case_model = re.sub(r"[–—]", "-", mixed_case_model)
    mixed_case_model = re.sub(r"\s+-\s+", " - ", mixed_case_model)
    mixed_case_model = re.sub(r"\s{2,}", " ", mixed_case_model).strip()
    mixed_case_model = mixed_case_model.rstrip(".")

    if (
        re.fullmatch(
            r"[A-Za-z0-9./_-]+(?:\s+-\s+|\s+[A-Za-z0-9./_-]+){0,8}",
            mixed_case_model,
        )
        and any(char.isdigit() for char in mixed_case_model)
        and any(char.isalpha() for char in mixed_case_model)
        and any(char.islower() for char in mixed_case_model)
    ):
        return mixed_case_model

    brands = model_brand_names()

    # Частый случай: "Бренд ABC123" -> "ABC123".
    brands_regex = known_brand_regex()
    if brands_regex:
        brand_match = re.search(
            rf"\b(?:{brands_regex})\b\s+([A-Z0-9][A-Z0-9./\\_-]{{2,}})",
            text,
            re.IGNORECASE,
        )
        if brand_match:
            return brand_match.group(1).strip(" .,/\\_-").replace("\\", "/").upper()

    generic_brand_model = model_tokens_after_brand(text, brands)
    if generic_brand_model:
        return generic_brand_model

    latin_model_text = text.replace("\\", "/")
    latin_model_tokens = re.findall(r"[A-Za-z0-9./_-]+", latin_model_text)
    if (
        latin_model_tokens
        and " ".join(latin_model_tokens).strip() == re.sub(r"\s+", " ", latin_model_text).strip()
        and 1 <= len(latin_model_tokens) <= 6
        and any(any(char.isdigit() for char in token) for token in latin_model_tokens)
        and any(any(char.isalpha() for char in token) for token in latin_model_tokens)
        and latin_model_tokens[0].upper() not in {"SERIE", "SERIES"}
        and latin_model_tokens[0].upper() not in brands
    ):
        return " ".join(token.strip(" .,/\\_-").upper() for token in latin_model_tokens if token.strip(" .,/\\_-"))

    ascii_tokens = re.findall(r"[A-Za-z0-9]+(?:[./_-][A-Za-z0-9]+)*", text)
    for start_index in range(max(0, len(ascii_tokens) - 6), len(ascii_tokens)):
        candidate_tokens = [token.strip(" .,/\\_-") for token in ascii_tokens[start_index:] if token.strip(" .,/\\_-")]
        if not (2 <= len(candidate_tokens) <= 6):
            continue
        if not any(any(char.isdigit() for char in token) for token in candidate_tokens):
            continue
        if not all(re.fullmatch(r"[A-Z0-9./_-]+", token) for token in candidate_tokens):
            continue
        if candidate_tokens[0].upper() in brands or candidate_tokens[0].upper() in {"SERIE", "SERIES"}:
            continue
        return " ".join(candidate_tokens).upper()

    ignored_tokens = {
        "ONLINE",
        "SALE",
        "NEW",
        "ОНЛАЙН",
        "РАСПРОДАЖА",
        "НОВИНКА",
        *brands,
    }
    code_tokens = []
    for token in re.findall(r"[A-Z\u0400-\u04FF0-9][A-Z\u0400-\u04FF0-9./\\_-]{2,}", text, flags=re.IGNORECASE):
        cleaned = token.strip(" .,/\\_-")
        if cleaned.upper() in ignored_tokens:
            continue
        has_digit = any(char.isdigit() for char in cleaned)
        has_letter = any(char.isalpha() for char in cleaned)
        if has_digit and has_letter:
            code_tokens.append(cleaned)

    if code_tokens:
        return code_tokens[-1].replace("\\", "/").upper()

    # Последний шанс: модель часто лежит в конце slug после названия бренда.
    slug = urlparse(product_url).path.rstrip("/").split("/")[-1]
    if brands_regex:
        slug_match = re.search(rf"(?:^|-)(?:{brands_regex})-([a-z0-9-]+)$", slug, re.IGNORECASE)
        if slug_match:
            return slug_match.group(1).replace("-", "").upper()

    url_model = model_from_url_slug(product_url)
    if url_model:
        return url_model

    return text
