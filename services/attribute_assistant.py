"""Isolated attribute-assistant domain logic.

This module deliberately does not import the existing scraping package. Its HTTP
client ignores process proxy variables so the ChatGPT-only proxy can never leak
into donor or product-page requests.
"""

from __future__ import annotations

import base64
import csv
import gzip
import io
import json
import re
import shutil
import socket
import threading
import uuid
from contextlib import nullcontext
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from ipaddress import ip_address
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Iterable
from urllib.parse import urljoin, urlparse

import chardet
import requests
from bs4 import BeautifulSoup
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session, object_session, selectinload

from config import ATTRIBUTE_ASSISTANT_DIR, ATTRIBUTE_ASSISTANT_MAX_URLS, REQUEST_TIMEOUT
from models import (
    AttributeAllowedValue,
    AttributeBatch,
    AttributeCategory,
    AttributeMappingRule,
    AttributeValueMappingRule,
    AttributeProductRevision,
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
DIMENSION_AXIS_TOKEN_PATTERN = (
    r"(?:ширин[а-яё]*|высот[а-яё]*|глубин[а-яё]*|длин[а-яё]*|"
    r"width|height|depth|length|[швгдwhdl])"
)
DIMENSION_AXIS_SEQUENCE_RE = re.compile(
    r"(?<![a-zа-яё])(" + DIMENSION_AXIS_TOKEN_PATTERN + r")"
    r"(?:\s*(?:[xх×*/;,]|\bby\b)\s*(" + DIMENSION_AXIS_TOKEN_PATTERN + r")){1,3}"
    r"(?![a-zа-яё])",
    re.IGNORECASE,
)
DIMENSION_AXIS_TOKEN_RE = re.compile(DIMENSION_AXIS_TOKEN_PATTERN, re.IGNORECASE)
DIMENSION_AXIS_LABELS = {
    "width": "Ширина",
    "height": "Высота",
    "depth": "Глубина",
    "length": "Длина",
}
HEADER_GROUP_RE = re.compile(r"^(.*?)\s*\(([^()]*)\)\s*$")
WORD_RE = re.compile(r"[a-zа-яё0-9]+", re.IGNORECASE)
SPECIFICATION_HEADING_RE = re.compile(
    r"(?:характеристик|параметр|спецификац|specification|properties)",
    re.IGNORECASE,
)
UI_NOISE_SELECTOR = (
    "script,style,svg,canvas,noscript,.glossary-tooltip,.tooltip,.popover,"
    ".tooltip-popper,[data-tooltip-content],[role='tooltip']"
)
IGNORED_NAME_TOKENS = {
    "максимальная", "максимальный", "макс", "мин", "об", "минуту", "ед",
    "значение", "характеристика", "параметр", "тип",
}
IGNORED_NAME_TOKENS.update({
    "система", "функция", "режим", "товар", "товара", "хранение", "хранения",
    "шт", "см", "мм", "метр", "метра", "литр", "литра", "вт", "гц",
    "кг", "дб", "эл", "расход",
})
IGNORED_NAME_TOKENS.update({"основной", "основная", "общий", "общая", "общее"})
BOOLEAN_TRUE_KEYS = {"да", "есть", "yes", "true", "1", "имеется", "присутствует"}
BOOLEAN_FALSE_KEYS = {"нет", "no", "false", "0", "отсутствует"}
RUSSIAN_NAME_SUFFIXES = (
    "иями", "ями", "ами", "ого", "ему", "ыми", "ими", "ией",
    "иях", "ах", "ях", "ий", "ый", "ая", "яя", "ое", "ее", "ые", "ие",
    "ов", "ев", "ом", "ем", "ам", "ям", "ию", "ью", "ия", "ии",
    "ей", "ой", "а", "я", "ы", "и", "у", "ю", "е",
)

NUMBER_WITH_UNIT_RE = re.compile(
    r"^\s*([+-]?\d+(?:[.,]\d+)?)\s*"
    r"(месяц(?:а|ев)?|мес\.?|год(?:а|ов)?|лет|квт(?:/ч)?|вт(?:/ч)?|см|мм|м|кг|мг|г|мл|л|дб|гц|ч)?\s*$",
    re.IGNORECASE,
)
LINEAR_UNIT_FACTORS: dict[str, tuple[str, Decimal]] = {
    "мм": ("length", Decimal("0.001")),
    "см": ("length", Decimal("0.01")),
    "м": ("length", Decimal("1")),
    "мг": ("mass", Decimal("0.001")),
    "г": ("mass", Decimal("1")),
    "кг": ("mass", Decimal("1000")),
    "мл": ("volume", Decimal("0.001")),
    "л": ("volume", Decimal("1")),
    "вт": ("power", Decimal("1")),
    "квт": ("power", Decimal("1000")),
}
LINEAR_UNIT_ALIASES = {
    "миллиметр": "мм", "миллиметра": "мм", "миллиметров": "мм",
    "сантиметр": "см", "сантиметра": "см", "сантиметров": "см",
    "метр": "м", "метра": "м", "метров": "м",
    "миллиграмм": "мг", "миллиграмма": "мг", "миллиграммов": "мг",
    "грамм": "г", "грамма": "г", "граммов": "г",
    "килограмм": "кг", "килограмма": "кг", "килограммов": "кг",
    "миллилитр": "мл", "миллилитра": "мл", "миллилитров": "мл",
    "литр": "л", "литра": "л", "литров": "л",
    **{unit: unit for unit in LINEAR_UNIT_FACTORS},
}
PROCESSING_MODES = {
    "check", "suggest", "auto", "auto_exact", "auto_primary",
    "auto_confident", "auto_all",
}

MAX_PUBLIC_REDIRECTS = 8
TEMPLATE_SNAPSHOT_SCHEMA = "attribute-template-snapshot"
PRODUCT_SNAPSHOT_SCHEMA = "attribute-product-snapshot"
SNAPSHOT_FORMAT_VERSION = 2

def product_template(product: AttributeProduct) -> AttributeTemplate | None:
    """Return the product-specific template; legacy rows fall back to their batch."""

    if product.template is not None:
        return product.template
    if bool((product.processing_state or {}).get("template_unresolved")):
        return None
    if product.template_id is None and product.batch is not None:
        return product.batch.template
    return None


def clean_text(value: Any) -> str:
    return SPACE_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip()


def is_technical_dash(value: Any) -> bool:
    """Return whether a value is the persisted technical-gap marker."""

    return clean_text(value) in {"-", "–", "—", "−"}

def clean_csv_cell(value: Any) -> str:
    return str(value or "").replace("\r\n", "\n").replace("\r", "\n").strip()



def normalize_key(value: Any) -> str:
    text = clean_text(value).casefold().replace("ё", "е")
    return " ".join(WORD_RE.findall(text))


def normalize_model(value: Any) -> str:
    return re.sub(r"[^A-ZА-ЯЁ0-9]", "", clean_text(value).upper())


def model_tokens(value: Any) -> list[str]:
    return re.findall(r"[a-zа-яё]+|\d+", clean_text(value).casefold(), re.IGNORECASE)


def _canonical_name_token(token: str) -> str:
    aliases = {
        "полок": "полка",
        "дверца": "дверь",
        "дверной": "дверь",
        "фасад": "дверь",
        "габарит": "размер",
        "габариты": "размер",
        "монтаж": "крепление",
        "электроэнергия": "энергия",
        "энергопотребление": "энергия",
    }
    token = aliases.get(token, token)
    if token.startswith(("двер", "фасад")):
        return "двер"
    if token.startswith(("суперзамораж", "суперзамороз")):
        return "суперзаморозка"
    if token.startswith("энергопотреб"):
        return "энергия"
    if token.startswith("электроэнерг"):
        return "энергия"
    if token.startswith("отделен"):
        return "камер"
    for suffix in RUSSIAN_NAME_SUFFIXES:
        if token.endswith(suffix) and len(token) - len(suffix) >= 4:
            token = token[:-len(suffix)]
            break
    if token.startswith("отделен"):
        return "камер"
    return token


def _name_tokens(value: Any) -> set[str]:
    text = clean_text(value).casefold().replace("ё", "е")
    # Axis order describes the tuple layout, not the attribute's semantic identity.
    # Treating ШxВxГ and ВxШxГ as words prevents otherwise identical fields from mapping.
    text = DIMENSION_AXIS_SEQUENCE_RE.sub(" ", text)
    text = re.sub(r"\bх\s*\.?\s*к\s*\.?\b", " холодильная камера ", text)
    text = re.sub(r"\bм\s*\.?\s*к\s*\.?\b", " морозильная камера ", text)
    # English marketing explanations in brackets reduce Russian-name similarity.
    text = re.sub(r"\([^)]*[a-z][^)]*\)", " ", text, flags=re.IGNORECASE)
    tokens = []
    for token in WORD_RE.findall(text):
        if token in IGNORED_NAME_TOKENS or len(token) <= 1:
            continue
        canonical = _canonical_name_token(token)
        if canonical and canonical not in IGNORED_NAME_TOKENS:
            tokens.append(canonical)
    return set(tokens)


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


def exact_value_key(value: Any) -> str:
    """Compare the actual value, preserving case, letters, punctuation and inner spaces."""
    return "" if value is None else str(value).strip()


def value_match_key(value: Any) -> str:
    """Ignore letter case when matching; preserve punctuation, letters and inner spaces."""
    return exact_value_key(value).lower()


def _canonical_matching_value(allowed: Iterable[AttributeAllowedValue], value: Any) -> str:
    active = [item for item in allowed if item.is_active]
    exact_key = exact_value_key(value)
    exact = next((item.value for item in active if exact_value_key(item.value) == exact_key), "")
    if exact:
        return exact
    key = value_match_key(value)
    return next((item.value for item in active if value_match_key(item.value) == key), "") if key else ""


def dictionary_value_key(value: Any, value_type: str = "select") -> str:
    # Persist literal keys so imported IDs and dictionary spelling remain unchanged.
    return exact_value_key(value)


def set_field_value_type(db: Session, field: AttributeTemplateField, value_type: str) -> None:
    # Accept historical snapshots and clients; every dictionary now uses exact keys.
    field.value_type = "select" if value_type == "select_exact" else value_type


def normalize_value(value: Any, value_type: str = "select", composite: bool = False) -> str:
    text = exact_value_key(value)
    if not text:
        return ""
    if value_type == "number":
        return normalize_number(text)
    if value_type == "dimensions":
        return normalize_dimensions(text)
    if value_type == "boolean":
        key = exact_value_key(text).casefold()
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
    return "select", False


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


def serialize_template(
    template: AttributeTemplate,
    include_values: bool = False,
    *,
    include_allowed_values: bool = True,
    allowed_value_counts: dict[int, int] | None = None,
) -> dict[str, Any]:
    result = {
        "id": template.id,
        "name": template.name,
        "category": template.category.full_path or template.category.name,
        "product_type": template.product_type,
        "description": template.description,
        "is_default": template.is_default,
        "is_active": template.is_active,
        "version": template.version,
        "updated_at": template.updated_at.isoformat(timespec="seconds") if template.updated_at else "",
        "field_count": len(template.fields),
    }
    if include_values:
        result["fields"] = [
            {
                "id": field.id,
                "group_name": field.group_name,
                "name": field.name,
                "synonyms": list(field.synonyms or []),
                "value_type": field.value_type,
                "is_composite": field.is_composite,
                "is_required": field.is_required,
                "separator": field.separator,
                "use_dash_if_empty": field.use_dash_if_empty,
                "conversion_rules": list(field.conversion_rules or []),
                "sort_order": field.sort_order,
                "allowed_values_count": (
                    allowed_value_counts.get(field.id, 0)
                    if allowed_value_counts is not None
                    else len(field.allowed_values)
                ),
                "allowed_values": [
                    {
                        "id": allowed.id,
                        "value": allowed.value,
                        "is_combination": allowed.is_combination,
                        "is_active": allowed.is_active,
                        "synonyms": [item.synonym for item in allowed.synonyms],
                    }
                    for allowed in field.allowed_values
                ] if include_allowed_values else [],
            }
            for field in template.fields
        ]
    return result


def allowed_value_options(
    field: AttributeTemplateField,
    query: str = "",
    limit: int = 80,
    offset: int = 0,
    include_inactive: bool = False,
) -> dict[str, Any]:
    available = [item for item in field.allowed_values if include_inactive or item.is_active]
    query_key = exact_value_key(query).casefold()
    if query_key:
        ranked: list[tuple[int, int, AttributeAllowedValue]] = []
        for item in available:
            # Search may ignore case; it never merges entries or accepts a value.
            searchable = [exact_value_key(item.value).casefold(), *(
                exact_value_key(synonym.synonym).casefold() for synonym in item.synonyms
            )]
            matching = [text for text in searchable if query_key in text]
            if not matching:
                continue
            quality = min(
                0 if text == query_key else 1 if text.startswith(query_key) else 2
                for text in matching
            )
            ranked.append((quality, item.sort_order, item))
        ranked.sort(key=lambda row: (row[0], row[1], row[2].value.casefold()))
        matches = [item for _quality, _order, item in ranked]
    else:
        matches = available
    safe_limit = max(1, min(int(limit or 80), 200))
    safe_offset = max(0, int(offset or 0))
    page = matches[safe_offset:safe_offset + safe_limit]
    return {
        "field_id": field.id,
        "total": len(available),
        "matched": len(matches),
        "offset": safe_offset,
        "limit": safe_limit,
        "has_more": safe_offset + len(page) < len(matches),
        "values": [
            {
                "id": item.id,
                "value": item.value,
                "is_active": item.is_active,
                "is_combination": item.is_combination,
                "synonyms": [synonym.synonym for synonym in item.synonyms],
            }
            for item in page
        ],
    }


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
            raw_entries: list[tuple[str, bool]] = []
            if composite:
                parts = [part for part in raw_value.split("/") if clean_text(part)]
                if len(parts) > 1:
                    raw_entries.append((normalize_value(raw_value, value_type, True), True))
                raw_entries.extend((part, False) for part in parts)
            else:
                raw_entries.append((raw_value, False))
            for raw_part, is_combination in raw_entries:
                try:
                    normalized = normalize_value(raw_part, value_type, False)
                except ValueError:
                    continue
                key = dictionary_value_key(normalized, field.value_type)
                if not key or key in seen:
                    continue
                seen.add(key)
                allowed_items.append(normalized)
                db.add(
                    AttributeAllowedValue(
                        field=field,
                        value=normalized,
                        normalized_value=key,
                        is_combination=is_combination,
                        sort_order=len(allowed_items) - 1,
                    )
                )
        snapshot_fields.append({"group": group_name, "name": attribute_name, "type": value_type, "values": allowed_items})
    db.flush()
    save_template_revision(db, template, "import", {"fields_count": len(snapshot_fields)})
    return template


def add_allowed_value(db: Session, field: AttributeTemplateField, value: str, synonym: str = "") -> AttributeAllowedValue:
    normalized = normalize_value(value, field.value_type, False)
    if len(normalized) > 1000:
        raise ValueError("Значение не должно превышать 1000 символов")
    key = dictionary_value_key(normalized, field.value_type)
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
    synonym_key = dictionary_value_key(synonym, field.value_type)
    if len(clean_text(synonym)) > 1000:
        raise ValueError("Синоним не должен превышать 1000 символов")
    if synonym_key and not any(item.normalized_synonym == synonym_key for item in allowed.synonyms):
        db.add(AttributeValueSynonym(allowed_value=allowed, synonym=exact_value_key(synonym), normalized_synonym=synonym_key))
    return allowed


def replace_allowed_value_synonyms(
    db: Session,
    allowed: AttributeAllowedValue,
    synonyms: Iterable[object],
) -> list[AttributeValueSynonym]:
    """Replace an allowed value's synonyms with a normalized, de-duplicated list."""
    raw_synonyms = list(synonyms)
    if len(raw_synonyms) > 100:
        raise ValueError("Для одного значения допускается не больше 100 синонимов")
    canonical_key = dictionary_value_key(allowed.value, allowed.field.value_type)
    existing = {item.normalized_synonym: item for item in allowed.synonyms}
    replacement: list[AttributeValueSynonym] = []
    seen: set[str] = set()

    for raw_synonym in raw_synonyms:
        synonym = exact_value_key(raw_synonym)
        if len(synonym) > 1000:
            raise ValueError("Синоним не должен превышать 1000 символов")
        synonym_key = dictionary_value_key(synonym, allowed.field.value_type)
        if not synonym_key or synonym_key == canonical_key or synonym_key in seen:
            continue
        seen.add(synonym_key)
        item = existing.get(synonym_key)
        if item is None:
            item = AttributeValueSynonym(
                allowed_value=allowed,
                synonym=synonym,
                normalized_synonym=synonym_key,
            )
        else:
            item.synonym = synonym
        replacement.append(item)

    allowed.synonyms = replacement
    db.flush()
    return replacement


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
            "value": exact_value_key(parts[2]),
        })
    return result


def _row_value(row: dict[str, str], *names: str) -> str:
    wanted = {normalize_key(name) for name in names}
    for key, value in row.items():
        if normalize_key(key) in wanted:
            return clean_csv_cell(value) if "attributes" in wanted else clean_text(value)
    return ""


