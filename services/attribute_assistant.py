"""Isolated attribute-assistant domain logic.

This module deliberately does not import the existing scraping package. Its HTTP
client ignores process proxy variables so the ChatGPT-only proxy can never leak
into donor or product-page requests.
"""

from __future__ import annotations

import csv
import io
import json
import re
import socket
import uuid
from difflib import SequenceMatcher
from ipaddress import ip_address
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import chardet
import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from config import ATTRIBUTE_ASSISTANT_DIR, REQUEST_TIMEOUT
from models import (
    AttributeAllowedValue,
    AttributeBatch,
    AttributeCategory,
    AttributeMappingRule,
    AttributeProcessingLog,
    AttributeProduct,
    AttributeProductSource,
    AttributeProductValue,
    AttributeTemplate,
    AttributeTemplateField,
    AttributeTemplateRevision,
    AttributeValueSynonym,
    Brand,
    Donor,
)


SPACE_RE = re.compile(r"\s+")
NUMBER_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?$")
DIMENSION_RE = re.compile(r"^[+-]?\d+(?:[.,]\d+)?(?:\s*[xXхХ×]\s*[+-]?\d+(?:[.,]\d+)?){1,3}$")
HEADER_GROUP_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")
WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
IGNORED_NAME_TOKENS = {
    "максимальная", "максимальный", "макс", "мин", "об", "минуту", "ед",
    "значение", "характеристика", "параметр", "тип",
}


def clean_text(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()

def clean_csv_cell(value: Any) -> str:
    text = str(value or "").replace("\xa0", " ").replace("\r\n", "\n").replace("\r", "\n")
    return "\n".join(clean_text(line) for line in text.split("\n")).strip()



def normalize_key(value: Any) -> str:
    text = clean_text(value).casefold().replace("ё", "е")
    return " ".join(WORD_RE.findall(text))


def normalize_model(value: Any) -> str:
    return re.sub(r"[^A-ZА-ЯЁ0-9]", "", clean_text(value).upper())


def _name_tokens(value: Any) -> set[str]:
    return {token for token in normalize_key(value).split() if token not in IGNORED_NAME_TOKENS and len(token) > 1}


def normalize_number(value: Any) -> str:
    text = clean_text(value)
    if not NUMBER_RE.fullmatch(text):
        raise ValueError("Некорректное числовое значение")
    number = text.replace(",", ".")
    if "." in number:
        number = number.rstrip("0").rstrip(".")
    return number


def normalize_dimensions(value: Any) -> str:
    text = clean_text(value)
    if not DIMENSION_RE.fullmatch(text):
        raise ValueError("Некорректные габариты")
    return re.sub(r"\s*[xXхХ×]\s*", "x", text).replace(",", ".")


def normalize_value(value: Any, value_type: str = "select", composite: bool = False) -> str:
    text = clean_text(value)
    if not text:
        return ""
    if value_type == "number":
        return normalize_number(text)
    if value_type == "dimensions":
        return normalize_dimensions(text)
    if value_type == "boolean":
        key = normalize_key(text)
        if key in {"да", "есть", "yes", "true", "1", "имеется"}:
            return "Да"
        if key in {"нет", "no", "false", "0", "отсутствует"}:
            return "Нет"
    if composite:
        parts = sorted({clean_text(part) for part in text.split("/") if clean_text(part)}, key=str.casefold)
        return "/".join(parts)
    return text


def infer_value_type(name: str, values: Iterable[str]) -> tuple[str, bool]:
    sample = [clean_text(value) for value in values if clean_text(value) and clean_text(value) != "-"]
    name_key = normalize_key(name)
    if any(word in name_key for word in ("габарит", "размеры", "высота x", "ширина x")):
        return "dimensions", False
    if sample and all(DIMENSION_RE.fullmatch(value) for value in sample):
        return "dimensions", False
    if sample and all(NUMBER_RE.fullmatch(value) for value in sample):
        return "number", False
    if any(word in name_key for word in ("список программ", "дополнительные программы", "индикация")):
        return "select", True
    return "select", any("/" in value for value in sample)


def decode_csv(data: bytes) -> str:
    for encoding in ("utf-8-sig", "cp1251"):
        try:
            return data.decode(encoding)
        except UnicodeDecodeError:
            pass
    detected = str((chardet.detect(data) or {}).get("encoding") or "latin-1")
    return data.decode(detected, errors="replace")


def csv_rows(data: bytes) -> tuple[list[str], list[dict[str, str]]]:
    text = decode_csv(data)
    sample = text[:8192]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=";,\t")
    except csv.Error:
        dialect = csv.excel
        dialect.delimiter = ";"
    reader = csv.DictReader(io.StringIO(text), dialect=dialect)
    headers = [clean_text(item) for item in (reader.fieldnames or [])]
    rows = [
        {clean_text(key): clean_csv_cell(value) for key, value in row.items() if key is not None}
        for row in reader
    ]
    return headers, rows


def split_template_header(header: str) -> tuple[str, str]:
    match = HEADER_GROUP_RE.match(clean_text(header))
    if not match:
        return clean_text(header), "Основные характеристики"
    return clean_text(match.group(1)), clean_text(match.group(2)) or "Основные характеристики"


