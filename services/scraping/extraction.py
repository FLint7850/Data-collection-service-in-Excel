"""URL normalization, extraction rules and HTTP/browser scraping engines."""

import html as html_lib
import re
import threading
import time
from bs4 import BeautifulSoup
from config import PRICE_RE
from database.session import session_scope
from models import Brand
from services.normalization import normalize_extraction_rules
from sqlalchemy import select
from typing import Dict, Iterable, List, Optional, Set

from services.scraping.http import (
    canonicalize_product_url_by_filters,
    normalize_url,
    product_url_filter_patterns,
    product_url_matches_filters,
)

def clean_text(value: str) -> str:
    return re.sub(r"\s+", " ", value.replace("\xa0", " ").replace("\u2009", " ")).strip()


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
    seen_models: Set[str] = set()
    try:
        cards = soup.select(card_selector)
    except Exception:
        return []
    url_selector = str(rules.get("product_url_selector", "") or "").strip()
    for card in cards:
        link_node = None
        if url_selector and not product_url_filter_patterns([], {"product_url_selector": url_selector}):
            try:
                link_node = card.select_one(url_selector)
            except Exception:
                link_node = None
        product_url = ""
        if url_selector:
            product_url = canonicalize_product_url_by_filters(
                normalize_url(link_node.get("href", "") if link_node else "", current_url),
                filters,
            )
            if product_url and (product_url in seen_urls or not product_url_matches_filters(product_url, filters)):
                continue

        model = extract_model_by_markers(str(card), rules)
        model_from_config = bool(model)
        if not model:
            model = first_by_selector(card, rules.get("model_selector", ""))
            model_from_config = bool(model)
        if has_configured_model_source(rules) and not model_from_config:
            continue
        model = finalize_scraped_model(model, product_url, rules, model_from_config)
        model_key = clean_text(model).casefold()
        if not model_key or (not product_url and model_key in seen_models):
            continue

        price = extract_price_from_container(card, rules.get("price_selector", ""))
        if not model or not price:
            continue

        if product_url:
            seen_urls.add(product_url)
        else:
            seen_models.add(model_key)
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