def _make_product_values(
    product: AttributeProduct,
    template: AttributeTemplate,
    stack: list[dict[str, str]],
    *,
    current_source: str = "current_csv",
    current_role: str = "Исходный CSV сайта",
) -> None:
    existing_by_name: dict[str, list[dict[str, str]]] = {}
    for item in stack:
        existing_by_name.setdefault(normalize_key(item["name"]), []).append(item)
    canonical_keys = {normalize_key(field.name) for field in template.fields}
    synonym_owners: dict[str, list[AttributeTemplateField]] = {}
    for field in template.fields:
        for synonym in field.synonyms or []:
            key = normalize_key(synonym)
            if key and key not in canonical_keys and field not in synonym_owners.get(key, []):
                synonym_owners.setdefault(key, []).append(field)
    consumed: set[int] = set()
    for field in template.fields:
        candidates = existing_by_name.get(normalize_key(field.name), [])
        if not candidates:
            candidates = [
                item
                for key, owners in synonym_owners.items()
                if owners == [field]
                for item in existing_by_name.get(key, [])
            ]
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
        if is_technical_dash(current):
            current = "-"
        if matched:
            consumed.add(id(matched))
        final = ""
        source = current_source if current else ""
        confidence = 0
        status = "missing"
        reason = ""
        source_details: dict[str, Any] = {}
        dash_reason = ""
        if current == "-":
            final = "-"
            status = "dash"
            reason = "Технический пропуск сохранён из исходного файла"
            dash_reason = "Импортировано из исходного CSV"
        elif current:
            matched_source_name = clean_text(
                matched.get("source_name") or matched.get("name")
            ) if matched else ""
            canonical, match_confidence, match_reason, suggestions = _allowed_match(
                field, current, matched_source_name or field.name
            )
            if canonical:
                final = canonical
                confidence = match_confidence
                status = "kept"
                reason = (
                    "Исходное значение приведено к каноническому значению справочника"
                    if canonical != current else "Исходное значение подтверждено справочником"
                )
            else:
                status = "suggested" if suggestions else "conflict"
                reason = match_reason
                source_details = {
                    "unknown_values": [{
                        "value": current,
                        "source": current_source,
                        "source_name": matched_source_name or field.name,
                        "url": product.source_url,
                        "role": current_role,
                        "suggestions": suggestions,
                        "reason": match_reason,
                    }]
                }
            if matched_source_name and matched_source_name != field.name:
                source_details["current_source_name"] = matched_source_name
            centimeters = _centimeter_value(current, matched_source_name or field.name, field.name)
            if centimeters is not None and centimeters != current:
                source_details["current_value_hint"] = f"{matched_source_name or field.name}: {current} → {centimeters} см"
        product.values.append(
            AttributeProductValue(
                template_field=field,
                group_name=field.group_name,
                attribute_name=field.name,
                current_value=current,
                proposed_value=suggestions[0] if current and status == "suggested" else "",
                final_value=final,
                source=source,
                confidence=confidence,
                status=status,
                reason=reason,
                dash_reason=dash_reason,
                source_details=source_details,
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
                source=current_source,
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
        processing_mode=processing_mode if processing_mode in PROCESSING_MODES else "suggest",
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
            template=template,
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
        return bool(addresses) and all(ip_address(address).is_global for address in addresses)
    except (OSError, ValueError):
        return False


def _open_public_response(
    session: requests.Session,
    url: str,
    *,
    headers: dict[str, str] | None = None,
) -> tuple[requests.Response, str]:
    """Open a public URL while validating every redirect before following it."""

    current_url = clean_text(url)
    visited: set[str] = set()
    for _redirect in range(MAX_PUBLIC_REDIRECTS + 1):
        if not _is_public_url(current_url):
            raise ValueError("Разрешены только публичные HTTP(S)-адреса")
        if current_url in visited:
            raise ValueError("Обнаружен циклический HTTP-редирект")
        visited.add(current_url)
        response = session.get(
            current_url,
            timeout=REQUEST_TIMEOUT,
            headers=headers or {},
            allow_redirects=False,
            stream=True,
        )
        if response.status_code not in {301, 302, 303, 307, 308}:
            return response, current_url
        location = clean_text(response.headers.get("location"))
        response.close()
        if not location:
            raise ValueError("Сервер вернул редирект без адреса назначения")
        current_url = urljoin(current_url, location)
        if not _is_public_url(current_url):
            raise ValueError("Страница перенаправила запрос на закрытый адрес")
    raise ValueError(f"Слишком много HTTP-редиректов (больше {MAX_PUBLIC_REDIRECTS})")


def _resolve_public_redirect_url(url: str) -> str:
    """Resolve HTTP redirects safely before handing a URL to a native engine."""

    with requests.Session() as session:
        session.trust_env = False
        response, final_url = _open_public_response(
            session,
            url,
            headers={
                "User-Agent": "Mozilla/5.0 (compatible; AttributeAssistant/1.0)",
                "Range": "bytes=0-0",
            },
        )
        response.close()
        return final_url


def fetch_public_html(url: str, max_bytes: int = 5 * 1024 * 1024) -> tuple[str, str]:
    with requests.Session() as session:
        session.trust_env = False
        response, final_url = _open_public_response(
            session,
            url,
            headers={"User-Agent": "Mozilla/5.0 (compatible; AttributeAssistant/1.0)"},
        )
        try:
            response.raise_for_status()
            chunks: list[bytes] = []
            size = 0
            for chunk in response.iter_content(65536):
                size += len(chunk)
                if size > max_bytes:
                    raise ValueError("Страница превышает допустимый размер")
                chunks.append(chunk)
            payload = b"".join(chunks)
            encoding = response.encoding or (chardet.detect(payload).get("encoding") if payload else None) or "utf-8"
            return payload.decode(encoding, errors="replace"), final_url
        finally:
            response.close()


class DonorPageFetcher:
    """Own all network engines for one Attribute Assistant processing run.

    Browser-backed donor methods share one dispatcher. Switching to a
    different browser engine closes the previous one first, so a run never owns
    more than one browser process. max_pages remains the maximum number of tabs
    in that browser.
    """

    def __init__(self, max_pages: int) -> None:
        from services.projects import parse_thread_count

        self.max_pages = max(1, parse_thread_count(max_pages))
        self._browser_session: Any = None
        self._browser_engine = ""
        self._browser_condition = threading.Condition(threading.RLock())
        self._active_browser_fetches = 0

    @staticmethod
    def _browser_engine_for(method_code: str) -> str:
        if method_code.startswith("botasaurus-browser") or method_code == "botasaurus-visible":
            return "botasaurus"
        if method_code == "botasaurus-debug-visible":
            return "botasaurus-debug-visible"
        if method_code == "crawl4ai":
            return "crawl4ai"
        if method_code == "scrapegraphai":
            return "scrapegraphai"
        return "playwright"

    def fetch_browser(self, donor: Donor, url: str) -> str | None:
        from services.scraping.browser import BrowserMethodSession

        method = donor.connection_method_row
        method_code = clean_text(method.code if method else "playwright") or "playwright"
        engine = self._browser_engine_for(method_code)
        with self._browser_condition:
            while self._active_browser_fetches and engine != self._browser_engine:
                self._browser_condition.wait()
            if self._browser_session is None:
                self._browser_session = BrowserMethodSession(
                    max_pages=self.max_pages,
                    initial_method=method_code,
                )
                self._browser_engine = engine
            elif engine != self._browser_engine:
                self._browser_session.restart(method=method_code)
                self._browser_engine = engine
            browser_session = self._browser_session
            self._active_browser_fetches += 1
        try:
            return browser_session.fetch(
                url,
                method_code,
                rules=dict(donor.extraction_rules or {}),
                product_url_filters=list(donor.product_url_filters or []),
                allow_empty_price=True,
            )
        finally:
            with self._browser_condition:
                self._active_browser_fetches -= 1
                self._browser_condition.notify_all()

    def close(self) -> None:
        with self._browser_condition:
            while self._active_browser_fetches:
                self._browser_condition.wait()
            if self._browser_session is not None:
                self._browser_session.close()
                self._browser_session = None
                self._browser_engine = ""

    def __enter__(self) -> "DonorPageFetcher":
        return self

    def __exit__(self, _error_type, _error, _traceback) -> None:
        self.close()


def fetch_donor_product_html(
    donor: Donor,
    url: str,
    max_bytes: int = 5 * 1024 * 1024,
    *,
    fetcher: DonorPageFetcher | None = None,
) -> tuple[str, str]:
    """Load one donor page through its saved connection method without changing parser runtime."""

    method = donor.connection_method_row
    method_code = clean_text(method.code if method else "requests") or "requests"
    if method_code == "requests":
        return fetch_public_html(url, max_bytes=max_bytes)
    final_url = _resolve_public_redirect_url(url)
    owns_fetcher = fetcher is None
    fetcher = fetcher or DonorPageFetcher(max_pages=donor.thread_count)
    try:
        if method and (method.is_browser_render or method.is_debug_visible):
            html = fetcher.fetch_browser(donor, final_url)
        elif method_code == "botasaurus-request":
            from services.scraping.http import fetch_with_botasaurus_request

            html = fetch_with_botasaurus_request(final_url)
        elif method_code == "scrapy":
            from services.scraping.browser import fetch_with_scrapy

            html = fetch_with_scrapy(final_url)
        elif method_code == "crawlee":
            from services.scraping.browser import fetch_with_crawlee

            html = fetch_with_crawlee(final_url)
        else:
            raise ValueError(f"Метод подключения «{method.name if method else method_code}» не поддерживается")
    finally:
        if owns_fetcher:
            fetcher.close()
    if html:
        if len(html.encode("utf-8", errors="ignore")) > max_bytes:
            raise ValueError("Страница превышает допустимый размер")
        return html, final_url
    if donor.auto_connection_fallback:
        return fetch_public_html(final_url, max_bytes=max_bytes)
    raise ValueError(f"Метод подключения «{method.name if method else method_code}» не смог открыть страницу")

def _jsonld_items(value: Any) -> Iterable[dict[str, Any]]:
    if isinstance(value, dict):
        if isinstance(value.get("@graph"), list):
            for item in value["@graph"]:
                yield from _jsonld_items(item)
        yield value
    elif isinstance(value, list):
        for item in value:
            yield from _jsonld_items(item)


def _remove_ui_noise(node: Any) -> None:
    # Remove children first because tooltip containers may be nested.
    for noisy in reversed(node.select(UI_NOISE_SELECTOR)):
        noisy.decompose()


def _text_without_ui_noise(node: Any) -> str:
    """Read a specification cell without tooltip/help text nested inside it."""

    fragment = BeautifulSoup(str(node), "html.parser")
    _remove_ui_noise(fragment)
    return clean_text(fragment.get_text(" "))


def _append_parsed_attribute(
    result: dict[str, Any],
    seen: set[tuple[str, str]],
    name: Any,
    value: Any,
    group: Any = "",
) -> None:
    clean_name = clean_text(name).rstrip(":").strip()
    clean_value = exact_value_key(value)
    key = (normalize_key(clean_name), exact_value_key(clean_value))
    if not clean_name or not clean_value or clean_name == clean_value or key in seen:
        return
    result["attributes"].append({
        "name": clean_name,
        "value": clean_value,
        "group": clean_text(group),
    })
    seen.add(key)


def _structural_specification_roots(soup: BeautifulSoup) -> list[Any]:
    roots: list[Any] = []
    seen: set[int] = set()
    for heading in soup.find_all(re.compile(r"^h[1-6]$", re.IGNORECASE)):
        if not SPECIFICATION_HEADING_RE.search(_text_without_ui_noise(heading)):
            continue
        level = int(str(heading.name)[1])
        sibling = heading.find_next_sibling()
        while sibling is not None:
            sibling_name = str(getattr(sibling, "name", "") or "").lower()
            if re.fullmatch(r"h[1-6]", sibling_name) and int(sibling_name[1]) <= level:
                break
            if sibling_name and id(sibling) not in seen:
                seen.add(id(sibling))
                roots.append(sibling)
            sibling = sibling.find_next_sibling()
    return roots


def _append_structural_specification_attributes(
    result: dict[str, Any],
    seen: set[tuple[str, str]],
    soup: BeautifulSoup,
) -> None:
    """Read repeated two-column rows inside a characteristics section without site CSS."""

    ignored_names = {
        "характеристики", "характеристики товара", "параметры", "описание",
        "показать все характеристики", "скрыть характеристики",
    }
    for root in _structural_specification_roots(soup):
        for row in root.find_all(["div", "li", "section"], recursive=True):
            if row.find(["button", "input", "select", "textarea", "form"]):
                continue
            children = [
                child for child in row.find_all(recursive=False)
                if getattr(child, "name", None)
                and child.name not in {"script", "style", "svg", "noscript"}
                and _text_without_ui_noise(child)
            ]
            if len(children) != 2:
                continue
            # Inline fragments commonly split a label into its title and axis order
            # (for example, "Габаритные размеры" + "(ШxВxГ)"). Only nested
            # block collections indicate that this is a wrapper around more rows.
            if any(
                len([
                    nested for nested in child.find_all(recursive=False)
                    if getattr(nested, "name", None) in {
                        "div", "li", "section", "table", "dl", "ul", "ol",
                    }
                    and _text_without_ui_noise(nested)
                ]) >= 2
                for child in children
            ):
                continue
            name = _text_without_ui_noise(children[0]).rstrip(":").strip()
            value = _text_without_ui_noise(children[1])
            if (
                not name
                or not value
                or len(name) > 240
                or len(value) > 2000
                or normalize_key(name) in ignored_names
            ):
                continue
            group = ""
            heading = row.find_previous(re.compile(r"^h[3-6]$", re.IGNORECASE))
            if heading is not None and root in heading.parents:
                group = _text_without_ui_noise(heading)
            _append_parsed_attribute(result, seen, name, value, group)


def _infer_product_model(name: str, url: str = "", brand: str = "") -> str:
    """Extract a model-like code from generic product metadata without brand rules."""

    tokens = re.findall(r"[A-Za-zА-Яа-яЁё0-9][A-Za-zА-Яа-яЁё0-9./_@-]*", clean_text(name))
    brand_key = normalize_key(brand)
    url_model = normalize_model(Path(urlparse(url).path).stem)
    ranked: list[tuple[int, int, str]] = []
    for end in range(1, len(tokens) + 1):
        for width in range(1, min(3, end) + 1):
            parts = tokens[end - width:end]
            candidate = " ".join(parts).strip(" .,/\\_-")
            compact = normalize_model(candidate)
            if (
                len(compact) < 4
                or not any(char.isalpha() for char in candidate)
                or not any(char.isdigit() for char in candidate)
                or normalize_key(parts[0]) == brand_key
            ):
                continue
            score = 100 - width * 8
            if url_model and compact in url_model:
                score += 80
            if end == len(tokens):
                score += 15
            if len(compact) >= 6:
                score += 5
            ranked.append((score, -width, candidate))
    if ranked:
        return max(ranked)[2]
    slug = clean_text(Path(urlparse(url).path.rstrip("/")).stem)
    if (
        slug
        and any(char.isalpha() for char in slug)
        and any(char.isdigit() for char in slug)
    ):
        return slug
    return ""


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
                        "value": exact_value_key(prop.get("value")),
                        "group": "",
                    })
    # Read JSON-LD first, then exclude help panels from row discovery as well as cell text.
    # A tooltip's title/body pair otherwise looks like a two-column specification.
    _remove_ui_noise(soup)
    selectors = ("table tr", ".characteristics tr", ".specifications tr", ".properties tr")
    seen = {(normalize_key(item["name"]), exact_value_key(item["value"])) for item in result["attributes"]}
    for row in soup.select(",".join(selectors)):
        cells = row.find_all(["th", "td"], recursive=False) or row.find_all(["th", "td"])
        if len(cells) < 2:
            continue
        _append_parsed_attribute(
            result,
            seen,
            _text_without_ui_noise(cells[0]),
            _text_without_ui_noise(cells[-1]),
        )
    for term in soup.select("dl dt"):
        definition = term.find_next_sibling("dd")
        if not definition:
            continue
        _append_parsed_attribute(
            result,
            seen,
            _text_without_ui_noise(term),
            _text_without_ui_noise(definition),
        )

    # Product sites often render specifications as semantic div/span pairs rather than tables.
    # Keep the selectors structural so this works across categories without domain-specific code.
    semantic_rows = (
        (".detail-properties__field", ".detail-properties__name", ".detail-properties__value"),
        (".characteristics__row", ".characteristics__name", ".characteristics__property"),
        (".characteristic__row", ".characteristic__name", ".characteristic__value"),
        (".specifications__row", ".specifications__name", ".specifications__value"),
        (".specification__row", ".specification__name", ".specification__value"),
        (".properties__row", ".properties__name", ".properties__value"),
        (".property__row", ".property__name", ".property__value"),
        (".parameters__row", ".parameters__name", ".parameters__value"),
        (".parameter__row", ".parameter__name", ".parameter__value"),
        ("[data-characteristic]", "[data-characteristic-name]", "[data-characteristic-value]"),
    )
    for row_selector, name_selector, value_selector in semantic_rows:
        for row in soup.select(row_selector):
            name_node = row.select_one(name_selector)
            value_node = row.select_one(value_selector)
            if not name_node or not value_node:
                continue
            group = ""
            block = row.find_parent(
                class_=re.compile(r"(?:characteristic|specification|propert|parameter).*(?:block|group)", re.I)
            )
            if block:
                heading = block.select_one(
                    ".characteristics__title,.characteristic__title,.specifications__title,"
                    ".specification__title,.properties__title,.parameters__title,h2,h3,h4"
                )
                group = _text_without_ui_noise(heading) if heading else ""
            _append_parsed_attribute(
                result,
                seen,
                _text_without_ui_noise(name_node),
                _text_without_ui_noise(value_node),
                group,
            )
    _append_structural_specification_attributes(result, seen, soup)
    if not result["name"]:
        heading = soup.select_one("h1")
        result["name"] = clean_text(heading.get_text(" ")) if heading else ""
    if not result["model"]:
        for attr in result["attributes"]:
            if normalize_key(attr["name"]) in {
                "модель", "код модели", "номер модели", "артикул", "код товара",
                "код продукта", "sku", "mpn",
            }:
                result["model"] = attr["value"]
                break
    if not result["model"]:
        for selector, attribute in (
            ('meta[itemprop="model"]', "content"),
            ('meta[itemprop="sku"]', "content"),
            ('meta[itemprop="mpn"]', "content"),
            ('[itemprop="model"]', None),
            ('[itemprop="sku"]', None),
            ('[data-product-model]', "data-product-model"),
            ('[data-model]', "data-model"),
        ):
            node = soup.select_one(selector)
            value = clean_text(node.get(attribute) if node and attribute else node.get_text(" ") if node else "")
            if value:
                result["model"] = value
                break
    if not result["model"]:
        result["model"] = _infer_product_model(
            result["name"],
            url,
            result["brand"],
        )
    crumbs = [clean_text(node.get_text(" ")) for node in soup.select('[itemprop="itemListElement"], .breadcrumb a, .breadcrumbs a')]
    if crumbs and not result["category"]:
        result["category"] = " > ".join(dict.fromkeys(item for item in crumbs if item))
    return result


def parse_product_html_for_donor(
    html: str,
    url: str,
    donor: Donor | None = None,
) -> dict[str, Any]:
    """Apply Attribute Assistant selectors without changing the parser monolith."""

    result = parse_product_html(html, url)
    if donor is None:
        return result
    settings = dict(donor.selector_settings or {})
    scoped = settings.get("attribute_assistant")
    if isinstance(scoped, dict):
        settings = {**settings, **scoped}
    rules = dict(donor.extraction_rules or {})
    soup = BeautifulSoup(html, "html.parser")
    _remove_ui_noise(soup)

    def selected_text(selector: object) -> str:
        text_selector = clean_text(selector)
        if not text_selector:
            return ""
        node = soup.select_one(text_selector)
        return _text_without_ui_noise(node) if node else ""

    try:
        result["name"] = selected_text(settings.get("name_selector")) or result["name"]
        result["model"] = (
            selected_text(settings.get("model_selector"))
            or selected_text(rules.get("model_selector"))
            or result["model"]
        )
        result["category"] = selected_text(settings.get("category_selector")) or result["category"]
        description = selected_text(settings.get("description_selector"))
        if description:
            result["description"] = description
        row_selector = clean_text(settings.get("attribute_row_selector"))
        name_selector = clean_text(settings.get("attribute_name_selector"))
        value_selector = clean_text(settings.get("attribute_value_selector"))
        group_selector = clean_text(settings.get("attribute_group_selector"))
        if row_selector and name_selector and value_selector:
            seen = {
                (normalize_key(item.get("name")), exact_value_key(item.get("value")))
                for item in result["attributes"]
            }
            for row in soup.select(row_selector):
                name_node = row.select_one(name_selector)
                value_node = row.select_one(value_selector)
                group_node = row.select_one(group_selector) if group_selector else None
                _append_parsed_attribute(
                    result,
                    seen,
                    _text_without_ui_noise(name_node) if name_node else "",
                    _text_without_ui_noise(value_node) if value_node else "",
                    _text_without_ui_noise(group_node) if group_node else "",
                )
    except Exception as error:
        result["selector_error"] = clean_text(error)
    return result


def find_template_for_category(
    db: Session,
    category: str,
    attributes: list[dict[str, Any]] | None = None,
) -> AttributeTemplate | None:
    key = normalize_key(category)
    templates = list(db.scalars(
        select(AttributeTemplate).where(AttributeTemplate.is_active.is_(True))
    ))
    if not templates:
        return None
    if len(templates) == 1:
        return templates[0]
    if not key and not attributes:
        defaults = [item for item in templates if item.is_default]
        return defaults[0] if len(defaults) == 1 else None
    exact = [item for item in templates if normalize_key(item.category.full_path) == key]
    if exact:
        return exact[0]

    ignored = {
        "главная", "каталог", "товары", "товар", "бренды", "бренд",
        "купить", "официальный", "сайт",
    }
    category_tokens = {item for item in key.split() if len(item) > 2 and item not in ignored}
    source_names = {
        normalize_key(item.get("name"))
        for item in (attributes or [])
        if normalize_key(item.get("name"))
    }
    ranked: list[tuple[float, AttributeTemplate]] = []
    for template in templates:
        target_text = " ".join(
            filter(None, (
                template.category.full_path,
                template.name,
                template.product_type,
            ))
        )
        target_key = normalize_key(target_text)
        target_tokens = {item for item in target_key.split() if len(item) > 2 and item not in ignored}
        token_score = (
            len(category_tokens & target_tokens) / min(len(category_tokens), len(target_tokens))
            if category_tokens and target_tokens else 0.0
        )
        phrase_score = 0.0
        if key and (key in target_key or target_key in key):
            phrase_score = 1.0
        elif key and target_key:
            phrase_score = SequenceMatcher(None, key, target_key).ratio()
        field_names = {normalize_key(field.name) for field in template.fields}
        attribute_score = (
            len(source_names & field_names) / min(len(source_names), len(field_names))
            if source_names and field_names else 0.0
        )
        score = max(phrase_score, token_score * 0.75 + attribute_score * 0.25)
        if template.is_default:
            score += 0.02
        ranked.append((score, template))
    ranked.sort(key=lambda pair: (pair[0], pair[1].updated_at), reverse=True)
    return ranked[0][1] if ranked and ranked[0][0] >= 0.45 else None