def serialize_template(template: AttributeTemplate, include_values: bool = False) -> dict[str, Any]:
    result = {
        "id": template.id,
        "name": template.name,
        "category": template.category.full_path or template.category.name,
        "product_type": template.product_type,
        "description": template.description,
        "is_default": template.is_default,
        "field_count": len(template.fields),
    }
    if include_values:
        result["fields"] = [
            {
                "id": field.id,
                "group_name": field.group_name,
                "name": field.name,
                "value_type": field.value_type,
                "is_composite": field.is_composite,
                "is_required": field.is_required,
                "sort_order": field.sort_order,
                "allowed_values": [
                    {
                        "id": allowed.id,
                        "value": allowed.value,
                        "synonyms": [item.synonym for item in allowed.synonyms],
                    }
                    for allowed in field.allowed_values if allowed.is_active
                ],
            }
            for field in template.fields
        ]
    return result


def import_template_csv(
    db: Session,
    data: bytes,
    *,
    name: str,
    category: str,
    product_type: str = "",
    description: str = "",
) -> AttributeTemplate:
    headers, rows = csv_rows(data)
    headers = [header for header in headers if header and not header.startswith("_")]
    if not headers:
        raise ValueError("В файле шаблона не найдены столбцы атрибутов")
    category_path = clean_text(category)
    if not category_path:
        raise ValueError("Укажите категорию шаблона")
    category_row = db.scalar(select(AttributeCategory).where(AttributeCategory.full_path == category_path))
    if not category_row:
        category_row = AttributeCategory(name=category_path.split(">")[-1].strip(), full_path=category_path)
        db.add(category_row)
        db.flush()
    template_name = clean_text(name) or category_row.name
    duplicate = db.scalar(
        select(AttributeTemplate).where(
            AttributeTemplate.category_id == category_row.id,
            AttributeTemplate.name == template_name,
        )
    )
    if duplicate:
        raise ValueError("Шаблон с таким именем в категории уже существует")
    template = AttributeTemplate(
        category=category_row,
        name=template_name,
        product_type=clean_text(product_type),
        description=clean_text(description),
        is_default=not bool(category_row.templates),
    )
    db.add(template)
    db.flush()
    snapshot_fields: list[dict[str, Any]] = []
    for order, header in enumerate(headers):
        attribute_name, group_name = split_template_header(header)
        column_values = [row.get(header, "") for row in rows]
        value_type, composite = infer_value_type(attribute_name, column_values)
        field = AttributeTemplateField(
            template=template,
            group_name=group_name,
            name=attribute_name,
            value_type=value_type,
            is_composite=composite,
            sort_order=order,
        )
        db.add(field)
        db.flush()
        seen: set[str] = set()
        allowed_items: list[str] = []
        for raw_value in column_values:
            if not raw_value or raw_value == "-":
                continue
            raw_parts = raw_value.split("/") if composite else [raw_value]
            for raw_part in raw_parts:
                try:
                    normalized = normalize_value(raw_part, value_type, False)
                except ValueError:
                    continue
                key = normalize_key(normalized)
                if not key or key in seen:
                    continue
                seen.add(key)
                allowed_items.append(normalized)
                db.add(
                    AttributeAllowedValue(
                        field=field,
                        value=normalized,
                        normalized_value=key,
                        sort_order=len(allowed_items) - 1,
                    )
                )
        snapshot_fields.append({"group": group_name, "name": attribute_name, "type": value_type, "values": allowed_items})
    db.add(AttributeTemplateRevision(template=template, action="import", snapshot={"fields": snapshot_fields}))
    db.flush()
    return template


def add_allowed_value(db: Session, field: AttributeTemplateField, value: str, synonym: str = "") -> AttributeAllowedValue:
    normalized = normalize_value(value, field.value_type, False)
    key = normalize_key(normalized)
    if not key:
        raise ValueError("Значение не может быть пустым")
    existing = db.scalar(
        select(AttributeAllowedValue).where(
            AttributeAllowedValue.field_id == field.id,
            AttributeAllowedValue.normalized_value == key,
        )
    )
    if existing:
        allowed = existing
        allowed.is_active = True
    else:
        allowed = AttributeAllowedValue(
            field=field,
            value=normalized,
            normalized_value=key,
            source="manual",
            sort_order=len(field.allowed_values),
        )
        db.add(allowed)
        db.flush()
    synonym_key = normalize_key(synonym)
    if synonym_key and not any(item.normalized_synonym == synonym_key for item in allowed.synonyms):
        db.add(AttributeValueSynonym(allowed_value=allowed, synonym=clean_text(synonym), normalized_synonym=synonym_key))
    return allowed



def parse_attribute_stack(value: str) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for raw_line in str(value or "").replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        if not clean_text(raw_line):
            continue
        parts = raw_line.split("|", 2)
        if len(parts) != 3:
            continue
        result.append({
            "group_name": clean_text(parts[0]),
            "name": clean_text(parts[1]),
            "value": clean_text(parts[2]),
        })
    return result


def _row_value(row: dict[str, str], *names: str) -> str:
    wanted = {normalize_key(name) for name in names}
    for key, value in row.items():
        if normalize_key(key) in wanted:
            return clean_csv_cell(value) if "attributes" in wanted else clean_text(value)
    return ""


def _make_product_values(product: AttributeProduct, template: AttributeTemplate, stack: list[dict[str, str]]) -> None:
    existing_by_name: dict[str, list[dict[str, str]]] = {}
    for item in stack:
        existing_by_name.setdefault(normalize_key(item["name"]), []).append(item)
    consumed: set[int] = set()
    for field in template.fields:
        candidates = existing_by_name.get(normalize_key(field.name), [])
        matched = next(
            (
                item for item in candidates
                if id(item) not in consumed and (
                    normalize_key(item["group_name"]) == normalize_key(field.group_name)
                    or len(candidates) == 1
                )
            ),
            None,
        )
        current = matched["value"] if matched else ""
        if matched:
            consumed.add(id(matched))
        product.values.append(
            AttributeProductValue(
                template_field=field,
                group_name=field.group_name,
                attribute_name=field.name,
                current_value=current,
                final_value=current,
                source="current_csv" if current else "",
                confidence=100 if current else 0,
                status="kept" if current else "missing",
                is_in_template=True,
                sort_order=field.sort_order,
            )
        )
    extra_order = len(template.fields)
    for item in stack:
        if id(item) in consumed:
            continue
        product.values.append(
            AttributeProductValue(
                group_name=item["group_name"],
                attribute_name=item["name"],
                current_value=item["value"],
                final_value=item["value"],
                source="current_csv",
                confidence=100,
                status="kept",
                is_in_template=False,
                is_extra_attribute=True,
                sort_order=extra_order,
            )
        )
        extra_order += 1


def refresh_batch_summary(batch: AttributeBatch) -> dict[str, int]:
    products = list(batch.products)
    values = [value for product in products for value in product.values]
    summary = {
        "products": len(products),
        "ready": sum(product.status == "ready" for product in products),
        "needs_review": sum(product.status != "ready" for product in products),
        "filled": sum(bool(value.final_value and value.final_value != "-") for value in values if value.is_in_template),
        "missing": sum(not value.final_value for value in values if value.is_in_template),
        "conflicts": sum(value.status == "conflict" for value in values),
        "suggestions": sum(value.status == "suggested" for value in values),
    }
    batch.summary = summary
    return summary


def refresh_product_status(product: AttributeProduct) -> str:
    review = any(
        value.is_in_template and (
            value.status in {"missing", "suggested", "conflict", "unknown", "ambiguous"}
            or not value.final_value
        )
        for value in product.values
    )
    product.status = "needs_review" if review else "ready"
    return product.status


def create_batch_from_csv(
    db: Session,
    template: AttributeTemplate,
    data: bytes,
    *,
    filename: str,
    name: str = "",
    processing_mode: str = "suggest",
) -> AttributeBatch:
    _headers, rows = csv_rows(data)
    if not rows:
        raise ValueError("CSV-файл не содержит товаров")
    batch = AttributeBatch(
        template=template,
        name=clean_text(name) or Path(filename).stem,
        input_mode="csv",
        processing_mode=processing_mode if processing_mode in {"suggest", "auto"} else "suggest",
        source_filename=clean_text(filename),
    )
    db.add(batch)
    db.flush()
    input_dir = ATTRIBUTE_ASSISTANT_DIR / "inputs"
    input_dir.mkdir(parents=True, exist_ok=True)
    stored = input_dir / f"{batch.id}_{uuid.uuid4().hex[:8]}.csv"
    stored.write_bytes(data)
    batch.original_path = str(stored)
    for index, row in enumerate(rows, start=1):
        model = _row_value(row, "_MODEL_", "MODEL", "Модель")
        if not model:
            continue
        product = AttributeProduct(
            batch=batch,
            external_id=_row_value(row, "_ID_", "ID"),
            model=model,
            name=_row_value(row, "_NAME_", "NAME", "Название"),
            brand=_row_value(row, "_BRAND_", "BRAND", "Бренд"),
        )
        db.add(product)
        _make_product_values(product, template, parse_attribute_stack(_row_value(row, "_ATTRIBUTES_", "ATTRIBUTES", "Атрибуты")))
        refresh_product_status(product)
    if not batch.products:
        raise ValueError("В CSV не найдено ни одной заполненной модели")
    refresh_batch_summary(batch)
    db.add(AttributeProcessingLog(batch_id=batch.id, action="csv_import", details={"rows": len(batch.products)}))
    db.flush()
    return batch


def _is_public_url(url: str) -> bool:
    parsed = urlparse(clean_text(url))
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        return False
    if parsed.username or parsed.password:
        return False
    try:
        addresses = {item[4][0] for item in socket.getaddrinfo(parsed.hostname, parsed.port or 443)}
        return bool(addresses) and all(not ip_address(address).is_private for address in addresses)
    except (OSError, ValueError):
        return False


def fetch_public_html(url: str, max_bytes: int = 5 * 1024 * 1024) -> tuple[str, str]:
    if not _is_public_url(url):
        raise ValueError("Разрешены только публичные HTTP(S)-адреса")
    session = requests.Session()
    session.trust_env = False
    response = session.get(
        url,
        timeout=REQUEST_TIMEOUT,
        headers={"User-Agent": "Mozilla/5.0 (compatible; AttributeAssistant/1.0)"},
        allow_redirects=True,
        stream=True,
    )
    response.raise_for_status()
    if not _is_public_url(response.url):
        raise ValueError("Страница перенаправила запрос на закрытый адрес")
    chunks: list[bytes] = []
    size = 0
    for chunk in response.iter_content(65536):
        size += len(chunk)
        if size > max_bytes:
            raise ValueError("Страница превышает допустимый размер")
        chunks.append(chunk)
    payload = b"".join(chunks)
    encoding = response.encoding or (chardet.detect(payload).get("encoding") if payload else None) or "utf-8"
    return payload.decode(encoding, errors="replace"), response.url