def _page_attribute_stack(
    db: Session,
    template: AttributeTemplate,
    attributes: list[dict[str, Any]],
) -> list[dict[str, str]]:
    """Align own-site rows with the template while retaining genuinely extra attributes."""

    cleaned = [
        {
            "group_name": clean_text(item.get("group")),
            "name": clean_text(item.get("name")),
            "value": exact_value_key(item.get("value")),
        }
        for item in attributes
        if clean_text(item.get("name")) and exact_value_key(item.get("value"))
    ]
    value_keys = {exact_value_key(item["value"]) for item in cleaned if exact_value_key(item["value"])}
    value_index = _allowed_value_field_index(template.fields, value_keys)
    claimed_fields: set[int] = set()
    result: list[dict[str, str]] = []
    for item in cleaned:
        mapping_rows = _attribute_mapping_rows(db, template, None, item, value_index)
        mapped_any = False
        for mapped_item, field, _confidence, _reason, _alternatives in mapping_rows:
            field_key = int(field.id) if field is not None and field.id is not None else 0
            if field is None or field_key in claimed_fields:
                continue
            mapped_any = True
            claimed_fields.add(field_key)
            result.append({
                "group_name": field.group_name,
                "name": field.name,
                "value": exact_value_key(mapped_item.get("value")),
                "source_name": clean_text(mapped_item.get("source_name") or item["name"]),
            })
        if not mapped_any:
            result.append(item)
    return result

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
    if len(cleaned_urls) > ATTRIBUTE_ASSISTANT_MAX_URLS:
        raise ValueError(
            f"За одну обработку можно передать не больше {ATTRIBUTE_ASSISTANT_MAX_URLS} ссылок"
        )
    if any(len(url) > 2048 for url in cleaned_urls):
        raise ValueError("Длина одной ссылки не должна превышать 2048 символов")
    parsed_pages: list[dict[str, Any]] = []
    discovered_templates: list[AttributeTemplate] = []
    for url in cleaned_urls:
        try:
            html, final_url = fetch_public_html(url)
            page = parse_product_html(html, final_url)
            page["_input_url"] = url
            page["_status"] = "parsed"
            page["_error"] = ""
            page["_template"] = template or find_template_for_category(
                db,
                page["category"],
                page["attributes"],
            )
            if page["_template"] is not None:
                discovered_templates.append(page["_template"])
        except Exception as error:
            slug = Path(urlparse(url).path.rstrip("/")).name
            page = {
                "url": url,
                "_input_url": url,
                "_status": "error",
                "_error": clean_text(error),
                "_template": template,
                "name": "",
                "model": slug,
                "brand": "",
                "category": "",
                "attributes": [],
            }
        parsed_pages.append(page)
    batch_template = template or next(iter(discovered_templates), None)
    if batch_template is None:
        batch_template = db.scalar(
            select(AttributeTemplate).where(
                AttributeTemplate.is_active.is_(True),
                AttributeTemplate.is_default.is_(True),
            ).order_by(AttributeTemplate.updated_at.desc())
        ) or db.scalar(
            select(AttributeTemplate).where(AttributeTemplate.is_active.is_(True)).order_by(AttributeTemplate.updated_at.desc())
        )
    if batch_template is None:
        details = "; ".join(
            f"{page['_input_url']}: {page['_error'] or 'шаблон не определён'}"
            for page in parsed_pages
        )
        raise ValueError(
            "Шаблон не определён автоматически. Выберите его вручную."
            + (f" {details}" if details else "")
        )
    batch = AttributeBatch(
        template=batch_template,
        name=clean_text(name) or f"Ссылки {len(cleaned_urls)}",
        input_mode="urls",
        processing_mode=processing_mode if processing_mode in PROCESSING_MODES else "suggest",
        source_urls=[
            {
                "url": page["_input_url"],
                "final_url": page.get("url", ""),
                "status": page["_status"] if page["_template"] is not None else "needs_template",
                "error": page["_error"],
                "template_id": page["_template"].id if page["_template"] is not None else None,
            }
            for page in parsed_pages
        ],
    )
    db.add(batch)
    db.flush()
    for index, page in enumerate(parsed_pages, start=1):
        selected_template = page["_template"]
        model = (
            clean_text(page["model"])
            or _infer_product_model(page["name"], page["url"], page["brand"])
            or clean_text(Path(urlparse(page["url"]).path.rstrip("/")).stem)
            or f"Товар {index}"
        )
        product = AttributeProduct(
            batch=batch,
            template=selected_template,
            model=model,
            name=page["name"],
            brand=page["brand"],
            category_name=page["category"],
            source_url=page["url"],
            sort_order=index - 1,
            processing_state={"template_unresolved": selected_template is None},
            status="needs_template" if selected_template is None else "needs_review",
        )
        db.add(product)
        if selected_template is not None:
            page_stack = _page_attribute_stack(db, selected_template, page["attributes"])
            _make_product_values(
                product,
                selected_template,
                page_stack,
                current_source="current_site",
                current_role="Исходная страница сайта",
            )
            mapped_current = sum(
                value.is_in_template and bool(value.current_value)
                for value in product.values
            )
            page["processing_stats"] = {
                "mapped": mapped_current,
                "unknown": sum(
                    value.is_in_template and value.status == "unknown"
                    for value in product.values
                ),
                "ambiguous": 0,
                "already_filled": mapped_current,
                "not_in_template": sum(not value.is_in_template for value in product.values),
            }
        product.sources.append(
            AttributeProductSource(
                url=page["url"],
                priority=0,
                role="own_site",
                status=(
                    "error" if page["_status"] == "error"
                    else "needs_template" if selected_template is None
                    else "parsed"
                ),
                parsed_data={**{key: value for key, value in page.items() if not key.startswith("_")}, "message": page["_error"]},
            )
        )
        db.flush()
        refresh_product_status(product)
    refresh_batch_summary(batch)
    db.flush()
    return batch


def restore_cached_site_current_values(product: AttributeProduct) -> int:
    """Backfill «Было» for URL batches that already cached parsed own-site attributes."""

    if product.batch.input_mode != "urls":
        return 0
    template = product_template(product)
    if template is None:
        return 0
    source = next(
        (
            item for item in product.sources
            if item.role == "own_site" and (item.parsed_data or {}).get("attributes")
        ),
        None,
    )
    if source is None:
        return 0
    stack = _page_attribute_stack(
        object_session(product) or object_session(template),
        template,
        list((source.parsed_data or {}).get("attributes") or []),
    )
    shadow = SimpleNamespace(values=[], source_url=product.source_url)
    _make_product_values(
        shadow,
        template,
        stack,
        current_source="current_site",
        current_role="Исходная страница сайта",
    )
    removed_extra_keys = {
        (
            normalize_key(item.get("group_name")),
            normalize_key(item.get("name")),
            exact_value_key(item.get("value")),
        )
        for item in list((product.processing_state or {}).get("removed_outside_template_attributes") or [])
        if isinstance(item, dict)
    }
    targets = {
        value.template_field_id: value
        for value in product.values
        if value.is_in_template and value.template_field_id is not None
    }
    restored_extra_keys = {
        (
            normalize_key(value.group_name),
            normalize_key(value.attribute_name),
            exact_value_key(value.current_value or value.final_value),
        )
        for value in shadow.values
        if not value.is_in_template and (
            normalize_key(value.group_name),
            normalize_key(value.attribute_name),
            exact_value_key(value.current_value or value.final_value),
        ) not in removed_extra_keys
    }
    changed = 0
    for existing in list(product.values):
        existing_key = (
            normalize_key(existing.group_name),
            normalize_key(existing.attribute_name),
            exact_value_key(existing.current_value or existing.final_value),
        )
        if (
            not existing.is_in_template
            and existing.source == "current_site"
            and existing_key not in restored_extra_keys
        ):
            product.values.remove(existing)
            changed += 1
    for restored in shadow.values:
        if restored.is_in_template:
            if not restored.current_value:
                continue
            restored_field_id = restored.template_field_id or (
                restored.template_field.id if restored.template_field is not None else None
            )
            target = targets.get(restored_field_id)
            if target is None:
                continue
            if target.current_value:
                if (
                    target.source != "current_site"
                    or _candidate_value_key(target, target.current_value) != _candidate_value_key(target, restored.current_value)
                ):
                    continue
                before = (
                    target.proposed_value,
                    target.final_value,
                    target.confidence,
                    target.status,
                    target.reason,
                    dict(target.source_details or {}),
                )
                previous_details = dict(target.source_details or {})
                restored_details = dict(restored.source_details or {})
                for key in ("current_source_name", "current_value_hint"):
                    if key in restored_details:
                        previous_details[key] = restored_details[key]
                    else:
                        previous_details.pop(key, None)
                unknown_values = [
                    item for item in list(previous_details.get("unknown_values") or [])
                    if not (
                        isinstance(item, dict)
                        and clean_text(item.get("source")) == "current_site"
                    )
                ] + list(restored_details.get("unknown_values") or [])
                if unknown_values:
                    previous_details["unknown_values"] = unknown_values
                else:
                    previous_details.pop("unknown_values", None)
                target.source_details = previous_details
                if target.status not in {"approved", "rejected"}:
                    target.final_value = restored.final_value
                    target.confidence = restored.confidence
                    target.status = restored.status
                    target.reason = restored.reason
                    target.proposed_value = restored.proposed_value or ""
                    if previous_details.get("candidates") or previous_details.get("unknown_values"):
                        _recalculate_candidate_state(product, target)
                after = (
                    target.proposed_value,
                    target.final_value,
                    target.confidence,
                    target.status,
                    target.reason,
                    dict(target.source_details or {}),
                )
                if after != before:
                    changed += 1
                continue
            previous_status = target.status
            previous_details = dict(target.source_details or {})
            target.current_value = restored.current_value
            target.source = "current_site"
            target.dash_reason = restored.dash_reason
            merged_details = previous_details
            merged_details.update(dict(restored.source_details or {}))
            target.source_details = merged_details
            if previous_status != "approved":
                target.final_value = restored.final_value
                target.confidence = restored.confidence
                target.status = restored.status
                target.reason = restored.reason
                target.proposed_value = restored.proposed_value or ""
                _recalculate_candidate_state(product, target)
            changed += 1
            continue
        restored_key = (
            normalize_key(restored.group_name),
            normalize_key(restored.attribute_name),
            exact_value_key(restored.current_value or restored.final_value),
        )
        if restored_key in removed_extra_keys:
            continue
        duplicate = next(
            (
                value for value in product.values
                if not value.is_in_template
                and (
                    normalize_key(value.group_name),
                    normalize_key(value.attribute_name),
                    exact_value_key(value.current_value or value.final_value),
                ) == restored_key
            ),
            None,
        )
        if duplicate is not None:
            if not duplicate.current_value:
                duplicate.current_value = restored.current_value
                duplicate.source = "current_site"
                changed += 1
            continue
        product.values.append(restored)
        changed += 1
    if changed:
        refresh_product_status(product)
        stats = dict((source.parsed_data or {}).get("processing_stats") or {})
        stats.update({
            "mapped": sum(value.is_in_template and bool(value.current_value) for value in product.values),
            "already_filled": sum(value.is_in_template and bool(value.current_value) for value in product.values),
            "not_in_template": sum(not value.is_in_template for value in product.values),
        })
        source.parsed_data = {**dict(source.parsed_data or {}), "processing_stats": stats}
    return changed


def backfill_cached_site_current_values(db: Session) -> int:
    """Run the legacy URL-product backfill once as an explicit data migration."""

    products = list(db.scalars(
        select(AttributeProduct)
        .join(AttributeBatch)
        .where(AttributeBatch.input_mode == "urls")
        .options(
            selectinload(AttributeProduct.batch),
            selectinload(AttributeProduct.sources),
            selectinload(AttributeProduct.values)
            .selectinload(AttributeProductValue.template_field),
            selectinload(AttributeProduct.template)
            .selectinload(AttributeTemplate.category),
            selectinload(AttributeProduct.template)
            .selectinload(AttributeTemplate.fields)
            .selectinload(AttributeTemplateField.allowed_values)
            .selectinload(AttributeAllowedValue.synonyms),
        )
    ))
    changed = 0
    for product in products:
        changed += restore_cached_site_current_values(product)
    if changed:
        for batch in {
            product.batch for product in products if product.batch is not None
        }:
            refresh_batch_summary(batch)
    return changed