def _jsonld_items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("@graph"), list):
            for item in value["@graph"]:
                yield from _jsonld_items(item)
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _jsonld_items(item)


def parse_product_html(html: str, url: str = "") -> dict[str, Any]:
    soup = BeautifulSoup(html, "html.parser")
    result: dict[str, Any] = {"url": url, "name": "", "model": "", "brand": "", "category": "", "attributes": []}
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or "{}")
        except (ValueError, TypeError):
            continue
        for item in _jsonld_items(data):
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if "Product" not in types:
                continue
            result["name"] = clean_text(item.get("name")) or result["name"]
            result["model"] = clean_text(item.get("model") or item.get("mpn") or item.get("sku")) or result["model"]
            brand = item.get("brand")
            result["brand"] = clean_text(brand.get("name") if isinstance(brand, dict) else brand) or result["brand"]
            result["category"] = clean_text(item.get("category")) or result["category"]
            for prop in item.get("additionalProperty") or []:
                if isinstance(prop, dict) and prop.get("name"):
                    result["attributes"].append({
                        "name": clean_text(prop.get("name")),
                        "value": clean_text(prop.get("value")),
                        "group": "",
                    })
    selectors = ("table tr", ".characteristics tr", ".specifications tr", ".properties tr")
    seen = {(normalize_key(item["name"]), normalize_key(item["value"])) for item in result["attributes"]}
    for row in soup.select(",".join(selectors)):
        cells = row.find_all(["th", "td"], recursive=False) or row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        name, value = clean_text(cells[0].get_text(" ")), clean_text(cells[-1].get_text(" "))
        key = (normalize_key(name), normalize_key(value))
        if name and value and name != value and key not in seen:
            result["attributes"].append({"name": name, "value": value, "group": ""})
            seen.add(key)
    for term in soup.select("dl dt"):
        definition = term.find_next_sibling("dd")
        if not definition:
            continue
        name, value = clean_text(term.get_text(" ")), clean_text(definition.get_text(" "))
        key = (normalize_key(name), normalize_key(value))
        if name and value and key not in seen:
            result["attributes"].append({"name": name, "value": value, "group": ""})
            seen.add(key)
    if not result["name"]:
        heading = soup.select_one("h1")
        result["name"] = clean_text(heading.get_text(" ")) if heading else ""
    if not result["model"]:
        for attr in result["attributes"]:
            if normalize_key(attr["name"]) in {"модель", "код модели", "артикул", "sku"}:
                result["model"] = attr["value"]
                break
    crumbs = [clean_text(node.get_text(" ")) for node in soup.select('[itemprop="itemListElement"], .breadcrumb a, .breadcrumbs a')]
    if crumbs and not result["category"]:
        result["category"] = " > ".join(dict.fromkeys(item for item in crumbs if item))
    return result


def find_template_for_category(db: Session, category: str) -> AttributeTemplate | None:
    key = normalize_key(category)
    if not key:
        return None
    templates = list(db.scalars(select(AttributeTemplate)))
    exact = [item for item in templates if normalize_key(item.category.full_path) == key]
    if exact:
        return exact[0]
    ranked = sorted(
        ((SequenceMatcher(None, key, normalize_key(item.category.full_path)).ratio(), item) for item in templates),
        key=lambda pair: pair[0],
        reverse=True,
    )
    return ranked[0][1] if ranked and ranked[0][0] >= 0.82 else None


def create_batch_from_urls(
    db: Session,
    urls: list[str],
    *,
    template: AttributeTemplate | None,
    name: str = "",
    processing_mode: str = "suggest",
) -> AttributeBatch:
    cleaned_urls = list(dict.fromkeys(clean_text(url) for url in urls if clean_text(url)))
    if not cleaned_urls:
        raise ValueError("Добавьте хотя бы одну ссылку")
    parsed_pages: list[dict[str, Any]] = []
    selected_template = template
    for url in cleaned_urls:
        html, final_url = fetch_public_html(url)
        page = parse_product_html(html, final_url)
        parsed_pages.append(page)
        selected_template = selected_template or find_template_for_category(db, page["category"])
    if not selected_template:
        raise ValueError("Категория не определена автоматически. Выберите шаблон вручную")
    batch = AttributeBatch(
        template=selected_template,
        name=clean_text(name) or f"Ссылки {len(cleaned_urls)}",
        input_mode="urls",
        processing_mode=processing_mode if processing_mode in {"suggest", "auto"} else "suggest",
    )
    db.add(batch)
    db.flush()
    for index, page in enumerate(parsed_pages, start=1):
        model = page["model"] or page["name"] or f"Товар {index}"
        product = AttributeProduct(
            batch=batch,
            model=model,
            name=page["name"],
            brand=page["brand"],
            category_name=page["category"],
            source_url=page["url"],
        )
        db.add(product)
        _make_product_values(product, selected_template, [])
        product.sources.append(
            AttributeProductSource(
                url=page["url"],
                priority=0,
                role="own_site",
                status="parsed",
                parsed_data=page,
            )
        )
        apply_parsed_attributes(db, product, page["attributes"], source="own_site", priority=0)
        refresh_product_status(product)
    refresh_batch_summary(batch)
    db.add(AttributeProcessingLog(batch_id=batch.id, action="url_import", details={"rows": len(batch.products)}))
    db.flush()
    return batch



def serialize_donor(donor: Donor) -> dict[str, Any]:
    return {
        "id": donor.id,
        "name": donor.brand.name,
        "group_name": donor.brand.group_name,
        "site_url": donor.site_url,
        "start_urls": list(donor.start_urls or []),
        "cached_products": len(donor.known_new_products or {}),
    }


def list_donors(db: Session, brand: str = "") -> list[dict[str, Any]]:
    statement = select(Donor).join(Brand, Donor.brand_id == Brand.id).order_by(Brand.name, Donor.id)
    rows = list(db.scalars(statement))
    brand_key = normalize_key(brand)
    if brand_key:
        matching = [
            donor for donor in rows
            if brand_key in normalize_key(donor.brand.name) or normalize_key(donor.brand.name) in brand_key
        ]
        if matching:
            rows = matching
    return [serialize_donor(donor) for donor in rows]


def _cached_product_url(donor: Donor, model: str) -> str:
    wanted = normalize_model(model)
    for key, raw_record in (donor.known_new_products or {}).items():
        record = raw_record if isinstance(raw_record, dict) else {"url": raw_record}
        candidates = [
            key,
            record.get("model"),
            record.get("sku"),
            record.get("name"),
        ]
        if any(normalize_model(candidate) == wanted for candidate in candidates if candidate):
            url = clean_text(record.get("url") or record.get("link"))
            if url:
                return urljoin(donor.site_url or (donor.start_urls or [""])[0], url)
    return ""


def resolve_donor_url(donor: Donor, model: str) -> tuple[str, str]:
    cached = _cached_product_url(donor, model)
    if cached:
        return cached, "Кэш ранее найденных товаров"
    wanted = normalize_model(model)
    start_urls = list(donor.start_urls or [])
    if donor.site_url and donor.site_url not in start_urls:
        start_urls.append(donor.site_url)
    for start_url in start_urls[:5]:
        try:
            html, final_url = fetch_public_html(start_url)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for anchor in soup.select("a[href]"):
            href = clean_text(anchor.get("href"))
            haystack = " ".join((
                clean_text(anchor.get_text(" ")),
                clean_text(anchor.get("title")),
                href,
            ))
            if wanted and wanted in normalize_model(haystack):
                return urljoin(final_url, href), "Найдена по модели на странице донора"
    return "", "Ссылка по модели не найдена"


def _mapping_score(source_name: str, field: AttributeTemplateField) -> float:
    source_key = normalize_key(source_name)
    target_key = normalize_key(field.name)
    if source_key == target_key:
        return 1.0
    source_tokens = _name_tokens(source_name)
    target_tokens = _name_tokens(field.name)
    if source_tokens and target_tokens:
        overlap = source_tokens & target_tokens
        coverage = len(overlap) / min(len(source_tokens), len(target_tokens))
        union = len(overlap) / len(source_tokens | target_tokens)
        if source_tokens <= target_tokens or target_tokens <= source_tokens:
            return 0.96
    else:
        coverage = union = 0.0
    sequence = SequenceMatcher(None, source_key, target_key).ratio()
    return min(0.99, 0.48 * sequence + 0.37 * coverage + 0.15 * union)


def map_attribute(
    db: Session,
    template: AttributeTemplate,
    donor_id: int | None,
    source_name: str,
) -> tuple[AttributeTemplateField | None, int, str, list[dict[str, Any]]]:
    source_key = normalize_key(source_name)
    if donor_id:
        rule = db.scalar(
            select(AttributeMappingRule).where(
                AttributeMappingRule.donor_id == donor_id,
                AttributeMappingRule.template_id == template.id,
                AttributeMappingRule.normalized_donor_attribute == source_key,
                AttributeMappingRule.is_active.is_(True),
            )
        )
        if rule:
            return rule.template_field, 100, "Сохранённое правило", []
    ranked = sorted(
        ((_mapping_score(source_name, field), field) for field in template.fields),
        key=lambda pair: pair[0],
        reverse=True,
    )
    alternatives = [
        {"field_id": field.id, "name": field.name, "group_name": field.group_name, "score": round(score * 100)}
        for score, field in ranked[:4]
    ]
    if not ranked or ranked[0][0] < 0.74:
        return None, round((ranked[0][0] if ranked else 0) * 100), "Низкая схожесть названий", alternatives
    best_score, best_field = ranked[0]
    margin = best_score - (ranked[1][0] if len(ranked) > 1 else 0)
    if len(ranked) > 1 and margin < 0.06 and best_score < 0.94:
        return None, round(best_score * 100), "Нужно уточнить атрибут", alternatives
    return best_field, round(best_score * 100), "Сопоставлено по названию", alternatives


def _allowed_match(field: AttributeTemplateField, raw_value: str) -> tuple[str, int, str, list[str]]:
    try:
        normalized = normalize_value(raw_value, field.value_type, field.is_composite)
    except ValueError as error:
        return "", 0, str(error), []
    allowed = [item for item in field.allowed_values if item.is_active]
    if field.is_composite:
        values: list[str] = []
        scores: list[int] = []
        unknown: list[str] = []
        for part in [clean_text(item) for item in raw_value.split("/") if clean_text(item)]:
            single, score, reason, suggestions = _allowed_match_single(field, part, allowed)
            if single:
                values.append(single)
                scores.append(score)
            else:
                unknown.append(part)
        if unknown:
            return "", 0, "Нет в справочнике: " + ", ".join(unknown), []
        return "/".join(sorted(set(values), key=str.casefold)), min(scores or [0]), "Составное значение проверено", []
    return _allowed_match_single(field, normalized, allowed)