def serialize_donor(donor: Donor) -> dict[str, Any]:
    return {
        "id": donor.id,
        "name": donor.brand.name,
        "group_name": donor.brand.group_name,
        "site_url": donor.site_url,
        "start_urls": list(donor.start_urls or []),
        "cached_products": len(donor.known_new_products or {}),
        "connection_method": donor.connection_method_row.code if donor.connection_method_row else "requests",
        "connection_name": donor.connection_method_row.name if donor.connection_method_row else "Обычный HTTP",
        "uses_browser": bool(donor.connection_method_row and donor.connection_method_row.is_browser_render),
        "uses_debug_visible": bool(donor.connection_method_row and donor.connection_method_row.is_debug_visible),
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


def _host_key(url: str) -> str:
    host = (urlparse(clean_text(url)).hostname or "").casefold()
    return host[4:] if host.startswith("www.") else host


def _same_site(left: str, right: str) -> bool:
    return bool(_host_key(left)) and _host_key(left) == _host_key(right)


def _sitemap_locations(xml: str) -> list[str]:
    # Namespace-independent and tolerant of imperfect sitemap XML.
    return [clean_text(item) for item in re.findall(r"<loc\b[^>]*>(.*?)</loc>", xml, re.I | re.S) if clean_text(item)]


def _site_sitemap_urls(site_url: str) -> list[str]:
    parsed = urlparse(clean_text(site_url))
    if not parsed.scheme or not parsed.netloc:
        return []
    root = f"{parsed.scheme}://{parsed.netloc}"
    result = [urljoin(root, "/sitemap.xml"), urljoin(root, "/sitemap_index.xml")]
    try:
        robots, final_url = fetch_public_html(urljoin(root, "/robots.txt"), max_bytes=512 * 1024)
        for line in robots.splitlines():
            if line.casefold().lstrip().startswith("sitemap:"):
                location = clean_text(line.split(":", 1)[1])
                if location:
                    result.append(urljoin(final_url, location))
    except Exception:
        pass
    return list(dict.fromkeys(result))


def _find_in_sitemaps(site_url: str, wanted: str, max_sitemaps: int = 12) -> str:
    queue = _site_sitemap_urls(site_url)
    visited: set[str] = set()
    while queue and len(visited) < max_sitemaps:
        sitemap_url = queue.pop(0)
        if sitemap_url in visited:
            continue
        visited.add(sitemap_url)
        try:
            xml, final_url = fetch_public_html(sitemap_url)
        except Exception:
            continue
        locations = _sitemap_locations(xml)
        for location in locations:
            absolute = urljoin(final_url, location)
            if _same_site(site_url, absolute) and wanted and wanted in normalize_model(absolute):
                return absolute
        for location in locations:
            absolute = urljoin(final_url, location)
            path = urlparse(absolute).path.casefold()
            if _same_site(site_url, absolute) and (path.endswith(".xml") or "sitemap" in path):
                if absolute not in visited and absolute not in queue:
                    queue.append(absolute)
    return ""


def _search_tokens(*values: str) -> set[str]:
    stop = {
        "товар", "купить", "цена", "модель", "бренд", "для", "или", "the",
        "bosch", "maunfeld", "neff", "smeg", "evelux",
    }
    result: set[str] = set()
    for value in values:
        for token in _name_tokens(value):
            if token in stop or len(token) < 4:
                continue
            result.add(token[: min(len(token), 8)])
    return result


def _catalog_link_score(anchor_text: str, href: str, tokens: set[str]) -> int:
    haystack = normalize_key(f"{anchor_text} {href}")
    score = 0
    for token in tokens:
        if token in haystack:
            score += 12
        elif len(token) >= 6 and token[:6] in haystack:
            score += 7
    path = urlparse(href).path.casefold()
    if any(part in path for part in ("catalog", "product", "tovar", "holodil", "kholodil", "refriger")):
        score += 2
    if any(part in path for part in ("login", "account", "cart", "compare", "favorite", "delivery", "contact", "blog", "news")):
        score -= 20
    return score


def _find_by_catalog_crawl(
    start_urls: list[str],
    wanted: str,
    *,
    product_name: str = "",
    category: str = "",
    max_pages: int = 24,
    max_depth: int = 2,
) -> str:
    roots = [clean_text(item) for item in start_urls if clean_text(item)]
    if not roots:
        return ""
    canonical_root = roots[0]
    tokens = _search_tokens(product_name, category)
    queue: list[tuple[str, int, int]] = [(item, 0, 0) for item in roots]
    queued = {item for item in roots}
    visited: set[str] = set()
    while queue and len(visited) < max_pages:
        queue.sort(key=lambda item: (-item[2], item[1]))
        page_url, depth, _score = queue.pop(0)
        queued.discard(page_url)
        if page_url in visited or not _same_site(canonical_root, page_url):
            continue
        visited.add(page_url)
        try:
            html, final_url = fetch_public_html(page_url)
        except Exception:
            continue
        soup = BeautifulSoup(html, "html.parser")
        candidates: list[tuple[int, str]] = []
        for anchor in soup.select("a[href]"):
            href = clean_text(anchor.get("href"))
            if not href or href.startswith(("#", "mailto:", "tel:", "javascript:")):
                continue
            absolute = urljoin(final_url, href).split("#", 1)[0]
            if not _same_site(canonical_root, absolute):
                continue
            text = clean_text(anchor.get_text(" "))
            title = clean_text(anchor.get("title"))
            haystack = f"{text} {title} {absolute}"
            if wanted and wanted in normalize_model(haystack):
                return absolute
            if depth >= max_depth:
                continue
            parsed = urlparse(absolute)
            if parsed.path.casefold().endswith((".jpg", ".jpeg", ".png", ".webp", ".gif", ".svg", ".pdf", ".zip")):
                continue
            if absolute in visited or absolute in queued:
                continue
            candidates.append((_catalog_link_score(f"{text} {title}", absolute, tokens), absolute))
        # Keep navigation bounded, but prefer links semantically related to the current product/category.
        for score, absolute in sorted(candidates, key=lambda pair: pair[0], reverse=True)[:48]:
            queue.append((absolute, depth + 1, score))
            queued.add(absolute)
    return ""


def resolve_donor_url(
    donor: Donor,
    model: str,
    product_name: str = "",
    category: str = "",
) -> tuple[str, str]:
    wanted = normalize_model(model)
    if not wanted:
        return "", "У товара не заполнена модель"

    cached = _cached_product_url(donor, model)
    if cached:
        return cached, "Кэш ранее найденных товаров"

    roots: list[str] = []
    # The main site must be first: donor.start_urls can point to a completely different category.
    if donor.site_url:
        site_root = clean_text(donor.site_url)
        roots.append(site_root)
        # Many dealer/catalog sites expose a human-readable category map even when XML sitemap is protected.
        roots.append(urljoin(site_root, "/map/"))
    roots.extend(clean_text(item) for item in (donor.start_urls or []) if clean_text(item))
    roots = list(dict.fromkeys(item for item in roots if item))

    seen_hosts: set[str] = set()
    for root in roots:
        host = _host_key(root)
        if not host or host in seen_hosts:
            continue
        seen_hosts.add(host)
        found = _find_in_sitemaps(root, wanted)
        if found:
            return found, "Найдена по модели в карте сайта"

    found = _find_by_catalog_crawl(
        roots[:8],
        wanted,
        product_name=product_name,
        category=category,
    )
    if found:
        return found, "Найдена по модели при обходе каталога"
    return "", "Ссылка на конкретный товар по модели не найдена на сайте донора"


def _name_mapping_score(source_name: str, target_name: str) -> float:
    source_key = normalize_key(source_name)
    target_key = normalize_key(target_name)
    if source_key == target_key:
        return 1.0
    source_tokens = _name_tokens(source_name)
    target_tokens = _name_tokens(target_name)
    if source_tokens and target_tokens:
        if source_tokens == target_tokens:
            return 1.0
        overlap = source_tokens & target_tokens
        coverage = len(overlap) / max(len(source_tokens), len(target_tokens))
        union = len(overlap) / len(source_tokens | target_tokens)
        subset = source_tokens <= target_tokens or target_tokens <= source_tokens
        # A one-word target must not absorb a much more specific feature
        # merely because both names share that generic word.
        if subset and min(len(source_tokens), len(target_tokens)) >= 3:
            source_only = source_tokens - target_tokens
            target_only = target_tokens - source_tokens
            # A specific donor row must not collapse into a broader total field.
            if source_only and not target_only:
                return 0.72
            return 0.96
    else:
        coverage = union = 0.0
    semantic_source = " ".join(sorted(source_tokens)) or source_key
    semantic_target = " ".join(sorted(target_tokens)) or target_key
    sequence = SequenceMatcher(None, semantic_source, semantic_target).ratio()
    return min(0.99, 0.48 * sequence + 0.37 * coverage + 0.15 * union)


def _mapping_score(source_name: str, field: AttributeTemplateField) -> float:
    names = [field.name, *list(field.synonyms or [])]
    return max((_name_mapping_score(source_name, name) for name in names), default=0.0)


def _name_supports_value_hint(source_name: str, target_name: str) -> bool:
    # A dictionary value may complete an abbreviated name, but must not discard
    # donor qualifiers to force a specific attribute into a more general field.
    source_tokens = _name_tokens(source_name)
    target_tokens = _name_tokens(target_name)
    if not source_tokens:
        # Names made entirely of generic words still need lexical evidence.
        source_tokens = set(normalize_key(source_name).split())
        target_tokens = set(normalize_key(target_name).split())
    return bool(source_tokens and source_tokens <= target_tokens)


def _allowed_value_field_index(
    fields: Iterable[AttributeTemplateField],
    wanted_keys: set[str] | None = None,
) -> dict[str, list[AttributeTemplateField]]:
    keys = {value_match_key(key) for key in (wanted_keys or set())}
    if keys & BOOLEAN_TRUE_KEYS:
        keys.update(BOOLEAN_TRUE_KEYS)
    if keys & BOOLEAN_FALSE_KEYS:
        keys.update(BOOLEAN_FALSE_KEYS)
    index: dict[str, list[AttributeTemplateField]] = {}
    for field in fields:
        for item in field.allowed_values:
            if not item.is_active:
                continue
            item_keys = {value_match_key(item.value)}
            for key in item_keys:
                if keys and key not in keys:
                    continue
                index.setdefault(key, []).append(field)
    return index


def _fields_with_exact_value(
    fields: Iterable[AttributeTemplateField],
    raw_value: str,
    value_index: dict[str, list[AttributeTemplateField]] | None = None,
) -> list[AttributeTemplateField]:
    raw_key = value_match_key(raw_value)
    if not raw_key:
        return []
    # Boolean and numeric values are too common to identify an attribute safely.
    # They remain value-validation signals after the name has been mapped.
    if (
        raw_key.casefold() in BOOLEAN_TRUE_KEYS | BOOLEAN_FALSE_KEYS
        or NUMBER_RE.fullmatch(exact_value_key(raw_value))
        or DIMENSION_RE.fullmatch(exact_value_key(raw_value))
    ):
        return []
    equivalent_keys = {raw_key}
    index = (
        value_index
        if value_index is not None
        else _allowed_value_field_index(fields, set(equivalent_keys))
    )
    matches = {
        field.id: field
        for key in equivalent_keys
        for field in index.get(key, [])
    }
    return list(matches.values())


def map_attribute(
    db: Session,
    template: AttributeTemplate,
    donor_id: int | None,
    source_name: str,
    raw_value: str = "",
    value_index: dict[str, list[AttributeTemplateField]] | None = None,
) -> tuple[AttributeTemplateField | None, int, str, list[dict[str, Any]]]:
    source_key = normalize_key(source_name)
    if not source_key:
        return None, 0, "Название атрибута не заполнено", []
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
    # Exact field names take precedence over synonyms, token normalization and
    # dictionary hints. An unknown value does not change the attribute's identity.
    exact_fields = [
        field for field in template.fields if normalize_key(field.name) == source_key
    ]
    if len(exact_fields) == 1:
        return exact_fields[0], 100, "Точное совпадение названия", []
    if len(exact_fields) > 1:
        return None, 100, "Название атрибута неоднозначно", [
            {"field_id": field.id, "name": field.name, "group_name": field.group_name, "score": 100}
            for field in exact_fields[:4]
        ]
    synonym_fields = [
        field
        for field in template.fields
        if any(normalize_key(synonym) == source_key for synonym in (field.synonyms or []))
    ]
    if len(synonym_fields) == 1:
        return synonym_fields[0], 100, "Синоним атрибута", []
    if len(synonym_fields) > 1:
        return None, 100, "Синоним атрибута неоднозначен", [
            {
                "field_id": field.id,
                "name": field.name,
                "group_name": field.group_name,
                "score": 100,
            }
            for field in synonym_fields[:4]
        ]
    ranked = sorted(
        ((_mapping_score(source_name, field), field) for field in template.fields),
        key=lambda pair: pair[0],
        reverse=True,
    )
    alternatives = [
        {"field_id": field.id, "name": field.name, "group_name": field.group_name, "score": round(score * 100)}
        for score, field in ranked[:4]
    ]
    exact_value_fields = _fields_with_exact_value(
        template.fields, raw_value, value_index
    )
    if len(exact_value_fields) == 1:
        matching_field = exact_value_fields[0]
        name_score = _mapping_score(source_name, matching_field)
        name_supported = any(
            _name_supports_value_hint(source_name, name)
            for name in [matching_field.name, *(matching_field.synonyms or [])]
        )
        if name_supported and (
            not ranked or ranked[0][0] < 0.74 or ranked[0][0] - name_score < 0.06
        ):
            return (
                matching_field,
                max(90, round(name_score * 100)),
                "Сопоставлено по названию и уникальному значению справочника",
                alternatives,
            )
    if not ranked or ranked[0][0] < 0.74:
        return None, round((ranked[0][0] if ranked else 0) * 100), "Низкая схожесть названий", alternatives
    best_score, best_field = ranked[0]
    margin = best_score - (ranked[1][0] if len(ranked) > 1 else 0)
    if len(ranked) > 1 and margin < 0.06:
        return None, round(best_score * 100), "Нужно уточнить атрибут", alternatives
    return best_field, round(best_score * 100), "Сопоставлено по названию или синониму", alternatives


def _decimal_text(value: Decimal) -> str:
    text = format(value.normalize(), "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _canonical_linear_unit(value: Any) -> str:
    return LINEAR_UNIT_ALIASES.get(normalize_key(value), "")


def _linear_unit_from_name(value: Any) -> str:
    # Units in donor tables are commonly stored in the attribute label rather
    # than repeated in every value (for example, "Длина кабеля, м" + "1.8").
    for token in reversed(WORD_RE.findall(normalize_key(value))):
        unit = _canonical_linear_unit(token)
        if unit:
            return unit
    return ""


def _dimension_axis(value: Any) -> str:
    key = normalize_key(value)
    if key == "ш" or key == "w" or key.startswith("ширин") or key == "width":
        return "width"
    if key == "в" or key == "h" or key.startswith("высот") or key == "height":
        return "height"
    if key == "г" or key == "d" or key.startswith("глубин") or key == "depth":
        return "depth"
    if key == "д" or key == "l" or key.startswith("длин") or key == "length":
        return "length"
    return ""


def _dimension_axis_order(source_name: str) -> tuple[list[str], tuple[int, int] | None]:
    """Read an explicit dimension order such as ШxВxГ or Depth x Width x Height."""

    text = clean_text(source_name)
    for match in DIMENSION_AXIS_SEQUENCE_RE.finditer(text):
        axes = [
            _dimension_axis(token.group(0))
            for token in DIMENSION_AXIS_TOKEN_RE.finditer(match.group(0))
        ]
        if len(axes) >= 2 and all(axes) and len(set(axes)) == len(axes):
            return axes, match.span()
    return [], None


def _dimension_component_name(source_name: str, axis: str, order_span: tuple[int, int]) -> str:
    """Replace a generic tuple label with one axis while retaining qualifiers and units."""

    context = source_name[:order_span[0]] + " " + source_name[order_span[1]:]
    context = re.sub(r"[\(\[\{]\s*[\)\]\}]", " ", context)
    context = re.sub(
        r"\b(?:(?:габаритн[а-яё]*|overall)\s+)?(?:размер[а-яё]*|dimensions?|measurements?)\b",
        " ",
        context,
        flags=re.IGNORECASE,
    )
    context = re.sub(r"\bгабарит[а-яё]*\b", " ", context, flags=re.IGNORECASE)
    context = clean_text(context)
    context = re.sub(r"^[\s,;:/\-–—]+|[\s,;:/\-–—]+$", "", context)
    label = DIMENSION_AXIS_LABELS[axis]
    if not context:
        return label
    if context.startswith((",", ";", ":")):
        return label + context
    return f"{label} {context}"


def _dimension_component_attributes(source_name: str, raw_value: str) -> list[dict[str, str]]:
    """Split an explicitly labelled dimension tuple into independently mappable facts."""

    axes, order_span = _dimension_axis_order(source_name)
    if not axes or order_span is None:
        return []
    text = exact_value_key(raw_value)
    unit_pattern = (
        r"(?:миллиметр(?:а|ов|ы|ах)?|сантиметр(?:а|ов|ы|ах)?|метр(?:а|ов|ы|ах)?|"
        r"millimeters?|millimetres?|centimeters?|centimetres?|meters?|metres?|мм|см|mm|cm|м|m)"
    )
    part_re = re.compile(
        r"([+]?[0-9]+(?:[.,][0-9]+)?)\s*(" + unit_pattern + r")?"
        r"(?=$|\s|[xXхХ×*/])",
        re.IGNORECASE,
    )
    parts = list(part_re.finditer(text))
    if len(parts) != len(axes) or not parts:
        return []
    if text[:parts[0].start()].strip() or text[parts[-1].end():].strip():
        return []
    separators = [text[left.end():right.start()].strip() for left, right in zip(parts, parts[1:])]
    if any(separator not in {"x", "X", "х", "Х", "×", "*", "/"} for separator in separators):
        return []

    explicit_units = [clean_text(part.group(2)) for part in parts]
    inherited_unit = ""
    if explicit_units[-1] and not any(explicit_units[:-1]):
        inherited_unit = explicit_units[-1]

    result: list[dict[str, str]] = []
    for index, (axis, part) in enumerate(zip(axes, parts)):
        value = clean_text(part.group(0))
        if not explicit_units[index] and inherited_unit:
            value = f"{part.group(1)} {inherited_unit}"
        result.append({
            "name": _dimension_component_name(source_name, axis, order_span),
            "value": value,
            "source_name": clean_text(source_name),
            "dimension_axis": axis,
        })
    return result


def _dimension_value_in_field_order(raw_value: str, source_name: str, field_name: str) -> str:
    """Reorder a tuple when both source and target explicitly declare their axes."""

    components = _dimension_component_attributes(source_name, raw_value)
    source_axes, _source_span = _dimension_axis_order(source_name)
    target_axes, _target_span = _dimension_axis_order(field_name)
    if (
        not components
        or source_axes == target_axes
        or len(source_axes) != len(target_axes)
        or set(source_axes) != set(target_axes)
    ):
        return exact_value_key(raw_value)
    values_by_axis = {
        component["dimension_axis"]: component["value"]
        for component in components
    }
    return " x ".join(values_by_axis[axis] for axis in target_axes)


def _attribute_mapping_rows(
    db: Session,
    template: AttributeTemplate,
    donor_id: int | None,
    item: dict[str, Any],
    value_index: dict[str, list[AttributeTemplateField]] | None = None,
) -> list[tuple[dict[str, Any], AttributeTemplateField | None, int, str, list[dict[str, Any]]]]:
    """Map one source row, decomposing only tuples whose axis order is explicit."""

    original = map_attribute(
        db,
        template,
        donor_id,
        clean_text(item.get("name")),
        exact_value_key(item.get("value")),
        value_index,
    )
    components = _dimension_component_attributes(
        clean_text(item.get("name")),
        exact_value_key(item.get("value")),
    )
    if not components:
        return [(item, *original)]

    component_rows = []
    used_field_ids: set[int] = set()
    if original[0] is not None and original[0].id is not None:
        used_field_ids.add(int(original[0].id))
    for component in components:
        mapped = map_attribute(
            db,
            template,
            donor_id,
            component["name"],
            component["value"],
            value_index,
        )
        field = mapped[0]
        field_id = int(field.id) if field is not None and field.id is not None else 0
        if not field_id or field_id in used_field_ids:
            continue
        used_field_ids.add(field_id)
        axis_label = DIMENSION_AXIS_LABELS[component["dimension_axis"]]
        component_rows.append((
            component,
            field,
            mapped[1],
            f"Составные габариты: ось «{axis_label}» определена по подписи; {mapped[2]}",
            mapped[3],
        ))

    rows = component_rows
    if original[0] is not None:
        rows = [(item, *original), *rows]
    return rows or [(item, *original)]


def _centimeter_value(
    raw_value: str, source_name: str = "", field_name: str = "", *, preserve_format: bool = False,
) -> str | None:
    """Convert only linear measures, preserving dimension order and range separators."""
    text = exact_value_key(raw_value)
    unit_pattern = r"(?:миллиметр(?:а|ов|ы|ах)?|сантиметр(?:а|ов|ы|ах)?|метр(?:а|ов|ы|ах)?|millimeters?|millimetres?|centimeters?|centimetres?|meters?|metres?|мм|см|mm|cm|м|m)"
    aliases = {"mm": "мм", "cm": "см", "m": "м"}

    def unit(value):
        key = value.casefold()
        if key.startswith(("миллиметр", "millimeter", "millimetre")):
            return "мм"
        if key.startswith(("сантиметр", "centimeter", "centimetre")):
            return "см"
        if key.startswith(("метр", "meter", "metre")):
            return "м"
        return aliases.get(key) or _canonical_linear_unit(key)

    def name_unit(name):
        matches = list(re.finditer(r"(?<![\w/])(" + unit_pattern + r")(?![\w²³/])", name, re.I))
        return unit(matches[-1].group(1)) if matches else ""

    # Area, volume and rates must never become linear centimeters.
    if re.search(r"(?:мм|см|mm|cm|м|m)\s*(?:[²³]|[23]\b|\^|/)", source_name + " " + field_name, re.I):
        return None
    part_re = re.compile(r"([+]?[0-9]+(?:[.,][0-9]+)?)\s*(" + unit_pattern + r")?(?=$|\s|[xXхХ×*/\-–—−])", re.I)
    parts = list(part_re.finditer(text))
    if not parts or text[:parts[0].start()].strip() or text[parts[-1].end():].strip():
        return None
    separators = [text[left.end():right.start()].strip() for left, right in zip(parts, parts[1:])]
    if any(separator not in {"x", "X", "х", "Х", "×", "*", "/", "-", "–", "—", "−"} for separator in separators):
        return None
    explicit_units = [unit(part.group(2)) if part.group(2) else "" for part in parts]
    inherited = name_unit(source_name) or name_unit(field_name)
    if not inherited and not any(explicit_units) and not re.search(
        r"высот|ширин|глубин|длин|диаметр|габарит|размер|толщин|радиус|расстояни|height|width|depth|length|diameter|dimensions",
        source_name + " " + field_name, re.I,
    ):
        return None
    # A single trailing unit applies to the whole dimension tuple (600x450x850 мм).
    if explicit_units[-1] and not any(explicit_units[:-1]):
        inherited = explicit_units[-1]
    inherited = inherited or "см"
    result = []
    formatted = text
    for index, part in enumerate(parts):
        source_unit = explicit_units[index] or inherited
        number = Decimal(part.group(1).replace(",", "."))
        factor = LINEAR_UNIT_FACTORS[source_unit][1] / LINEAR_UNIT_FACTORS["см"][1]
        if index:
            separator = separators[index - 1]
            result.append("x" if separator in {"x", "X", "х", "Х", "×", "*"} else separator)
        result.append(_decimal_text(number * factor))
    if preserve_format:
        for index in range(len(parts) - 1, -1, -1):
            part = parts[index]
            source_unit = explicit_units[index] or inherited
            factor = LINEAR_UNIT_FACTORS[source_unit][1] / LINEAR_UNIT_FACTORS["см"][1]
            number_text = part.group(1)
            if factor != 1:
                number_text = _decimal_text(Decimal(number_text.replace(",", ".")) * factor)
                if "," in part.group(1):
                    number_text = number_text.replace(".", ",")
            replacement = number_text
            if part.group(2):
                replacement += text[part.end(1):part.start(2)] + (part.group(2) if source_unit == "см" else "см")
            else:
                replacement += text[part.end(1):part.end()]
            formatted = formatted[:part.start()] + replacement + formatted[part.end():]
        return formatted
    return "".join(result)


def _converted_value_candidates(
    field: AttributeTemplateField,
    raw_value: str,
    source_name: str = "",
) -> list[str]:
    text_value = exact_value_key(raw_value)
    candidates = [text_value]
    for rule in list(field.conversion_rules or []):
        if not isinstance(rule, dict):
            continue
        source = exact_value_key(rule.get("from_value"))
        if source and value_match_key(source) == value_match_key(text_value) and exact_value_key(rule.get("to_value")):
            candidates.insert(0, exact_value_key(rule["to_value"]))
    if field.value_type not in {"number", "dimensions", "boolean"} and not field.conversion_rules:
        return list(dict.fromkeys(candidates))
    match = NUMBER_WITH_UNIT_RE.fullmatch(text_value)
    if not match:
        return list(dict.fromkeys(candidates))
    try:
        number = Decimal(match.group(1).replace(",", "."))
    except InvalidOperation:
        return list(dict.fromkeys(candidates))
    raw_unit = normalize_key(match.group(2) or "")
    source_unit = (
        _canonical_linear_unit(raw_unit)
        or _linear_unit_from_name(raw_unit)
        or _linear_unit_from_name(source_name)
    )
    target_unit = _linear_unit_from_name(field.name)
    if (raw_unit.startswith(("месяц", "мес")) or (not raw_unit and "мес" in normalize_key(source_name))) and number % 12 == 0:
        years = int(number / 12)
        candidates[:0] = [
            f"{years} год",
            f"{years} года",
            f"{years} лет",
        ]
    elif source_unit and target_unit:
        source_family, source_factor = LINEAR_UNIT_FACTORS[source_unit]
        target_family, target_factor = LINEAR_UNIT_FACTORS[target_unit]
        if source_family == target_family:
            converted = _decimal_text(number * source_factor / target_factor)
            candidates[:0] = [converted, f"{converted} {target_unit}"]
        elif raw_unit:
            candidates.insert(0, _decimal_text(number))
    elif target_unit:
        normalized_number = _decimal_text(number)
        candidates[:0] = [normalized_number, f"{normalized_number} {target_unit}"]
    elif source_unit or raw_unit:
        candidates.insert(0, _decimal_text(number))
    for rule in list(field.conversion_rules or []):
        if not isinstance(rule, dict):
            continue
        from_unit = normalize_key(rule.get("from_unit"))
        if from_unit and from_unit != raw_unit and _canonical_linear_unit(from_unit) != source_unit:
            continue
        try:
            factor = Decimal(str(rule.get("factor", 1)).replace(",", "."))
        except InvalidOperation:
            continue
        converted = _decimal_text(number * factor)
        suffix = clean_text(rule.get("suffix"))
        candidates.insert(0, f"{converted} {suffix}".strip())
    return list(dict.fromkeys(item for item in candidates if item))


def _allowed_match(
    field: AttributeTemplateField,
    raw_value: str,
    source_name: str = "",
) -> tuple[str, int, str, list[str]]:
    allowed = [item for item in field.allowed_values if item.is_active]
    ordered_value = _dimension_value_in_field_order(raw_value, source_name, field.name)
    axes_reordered = exact_value_key(ordered_value) != exact_value_key(raw_value)
    order_reason = "Порядок осей приведён к формату целевого поля; " if axes_reordered else ""
    centimeters = _centimeter_value(ordered_value, source_name, field.name)
    if centimeters is not None:
        if not allowed and field.value_type in {"number", "dimensions"}:
            try:
                normalized = normalize_value(centimeters, field.value_type)
            except ValueError as error:
                return "", 0, str(error), []
            return normalized, 96, order_reason + "Конвертация единиц в сантиметры; формат проверен", []
        formatted = _centimeter_value(ordered_value, source_name, field.name, preserve_format=True)
        variants = list(dict.fromkeys([formatted, centimeters, centimeters.replace(".", ","), f"{centimeters} см", f"{centimeters} cm"]))
        nearest_values = []
        for variant in variants:
            canonical, confidence, reason, nearest = _allowed_match_single(field, variant, allowed, source_name)
            if canonical:
                return canonical, confidence, order_reason + "Конвертация единиц в сантиметры; " + reason, []
            nearest_values.extend(nearest)
        return "", 0, f"Значения {centimeters} см нет в справочнике", list(dict.fromkeys(nearest_values))[:3]
    if field.value_type not in {"number", "dimensions", "boolean"}:
        direct = _allowed_match_single(field, exact_value_key(raw_value), allowed, source_name)
        if direct[0] and allowed:
            return direct
    if _is_presence_marker(field, raw_value):
        return (
            "",
            0,
            "Логическое значение описывает наличие характеристики, а не значение справочника",
            [],
        )
    if field.is_composite:
        try:
            normalized_full = normalize_value(raw_value, field.value_type, True)
        except ValueError as error:
            return "", 0, str(error), []
        combination = next(
            (item for item in allowed if item.is_combination and value_match_key(item.value) == value_match_key(normalized_full)),
            None,
        )
        if combination:
            return combination.value, 100, "Готовая комбинация справочника", []
        component_values = [item for item in allowed if not item.is_combination]
        values: list[str] = []
        scores: list[int] = []
        unknown: list[str] = []
        suggestions: list[str] = []
        for part in [clean_text(item) for item in raw_value.split("/") if clean_text(item)]:
            single, score, _reason, nearest = _allowed_match_single(field, part, component_values, source_name)
            if single:
                values.append(single)
                scores.append(score)
            else:
                unknown.append(part)
                suggestions.extend(nearest)
        if unknown:
            return "", 0, "Нет в справочнике: " + ", ".join(unknown), list(dict.fromkeys(suggestions))[:3]
        return "/".join(sorted(set(values), key=str.casefold)), min(scores or [0]), "Составное значение проверено", []

    last_reason = "Значения нет в справочнике"
    suggestions: list[str] = []
    for candidate in _converted_value_candidates(field, raw_value, source_name):
        try:
            normalized = normalize_value(candidate, field.value_type, False)
        except ValueError as error:
            last_reason = str(error)
            continue
        canonical, confidence, reason, nearest = _allowed_match_single(field, normalized, allowed, source_name)
        suggestions.extend(nearest)
        if canonical:
            if exact_value_key(candidate) != exact_value_key(raw_value):
                reason = "Конвертация единиц; " + reason
            return canonical, confidence, reason, list(dict.fromkeys(suggestions))[:3]
        last_reason = reason
    return "", 0, last_reason, list(dict.fromkeys(suggestions))[:3]


def _is_presence_marker(field: AttributeTemplateField, value: Any) -> bool:
    """Return whether a yes/no value only marks presence of a semantic option."""

    key = exact_value_key(value).casefold()
    boolean_keys = BOOLEAN_TRUE_KEYS | BOOLEAN_FALSE_KEYS
    if key not in boolean_keys or field.value_type == "boolean":
        return False
    active_keys = {
        exact_value_key(item.value).casefold()
        for item in field.allowed_values
        if item.is_active
    }
    return any(item_key and item_key not in boolean_keys for item_key in active_keys)

def _allowed_match_single(
    field: AttributeTemplateField,
    value: str,
    allowed: list[AttributeAllowedValue],
    source_name: str = "",
) -> tuple[str, int, str, list[str]]:
    key = exact_value_key(value)
    if not key:
        return "", 0, "Значение не заполнено", []
    canonical = _canonical_matching_value(allowed, value)
    if canonical:
        reason = "Точное значение справочника" if exact_value_key(canonical) == key else "Совпадение со справочником без учёта регистра"
        return canonical, 100, reason, []
    for comparison in (exact_value_key, value_match_key):
        for item in allowed:
            if any(comparison(synonym.synonym) == comparison(value) for synonym in item.synonyms):
                return item.value, 98, "Синоним значения", []
    if field.value_type in {"number", "dimensions"} and not allowed:
        return value, 96, "Формат проверен", []
    if field.value_type == "text" and not allowed:
        return value, 95, "Текстовое значение проверено", []
    if NUMBER_RE.fullmatch(value):
        numeric_value = Decimal(value.replace(",", "."))
        numeric_allowed = []
        for item in allowed:
            if NUMBER_RE.fullmatch(item.value):
                distance = abs(Decimal(item.value.replace(",", ".")) - numeric_value)
                numeric_allowed.append((distance, item.sort_order, item.value))
        numeric_allowed.sort()
        nearby = [item for distance, _order, item in numeric_allowed
                  if distance <= max(abs(numeric_value), abs(Decimal(item.replace(",", ".")))) * Decimal("0.2")]
        return "", 0, "Точного числового значения нет в справочнике", nearby[:3]
    ranked = sorted(
        ((SequenceMatcher(None, value_match_key(value), value_match_key(item.value)).ratio(), item.value) for item in allowed),
        reverse=True,
    )
    return "", 0, "Значения нет в справочнике", [item for score, item in ranked if score >= 0.6][:3]


def _target_value(product: AttributeProduct, field_id: int) -> AttributeProductValue | None:
    return next((value for value in product.values if value.template_field_id == field_id), None)


def _candidate_value_key(target: AttributeProductValue, value: Any) -> str:
    field = target.template_field
    if field:
        try:
            normalized = normalize_value(value, field.value_type, field.is_composite)
            return value_match_key(normalized)
        except ValueError:
            pass
    return value_match_key(value)


def _current_reference_value(target: AttributeProductValue) -> str:
    # current_value remains the original source text for audit. final_value may
    # contain its canonical dictionary equivalent (for example, 1.8 m -> 180 cm).
    return target.final_value or target.current_value


def _has_confirmed_decision(target: AttributeProductValue) -> bool:
    return target.status in {"rejected", "dash"} or (
        target.status == "approved" and not (target.source_details or {}).get("auto_accepted")
    )


def record_unknown_value(
    product: AttributeProduct,
    target: AttributeProductValue,
    *,
    raw_value: str,
    source: str,
    source_name: str,
    source_url: str = "",
    donor_id: int | None = None,
    role: str = "",
    suggestions: list[str],
    reason: str,
) -> None:
    """Keep a mapped fact even when its value does not belong to the dictionary."""
    details = dict(target.source_details or {})

    def same_source(item):
        return (isinstance(item, dict) and item.get("source") == source
                and item.get("source_name") == source_name and item.get("url", "") == source_url)

    details["unknown_values"] = [item for item in details.get("unknown_values", []) if not same_source(item)] + [{
        "value": exact_value_key(raw_value), "source": source, "source_name": source_name,
        "url": source_url, "donor_id": donor_id, "role": role,
        "suggestions": list(dict.fromkeys(suggestions)), "reason": reason,
    }]
    details["candidates"] = [item for item in details.get("candidates", []) if not same_source(item)]
    target.source_details = details
    if not _has_confirmed_decision(target):
        _recalculate_candidate_state(product, target)


def _apply_dictionary_review(target: AttributeProductValue, candidates: list[dict]) -> bool:
    unknown = [item for item in (target.source_details or {}).get("unknown_values", []) if isinstance(item, dict)]
    if not unknown or _has_confirmed_decision(target):
        return False
    current_unknown = any(item.get("value") == target.current_value
                          and item.get("source") in {"current_site", "current_csv"} for item in unknown)
    valid_original = bool(target.current_value and target.final_value and not current_unknown)
    distinct = list({value_match_key(item["value"]): item["value"] for item in reversed(candidates)}.values())
    # Disagreement between known dictionary values remains a source conflict.
    if len(distinct) > 1 or (valid_original and any(
        _candidate_value_key(target, value) != _candidate_value_key(target, target.final_value)
        for value in distinct
    )):
        return False
    alternatives = list(dict.fromkeys(value for item in unknown for value in item.get("suggestions", [])))
    proposals = alternatives if valid_original else (distinct or alternatives)
    target.proposed_value = proposals[0] if proposals else ""
    if not valid_original:
        target.final_value = ""
    target.status = "suggested" if proposals else "conflict"
    target.confidence = int(candidates[0].get("confidence", 0)) if candidates else 0
    target.source = candidates[0].get("source", "") if candidates else unknown[0].get("source", "")
    target.reason = ("Значение отсутствует в справочнике; есть варианты для ручного выбора"
                     if proposals else "Атрибут соответствует шаблону, но его значение отсутствует в справочнике")
    return True


def _recalculate_candidate_state(
    product: AttributeProduct,
    target: AttributeProductValue,
) -> None:
    candidates = [
        item for item in list((target.source_details or {}).get("candidates") or [])
        if isinstance(item, dict) and exact_value_key(item.get("value"))
    ]
    if _apply_dictionary_review(target, candidates):
        return
    if target.current_value:
        current_key = _candidate_value_key(target, _current_reference_value(target))
        conflicts = [
            item for item in candidates
            if _candidate_value_key(target, item["value"]) != current_key
        ]
        target.proposed_value = ""
        target.status = "conflict" if conflicts else "kept"
        target.reason = (
            "Источник расходится с исходным значением; исходное значение сохранено"
            if conflicts else "Источники подтверждают исходное значение"
        )
        return
    if not candidates:
        unknown_values = list((target.source_details or {}).get("unknown_values") or [])
        if not target.final_value:
            target.proposed_value = ""
            target.source = ""
            target.confidence = 0
            target.status = "conflict" if unknown_values else "missing"
            target.reason = (
                "Значения нет в справочнике" if unknown_values
                else "Значение пока не найдено"
            )
        return
    distinct = {_candidate_value_key(target, item["value"]) for item in candidates}
    if len(distinct) > 1:
        target.status = "conflict"
        target.reason = "Источники предлагают разные значения"
        target.proposed_value = ""
        target.final_value = ""
        target.confidence = max(int(item.get("confidence") or 0) for item in candidates)
        return
    best = sorted(
        candidates,
        key=lambda item: (int(item.get("priority") or 0), -int(item.get("confidence") or 0)),
    )[0]
    target.proposed_value = exact_value_key(best.get("value"))
    target.source = clean_text(best.get("source"))
    supporting_sources = {
        (clean_text(item.get("source")), clean_text(item.get("url")))
        for item in candidates
        if _candidate_value_key(target, item["value"])
        == _candidate_value_key(target, best["value"])
    }
    corroboration_bonus = min(8, max(0, len(supporting_sources) - 1) * 4)
    target.confidence = min(100, int(best.get("confidence") or 0) + corroboration_bonus)
    target.reason = clean_text(best.get("reason"))
    if corroboration_bonus:
        target.reason += f"; подтверждено источниками: {len(supporting_sources)}"
    mode = product.batch.processing_mode
    auto = (
        (mode == "auto_exact" and target.confidence == 100)
        or (mode == "auto_primary" and int(best.get("priority") or 0) == 0 and target.confidence >= 85)
        or (mode in {"auto", "auto_confident"} and target.confidence >= 95)
        or mode == "auto_all"
    )
    target.final_value = best["value"] if auto else ""
    target.status = "approved" if auto else "suggested"
    target.source_details = {**(target.source_details or {}), "auto_accepted": auto}


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
    raw_value: str = "",
    source_role: str = "",
    donor_id: int | None = None,
) -> None:
    details = dict(target.source_details or {})
    candidates = [
        item for item in list(details.get("candidates") or [])
        if not (
            isinstance(item, dict)
            and clean_text(item.get("source")) == clean_text(source)
            and clean_text(item.get("source_name")) == clean_text(source_name)
            and clean_text(item.get("url")) == clean_text(source_url)
        )
    ]
    candidate = {
        "value": value,
        "raw_value": exact_value_key(raw_value) or value,
        "confidence": confidence,
        "source": source,
        "reason": reason,
        "priority": priority,
        "source_name": source_name,
        "url": source_url,
        "role": source_role,
        "donor_id": donor_id,
        "matches_current": bool(
            target.current_value
            and _candidate_value_key(target, _current_reference_value(target))
            == _candidate_value_key(target, value)
        ),
    }
    candidates.append(candidate)
    details["candidates"] = candidates
    target.source_details = details
    _recalculate_candidate_state(product, target)


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
    stats = {
        "mapped": 0,
        "unknown": 0,
        "ambiguous": 0,
        "already_filled": 0,
        "not_in_template": 0,
    }
    template = product_template(product)
    if template is None:
        stats["not_in_template"] = len(attributes)
        return stats
    value_keys = {exact_value_key(item.get("value")) for item in attributes if exact_value_key(item.get("value"))}
    value_index = _allowed_value_field_index(template.fields, value_keys)
    for original_item in attributes:
        original_name = clean_text(original_item.get("name"))
        original_value = exact_value_key(original_item.get("value"))
        if not original_name or not original_value:
            continue
        mapping_rows = _attribute_mapping_rows(
            db, template, donor_id, original_item, value_index
        )
        for item, field, mapping_confidence, mapping_reason, _alternatives in mapping_rows:
            mapping_name = clean_text(item.get("name"))
            source_name = clean_text(item.get("source_name") or mapping_name)
            raw_value = exact_value_key(item.get("value"))
            if not mapping_name or not raw_value:
                continue
            if not field:
                stats["ambiguous"] += 1
                continue
            target = _target_value(product, field.id)
            if not target:
                stats["not_in_template"] += 1
                continue
            saved_value = _saved_value_mapping(db, donor_id, field, raw_value)
            if saved_value:
                canonical, value_confidence, value_reason, suggestions = saved_value, 100, "Сохранённое правило значения", []
            else:
                canonical, value_confidence, value_reason, suggestions = _allowed_match(
                    field, raw_value, source_name
                )
            if not canonical:
                stats["unknown"] += 1
                record_unknown_value(
                    product, target, raw_value=raw_value, source=source, source_name=source_name,
                    source_url=source_url, donor_id=donor_id,
                    role="Основной донор" if priority == 0 else "Дополнительный донор",
                    suggestions=suggestions, reason=value_reason,
                )
                if target.current_value:
                    stats["already_filled"] += 1
                continue
            details = dict(target.source_details or {})
            previous_unknown = list(details.get("unknown_values") or [])
            details["unknown_values"] = [
                unknown_item for unknown_item in previous_unknown
                if not (
                    isinstance(unknown_item, dict)
                    and clean_text(unknown_item.get("source")) == clean_text(source)
                    and clean_text(unknown_item.get("source_name")) == source_name
                    and clean_text(unknown_item.get("url")) == clean_text(source_url)
                    and int(unknown_item.get("donor_id") or 0) == int(donor_id or 0)
                )
            ]
            if details["unknown_values"] != previous_unknown:
                target.source_details = details
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
                raw_value=raw_value,
                source_role="Основной донор" if priority == 0 else "Дополнительный донор",
                donor_id=donor_id,
            )
            stats["mapped"] += 1
            if target.current_value:
                stats["already_filled"] += 1
    refresh_product_status(product)
    return stats