def _allowed_match_single(
    field: AttributeTemplateField,
    value: str,
    allowed: list[AttributeAllowedValue],
) -> tuple[str, int, str, list[str]]:
    key = normalize_key(value)
    if field.value_type in {"number", "dimensions"} and not allowed:
        return value, 96, "Формат проверен", []
    for item in allowed:
        if item.normalized_value == key:
            return item.value, 100, "Точное значение справочника", []
        if any(synonym.normalized_synonym == key for synonym in item.synonyms):
            return item.value, 98, "Синоним значения", []
    ranked = sorted(
        ((SequenceMatcher(None, key, item.normalized_value).ratio(), item.value) for item in allowed),
        reverse=True,
    )
    suggestions = [value for _score, value in ranked[:3]]
    if ranked and ranked[0][0] >= 0.88:
        return ranked[0][1], round(ranked[0][0] * 100), "Ближайшее значение справочника", suggestions
    return "", 0, "Значения нет в справочнике", suggestions


def _target_value(product: AttributeProduct, field_id: int) -> AttributeProductValue | None:
    return next((value for value in product.values if value.template_field_id == field_id), None)


def apply_candidate(
    product: AttributeProduct,
    target: AttributeProductValue,
    *,
    value: str,
    confidence: int,
    source: str,
    reason: str,
    priority: int,
    source_name: str,
    source_url: str = "",
) -> None:
    if target.current_value:
        return
    details = dict(target.source_details or {})
    candidates = list(details.get("candidates") or [])
    candidate = {
        "value": value,
        "confidence": confidence,
        "source": source,
        "reason": reason,
        "priority": priority,
        "source_name": source_name,
        "url": source_url,
    }
    candidates.append(candidate)
    details["candidates"] = candidates
    target.source_details = details
    distinct = {normalize_key(item["value"]) for item in candidates if item.get("value")}
    if len(distinct) > 1:
        target.status = "conflict"
        target.reason = "Источники предлагают разные значения"
        target.proposed_value = ""
        target.final_value = ""
        target.confidence = max(item["confidence"] for item in candidates)
        return
    best = sorted(candidates, key=lambda item: (int(item["priority"]), -int(item["confidence"])))[0]
    target.proposed_value = best["value"]
    target.source = best["source"]
    target.confidence = best["confidence"]
    target.reason = best["reason"]
    auto = product.batch.processing_mode == "auto" and best["confidence"] >= 90
    target.final_value = best["value"] if auto else ""
    target.status = "approved" if auto else "suggested"


def apply_parsed_attributes(
    db: Session,
    product: AttributeProduct,
    attributes: list[dict[str, Any]],
    *,
    source: str,
    priority: int,
    donor_id: int | None = None,
    source_url: str = "",
) -> dict[str, int]:
    stats = {"mapped": 0, "unknown": 0, "ambiguous": 0}
    template = product.batch.template
    for item in attributes:
        source_name = clean_text(item.get("name"))
        raw_value = clean_text(item.get("value"))
        if not source_name or not raw_value:
            continue
        field, mapping_confidence, mapping_reason, alternatives = map_attribute(
            db, template, donor_id, source_name
        )
        if not field:
            stats["ambiguous"] += 1
            db.add(
                AttributeProcessingLog(
                    batch_id=product.batch_id,
                    product_id=product.id,
                    action="unmapped_attribute",
                    details={
                        "source": source,
                        "source_name": source_name,
                        "value": raw_value,
                        "reason": mapping_reason,
                        "alternatives": alternatives,
                    },
                )
            )
            continue
        target = _target_value(product, field.id)
        if not target or target.current_value:
            continue
        canonical, value_confidence, value_reason, suggestions = _allowed_match(field, raw_value)
        if not canonical:
            stats["unknown"] += 1
            details = dict(target.source_details or {})
            unknown = list(details.get("unknown_values") or [])
            unknown.append({
                "value": raw_value,
                "source": source,
                "source_name": source_name,
                "suggestions": suggestions,
                "reason": value_reason,
            })
            details["unknown_values"] = unknown
            target.source_details = details
            if target.status == "missing":
                target.status = "unknown"
                target.reason = value_reason
            continue
        confidence = min(mapping_confidence, value_confidence)
        apply_candidate(
            product,
            target,
            value=canonical,
            confidence=confidence,
            source=source,
            reason=f"{mapping_reason}; {value_reason}",
            priority=priority,
            source_name=source_name,
            source_url=source_url,
        )
        stats["mapped"] += 1
    refresh_product_status(product)
    return stats


def process_product_donors(db: Session, product: AttributeProduct, donor_ids: list[int]) -> dict[str, Any]:
    donor_ids = list(dict.fromkeys(int(item) for item in donor_ids))
    if not donor_ids:
        raise ValueError("Выберите хотя бы одного донора")
    product.sources[:] = [item for item in product.sources if item.role == "own_site"]
    reports: list[dict[str, Any]] = []
    raw_dir = ATTRIBUTE_ASSISTANT_DIR / "raw" / str(product.batch_id) / str(product.id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    for priority, donor_id in enumerate(donor_ids):
        donor = db.get(Donor, donor_id)
        if not donor:
            reports.append({"donor_id": donor_id, "status": "error", "message": "Донор не найден"})
            continue
        url, resolved_by = resolve_donor_url(donor, product.model)
        role = "primary" if priority == 0 else "verification"
        if not url:
            db.add(AttributeProductSource(
                product=product,
                donor=donor,
                url=donor.site_url or (donor.start_urls or [""])[0],
                priority=priority,
                role=role,
                status="not_found",
                parsed_data={"message": resolved_by},
            ))
            reports.append({"donor_id": donor.id, "name": donor.brand.name, "status": "not_found", "message": resolved_by})
            continue
        try:
            html, final_url = fetch_public_html(url)
            parsed = parse_product_html(html, final_url)
            raw_path = raw_dir / f"{priority}_{donor.id}.html"
            raw_path.write_text(html, encoding="utf-8")
            db.add(AttributeProductSource(
                product=product,
                donor=donor,
                url=final_url,
                priority=priority,
                role=role,
                status="parsed",
                raw_html_path=str(raw_path),
                parsed_data=parsed,
            ))
            stats = apply_parsed_attributes(
                db,
                product,
                parsed["attributes"],
                source=donor.brand.name,
                priority=priority,
                donor_id=donor.id,
                source_url=final_url,
            )
            reports.append({
                "donor_id": donor.id,
                "name": donor.brand.name,
                "status": "parsed",
                "url": final_url,
                "resolved_by": resolved_by,
                **stats,
            })
        except Exception as error:
            db.add(AttributeProductSource(
                product=product,
                donor=donor,
                url=url,
                priority=priority,
                role=role,
                status="error",
                parsed_data={"message": str(error)},
            ))
            reports.append({"donor_id": donor.id, "name": donor.brand.name, "status": "error", "message": str(error)})
    refresh_product_status(product)
    refresh_batch_summary(product.batch)
    db.add(AttributeProcessingLog(batch_id=product.batch_id, product_id=product.id, action="donor_processing", details={"donors": reports}))
    return {"product_id": product.id, "reports": reports}


def save_mapping_rule(
    db: Session,
    *,
    donor_id: int,
    template: AttributeTemplate,
    field: AttributeTemplateField,
    donor_attribute_name: str,
) -> AttributeMappingRule:
    key = normalize_key(donor_attribute_name)
    if not key:
        raise ValueError("Название атрибута донора не заполнено")
    rule = db.scalar(
        select(AttributeMappingRule).where(
            AttributeMappingRule.donor_id == donor_id,
            AttributeMappingRule.template_id == template.id,
            AttributeMappingRule.normalized_donor_attribute == key,
        )
    )
    if not rule:
        rule = AttributeMappingRule(
            donor_id=donor_id,
            template=template,
            template_field=field,
            donor_attribute_name=clean_text(donor_attribute_name),
            normalized_donor_attribute=key,
        )
        db.add(rule)
    else:
        rule.template_field = field
        rule.donor_attribute_name = clean_text(donor_attribute_name)
        rule.is_active = True
    return rule



def serialize_value(value: AttributeProductValue) -> dict[str, Any]:
    return {
        "id": value.id,
        "field_id": value.template_field_id,
        "group_name": value.group_name,
        "name": value.attribute_name,
        "current_value": value.current_value,
        "proposed_value": value.proposed_value,
        "final_value": value.final_value,
        "source": value.source,
        "confidence": value.confidence,
        "status": value.status,
        "reason": value.reason,
        "dash_reason": value.dash_reason,
        "is_in_template": value.is_in_template,
        "is_extra": value.is_extra_attribute,
        "source_details": value.source_details or {},
        "sort_order": value.sort_order,
    }


def serialize_product(product: AttributeProduct, detailed: bool = False) -> dict[str, Any]:
    result = {
        "id": product.id,
        "model": product.model,
        "name": product.name,
        "brand": product.brand,
        "category_name": product.category_name,
        "source_url": product.source_url,
        "status": product.status,
        "counts": {
            "missing": sum(value.is_in_template and not value.final_value for value in product.values),
            "conflicts": sum(value.status == "conflict" for value in product.values),
            "suggestions": sum(value.status == "suggested" for value in product.values),
        },
    }
    if detailed:
        result["values"] = [serialize_value(value) for value in product.values]
        result["sources"] = [
            {
                "id": source.id,
                "donor_id": source.donor_id,
                "donor_name": source.donor.brand.name if source.donor else "Страница сайта",
                "url": source.url,
                "priority": source.priority,
                "role": source.role,
                "status": source.status,
                "message": (source.parsed_data or {}).get("message", ""),
            }
            for source in product.sources
        ]
    return result


def serialize_batch(batch: AttributeBatch, detailed: bool = False) -> dict[str, Any]:
    result = {
        "id": batch.id,
        "name": batch.name,
        "input_mode": batch.input_mode,
        "processing_mode": batch.processing_mode,
        "status": batch.status,
        "source_filename": batch.source_filename,
        "summary": refresh_batch_summary(batch),
        "template": serialize_template(batch.template),
        "export_ready": bool(batch.export_path and Path(batch.export_path).is_file()),
        "created_at": batch.created_at.isoformat(timespec="seconds") if batch.created_at else "",
    }
    if detailed:
        result["products"] = [serialize_product(product) for product in batch.products]
    return result


def workspace(db: Session) -> dict[str, Any]:
    templates = list(db.scalars(select(AttributeTemplate).order_by(AttributeTemplate.updated_at.desc())))
    batches = list(db.scalars(select(AttributeBatch).order_by(AttributeBatch.updated_at.desc()).limit(30)))
    return {
        "templates": [serialize_template(template) for template in templates],
        "donors": list_donors(db),
        "batches": [serialize_batch(batch) for batch in batches],
    }


def update_product_value(
    value: AttributeProductValue,
    *,
    action: str,
    manual_value: str = "",
    dash_reason: str = "",
) -> AttributeProductValue:
    if value.current_value:
        raise ValueError("Исходное заполненное значение защищено от изменения")
    field = value.template_field
    if action == "accept":
        selected = clean_text(manual_value) or value.proposed_value
        if not selected:
            raise ValueError("Нет предложения для подтверждения")
        if field:
            canonical, confidence, reason, suggestions = _allowed_match(field, selected)
            if not canonical:
                hint = f" Ближайшие: {', '.join(suggestions)}." if suggestions else ""
                raise ValueError("Значения нет в справочнике." + hint)
            selected = canonical
            value.confidence = max(value.confidence, confidence)
            value.reason = clean_text(value.reason) or reason
        value.final_value = selected
        value.proposed_value = selected
        value.status = "approved"
        value.dash_reason = ""
        value.source = value.source or "manual"
    elif action == "reject":
        value.final_value = ""
        value.proposed_value = ""
        value.status = "missing"
        value.reason = "Предложение отклонено пользователем"
    elif action == "dash":
        reason = clean_text(dash_reason)
        if not reason:
            raise ValueError("Для технического пропуска укажите причину")
        value.final_value = "-"
        value.proposed_value = "-"
        value.status = "dash"
        value.dash_reason = reason
        value.reason = "Технический пропуск подтверждён пользователем"
        value.source = "manual"
    else:
        raise ValueError("Неизвестное действие")
    refresh_product_status(value.product)
    refresh_batch_summary(value.product.batch)
    return value


def bulk_action(batch: AttributeBatch, action: str, minimum_confidence: int = 90, dash_reason: str = "") -> int:
    changed = 0
    for product in batch.products:
        for value in product.values:
            if value.current_value or not value.is_in_template:
                continue
            if action == "accept_high" and value.status == "suggested" and value.confidence >= minimum_confidence:
                update_product_value(value, action="accept")
                changed += 1
            elif action == "fill_dashes" and not value.final_value and value.status not in {"conflict"}:
                update_product_value(value, action="dash", dash_reason=dash_reason or "Не найдено после проверки источников")
                changed += 1
        refresh_product_status(product)
    refresh_batch_summary(batch)
    return changed


def apply_similar_products(db: Session, product: AttributeProduct) -> int:
    changed = 0
    peers = list(
        db.scalars(
            select(AttributeProduct).join(AttributeBatch).where(
                AttributeBatch.template_id == product.batch.template_id,
                AttributeProduct.id != product.id,
            ).limit(100)
        )
    )
    for target in product.values:
        field = target.template_field
        if target.current_value or target.final_value or not field:
            continue
        if field.value_type in {"number", "dimensions"}:
            continue
        candidates: list[str] = []
        for peer in peers:
            peer_value = _target_value(peer, field.id)
            if peer_value and peer_value.final_value and peer_value.final_value != "-":
                candidates.append(peer_value.final_value)
        if len(candidates) < 2:
            continue
        counts = {candidate: candidates.count(candidate) for candidate in set(candidates)}
        best, count = max(counts.items(), key=lambda pair: pair[1])
        confidence = round(count / len(candidates) * 80)
        if confidence < 60:
            continue
        apply_candidate(
            product,
            target,
            value=best,
            confidence=confidence,
            source="Похожие товары",
            reason=f"Совпадает у {count} из {len(candidates)} похожих товаров",
            priority=50,
            source_name=field.name,
        )
        changed += 1
    refresh_product_status(product)
    refresh_batch_summary(product.batch)
    return changed


def export_batch_csv(batch: AttributeBatch) -> Path:
    unresolved = [
        value
        for product in batch.products
        for value in product.values
        if value.is_in_template and (not value.final_value or value.status == "conflict")
    ]
    if unresolved:
        raise ValueError(f"Экспорт остановлен: проверьте ещё {len(unresolved)} значений")
    output_dir = ATTRIBUTE_ASSISTANT_DIR / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"attributes_{batch.id}_{uuid.uuid4().hex[:8]}.csv"
    path = output_dir / filename
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["_MODEL_", "_ATTRIBUTES_"], delimiter=";", lineterminator="\r\n")
    writer.writeheader()
    for product in batch.products:
        ordered = sorted(product.values, key=lambda value: (not value.is_in_template, value.sort_order, value.id))
        stack = "\n".join(
            f"{value.group_name}|{value.attribute_name}|{value.final_value}"
            for value in ordered
        )
        writer.writerow({"_MODEL_": product.model, "_ATTRIBUTES_": stack})
    path.write_bytes(stream.getvalue().encode("cp1251", errors="replace"))
    batch.export_path = str(path)
    batch.status = "completed"
    refresh_batch_summary(batch)
    return path


def resolve_export_path(batch: AttributeBatch) -> Path | None:
    if not batch.export_path:
        return None
    path = Path(batch.export_path).resolve()
    root = (ATTRIBUTE_ASSISTANT_DIR / "exports").resolve()
    return path if path.is_file() and root in path.parents else None


def delete_batch_files(batch: AttributeBatch) -> None:
    for raw_path in (batch.original_path, batch.export_path):
        if not raw_path:
            continue
        path = Path(raw_path)
        try:
            resolved = path.resolve()
            if ATTRIBUTE_ASSISTANT_DIR.resolve() in resolved.parents:
                resolved.unlink(missing_ok=True)
        except OSError:
            pass