def _clear_donor_evidence(product: AttributeProduct) -> None:
    """Remove only donor-derived evidence before applying a fresh donor run."""

    donor_roles = {"primary", "verification"}
    donor_candidate_roles = {"Основной донор", "Дополнительный донор"}
    donor_sources = {
        clean_text(item.donor.brand.name)
        for item in product.sources
        if item.role in donor_roles and item.donor is not None
    }
    product.sources[:] = [
        item for item in product.sources
        if item.role not in donor_roles
    ]
    for value in product.values:
        details = dict(value.source_details or {})
        candidates = [
            item for item in list(details.get("candidates") or [])
            if not (
                isinstance(item, dict)
                and (
                    clean_text(item.get("role")) in donor_candidate_roles
                    or int(item.get("donor_id") or 0) > 0
                )
            )
        ]
        unknown_values = [
            item for item in list(details.get("unknown_values") or [])
            if not (
                isinstance(item, dict)
                and (
                    clean_text(item.get("role")) in donor_candidate_roles
                    or int(item.get("donor_id") or 0) > 0
                )
            )
        ]
        details["candidates"] = candidates
        details["unknown_values"] = unknown_values
        old_source = clean_text(value.source)
        value.source_details = details
        if old_source in donor_sources and not value.current_value:
            value.proposed_value = ""
            value.final_value = ""
            value.source = ""
        _recalculate_candidate_state(product, value)


def process_product_donors(
    db: Session,
    product: AttributeProduct,
    donor_ids: list[int],
    *,
    url_overrides: dict[str, str] | None = None,
    fetcher: DonorPageFetcher | None = None,
) -> dict[str, Any]:
    donor_ids = list(dict.fromkeys(int(item) for item in donor_ids))
    if not donor_ids:
        raise ValueError("Выберите хотя бы одного донора")
    url_overrides = {
        str(key): clean_text(value)
        for key, value in (url_overrides or {}).items()
        if clean_text(value)
    }
    donors = {donor.id: donor for donor in db.scalars(
        select(Donor).where(Donor.id.in_(donor_ids))
    )}
    product_id = product.id
    template = product_template(product)
    model = product.model
    product_name = product.name
    category_name = product.category_name or (template.category.full_path if template else "")
    # End any pending read/write transaction before URL discovery and page loading.
    db.commit()

    collected: list[dict[str, Any]] = []
    raw_dir = ATTRIBUTE_ASSISTANT_DIR / "raw" / str(product.batch_id) / str(product.id)
    raw_dir.mkdir(parents=True, exist_ok=True)
    max_pages = max((donor.thread_count for donor in donors.values()), default=1)
    fetcher_context = nullcontext(fetcher) if fetcher is not None else DonorPageFetcher(max_pages=max_pages)
    with fetcher_context as active_fetcher:
        for priority, donor_id in enumerate(donor_ids):
            donor = donors.get(donor_id)
            if not donor:
                collected.append({
                    "donor_id": donor_id,
                    "priority": priority,
                    "status": "error",
                    "message": "Донор не найден",
                })
                continue
            manual_url = url_overrides.get(str(donor.id), "")
            if manual_url:
                url, resolved_by = manual_url, "Ссылка задана пользователем"
            else:
                url, resolved_by = resolve_donor_url(
                    donor,
                    model,
                    product_name=product_name,
                    category=category_name,
                )
            role = "primary" if priority == 0 else "verification"
            base = {
                "donor_id": donor.id,
                "donor_name": donor.brand.name,
                "priority": priority,
                "role": role,
                "resolved_by": resolved_by,
                "url": url,
            }
            if not url:
                collected.append({
                    **base,
                    "status": "not_found",
                    "message": resolved_by,
                    "source_url": donor.site_url or (donor.start_urls or [""])[0],
                })
                continue
            try:
                html, final_url = fetch_donor_product_html(donor, url, fetcher=active_fetcher)
                parsed = parse_product_html_for_donor(html, final_url, donor)
                attribute_count = len(parsed["attributes"])
                source_status = "parsed" if attribute_count else "no_attributes"
                source_message = (
                    resolved_by if attribute_count
                    else f"{resolved_by}; страница открыта, характеристики не распознаны"
                )
                raw_path = raw_dir / f"{priority}_{donor.id}.html"
                raw_path.write_text(html, encoding="utf-8")
                collected.append({
                    **base,
                    "status": source_status,
                    "message": source_message,
                    "url": final_url,
                    "parsed": parsed,
                    "raw_path": str(raw_path),
                    "attributes_found": attribute_count,
                })
            except Exception as error:
                collected.append({
                    **base,
                    "status": "error",
                    "message": str(error),
                })

    db.expire_all()
    product = db.get(AttributeProduct, product_id)
    if product is None:
        raise ValueError("Товар был удалён во время обработки")
    _clear_donor_evidence(product)
    # DELETE must reach SQLite before rows with the same unique key are inserted again.
    db.flush()
    product.selected_donor_ids = donor_ids
    product.donor_url_overrides = url_overrides
    reports: list[dict[str, Any]] = []
    for item in collected:
        donor_id = int(item.get("donor_id") or 0)
        donor = donors.get(donor_id)
        if not donor:
            reports.append({
                "donor_id": donor_id,
                "status": "error",
                "message": clean_text(item.get("message")),
            })
            continue
        priority = int(item.get("priority") or 0)
        role = clean_text(item.get("role"))
        status = clean_text(item.get("status"))
        if status in {"not_found", "error"}:
            db.add(AttributeProductSource(
                product=product,
                donor=donor,
                url=clean_text(item.get("source_url") or item.get("url")),
                priority=priority,
                role=role,
                status=status,
                parsed_data={"message": clean_text(item.get("message"))},
            ))
            reports.append({
                "donor_id": donor.id,
                "name": item["donor_name"],
                "status": status,
                "message": clean_text(item.get("message")),
            })
            continue
        parsed = dict(item.get("parsed") or {})
        final_url = clean_text(item.get("url"))
        stats = apply_parsed_attributes(
            db,
            product,
            list(parsed.get("attributes") or []),
            source=item["donor_name"],
            priority=priority,
            donor_id=donor.id,
            source_url=final_url,
        )
        parsed["message"] = clean_text(item.get("message"))
        parsed["processing_stats"] = stats
        db.add(AttributeProductSource(
            product=product,
            donor=donor,
            url=final_url,
            priority=priority,
            role=role,
            status=status,
            raw_html_path=clean_text(item.get("raw_path")),
            parsed_data=parsed,
        ))
        reports.append({
            "donor_id": donor.id,
            "name": item["donor_name"],
            "status": status,
            "url": final_url,
            "resolved_by": clean_text(item.get("resolved_by")),
            "attributes_found": int(item.get("attributes_found") or 0),
            **stats,
        })
    state = dict(product.processing_state or {})
    state["donors_processed"] = True
    state["donor_reports"] = reports
    state["last_processing_complete"] = all(
        report.get("status") not in {"error", "not_found"} for report in reports
    )
    product.processing_state = state
    product.donor_urls = [
        report.get("url", "") for report in reports if report.get("url")
    ]
    refresh_product_status(product)
    refresh_batch_summary(product.batch)
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



def _saved_value_mapping(
    db: Session,
    donor_id: int | None,
    field: AttributeTemplateField,
    raw_value: str,
) -> str:
    if not donor_id:
        return ""
    rule = db.scalar(
        select(AttributeValueMappingRule).where(
            AttributeValueMappingRule.donor_id == donor_id,
            AttributeValueMappingRule.template_field_id == field.id,
            AttributeValueMappingRule.normalized_raw_value == dictionary_value_key(raw_value, field.value_type),
            AttributeValueMappingRule.is_active.is_(True),
        )
    )
    if rule and rule.allowed_value.is_active:
        return rule.allowed_value.value
    matches = [candidate.allowed_value.value for candidate in db.scalars(
        select(AttributeValueMappingRule).where(
            AttributeValueMappingRule.donor_id == donor_id,
            AttributeValueMappingRule.template_field_id == field.id,
            AttributeValueMappingRule.is_active.is_(True),
        ).order_by(AttributeValueMappingRule.id)
    ) if candidate.allowed_value.is_active and value_match_key(candidate.raw_value) == value_match_key(raw_value)]
    # Older case variants may point to conflicting rules; do not choose one arbitrarily.
    if matches and len({value_match_key(value) for value in matches}) == 1:
        return matches[0]
    return ""


def save_value_mapping_rule(
    db: Session,
    *,
    donor_id: int,
    field: AttributeTemplateField,
    raw_value: str,
    allowed_value_id: int,
) -> AttributeValueMappingRule:
    if not db.get(Donor, donor_id):
        raise ValueError("Донор не найден")
    raw = exact_value_key(raw_value)
    key = dictionary_value_key(raw, field.value_type)
    if not key:
        raise ValueError("Исходное значение донора не заполнено")
    allowed = db.get(AttributeAllowedValue, allowed_value_id)
    if not allowed or allowed.field_id != field.id or not allowed.is_active:
        raise ValueError("Разрешённое значение атрибута не найдено")
    rule = db.scalar(
        select(AttributeValueMappingRule).where(
            AttributeValueMappingRule.donor_id == donor_id,
            AttributeValueMappingRule.template_field_id == field.id,
            AttributeValueMappingRule.normalized_raw_value == key,
        )
    )
    if rule is None:
        rule = AttributeValueMappingRule(
            donor_id=donor_id,
            template_field=field,
            allowed_value=allowed,
            raw_value=raw,
            normalized_raw_value=key,
        )
        db.add(rule)
    else:
        rule.allowed_value = allowed
        rule.raw_value = raw
        rule.is_active = True
    return rule


def list_value_mapping_rules(
    db: Session,
    template_id: int | None = None,
) -> list[dict[str, Any]]:
    statement = select(AttributeValueMappingRule).order_by(
        AttributeValueMappingRule.updated_at.desc()
    )
    if template_id:
        statement = statement.join(AttributeTemplateField).where(
            AttributeTemplateField.template_id == template_id
        )
    return [
        {
            "id": row.id,
            "donor_id": row.donor_id,
            "donor_name": row.donor.brand.name,
            "template_id": row.template_field.template_id,
            "field_id": row.template_field_id,
            "field_name": row.template_field.name,
            "raw_value": row.raw_value,
            "allowed_value_id": row.allowed_value_id,
            "allowed_value": row.allowed_value.value,
            "is_active": row.is_active,
        }
        for row in db.scalars(statement)
    ]


def serialize_value(
    value: AttributeProductValue,
    *,
    include_allowed_values: bool = True,
    allowed_values_count: int | None = None,
) -> dict[str, Any]:
    field = value.template_field
    active_allowed = None
    if field and (include_allowed_values or allowed_values_count is None):
        active_allowed = [item for item in field.allowed_values if item.is_active]
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
        "value_type": field.value_type if field else "text",
        "is_composite": bool(field and field.is_composite),
        "allowed_values_count": (
            int(allowed_values_count)
            if allowed_values_count is not None
            else len(active_allowed or [])
        ),
        "allowed_values": [
            {"id": item.id, "value": item.value, "is_combination": item.is_combination}
            for item in sorted(
                active_allowed or [],
                key=lambda item: (item.sort_order, item.value.casefold()),
            )[:200]
        ] if field and include_allowed_values else [],
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
        "template": serialize_template(product_template(product)) if product_template(product) else None,
        "selected_donor_ids": list(product.selected_donor_ids or []),
        "donor_url_overrides": dict(product.donor_url_overrides or {}),
        "donor_urls": list(product.donor_urls or []),
        "processing_state": dict(product.processing_state or {}),
        "counts": {
            "missing": sum(value.is_in_template and not value.final_value for value in product.values),
            "conflicts": sum(value.status == "conflict" for value in product.values),
            "suggestions": sum(value.status == "suggested" for value in product.values),
            "outside_template": sum(not value.is_in_template for value in product.values),
        },
    }
    if detailed:
        template = product_template(product)
        if template and result["template"] is not None:
            result["template"]["fields"] = [
                {
                    "id": field.id,
                    "group_name": field.group_name,
                    "name": field.name,
                    "value_type": field.value_type,
                    "is_composite": field.is_composite,
                    "is_required": field.is_required,
                    "sort_order": field.sort_order,
                }
                for field in template.fields
            ]
        field_ids = {
            value.template_field_id
            for value in product.values
            if value.template_field_id is not None
        }
        allowed_counts: dict[int, int] = {}
        session = object_session(product)
        if session is not None and field_ids:
            allowed_counts = dict(session.execute(
                select(AttributeAllowedValue.field_id, func.count(AttributeAllowedValue.id))
                .where(
                    AttributeAllowedValue.field_id.in_(field_ids),
                    AttributeAllowedValue.is_active.is_(True),
                )
                .group_by(AttributeAllowedValue.field_id)
            ).all())
        result["values"] = [
            serialize_value(
                value,
                include_allowed_values=False,
                allowed_values_count=allowed_counts.get(value.template_field_id, 0),
            )
            for value in product.values
        ]
        result["sources"] = [
            {
                "id": source.id,
                "donor_id": source.donor_id,
                "donor_name": (
                    "ChatGPT" if source.role == "chatgpt"
                    else source.donor.brand.name if source.donor
                    else "Страница сайта"
                ),
                "source_type": (
                    "chatgpt" if source.role == "chatgpt"
                    else "donor" if source.donor
                    else "site"
                ),
                "url": source.url,
                "priority": source.priority,
                "role": source.role,
                "status": source.status,
                "message": (source.parsed_data or {}).get("message", ""),
                "attributes": [],
                "attributes_found": len((source.parsed_data or {}).get("attributes") or []),
                "mapped": int(((source.parsed_data or {}).get("processing_stats") or {}).get("mapped") or 0),
                "unknown": int(((source.parsed_data or {}).get("processing_stats") or {}).get("unknown") or 0),
                "ambiguous": int(((source.parsed_data or {}).get("processing_stats") or {}).get("ambiguous") or 0),
                "already_filled": int(((source.parsed_data or {}).get("processing_stats") or {}).get("already_filled") or 0),
            }
            for source in product.sources
            if source.donor is not None or source.role == "chatgpt"
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
        "source_urls": list(batch.source_urls or []),
        "original_ready": bool(batch.original_path and Path(batch.original_path).is_file()),
        "summary": refresh_batch_summary(batch) if detailed or not batch.summary else dict(batch.summary),
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
    batch_rows = [serialize_batch(batch) for batch in batches]
    return {
        "templates": [serialize_template(template) for template in templates],
        "donors": list_donors(db),
        "batches": batch_rows,
        "dashboard": {
            "active_templates": sum(template.is_active for template in templates),
            "batches": len(batch_rows),
            "products": sum(int((item.get("summary") or {}).get("products") or 0) for item in batch_rows),
            "ready": sum(int((item.get("summary") or {}).get("ready") or 0) for item in batch_rows),
            "conflicts": sum(int((item.get("summary") or {}).get("conflicts") or 0) for item in batch_rows),
            "missing": sum(int((item.get("summary") or {}).get("missing") or 0) for item in batch_rows),
        },
    }


def update_product_value(
    value: AttributeProductValue,
    *,
    action: str,
    manual_value: str = "",
    dash_reason: str = "",
) -> AttributeProductValue:
    field = value.template_field
    if action == "accept":
        manual_selected = exact_value_key(manual_value)
        selected = manual_selected or value.proposed_value
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
        value.source_details = {**(value.source_details or {}), "auto_accepted": False}
        value.dash_reason = ""
        if manual_selected:
            value.source = "manual"
            value.reason = "Итоговое значение выбрано пользователем из шаблона"
        else:
            value.source = value.source or "manual"
    elif action == "reject":
        value.proposed_value = ""
        value.dash_reason = ""
        if value.current_value:
            value.final_value = value.current_value
            value.source = "current_csv"
            value.reason = "Предложение отклонено; сохранено исходное значение"
        else:
            value.final_value = ""
            value.reason = "Предложение отклонено пользователем"
        value.status = "rejected"
    elif action == "dash":
        if value.current_value and not is_technical_dash(value.current_value):
            raise ValueError("Технический пропуск нельзя поставить вместо заполненного исходного значения")
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


def delete_extra_product_value(db: Session, value: AttributeProductValue) -> AttributeProduct:
    if value.is_in_template or not value.is_extra_attribute:
        raise ValueError("Удалять можно только атрибуты вне шаблона")
    product = value.product
    if product.batch.input_mode == "urls":
        state = dict(product.processing_state or {})
        removed = list(state.get("removed_outside_template_attributes") or [])
        marker = {
            "group_name": normalize_key(value.group_name),
            "name": normalize_key(value.attribute_name),
            "value": exact_value_key(value.current_value or value.final_value),
        }
        if marker not in removed:
            removed.append(marker)
        state["removed_outside_template_attributes"] = removed
        product.processing_state = state
    if value in product.values:
        product.values.remove(value)
    else:
        db.delete(value)
    db.flush()
    refresh_product_status(product)
    refresh_batch_summary(product.batch)
    return product


def bulk_action(batch: AttributeBatch, action: str, minimum_confidence: int = 90, dash_reason: str = "") -> int:
    changed = 0
    for product in batch.products:
        for value in product.values:
            if not value.is_in_template:
                continue
            if (
                action == "accept_high"
                and not value.current_value
                and value.status == "suggested"
                and value.confidence >= minimum_confidence
            ):
                update_product_value(value, action="accept")
                changed += 1
            elif (
                action == "fill_dashes"
                and not value.final_value
                and value.status != "conflict"
                and (not value.current_value or is_technical_dash(value.current_value))
            ):
                update_product_value(value, action="dash", dash_reason=dash_reason or "Не найдено после проверки источников")
                changed += 1
        refresh_product_status(product)
    refresh_batch_summary(batch)
    return changed


def apply_similar_products(db: Session, product: AttributeProduct) -> int:
    template = product_template(product)
    if template is None:
        return 0
    candidates = list(db.scalars(
        select(AttributeProduct).where(AttributeProduct.id != product.id).limit(500)
    ))
    product_model_tokens = set(model_tokens(product.model))
    ranked_peers: list[tuple[int, AttributeProduct]] = []
    for peer in candidates:
        peer_template = product_template(peer)
        if peer_template is None or peer_template.id != template.id:
            continue
        score = 20
        if normalize_key(product.brand) and normalize_key(product.brand) == normalize_key(peer.brand):
            score += 35
        if normalize_key(product.category_name) and normalize_key(product.category_name) == normalize_key(peer.category_name):
            score += 15
        peer_tokens = set(model_tokens(peer.model))
        if product_model_tokens and peer_tokens:
            overlap = len(product_model_tokens & peer_tokens) / len(product_model_tokens | peer_tokens)
            score += round(overlap * 30)
        if score >= 35:
            ranked_peers.append((score, peer))
    ranked_peers.sort(key=lambda item: item[0], reverse=True)
    ranked_peers = ranked_peers[:60]
    changed = 0
    for target in product.values:
        field = target.template_field
        if target.current_value or target.final_value or not field:
            continue
        if field.value_type in {"number", "dimensions"}:
            continue
        weighted: dict[str, int] = {}
        examples: dict[str, list[str]] = {}
        for score, peer in ranked_peers:
            peer_value = _target_value(peer, field.id)
            if peer_value and peer_value.final_value and peer_value.final_value != "-":
                weighted[peer_value.final_value] = weighted.get(peer_value.final_value, 0) + score
                examples.setdefault(peer_value.final_value, []).append(peer.model)
        if not weighted:
            continue
        best, best_weight = max(weighted.items(), key=lambda item: item[1])
        total_weight = sum(weighted.values())
        agreement = best_weight / total_weight if total_weight else 0
        sample_count = len(examples.get(best, []))
        confidence = min(88, round(45 + agreement * 30 + min(sample_count, 5) * 3))
        if confidence < 65:
            continue
        apply_candidate(
            product,
            target,
            value=best,
            confidence=confidence,
            source="Похожие товары",
            reason=(
                f"Взвешенное совпадение у {sample_count} похожих товаров; "
                f"учтены шаблон, бренд, категория и близость модели"
            ),
            priority=50,
            source_name=field.name,
        )
        changed += 1
    refresh_product_status(product)
    refresh_batch_summary(product.batch)
    return changed

def export_batch_csv(batch: AttributeBatch, *, ready_only: bool = False) -> Path:
    selected_products = [
        product for product in batch.products
        if not ready_only or product.status == "ready"
    ]
    if not selected_products:
        raise ValueError("Нет готовых товаров для экспорта" if ready_only else "Нет товаров для экспорта")
    output_dir = ATTRIBUTE_ASSISTANT_DIR / "exports"
    output_dir.mkdir(parents=True, exist_ok=True)
    filename = f"attributes_{batch.id}_{uuid.uuid4().hex[:8]}.csv"
    path = output_dir / filename
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=["_MODEL_", "_ATTRIBUTES_"], delimiter=";", lineterminator="\r\n")
    writer.writeheader()
    for product in selected_products:
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


def delete_batch_files(batch: AttributeBatch) -> int:
    """Remove every file owned by a processing batch from attribute storage."""

    storage_root = ATTRIBUTE_ASSISTANT_DIR.resolve()
    candidates: set[Path] = set()

    def remember(raw_path: str) -> None:
        if not raw_path:
            return
        path = Path(raw_path)
        if not path.is_absolute():
            path = ATTRIBUTE_ASSISTANT_DIR / path
        candidates.add(path)

    for raw_path in (batch.original_path, batch.export_path, batch.report_filename):
        remember(raw_path)
    if batch.stored_filename:
        remember(str(ATTRIBUTE_ASSISTANT_DIR / "inputs" / Path(batch.stored_filename).name))
    if batch.export_filename:
        remember(str(ATTRIBUTE_ASSISTANT_DIR / "exports" / Path(batch.export_filename).name))
    for product in batch.products:
        for source in product.sources:
            remember(source.raw_html_path)
    for path in (ATTRIBUTE_ASSISTANT_DIR / "exports").glob(f"attributes_{batch.id}_*.csv"):
        candidates.add(path)
    for path in (ATTRIBUTE_ASSISTANT_DIR / "reports").glob(f"attribute_report_{batch.id}_*.csv"):
        candidates.add(path)

    removed = 0
    for path in candidates:
        try:
            resolved = path.resolve()
            if storage_root not in resolved.parents or not resolved.is_file():
                continue
            resolved.unlink()
            removed += 1
        except OSError:
            continue

    raw_directory = (ATTRIBUTE_ASSISTANT_DIR / "raw" / str(batch.id)).resolve()
    try:
        if storage_root in raw_directory.parents and raw_directory.is_dir():
            removed += sum(path.is_file() for path in raw_directory.rglob("*"))
            shutil.rmtree(raw_directory)
    except OSError:
        pass
    return removed


def delete_attribute_batch(db: Session, batch: AttributeBatch) -> dict[str, int]:
    """Delete a processing and all of its data without touching its template."""

    product_ids = [product.id for product in batch.products if product.id is not None]
    if product_ids:
        db.execute(
            delete(AttributeProductRevision).where(
                AttributeProductRevision.product_id.in_(product_ids)
            )
        )
    removed_files = delete_batch_files(batch)
    products = len(batch.products)
    db.delete(batch)
    db.flush()
    return {"products": products, "files": removed_files}


def delete_attribute_template(db: Session, template: AttributeTemplate) -> None:
    """Delete an explicitly selected template only when no processing uses it."""

    batch_count = int(db.scalar(
        select(func.count(AttributeBatch.id)).where(
            AttributeBatch.template_id == template.id
        )
    ) or 0)
    product_count = int(db.scalar(
        select(func.count(AttributeProduct.id)).where(
            AttributeProduct.template_id == template.id
        )
    ) or 0)
    if batch_count or product_count:
        raise ValueError(
            "Шаблон используется: "
            f"обработок — {batch_count}, товаров — {product_count}. "
            "Сначала удалите связанные обработки или назначьте товарам другой шаблон."
        )

    field_ids = list(db.scalars(
        select(AttributeTemplateField.id).where(
            AttributeTemplateField.template_id == template.id
        )
    ))
    if field_ids:
        db.execute(
            delete(AttributeValueMappingRule).where(
                AttributeValueMappingRule.template_field_id.in_(field_ids)
            )
        )
    db.execute(
        delete(AttributeMappingRule).where(
            AttributeMappingRule.template_id == template.id
        )
    )
    db.delete(template)
    db.flush()


def template_snapshot(template: AttributeTemplate) -> dict[str, Any]:
    return {
        "schema": TEMPLATE_SNAPSHOT_SCHEMA,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "name": template.name,
        "category": template.category.full_path,
        "product_type": template.product_type,
        "description": template.description,
        "is_default": template.is_default,
        "is_active": template.is_active,
        "fields": [
            {
                "id": field.id,
                "group_name": field.group_name,
                "name": field.name,
                "synonyms": list(field.synonyms or []),
                "value_type": field.value_type,
                "is_composite": field.is_composite,
                "is_required": field.is_required,
                "separator": field.separator,
                "use_dash_if_empty": field.use_dash_if_empty,
                "conversion_rules": list(field.conversion_rules or []),
                "sort_order": field.sort_order,
                "allowed_values": [
                    {
                        "id": allowed.id,
                        "value": allowed.value,
                        "is_combination": allowed.is_combination,
                        "is_active": allowed.is_active,
                        "sort_order": allowed.sort_order,
                        "source": allowed.source,
                        "synonyms": [synonym.synonym for synonym in allowed.synonyms],
                    }
                    for allowed in field.allowed_values
                ],
            }
            for field in template.fields
        ],
    }


def _pack_snapshot(snapshot: dict[str, Any], schema: str) -> dict[str, Any]:
    payload = json.dumps(
        snapshot,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    compressed = gzip.compress(payload, compresslevel=6)
    return {
        "schema": schema,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "encoding": "gzip+base64",
        "payload": base64.b64encode(compressed).decode("ascii"),
    }


def _unpack_snapshot(snapshot: dict[str, Any], schema: str) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise ValueError("Снимок имеет некорректный формат")
    if snapshot.get("encoding") != "gzip+base64":
        return snapshot
    if clean_text(snapshot.get("schema")) != schema:
        raise ValueError("Снимок относится к другому типу данных")
    try:
        payload = base64.b64decode(clean_text(snapshot.get("payload")), validate=True)
        decoded = json.loads(gzip.decompress(payload).decode("utf-8"))
    except (OSError, ValueError, TypeError, json.JSONDecodeError) as error:
        raise ValueError("Не удалось прочитать сжатый снимок") from error
    if not isinstance(decoded, dict):
        raise ValueError("Снимок имеет некорректный формат")
    return decoded


def save_template_revision(
    db: Session,
    template: AttributeTemplate,
    action: str,
    report: dict[str, Any] | None = None,
) -> AttributeTemplateRevision:
    loaded_template = db.scalar(
        select(AttributeTemplate)
        .where(AttributeTemplate.id == template.id)
        .options(
            selectinload(AttributeTemplate.category),
            selectinload(AttributeTemplate.fields)
            .selectinload(AttributeTemplateField.allowed_values)
            .selectinload(AttributeAllowedValue.synonyms),
        )
    ) or template
    revision = AttributeTemplateRevision(
        template=template,
        version=template.version,
        action=action,
        snapshot=_pack_snapshot(
            template_snapshot(loaded_template),
            TEMPLATE_SNAPSHOT_SCHEMA,
        ),
        report=report or {},
    )
    db.add(revision)
    return revision


def save_allowed_value_revision(
    db: Session,
    allowed: AttributeAllowedValue,
    action: str,
    report: dict[str, Any] | None = None,
) -> AttributeTemplateRevision:
    template = allowed.field.template
    details = {"allowed_id": allowed.id, "field_id": allowed.field_id, **(report or {})}
    revision = AttributeTemplateRevision(
        template=template,
        version=template.version,
        action=action,
        snapshot={
            "kind": "allowed_value",
            "allowed_value": {
                "id": allowed.id,
                "field_id": allowed.field_id,
                "value": allowed.value,
                "is_combination": allowed.is_combination,
                "is_active": allowed.is_active,
                "sort_order": allowed.sort_order,
                "source": allowed.source,
                "synonyms": [item.synonym for item in allowed.synonyms],
            },
        },
        report=details,
    )
    db.add(revision)
    return revision


TEMPLATE_FIELD_TYPES = {"select", "select_exact", "text", "number", "dimensions", "boolean"}
TEMPLATE_FIELD_UPDATE_KEYS = {
    "group_name",
    "name",
    "synonyms",
    "value_type",
    "separator",
    "is_required",
    "is_composite",
    "use_dash_if_empty",
    "sort_order",
    "conversion_rules",
}


def _validated_template_field_synonyms(
    field: AttributeTemplateField,
    synonyms: Iterable[object],
    *,
    canonical_name: str | None = None,
) -> list[str]:
    raw_synonyms = list(synonyms)
    if len(raw_synonyms) > 100:
        raise ValueError("Для одного атрибута допускается не больше 100 синонимов")
    canonical_key = normalize_key(canonical_name if canonical_name is not None else field.name)
    occupied: dict[str, str] = {}
    for other in field.template.fields:
        if other.id == field.id:
            continue
        occupied[normalize_key(other.name)] = other.name
        for synonym in other.synonyms or []:
            key = normalize_key(synonym)
            if key:
                occupied[key] = other.name

    result: list[str] = []
    seen: set[str] = set()
    for raw_synonym in raw_synonyms:
        synonym = clean_text(raw_synonym)
        if len(synonym) > 500:
            raise ValueError("Синоним атрибута не должен превышать 500 символов")
        synonym_key = normalize_key(synonym)
        if not synonym_key or synonym_key == canonical_key or synonym_key in seen:
            continue
        owner = occupied.get(synonym_key)
        if owner:
            raise ValueError(
                f"Синоним «{synonym}» уже относится к атрибуту «{owner}»"
            )
        seen.add(synonym_key)
        result.append(synonym)
    return result


def replace_template_field_synonyms(
    db: Session,
    field: AttributeTemplateField,
    synonyms: Iterable[object],
) -> list[str]:
    replacement = _validated_template_field_synonyms(field, synonyms)
    field.synonyms = replacement
    db.flush()
    return replacement


def apply_template_field_synonyms(db: Session, field: AttributeTemplateField) -> int:
    """Apply saved aliases to existing unmatched facts without fetching donor pages."""
    keys = {normalize_key(synonym) for synonym in field.synonyms or []}
    if not keys:
        return 0
    products = db.scalars(
        select(AttributeProduct).join(AttributeBatch).where(
            (AttributeProduct.template_id == field.template_id)
            | (
                AttributeProduct.template_id.is_(None)
                & (AttributeBatch.template_id == field.template_id)
            )
        )
    )
    changed = 0
    batches: dict[int, AttributeBatch] = {}
    for product in products:
        if product_template(product) is not field.template:
            continue
        target = _target_value(product, field.id)
        if target is None or _has_confirmed_decision(target):
            continue
        extras = [
            value for value in product.values
            if not value.is_in_template
            and normalize_key(value.attribute_name) in keys
            and value.source in {"current_csv", "current_site"}
            and value.current_value
            and not _has_confirmed_decision(value)
        ]
        donor_rows = []
        for source in product.sources:
            if source.role not in {"primary", "verification"} or source.donor is None:
                continue
            attributes = [
                item for item in (source.parsed_data or {}).get("attributes") or []
                if normalize_key(item.get("name")) in keys
                and map_attribute(
                    db, field.template, source.donor_id, item.get("name"), item.get("value", "")
                )[0] is field
            ]
            if attributes:
                donor_rows.append((source, attributes))
        if not extras and not donor_rows:
            continue
        before = capture_product_snapshot(product)
        for extra in extras:
            # Keep a differing original visible instead of silently replacing it.
            if target.current_value:
                continue
            shadow = SimpleNamespace(values=[], source_url=product.source_url)
            _make_product_values(
                shadow, field.template,
                [{"name": extra.attribute_name, "group_name": extra.group_name, "value": extra.current_value}],
                current_source=extra.source,
                current_role="Исходная страница сайта" if extra.source == "current_site" else "Исходный CSV сайта",
            )
            restored = next(value for value in shadow.values if value.template_field is field)
            if not restored.current_value:
                continue
            details = dict(target.source_details or {})
            for key, value in (restored.source_details or {}).items():
                if key == "unknown_values":
                    details[key] = [*details.get(key, []), *value]
                else:
                    details[key] = value
            for key in (
                "current_value", "proposed_value", "final_value", "confidence",
                "status", "reason", "source", "dash_reason",
            ):
                setattr(target, key, getattr(restored, key))
            target.source_details = details
            if details.get("candidates"):
                _recalculate_candidate_state(product, target)
            product.values.remove(extra)
        for source, attributes in donor_rows:
            # A newly explicit alias can replace an earlier fuzzy assignment.
            names = {normalize_key(item["name"]) for item in attributes}
            for existing in product.values:
                if _has_confirmed_decision(existing):
                    continue
                details = dict(existing.source_details or {})
                updated = False
                for key in ("candidates", "unknown_values"):
                    evidence = list(details.get(key) or [])
                    kept = [
                        item for item in evidence
                        if not (
                            int(item.get("donor_id") or 0) == source.donor_id
                            and clean_text(item.get("url")) == source.url
                            and normalize_key(item.get("source_name")) in names
                        )
                    ]
                    if kept != evidence:
                        details[key] = kept
                        updated = True
                if updated:
                    existing.source_details = details
                    if not existing.current_value:
                        existing.final_value = ""
                    _recalculate_candidate_state(product, existing)
            apply_parsed_attributes(
                db, product, attributes, source=source.donor.brand.name,
                priority=source.priority, donor_id=source.donor_id, source_url=source.url,
            )
        refresh_product_status(product)
        if capture_product_snapshot(product) != before:
            save_product_snapshot(db, product, "Перед применением синонимов атрибута", before)
            changed += 1
            batches[product.batch_id] = product.batch
    for batch in batches.values():
        refresh_batch_summary(batch)
    return changed


def _validated_conversion_rules(value: Any) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Правила конвертации должны быть JSON-массивом")
    if len(value) > 100:
        raise ValueError("Для одного атрибута допускается не больше 100 правил конвертации")
    allowed_keys = {"from_value", "to_value", "from_unit", "factor", "suffix"}
    result: list[dict[str, Any]] = []
    for index, raw_rule in enumerate(value, start=1):
        if not isinstance(raw_rule, dict):
            raise ValueError(f"Правило конвертации #{index} должно быть объектом")
        unknown_keys = set(raw_rule) - allowed_keys
        if unknown_keys:
            raise ValueError(
                f"Правило конвертации #{index} содержит неизвестные поля: "
                + ", ".join(sorted(unknown_keys))
            )
        rule = {
            key: clean_text(raw_rule.get(key))
            for key in allowed_keys
            if raw_rule.get(key) is not None
        }
        has_value_mapping = bool(rule.get("from_value") and rule.get("to_value"))
        has_unit_mapping = bool(rule.get("from_unit"))
        if not has_value_mapping and not has_unit_mapping:
            raise ValueError(
                f"В правиле конвертации #{index} задайте from_value/to_value "
                "или from_unit"
            )
        if ("from_value" in rule) != ("to_value" in rule):
            raise ValueError(
                f"В правиле конвертации #{index} from_value и to_value "
                "должны быть заданы вместе"
            )
        if "factor" in rule:
            try:
                Decimal(rule["factor"].replace(",", "."))
            except InvalidOperation as error:
                raise ValueError(
                    f"В правиле конвертации #{index} factor должен быть числом"
                ) from error
        if any(len(item) > 1000 for item in rule.values()):
            raise ValueError(f"Правило конвертации #{index} содержит слишком длинное значение")
        result.append(rule)
    return result


def validate_template_field_update(
    db: Session,
    field: AttributeTemplateField,
    payload: dict[str, Any],
) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise ValueError("Параметры атрибута должны быть объектом")
    unknown = set(payload) - TEMPLATE_FIELD_UPDATE_KEYS
    if unknown:
        raise ValueError("Неизвестные параметры атрибута: " + ", ".join(sorted(unknown)))
    group_name = (
        clean_text(payload.get("group_name"))
        if "group_name" in payload else field.group_name
    )
    name = clean_text(payload.get("name")) if "name" in payload else field.name
    value_type = (
        clean_text(payload.get("value_type"))
        if "value_type" in payload else field.value_type
    )
    separator = (
        clean_text(payload.get("separator"))
        if "separator" in payload else field.separator
    )
    if not group_name:
        raise ValueError("Название группы не может быть пустым")
    if not name:
        raise ValueError("Название атрибута не может быть пустым")
    if len(group_name) > 255:
        raise ValueError("Название группы не должно превышать 255 символов")
    if len(name) > 500:
        raise ValueError("Название атрибута не должно превышать 500 символов")
    if value_type == "select_exact":
        value_type = "select"
    if value_type not in TEMPLATE_FIELD_TYPES:
        raise ValueError("Неизвестный тип атрибута")
    if not separator or len(separator) > 8:
        raise ValueError("Разделитель должен содержать от 1 до 8 символов")
    duplicate = next(
        (
            item for item in field.template.fields
            if item.id != field.id
            and normalize_key(item.group_name) == normalize_key(group_name)
            and normalize_key(item.name) == normalize_key(name)
        ),
        None,
    )
    if duplicate:
        raise ValueError("Такой атрибут уже есть в этой группе")
    name_key = normalize_key(name)
    synonym_owner = next(
        (
            item
            for item in field.template.fields
            if item.id != field.id
            and any(normalize_key(synonym) == name_key for synonym in (item.synonyms or []))
        ),
        None,
    )
    if synonym_owner:
        raise ValueError(
            f"Название уже используется как синоним атрибута «{synonym_owner.name}»"
        )

    updates: dict[str, Any] = {}
    for key in ("group_name", "name", "value_type", "separator"):
        if key in payload:
            updates[key] = {
                "group_name": group_name,
                "name": name,
                "value_type": value_type,
                "separator": separator,
            }[key]
    for key in ("is_required", "is_composite", "use_dash_if_empty"):
        if key in payload:
            if not isinstance(payload.get(key), bool):
                raise ValueError(f"{key} должен быть логическим значением")
            updates[key] = payload[key]
    if "sort_order" in payload:
        try:
            sort_order = int(payload.get("sort_order"))
        except (TypeError, ValueError) as error:
            raise ValueError("Порядок атрибута должен быть целым числом") from error
        if sort_order < 0 or sort_order > 100_000:
            raise ValueError("Порядок атрибута находится вне допустимого диапазона")
        updates["sort_order"] = sort_order
    if "conversion_rules" in payload:
        updates["conversion_rules"] = _validated_conversion_rules(
            payload.get("conversion_rules")
        )
    if "synonyms" in payload or "name" in payload:
        synonyms = payload.get("synonyms") if "synonyms" in payload else field.synonyms
        if not isinstance(synonyms, list):
            raise ValueError("Синонимы атрибута должны быть переданы списком")
        updates["synonyms"] = _validated_template_field_synonyms(
            field,
            synonyms,
            canonical_name=name,
        )
    return updates


def create_template_field(
    db: Session,
    template: AttributeTemplate,
    *,
    group_name: str,
    name: str,
    value_type: str = "select",
    is_required: bool = True,
    is_composite: bool = False,
    separator: str = "/",
) -> AttributeTemplateField:
    group = clean_text(group_name) or "Основные характеристики"
    field_name = clean_text(name)
    kind = clean_text(value_type) or "select"
    if kind == "select_exact":
        kind = "select"
    if not field_name:
        raise ValueError("Укажите название атрибута")
    if kind not in TEMPLATE_FIELD_TYPES:
        raise ValueError("Неизвестный тип атрибута")
    if len(group) > 255:
        raise ValueError("Название группы не должно превышать 255 символов")
    if len(field_name) > 500:
        raise ValueError("Название атрибута не должно превышать 500 символов")
    conflicting_synonym = next(
        (
            item
            for item in template.fields
            if any(
                normalize_key(synonym) == normalize_key(field_name)
                for synonym in (item.synonyms or [])
            )
        ),
        None,
    )
    if conflicting_synonym:
        raise ValueError(
            f"Название уже используется как синоним атрибута «{conflicting_synonym.name}»"
        )
    clean_separator = clean_text(separator) or "/"
    if len(clean_separator) > 8:
        raise ValueError("Разделитель не должен превышать 8 символов")
    duplicate = next(
        (
            field for field in template.fields
            if normalize_key(field.group_name) == normalize_key(group)
            and normalize_key(field.name) == normalize_key(field_name)
        ),
        None,
    )
    if duplicate:
        raise ValueError("Такой атрибут уже есть в этой группе")
    save_template_revision(db, template, "before_field_create")
    field = AttributeTemplateField(
        template=template,
        group_name=group,
        name=field_name,
        value_type=kind,
        is_required=bool(is_required),
        is_composite=bool(is_composite),
        separator=clean_separator,
        sort_order=max((item.sort_order for item in template.fields), default=-1) + 1,
    )
    db.add(field)
    template.version += 1
    db.flush()
    return field


def delete_template_field(
    db: Session,
    field: AttributeTemplateField,
) -> AttributeTemplate:
    template = field.template
    save_template_revision(db, template, "before_field_delete", {"field_id": field.id})
    product_values = list(db.scalars(
        select(AttributeProductValue).where(
            AttributeProductValue.template_field_id == field.id
        )
    ))
    for value in product_values:
        if any(clean_text(item) for item in (
            value.current_value, value.proposed_value, value.final_value
        )):
            value.template_field = None
            value.is_in_template = False
            value.is_extra_attribute = True
        else:
            db.delete(value)
    if field in template.fields:
        template.fields.remove(field)
    else:
        db.delete(field)
    db.flush()
    remaining = sorted(
        (item for item in template.fields if item.id != field.id),
        key=lambda item: (item.sort_order, item.id),
    )
    for order, item in enumerate(remaining):
        item.sort_order = order
    template.version += 1
    db.flush()
    return template


def preview_template_csv(
    data: bytes,
    template: AttributeTemplate | None = None,
) -> dict[str, Any]:
    headers, rows = csv_rows(data)
    headers = [header for header in headers if header and not header.startswith("_")]
    if not headers:
        raise ValueError("В файле шаблона не найдены столбцы атрибутов")
    existing = {
        (normalize_key(field.group_name), normalize_key(field.name)): field
        for field in (template.fields if template else [])
    }
    fields: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_columns: set[tuple[str, str]] = set()
    for order, header in enumerate(headers):
        name, group = split_template_header(header)
        key = (normalize_key(group), normalize_key(name))
        if key in seen_columns:
            warnings.append(f"Повторяющийся атрибут: {group} / {name}")
            continue
        seen_columns.add(key)
        raw_values = [row.get(header, "") for row in rows if row.get(header, "") not in {"", "-"}]
        value_type, composite = infer_value_type(name, raw_values)
        old = existing.get(key)
        if old and old.value_type in {"select", "select_exact"}:
            value_type, composite = "select", old.is_composite
        normalized_values: list[str] = []
        invalid: list[str] = []
        for raw in raw_values:
            try:
                normalized = normalize_value(raw, value_type, composite)
            except ValueError:
                invalid.append(raw)
                continue
            if normalized not in normalized_values:
                normalized_values.append(normalized)
        old = existing.get(key)
        old_values = {dictionary_value_key(item.value, value_type) for item in old.allowed_values} if old else set()
        new_keys = {dictionary_value_key(item, value_type) for item in normalized_values}
        fields.append({
            "order": order,
            "group_name": group,
            "name": name,
            "value_type": value_type,
            "is_composite": composite,
            "values": normalized_values,
            "invalid_values": invalid[:20],
            "change": "update" if old else "add",
            "added_values": [item for item in normalized_values if dictionary_value_key(item, value_type) not in old_values],
            "removed_values": [item.value for item in old.allowed_values if dictionary_value_key(item.value, value_type) not in new_keys] if old else [],
        })
        if normalize_key(name) in {"атрибут", "атрибуты", "характеристики"} and len(normalized_values) > 8:
            warnings.append(
                f"Столбец «{name}» похож на перечень названий атрибутов. Проверьте ориентацию файла."
            )
        if invalid:
            warnings.append(f"{group} / {name}: некорректных значений — {len(invalid)}")
    removed_fields = [
        {"id": field.id, "group_name": field.group_name, "name": field.name}
        for key, field in existing.items() if key not in seen_columns
    ]
    return {
        "rows": len(rows),
        "fields": fields,
        "removed_fields": removed_fields,
        "warnings": warnings,
        "can_import": bool(fields) and not any("ориентацию файла" in item for item in warnings),
    }


def update_template_from_csv(
    db: Session,
    template: AttributeTemplate,
    data: bytes,
    *,
    mode: str = "merge",
) -> dict[str, Any]:
    preview = preview_template_csv(data, template)
    if not preview["can_import"]:
        raise ValueError("Импорт остановлен: исправьте предупреждения предварительной проверки")
    save_template_revision(db, template, "before_csv_update", {"mode": mode})
    existing = {
        (normalize_key(field.group_name), normalize_key(field.name)): field
        for field in template.fields
    }
    touched: set[int] = set()
    for item in preview["fields"]:
        key = (normalize_key(item["group_name"]), normalize_key(item["name"]))
        field = existing.get(key)
        if field is None:
            field = AttributeTemplateField(template=template, group_name=item["group_name"], name=item["name"])
            db.add(field)
            db.flush()
        field.sort_order = int(item["order"])
        set_field_value_type(db, field, item["value_type"])
        field.is_composite = bool(item["is_composite"])
        touched.add(field.id)
        if mode == "replace":
            for allowed in field.allowed_values:
                allowed.is_active = False
        for raw in item["values"]:
            entries = [raw]
            if field.is_composite and field.separator in raw:
                entries.extend(part for part in raw.split(field.separator) if clean_text(part))
            for entry in entries:
                allowed = add_allowed_value(db, field, entry)
                allowed.is_combination = bool(field.is_composite and field.separator in entry)
    if mode == "replace":
        for field in template.fields:
            if field.id not in touched:
                field.is_required = False
    template.version += 1
    return preview


def copy_template(
    db: Session,
    template: AttributeTemplate,
    *,
    name: str,
    category: str = "",
) -> AttributeTemplate:
    category_path = clean_text(category) or template.category.full_path
    category_row = db.scalar(select(AttributeCategory).where(AttributeCategory.full_path == category_path))
    if category_row is None:
        category_row = AttributeCategory(name=category_path.split(">")[-1].strip(), full_path=category_path)
        db.add(category_row)
        db.flush()
    copy_name = clean_text(name) or f"{template.name} — копия"
    duplicate = db.scalar(select(AttributeTemplate).where(
        AttributeTemplate.category_id == category_row.id,
        AttributeTemplate.name == copy_name,
    ))
    if duplicate:
        raise ValueError("Шаблон с таким именем в категории уже существует")
    result = AttributeTemplate(
        category=category_row,
        name=copy_name,
        product_type=template.product_type,
        description=template.description,
        is_default=False,
    )
    db.add(result)
    db.flush()
    for source_field in template.fields:
        field = AttributeTemplateField(
            template=result,
            group_name=source_field.group_name,
            name=source_field.name,
            synonyms=list(source_field.synonyms or []),
            is_required=source_field.is_required,
            value_type=source_field.value_type,
            is_composite=source_field.is_composite,
            separator=source_field.separator,
            conversion_rules=list(source_field.conversion_rules or []),
            sort_order=source_field.sort_order,
            use_dash_if_empty=source_field.use_dash_if_empty,
        )
        db.add(field)
        db.flush()
        for source_value in source_field.allowed_values:
            value = AttributeAllowedValue(
                field=field,
                value=source_value.value,
                normalized_value=source_value.normalized_value,
                is_combination=source_value.is_combination,
                is_active=source_value.is_active,
                sort_order=source_value.sort_order,
                source="template_copy",
            )
            db.add(value)
            db.flush()
            for source_synonym in source_value.synonyms:
                db.add(AttributeValueSynonym(
                    allowed_value=value,
                    synonym=source_synonym.synonym,
                    normalized_synonym=source_synonym.normalized_synonym,
                ))
    save_template_revision(db, result, "copy")
    return result


def restore_template_revision(
    db: Session,
    template: AttributeTemplate,
    revision: AttributeTemplateRevision,
) -> None:
    if revision.template_id != template.id:
        raise ValueError("Версия относится к другому шаблону")
    snapshot = revision.snapshot or {}
    if snapshot.get("kind") == "allowed_value":
        value_data = dict(snapshot.get("allowed_value") or {})
        allowed = db.get(AttributeAllowedValue, int(value_data.get("id") or 0))
        if not allowed or allowed.field.template_id != template.id:
            raise ValueError("Значение из версии шаблона не найдено")
        normalized = normalize_value(value_data.get("value"), allowed.field.value_type, False)
        normalized_key = dictionary_value_key(normalized, allowed.field.value_type)
        duplicate = db.scalar(
            select(AttributeAllowedValue.id).where(
                AttributeAllowedValue.field_id == allowed.field_id,
                AttributeAllowedValue.id != allowed.id,
                AttributeAllowedValue.normalized_value == normalized_key,
            )
        )
        if duplicate:
            raise ValueError("Нельзя восстановить значение: такое значение уже есть в справочнике")
        save_allowed_value_revision(db, allowed, "before_restore", {"revision_id": revision.id})
        allowed.value = normalized
        allowed.normalized_value = normalized_key
        allowed.is_combination = bool(value_data.get("is_combination"))
        allowed.is_active = bool(value_data.get("is_active", True))
        allowed.sort_order = int(value_data.get("sort_order") or 0)
        allowed.source = clean_text(value_data.get("source")) or allowed.source
        replace_allowed_value_synonyms(db, allowed, value_data.get("synonyms") or [])
        template.version += 1
        return
    snapshot = _unpack_snapshot(snapshot, TEMPLATE_SNAPSHOT_SCHEMA)
    save_template_revision(db, template, "before_restore", {"revision_id": revision.id})
    template.name = clean_text(snapshot.get("name")) or template.name
    template.product_type = clean_text(snapshot.get("product_type"))
    template.description = clean_text(snapshot.get("description"))
    template.is_default = bool(snapshot.get("is_default", template.is_default))
    template.is_active = bool(snapshot.get("is_active", True))
    category_path = clean_text(snapshot.get("category"))
    if category_path:
        category = db.scalar(
            select(AttributeCategory).where(AttributeCategory.full_path == category_path)
        )
        if category is None:
            category = AttributeCategory(
                name=category_path.replace("→", ">").split(">")[-1].strip(),
                full_path=category_path,
            )
            db.add(category)
            db.flush()
        template.category = category

    current_fields = list(template.fields)
    fields_by_id = {item.id: item for item in current_fields if item.id is not None}
    fields_by_key = {
        (normalize_key(item.group_name), normalize_key(item.name)): item
        for item in current_fields
    }
    restored_fields: set[int] = set()
    for field_data in list(snapshot.get("fields") or []):
        if not isinstance(field_data, dict):
            continue
        key = (normalize_key(field_data.get("group_name")), normalize_key(field_data.get("name")))
        snapshot_field_id = int(field_data.get("id") or 0)
        field = fields_by_id.get(snapshot_field_id) or fields_by_key.get(key)
        if field is None:
            field = AttributeTemplateField(
                template=template,
                group_name=clean_text(field_data.get("group_name")) or "Основные характеристики",
                name=clean_text(field_data.get("name")),
            )
            db.add(field)
            db.flush()
        restored_fields.add(int(field.id))
        field.group_name = clean_text(field_data.get("group_name")) or "Основные характеристики"
        field.name = clean_text(field_data.get("name"))
        restored_synonyms: list[str] = []
        restored_synonym_keys: set[str] = set()
        canonical_key = normalize_key(field.name)
        for raw_synonym in field_data.get("synonyms") or []:
            synonym = clean_text(raw_synonym)
            synonym_key = normalize_key(synonym)
            if (
                synonym_key
                and synonym_key != canonical_key
                and synonym_key not in restored_synonym_keys
            ):
                restored_synonym_keys.add(synonym_key)
                restored_synonyms.append(synonym)
        field.synonyms = restored_synonyms
        for attr in ("value_type", "separator"):
            if field_data.get(attr) is not None:
                if attr == "value_type":
                    set_field_value_type(db, field, clean_text(field_data.get(attr)))
                else:
                    setattr(field, attr, clean_text(field_data.get(attr)))
        for attr in ("is_composite", "is_required", "use_dash_if_empty"):
            if field_data.get(attr) is not None:
                setattr(field, attr, bool(field_data.get(attr)))
        field.sort_order = int(field_data.get("sort_order") or 0)
        field.conversion_rules = list(field_data.get("conversion_rules") or [])
        current_allowed = list(field.allowed_values)
        allowed_by_id = {
            item.id: item for item in current_allowed if item.id is not None
        }
        allowed_by_key = {
            item.normalized_value: item for item in current_allowed
        }
        restored_allowed: set[int] = set()
        for value_data in list(field_data.get("allowed_values") or []):
            if not isinstance(value_data, dict):
                continue
            normalized_value = normalize_value(
                value_data.get("value", ""),
                field.value_type,
                False,
            )
            allowed = (
                allowed_by_id.get(int(value_data.get("id") or 0))
                or allowed_by_key.get(dictionary_value_key(normalized_value, field.value_type))
            )
            if allowed is None:
                allowed = add_allowed_value(db, field, normalized_value)
            allowed.value = normalized_value
            allowed.normalized_value = dictionary_value_key(normalized_value, field.value_type)
            allowed.is_combination = bool(value_data.get("is_combination"))
            allowed.is_active = bool(value_data.get("is_active", True))
            allowed.sort_order = int(value_data.get("sort_order") or 0)
            allowed.source = clean_text(value_data.get("source")) or allowed.source
            replace_allowed_value_synonyms(db, allowed, value_data.get("synonyms") or [])
            restored_allowed.add(int(allowed.id))
        for allowed in current_allowed:
            if int(allowed.id) not in restored_allowed:
                db.delete(allowed)

    for field in current_fields:
        if int(field.id) in restored_fields:
            continue
        product_values = list(db.scalars(
            select(AttributeProductValue).where(
                AttributeProductValue.template_field_id == field.id
            )
        ))
        for value in product_values:
            if any(clean_text(item) for item in (
                value.current_value,
                value.proposed_value,
                value.final_value,
            )):
                value.template_field = None
                value.is_in_template = False
                value.is_extra_attribute = True
            else:
                db.delete(value)
        db.delete(field)
    template.version += 1


def _product_snapshot_payload(product: AttributeProduct) -> dict[str, Any]:
    return {
        "schema": PRODUCT_SNAPSHOT_SCHEMA,
        "format_version": SNAPSHOT_FORMAT_VERSION,
        "product": {
            "template_id": product.template_id,
            "external_id": product.external_id,
            "model": product.model,
            "name": product.name,
            "brand": product.brand,
            "category_name": product.category_name,
            "source_url": product.source_url,
            "sort_order": product.sort_order,
            "donor_urls": list(product.donor_urls or []),
            "selected_donor_ids": list(product.selected_donor_ids or []),
            "donor_url_overrides": dict(product.donor_url_overrides or {}),
            "processing_state": dict(product.processing_state or {}),
            "status": product.status,
        },
        "selected_donor_ids": list(product.selected_donor_ids or []),
        "donor_url_overrides": dict(product.donor_url_overrides or {}),
        "values": [
            {
                "id": value.id,
                "template_field_id": value.template_field_id,
                "name": value.attribute_name,
                "attribute_name": value.attribute_name,
                "group_name": value.group_name,
                "current_value": value.current_value,
                "proposed_value": value.proposed_value,
                "final_value": value.final_value,
                "source": value.source,
                "confidence": value.confidence,
                "status": value.status,
                "is_in_template": value.is_in_template,
                "is_extra_attribute": value.is_extra_attribute,
                "reason": value.reason,
                "dash_reason": value.dash_reason,
                "source_details": dict(value.source_details or {}),
                "sort_order": value.sort_order,
            }
            for value in product.values
        ],
        "sources": [
            {
                "id": source.id,
                "donor_id": source.donor_id,
                "url": source.url,
                "priority": source.priority,
                "role": source.role,
                "status": source.status,
                "raw_html_path": source.raw_html_path,
                "parsed_data": dict(source.parsed_data or {}),
            }
            for source in product.sources
        ],
    }


def snapshot_product(db: Session, product: AttributeProduct, action: str) -> AttributeProductRevision:
    return save_product_snapshot(db, product, action, capture_product_snapshot(product))


def capture_product_snapshot(product: AttributeProduct) -> dict[str, Any]:
    """Capture a restorable snapshot without opening a write transaction."""

    return _pack_snapshot(
        _product_snapshot_payload(product),
        PRODUCT_SNAPSHOT_SCHEMA,
    )


def save_product_snapshot(
    db: Session,
    product: AttributeProduct,
    action: str,
    snapshot: dict[str, Any],
) -> AttributeProductRevision:
    """Persist a previously captured snapshot immediately before a mutation."""

    revision = AttributeProductRevision(
        product_id=product.id,
        label=action,
        snapshot=snapshot,
    )
    db.add(revision)
    db.flush()
    return revision


def restore_product_snapshot(
    db: Session,
    product: AttributeProduct,
    revision: AttributeProductRevision,
) -> None:
    if revision.product_id != product.id:
        raise ValueError("Снимок товара не найден")
    snapshot_product(db, product, f"Перед восстановлением #{revision.id}")
    details = _unpack_snapshot(revision.snapshot or {}, PRODUCT_SNAPSHOT_SCHEMA)
    if int(details.get("format_version") or 0) < SNAPSHOT_FORMAT_VERSION:
        values = {value.id: value for value in product.values}
        for item in details.get("values") or []:
            value = values.get(int(item.get("id") or 0))
            if value is None:
                continue
            for attr in ("proposed_value", "final_value", "source", "status", "reason", "dash_reason"):
                setattr(value, attr, item.get(attr) or "")
            value.confidence = int(item.get("confidence") or 0)
            value.source_details = dict(item.get("source_details") or {})
        product.selected_donor_ids = list(details.get("selected_donor_ids") or [])
        product.donor_url_overrides = dict(details.get("donor_url_overrides") or {})
        refresh_product_status(product)
        refresh_batch_summary(product.batch)
        return

    product_data = dict(details.get("product") or {})
    template_id = int(product_data.get("template_id") or 0)
    if template_id:
        template = db.get(AttributeTemplate, template_id)
        if template is None:
            raise ValueError("Шаблон из снимка больше не существует")
        product.template = template
    else:
        product.template = None
    for attr in (
        "external_id", "model", "name", "brand", "category_name", "source_url",
    ):
        setattr(product, attr, clean_text(product_data.get(attr)))
    product.sort_order = int(product_data.get("sort_order") or 0)
    product.donor_urls = list(product_data.get("donor_urls") or [])
    product.selected_donor_ids = list(product_data.get("selected_donor_ids") or [])
    product.donor_url_overrides = dict(product_data.get("donor_url_overrides") or {})
    product.processing_state = dict(product_data.get("processing_state") or {})
    product.status = clean_text(product_data.get("status")) or "needs_review"

    value_items = [
        item for item in list(details.get("values") or [])
        if isinstance(item, dict)
    ]
    value_ids = {int(item.get("id") or 0) for item in value_items}
    current_values = {int(value.id): value for value in product.values}
    for value_id, value in current_values.items():
        if value_id not in value_ids:
            db.delete(value)
    source_items = [
        item for item in list(details.get("sources") or [])
        if isinstance(item, dict)
    ]
    source_ids = {int(item.get("id") or 0) for item in source_items}
    current_sources = {int(source.id): source for source in product.sources}
    for source_id, source in current_sources.items():
        if source_id not in source_ids:
            db.delete(source)
    db.flush()

    for item in value_items:
        field_id = int(item.get("template_field_id") or 0)
        field = db.get(AttributeTemplateField, field_id) if field_id else None
        if field is not None and template_id and field.template_id != template_id:
            field = None
        value_id = int(item.get("id") or 0)
        value = current_values.get(value_id)
        if value is None:
            value = AttributeProductValue(id=value_id or None, product=product)
            db.add(value)
        value.template_field = field
        value.group_name = clean_text(item.get("group_name"))
        value.attribute_name = clean_text(item.get("attribute_name") or item.get("name"))
        value.current_value = exact_value_key(item.get("current_value"))
        value.proposed_value = exact_value_key(item.get("proposed_value"))
        value.final_value = exact_value_key(item.get("final_value"))
        value.source = clean_text(item.get("source"))
        value.confidence = max(0, min(100, int(item.get("confidence") or 0)))
        value.status = clean_text(item.get("status")) or "missing"
        value.is_in_template = bool(item.get("is_in_template"))
        value.is_extra_attribute = bool(item.get("is_extra_attribute"))
        value.reason = clean_text(item.get("reason"))
        value.dash_reason = clean_text(item.get("dash_reason"))
        value.source_details = dict(item.get("source_details") or {})
        value.sort_order = int(item.get("sort_order") or 0)
    for item in source_items:
        donor_id = int(item.get("donor_id") or 0)
        if donor_id and db.get(Donor, donor_id) is None:
            donor_id = 0
        source_id = int(item.get("id") or 0)
        source = current_sources.get(source_id)
        if source is None:
            source = AttributeProductSource(id=source_id or None, product=product)
            db.add(source)
        source.donor_id = donor_id or None
        source.url = clean_text(item.get("url"))
        source.priority = int(item.get("priority") or 0)
        source.role = clean_text(item.get("role")) or "primary"
        source.status = clean_text(item.get("status")) or "resolved"
        source.raw_html_path = clean_text(item.get("raw_html_path"))
        source.parsed_data = dict(item.get("parsed_data") or {})
    db.flush()
    refresh_product_status(product)
    refresh_batch_summary(product.batch)


def product_history(db: Session, product: AttributeProduct) -> list[dict[str, Any]]:
    rows = list(db.scalars(
        select(AttributeProductRevision).where(
            AttributeProductRevision.product_id == product.id,
        ).order_by(AttributeProductRevision.created_at.desc()).limit(50)
    ))

    current_names = {
        value.id: {"name": value.attribute_name, "group_name": value.group_name}
        for value in product.values
    }
    current_details = _product_snapshot_payload(product)

    def _states(details: dict[str, Any]) -> dict[int, dict[str, Any]]:
        states: dict[int, dict[str, Any]] = {}
        for item in details.get("values") or []:
            value_id = int(item.get("id") or 0)
            if value_id:
                states[value_id] = item
        return states

    def _state_key(item: dict[str, Any]) -> tuple[Any, ...]:
        return (
            exact_value_key(item.get("current_value")),
            exact_value_key(item.get("proposed_value")),
            exact_value_key(item.get("final_value")),
            clean_text(item.get("source")),
            int(item.get("confidence") or 0),
            clean_text(item.get("status")),
            clean_text(item.get("reason")),
            clean_text(item.get("dash_reason")),
        )

    def _display_value(item: dict[str, Any]) -> str:
        final_value = exact_value_key(item.get("final_value"))
        if final_value:
            return final_value
        if clean_text(item.get("status")) == "dash":
            return "-"
        return (
            exact_value_key(item.get("proposed_value"))
            or exact_value_key(item.get("current_value"))
            or "—"
        )

    def _label(value: object) -> str:
        raw = clean_text(value) or "Изменение"
        action_labels = {
            "Перед обработкой доноров": "Обработка доноров",
            "Перед анализом ChatGPT": "Анализ ChatGPT",
            "Перед поиском по похожим товарам": "Поиск по похожим товарам",
            "Перед добавлением ручных характеристик": "Добавление ручных характеристик",
            "Перед ручным сопоставлением атрибута": "Ручное сопоставление атрибута",
            "Перед массовым действием accept_high": "Массовое принятие уверенных значений",
            "Перед массовым действием fill_dashes": "Массовое заполнение технических пропусков",
        }
        if raw in action_labels:
            return action_labels[raw]
        prefix = "Перед изменением "
        if raw.startswith(prefix):
            return f"Изменение: {raw[len(prefix):]}"
        if raw.startswith("Перед "):
            raw = raw[len("Перед "):]
            return raw[:1].upper() + raw[1:]
        return raw

    history: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        before_details = _unpack_snapshot(row.snapshot or {}, PRODUCT_SNAPSHOT_SCHEMA)
        after_details = (
            current_details
            if index == 0
            else _unpack_snapshot(rows[index - 1].snapshot or {}, PRODUCT_SNAPSHOT_SCHEMA)
        )
        before_states = _states(before_details)
        after_states = _states(after_details)
        changes: list[dict[str, Any]] = []

        for value_id in sorted(set(before_states) | set(after_states)):
            before = before_states.get(value_id, {})
            after = after_states.get(value_id, {})
            if _state_key(before) == _state_key(after):
                continue
            names = current_names.get(value_id, {})
            changes.append({
                "field_id": value_id,
                "name": clean_text(after.get("name") or before.get("name") or names.get("name")) or f"Атрибут #{value_id}",
                "group_name": clean_text(after.get("group_name") or before.get("group_name") or names.get("group_name")),
                "before": _display_value(before),
                "after": _display_value(after),
                "before_status": clean_text(before.get("status")),
                "after_status": clean_text(after.get("status")),
                "before_source": clean_text(before.get("source")),
                "after_source": clean_text(after.get("source")),
                "before_confidence": int(before.get("confidence") or 0),
                "after_confidence": int(after.get("confidence") or 0),
            })

        before_donors = list(before_details.get("selected_donor_ids") or [])
        after_donors = list(after_details.get("selected_donor_ids") or [])
        if before_donors != after_donors:
            changes.append({
                "field_id": 0,
                "name": "Источники данных",
                "group_name": "",
                "before": f"Выбрано: {len(before_donors)}",
                "after": f"Выбрано: {len(after_donors)}",
                "before_status": "",
                "after_status": "",
                "before_source": "",
                "after_source": "",
                "before_confidence": 0,
                "after_confidence": 0,
            })

        history.append({
            "id": row.id,
            "label": _label(row.label),
            "created_at": row.created_at.isoformat(timespec="seconds") if row.created_at else "",
            "changed_count": len(changes),
            "changes": changes[:20],
        })
    return history


def batch_report(batch: AttributeBatch) -> dict[str, Any]:
    products: list[dict[str, Any]] = []
    totals = {"products": len(batch.products), "ready": 0, "conflicts": 0, "missing": 0, "unknown": 0, "dashes": 0}
    for product in batch.products:
        conflicts = sum(value.status == "conflict" for value in product.values)
        missing = sum(value.is_in_template and not value.final_value for value in product.values)
        unknown = sum(value.status == "unknown" for value in product.values)
        dashes = sum(value.final_value == "-" for value in product.values)
        ready = conflicts == 0 and missing == 0
        totals["ready"] += int(ready)
        totals["conflicts"] += conflicts
        totals["missing"] += missing
        totals["unknown"] += unknown
        totals["dashes"] += dashes
        products.append({
            "id": product.id,
            "model": product.model,
            "name": product.name,
            "template": product_template(product).name if product_template(product) else "Не выбран",
            "ready": ready,
            "conflicts": conflicts,
            "missing": missing,
            "unknown": unknown,
            "dashes": dashes,
        })
    return {"totals": totals, "products": products, "can_export": totals["conflicts"] == 0 and totals["missing"] == 0}


def resolve_original_path(batch: AttributeBatch) -> Path | None:
    if not batch.original_path:
        return None
    path = Path(batch.original_path).resolve()
    root = ATTRIBUTE_ASSISTANT_DIR.resolve()
    return path if path.is_file() and (path == root or root in path.parents) else None

def export_batch_report_csv(batch: AttributeBatch) -> Path:
    report = batch_report(batch)
    output_dir = ATTRIBUTE_ASSISTANT_DIR / "reports"
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"attribute_report_{batch.id}_{uuid.uuid4().hex[:8]}.csv"
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(
        stream,
        fieldnames=["Модель", "Товар", "Шаблон", "Готов", "Конфликты", "Пропуски", "Нет в справочнике", "Технические пропуски"],
        delimiter=";",
        lineterminator="\r\n",
    )
    writer.writeheader()
    for item in report["products"]:
        writer.writerow({
            "Модель": item["model"],
            "Товар": item["name"],
            "Шаблон": item["template"],
            "Готов": "Да" if item["ready"] else "Нет",
            "Конфликты": item["conflicts"],
            "Пропуски": item["missing"],
            "Нет в справочнике": item["unknown"],
            "Технические пропуски": item["dashes"],
        })
    path.write_bytes(stream.getvalue().encode("utf-8-sig"))
    batch.report_filename = str(path)
    return path


def resolve_report_path(batch: AttributeBatch) -> Path | None:
    if not batch.report_filename:
        return None
    path = Path(batch.report_filename).resolve()
    root = (ATTRIBUTE_ASSISTANT_DIR / "reports").resolve()
    return path if path.is_file() and root in path.parents else None

def assign_product_template(
    db: Session,
    product: AttributeProduct,
    template: AttributeTemplate,
) -> None:
    snapshot_product(db, product, f"Смена шаблона на {template.name}")
    stack = [
        {"group_name": value.group_name, "name": value.attribute_name, "value": value.current_value or value.final_value}
        for value in product.values if value.current_value or value.final_value
    ]
    product.values.clear()
    db.flush()
    product.template = template
    state = dict(product.processing_state or {})
    state["template_unresolved"] = False
    product.processing_state = state
    _make_product_values(product, template, stack)
    refresh_product_status(product)
    refresh_batch_summary(product.batch)


def recommend_donors(db: Session, product: AttributeProduct) -> list[dict[str, Any]]:
    rows = list(db.scalars(select(Donor).join(Brand, Donor.brand_id == Brand.id)))
    model_key = normalize_model(product.model)
    brand_key = normalize_key(product.brand)
    ranked: list[tuple[int, Donor, list[str]]] = []
    for donor in rows:
        score = 10
        reasons: list[str] = []
        donor_brand = normalize_key(donor.brand.name)
        if brand_key and (brand_key == donor_brand or brand_key in donor_brand or donor_brand in brand_key):
            score += 55
            reasons.append("совпадает бренд")
        if _cached_product_url(donor, product.model):
            score += 30
            reasons.append("модель есть в кэше донора")
        if model_key and model_key in normalize_key(json.dumps(donor.known_new_products or {}, ensure_ascii=False)):
            score += 15
            reasons.append("модель встречается в каталоге")
        if donor.brand.primary_donor_id == donor.id:
            score += 5
            reasons.append("основной донор бренда")
        ranked.append((min(score, 100), donor, reasons))
    ranked.sort(key=lambda item: (-item[0], item[1].brand.name.casefold()))
    return [
        {**serialize_donor(donor), "score": score, "reasons": reasons, "recommended": score >= 60}
        for score, donor, reasons in ranked
    ]


def list_mapping_rules(db: Session, template_id: int | None = None) -> list[dict[str, Any]]:
    statement = select(AttributeMappingRule).order_by(AttributeMappingRule.updated_at.desc())
    if template_id:
        statement = statement.where(AttributeMappingRule.template_id == template_id)
    return [
        {
            "id": row.id,
            "donor_id": row.donor_id,
            "donor_name": row.donor.brand.name,
            "template_id": row.template_id,
            "field_id": row.template_field_id,
            "field_name": row.template_field.name,
            "donor_attribute_name": row.donor_attribute_name,
            "confidence": row.confidence,
            "is_active": row.is_active,
        }
        for row in db.scalars(statement)
    ]
