"""Attribute Assistant domain logic.

The module deliberately never writes to OpenCart. It prepares a reviewable local
workspace and emits CSV files compatible with CSV Price Pro.
"""

from __future__ import annotations

import csv
import io
import ipaddress
import json
import re
import socket
from collections import Counter
from datetime import UTC, datetime
from difflib import SequenceMatcher
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Sequence, Tuple
from urllib.parse import unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup, Tag
from sqlalchemy import func, select
from sqlalchemy.orm import joinedload, selectinload

from config import ATTRIBUTE_ASSISTANT_DIR, MSK_TZ
from models import (
    AttributeAllowedValue,
    AttributeBatch,
    AttributeCategory,
    AttributeDonor,
    AttributeDonorProductSource,
    AttributeMappingRule,
    AttributeProcessingLog,
    AttributeProduct,
    AttributeProductValue,
    AttributeTemplate,
    AttributeTemplateField,
    AttributeTemplateRevision,
    AttributeValueSynonym,
)
from services.normalization import output_text, safe_filename
from services.scraping import clean_text as _scraping_clean_text


ATTRIBUTE_HEADER_RE = re.compile(r"^(?P<name>.+)\s+\((?P<group>[^()]*)\)\s*$")
DIMENSION_SEPARATOR_RE = re.compile(r"\s*[xхXХ×]\s*")
NUMBER_RE = re.compile(r"^[+-]?\d+(?:\.\d+)?$")
WHITESPACE_RE = re.compile(r"\s+")
CSV_ENCODINGS = ("utf-8-sig", "cp1251", "utf-8")
PROCESSING_MODES = {"check", "suggest", "auto_high", "auto_all"}
VALUE_TYPES = {"text", "select", "number", "boolean", "composite", "dimensions"}
REVIEW_STATUSES = {"missing", "dash", "proposed", "conflict", "needs_review"}
DEFAULT_HTTP_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124 Safari/537.36"
    ),
    "Accept-Language": "ru-RU,ru;q=0.9,en;q=0.7",
}
HTML_CHARSET_RE = re.compile(r"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", re.I)
HTML_META_CHARSET_RE = re.compile(
    rb"<meta\b[^>]*\bcharset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)",
    re.I,
)
GENERIC_ATTRIBUTE_ROW_SELECTOR = ", ".join(
    (
        '[itemprop="additionalProperty"]',
        '[itemtype*="schema.org/PropertyValue" i]',
        '[class*="characteristic" i]',
        '[class*="property" i]',
        '[class*="specification" i]',
        '[class*="parameter" i]',
        '[class*="attribute" i]',
        '[class*="-char-" i]',
        '[class^="char-" i]',
        '[class$="-char" i]',
    )
)
GENERIC_ATTRIBUTE_NAME_SELECTOR = ", ".join(
    (
        '[itemprop="name"]',
        '[class~="title" i]',
        '[class~="name" i]',
        '[class~="label" i]',
        '[class$="-title" i]',
        '[class$="-name" i]',
        '[class^="title-" i]',
        '[class^="name-" i]',
    )
)
GENERIC_ATTRIBUTE_VALUE_SELECTOR = ", ".join(
    (
        '[itemprop="value"]',
        '[class~="value" i]',
        '[class$="-value" i]',
        '[class^="value-" i]',
    )
)
ATTRIBUTE_CONTEXT_HINTS = frozenset(
    {
        "attribute",
        "attributes",
        "attr",
        "attrs",
        "characteristic",
        "characteristics",
        "char",
        "chars",
        "detail",
        "details",
        "feature",
        "features",
        "option",
        "options",
        "parameter",
        "parameters",
        "param",
        "params",
        "property",
        "properties",
        "prop",
        "props",
        "spec",
        "specs",
        "specification",
        "specifications",
        "technical",
    }
)
ATTRIBUTE_NAME_HINTS = frozenset(
    {"attribute", "caption", "characteristic", "key", "label", "name", "parameter", "property", "term", "title"}
)
ATTRIBUTE_VALUE_HINTS = frozenset({"answer", "content", "data", "description", "text", "val", "value"})


def clean_text(value: object) -> str:
    """Normalize text from forms, HTML and JSON without assuming it is a string."""
    return _scraping_clean_text(str(value or ""))


def db_datetime_iso(value: Optional[datetime]) -> str:
    if value is None:
        return ""
    aware = value if value.tzinfo is not None else value.replace(tzinfo=UTC)
    return aware.astimezone(MSK_TZ).isoformat(timespec="seconds")


def assistant_subdir(name: str) -> Path:
    path = ATTRIBUTE_ASSISTANT_DIR / name
    path.mkdir(parents=True, exist_ok=True)
    return path


def decode_csv_content(content: bytes) -> Tuple[str, str]:
    for encoding in CSV_ENCODINGS:
        try:
            return content.decode(encoding), encoding
        except UnicodeDecodeError:
            continue
    raise ValueError("Не удалось определить кодировку CSV. Используйте UTF-8 или Windows-1251.")


def read_semicolon_csv(content: bytes) -> Tuple[List[str], List[List[str]], str]:
    text, encoding = decode_csv_content(content)
    csv.field_size_limit(max(csv.field_size_limit(), 50 * 1024 * 1024))
    rows = list(csv.reader(io.StringIO(text, newline=""), delimiter=";"))
    if not rows:
        raise ValueError("CSV-файл пуст")
    headers = [clean_text(str(value or "")).lstrip("\ufeff") for value in rows[0]]
    if not any(headers):
        raise ValueError("В CSV отсутствует строка заголовков")
    width = len(headers)
    data_rows = [list(row[:width]) + [""] * max(0, width - len(row)) for row in rows[1:]]
    return headers, data_rows, encoding


def parse_template_header(value: object) -> Tuple[str, str]:
    """Split the last parenthesized fragment into the attribute group."""
    header = clean_text(str(value or ""))
    match = ATTRIBUTE_HEADER_RE.match(header)
    if not match:
        raise ValueError(
            f"Заголовок «{header}» должен иметь формат «Название атрибута (Группа)»"
        )
    name = clean_text(match.group("name"))
    group = clean_text(match.group("group"))
    if not name or not group:
        raise ValueError(f"Не удалось определить атрибут и группу в заголовке «{header}»")
    return name, group


def infer_value_type(attribute_name: str, values: Sequence[str]) -> Tuple[str, bool]:
    normalized_name = attribute_name.casefold()
    joined = " ".join(values)
    dimensions_hint = bool(re.search(r"[вшгд]\s*[xхXХ×]\s*[вшгд]", attribute_name, re.I))
    if "габарит" in normalized_name and (
        dimensions_hint or any(separator in joined for separator in ("x", "х", "X", "Х", "×"))
    ):
        return "dimensions", False
    if any("/" in value for value in values):
        return "composite", True
    if re.search(
        r"(?:^|[,\s(])(см|мм|кг|вт|л|дб|квт|°c|°с|об[./ ]*мин|шт)(?:$|[,\s)/])",
        normalized_name,
    ):
        return "number", False
    if normalized_name.startswith(("есть ", "наличие ")) or normalized_name in {
        "защита от детей",
        "дисплей",
        "ледогенератор",
    }:
        return "boolean", False
    return "select", False


def normalize_attribute_value(value: object, value_type: str = "select", separator: str = "/") -> str:
    text = clean_text(str(value or ""))
    if not text:
        return ""
    if value_type == "dimensions":
        text = DIMENSION_SEPARATOR_RE.sub(" x ", text).replace(",", ".")
    elif value_type == "number":
        text = text.replace(",", ".")
    elif value_type == "composite":
        delimiter = separator or "/"
        parts = sorted(
            {clean_text(part) for part in text.split(delimiter) if clean_text(part)},
            key=str.casefold,
        )
        text = delimiter.join(parts)
    return WHITESPACE_RE.sub(" ", text).strip()


def normalized_lookup_value(value: object, value_type: str = "select", separator: str = "/") -> str:
    return normalize_attribute_value(value, value_type, separator).replace("ё", "е").casefold()


def _is_valid_dictionary_value(value: str, value_type: str, separator: str = "/") -> bool:
    if not value or value == "-":
        return bool(value)
    if value_type == "number":
        return bool(NUMBER_RE.match(value))
    if value_type == "dimensions":
        parts = value.split("x")
        return 2 <= len(parts) <= 4 and all(NUMBER_RE.match(part.strip()) for part in parts)
    if value_type == "composite":
        return all(clean_text(part) for part in value.split(separator or "/"))
    return True


def _attribute_key(group: str, name: str) -> Tuple[str, str]:
    return (
        WHITESPACE_RE.sub(" ", group).strip().casefold(),
        WHITESPACE_RE.sub(" ", name).strip().casefold(),
    )


def _parse_bool(value: object, default: bool = False) -> bool:
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    return str(value).strip().casefold() in {"1", "true", "yes", "on", "да"}


def _template_options():
    return (
        joinedload(AttributeTemplate.category),
        selectinload(AttributeTemplate.fields)
        .selectinload(AttributeTemplateField.allowed_values)
        .selectinload(AttributeAllowedValue.synonyms),
    )


def load_template(db, template_id: object) -> Optional[AttributeTemplate]:
    try:
        parsed_id = int(template_id)
    except (TypeError, ValueError):
        return None
    return db.scalar(
        select(AttributeTemplate).where(AttributeTemplate.id == parsed_id).options(*_template_options())
    )


def list_templates(db) -> List[AttributeTemplate]:
    return list(
        db.scalars(
            select(AttributeTemplate)
            .join(AttributeCategory)
            .options(*_template_options())
            .order_by(AttributeCategory.name, AttributeTemplate.name)
        ).unique()
    )


def _allowed_value_payload(value: AttributeAllowedValue, include_synonyms: bool = True) -> Dict[str, object]:
    payload: Dict[str, object] = {
        "id": value.id,
        "value": output_text(value.value),
        "value_type": value.value_type,
        "is_global": bool(value.is_global),
        "is_recommended": bool(value.is_recommended),
        "is_active": bool(value.is_active),
        "source": value.source,
        "sort_order": value.sort_order,
    }
    if include_synonyms:
        payload["synonyms"] = [
            {"id": synonym.id, "synonym": output_text(synonym.synonym)}
            for synonym in value.synonyms or []
        ]
    return payload


def template_summary(template: AttributeTemplate) -> Dict[str, object]:
    fields = [field for field in template.fields or [] if field.is_active]
    return {
        "id": template.id,
        "name": output_text(template.name),
        "description": output_text(template.description),
        "product_type": output_text(template.product_type),
        "is_active": bool(template.is_active),
        "is_default": bool(template.is_default),
        "version": template.version,
        "category": {
            "id": template.category.id,
            "name": output_text(template.category.name),
            "parent_name": output_text(template.category.parent_name),
            "full_path": output_text(template.category.full_path),
            "external_key": output_text(template.category.external_key),
        },
        "fields_count": len(fields),
        "values_count": sum(
            len([value for value in field.allowed_values or [] if value.is_active]) for field in fields
        ),
        "updated_at": db_datetime_iso(template.updated_at),
    }


def public_template(template: AttributeTemplate) -> Dict[str, object]:
    payload = template_summary(template)
    payload["fields"] = [
        {
            "id": field.id,
            "group_name": output_text(field.group_name),
            "name": output_text(field.name),
            "is_required": bool(field.is_required),
            "value_type": field.value_type,
            "is_composite": bool(field.is_composite),
            "separator": field.separator,
            "sort_order": field.sort_order,
            "use_dash_if_empty": bool(field.use_dash_if_empty),
            "is_active": bool(field.is_active),
            "allowed_values": [
                _allowed_value_payload(item)
                for item in field.allowed_values or []
            ],
        }
        for field in template.fields or []
    ]
    return payload


def compact_template_summaries(db) -> List[Dict[str, object]]:
    rows = db.execute(
        select(
            AttributeTemplate,
            AttributeCategory,
            func.count(func.distinct(AttributeTemplateField.id)).label("fields_count"),
            func.count(AttributeAllowedValue.id).label("values_count"),
        )
        .join(AttributeCategory, AttributeCategory.id == AttributeTemplate.category_id)
        .outerjoin(
            AttributeTemplateField,
            (AttributeTemplateField.template_id == AttributeTemplate.id)
            & AttributeTemplateField.is_active.is_(True),
        )
        .outerjoin(
            AttributeAllowedValue,
            (AttributeAllowedValue.field_id == AttributeTemplateField.id)
            & AttributeAllowedValue.is_active.is_(True),
        )
        .group_by(AttributeTemplate.id, AttributeCategory.id)
        .order_by(AttributeCategory.name, AttributeTemplate.name)
    ).all()
    return [
        {
            "id": template.id,
            "name": output_text(template.name),
            "description": output_text(template.description),
            "product_type": output_text(template.product_type),
            "is_active": bool(template.is_active),
            "is_default": bool(template.is_default),
            "version": template.version,
            "category": {
                "id": category.id,
                "name": output_text(category.name),
                "parent_name": output_text(category.parent_name),
                "full_path": output_text(category.full_path),
                "external_key": output_text(category.external_key),
            },
            "fields_count": int(fields_count or 0),
            "values_count": int(values_count or 0),
            "updated_at": db_datetime_iso(template.updated_at),
        }
        for template, category, fields_count, values_count in rows
    ]


def _template_snapshot(template: AttributeTemplate) -> Dict[str, object]:
    return {
        "name": template.name,
        "description": template.description,
        "product_type": template.product_type,
        "is_active": template.is_active,
        "is_default": template.is_default,
        "fields": [
            {
                "group_name": field.group_name,
                "name": field.name,
                "is_required": field.is_required,
                "value_type": field.value_type,
                "is_composite": field.is_composite,
                "separator": field.separator,
                "sort_order": field.sort_order,
                "use_dash_if_empty": field.use_dash_if_empty,
                "is_active": field.is_active,
                "values": [
                    {
                        "value": value.value,
                        "value_type": value.value_type,
                        "is_global": value.is_global,
                        "is_recommended": value.is_recommended,
                        "is_active": value.is_active,
                        "source": value.source,
                        "sort_order": value.sort_order,
                        "synonyms": [synonym.synonym for synonym in value.synonyms or []],
                    }
                    for value in field.allowed_values or []
                ],
            }
            for field in sorted(template.fields or [], key=lambda item: (item.sort_order, item.id))
        ],
    }


def _save_template_revision(db, template: AttributeTemplate, action: str, report: Optional[dict] = None) -> None:
    db.add(
        AttributeTemplateRevision(
            template_id=template.id,
            version=template.version,
            action=action,
            snapshot=_template_snapshot(template),
            report=dict(report or {}),
        )
    )


def list_template_revisions(db, template_id: object) -> List[Dict[str, object]]:
    template = load_template(db, template_id)
    if template is None:
        return []
    revisions = list(
        db.scalars(
            select(AttributeTemplateRevision)
            .where(AttributeTemplateRevision.template_id == template.id)
            .order_by(AttributeTemplateRevision.id.desc())
        )
    )
    return [
        {
            "id": revision.id,
            "version": revision.version,
            "action": revision.action,
            "report": revision.report or {},
            "created_at": db_datetime_iso(revision.created_at),
        }
        for revision in revisions
    ]


def restore_template_revision(
    db,
    template: AttributeTemplate,
    revision_id: object,
) -> AttributeTemplate:
    try:
        parsed_id = int(revision_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Некорректная версия шаблона") from error
    revision = db.scalar(
        select(AttributeTemplateRevision).where(
            AttributeTemplateRevision.id == parsed_id,
            AttributeTemplateRevision.template_id == template.id,
        )
    )
    if revision is None:
        raise LookupError("Версия шаблона не найдена")
    snapshot = dict(revision.snapshot or {})
    fields_snapshot = snapshot.get("fields")
    if not isinstance(fields_snapshot, list):
        raise ValueError("Снимок шаблона повреждён")

    _save_template_revision(
        db,
        template,
        "before_restore",
        {"target_revision_id": revision.id, "target_version": revision.version},
    )
    template.version += 1
    for key in ("name", "description", "product_type"):
        if key in snapshot:
            setattr(template, key, clean_text(snapshot[key]))
    for key in ("is_active", "is_default"):
        if key in snapshot:
            setattr(template, key, bool(snapshot[key]))

    existing_fields = {
        _attribute_key(field.group_name, field.name): field
        for field in template.fields or []
    }
    retained_field_ids = set()
    for field_data in fields_snapshot:
        if not isinstance(field_data, dict):
            continue
        group_name = clean_text(field_data.get("group_name"))
        name = clean_text(field_data.get("name"))
        if not group_name or not name:
            continue
        field = existing_fields.get(_attribute_key(group_name, name))
        if field is None:
            field = AttributeTemplateField(template=template, group_name=group_name, name=name)
            db.add(field)
            db.flush()
        retained_field_ids.add(field.id)
        field.group_name = group_name
        field.name = name
        field.is_required = bool(field_data.get("is_required", True))
        value_type = str(field_data.get("value_type") or "select")
        field.value_type = value_type if value_type in VALUE_TYPES else "select"
        field.is_composite = bool(field_data.get("is_composite"))
        field.separator = clean_text(field_data.get("separator"))[:16] or "/"
        field.sort_order = int(field_data.get("sort_order") or 0)
        field.use_dash_if_empty = bool(field_data.get("use_dash_if_empty", True))
        field.is_active = bool(field_data.get("is_active", True))

        existing_values = {value.normalized_value: value for value in field.allowed_values or []}
        retained_value_ids = set()
        for value_data in field_data.get("values") or []:
            if not isinstance(value_data, dict):
                continue
            canonical = normalize_attribute_value(
                value_data.get("value"),
                field.value_type,
                field.separator,
            )
            normalized = normalized_lookup_value(canonical, field.value_type, field.separator)
            if not normalized:
                continue
            value = existing_values.get(normalized)
            if value is None:
                value = AttributeAllowedValue(
                    field=field,
                    value=canonical,
                    normalized_value=normalized,
                )
                db.add(value)
                db.flush()
            retained_value_ids.add(value.id)
            value.value = canonical
            value.normalized_value = normalized
            value.value_type = str(value_data.get("value_type") or "value")[:32]
            value.is_global = bool(value_data.get("is_global"))
            value.is_recommended = bool(value_data.get("is_recommended", True))
            value.is_active = bool(value_data.get("is_active", True))
            value.source = str(value_data.get("source") or "restore")[:64]
            value.sort_order = int(value_data.get("sort_order") or 0)
            wanted_synonyms = {
                normalized_lookup_value(item, field.value_type, field.separator): clean_text(item)
                for item in value_data.get("synonyms") or []
                if clean_text(item)
            }
            for synonym in list(value.synonyms or []):
                if synonym.normalized_synonym not in wanted_synonyms:
                    db.delete(synonym)
            existing_synonyms = {item.normalized_synonym for item in value.synonyms or []}
            for normalized_synonym, synonym_text in wanted_synonyms.items():
                if normalized_synonym not in existing_synonyms:
                    db.add(
                        AttributeValueSynonym(
                            allowed_value=value,
                            synonym=synonym_text,
                            normalized_synonym=normalized_synonym,
                        )
                    )
        for value in list(field.allowed_values or []):
            if value.id not in retained_value_ids:
                db.delete(value)

    for field in list(template.fields or []):
        if field.id not in retained_field_ids:
            db.delete(field)
    db.flush()
    _save_template_revision(
        db,
        template,
        "restored",
        {"source_revision_id": revision.id, "source_version": revision.version},
    )
    db.flush()
    db.expire(template, ["fields"])
    return load_template(db, template.id) or template


def _category_for_template(
    db,
    category_name: str,
    category_path: str,
    *,
    external_key: str = "",
) -> AttributeCategory:
    full_path = clean_text(category_path or category_name)[:500]
    name = clean_text(category_name or full_path.split("→")[-1])[:255]
    if not name or not full_path:
        raise ValueError("Укажите название и путь категории")
    category = db.scalar(select(AttributeCategory).where(AttributeCategory.full_path == full_path))
    parent_name = clean_text(full_path.split("→")[-2])[:255] if "→" in full_path else ""
    if category is None:
        category = AttributeCategory(
            name=name,
            parent_name=parent_name,
            full_path=full_path,
            external_key=clean_text(external_key)[:128],
        )
        db.add(category)
        db.flush()
    else:
        category.name = name
        category.parent_name = parent_name
        if external_key:
            category.external_key = clean_text(external_key)[:128]
    return category


def parse_template_csv(content: bytes) -> Tuple[List[Dict[str, object]], Dict[str, object]]:
    headers, rows, encoding = read_semicolon_csv(content)
    vertical_values = [clean_text(row[0]) for row in rows if row and clean_text(row[0])]
    is_vertical = len(headers) == 1 and headers[0].casefold().startswith(
        ("атрибут", "attributes", "список атрибутов")
    )
    if is_vertical:
        parsed_headers = [parse_template_header(value) for value in vertical_values]
        values_by_column: List[List[str]] = [[] for _ in parsed_headers]
        source_format = "vertical"
    else:
        parsed_headers = [parse_template_header(header) for header in headers]
        values_by_column = [
            [clean_text(row[index]) for row in rows if index < len(row)]
            for index in range(len(parsed_headers))
        ]
        source_format = "dictionary"
    keys = [(group.casefold(), name.casefold()) for name, group in parsed_headers]
    duplicated_headers = [key for key, count in Counter(keys).items() if count > 1]
    if duplicated_headers:
        raise ValueError("В шаблоне есть повторяющиеся столбцы атрибутов")

    report: Dict[str, object] = {
        "encoding": encoding,
        "source_format": source_format,
        "duplicate_values": 0,
        "empty_values": 0,
        "invalid_values": [],
    }
    parsed_fields: List[Dict[str, object]] = []
    for index, (name, group) in enumerate(parsed_headers):
        raw_values = values_by_column[index]
        value_type, is_composite = infer_value_type(name, raw_values)
        values: List[str] = []
        seen = set()
        for raw in raw_values:
            if not raw:
                report["empty_values"] = int(report["empty_values"]) + 1
                continue
            canonical = normalize_attribute_value(raw, value_type)
            normalized = normalized_lookup_value(canonical, value_type)
            if not normalized:
                report["empty_values"] = int(report["empty_values"]) + 1
                continue
            if normalized in seen:
                report["duplicate_values"] = int(report["duplicate_values"]) + 1
                continue
            if not _is_valid_dictionary_value(canonical, value_type):
                report["invalid_values"].append(
                    {"group_name": group, "attribute_name": name, "value": raw}
                )
                continue
            seen.add(normalized)
            values.append(canonical)
        parsed_fields.append(
            {
                "group_name": group,
                "name": name,
                "value_type": value_type,
                "is_composite": is_composite,
                "separator": "/",
                "sort_order": index,
                "values": values,
            }
        )
    return parsed_fields, report


def _template_diff(template: Optional[AttributeTemplate], parsed_fields: Sequence[Dict[str, object]]) -> Dict[str, object]:
    existing_fields = {
        _attribute_key(field.group_name, field.name): field for field in (template.fields if template else [])
    }
    incoming = {
        _attribute_key(str(field["group_name"]), str(field["name"])): field for field in parsed_fields
    }
    new_fields = [
        f"{field['name']} ({field['group_name']})"
        for key, field in incoming.items()
        if key not in existing_fields
    ]
    removed_fields = [
        f"{field.name} ({field.group_name})"
        for key, field in existing_fields.items()
        if key not in incoming
    ]
    new_values: List[Dict[str, str]] = []
    removed_values: List[Dict[str, str]] = []
    changed_groups: List[Dict[str, str]] = []
    existing_by_name = {
        normalized_lookup_value(field.name): field
        for field in (template.fields if template else [])
    }
    incoming_by_name = {
        normalized_lookup_value(str(field["name"])): field
        for field in parsed_fields
    }
    for name_key, parsed in incoming_by_name.items():
        current = existing_by_name.get(name_key)
        if current and normalized_lookup_value(current.group_name) != normalized_lookup_value(parsed["group_name"]):
            changed_groups.append(
                {
                    "attribute": str(parsed["name"]),
                    "from": current.group_name,
                    "to": str(parsed["group_name"]),
                }
            )
    for key, parsed in incoming.items():
        current = existing_fields.get(key)
        current_values = {
            item.normalized_value: item.value for item in (current.allowed_values if current else [])
        }
        incoming_values = {
            normalized_lookup_value(value, str(parsed["value_type"])): value
            for value in parsed["values"]
        }
        for normalized, value in incoming_values.items():
            if normalized not in current_values:
                new_values.append({"attribute": str(parsed["name"]), "value": value})
        for normalized, value in current_values.items():
            if normalized not in incoming_values:
                removed_values.append({"attribute": str(parsed["name"]), "value": value})
    return {
        "new_fields": new_fields,
        "removed_fields": removed_fields,
        "new_values": new_values,
        "removed_values": removed_values,
        "changed_groups": changed_groups,
        "new_fields_count": len(new_fields),
        "removed_fields_count": len(removed_fields),
        "new_values_count": len(new_values),
        "removed_values_count": len(removed_values),
        "changed_groups_count": len(changed_groups),
    }


def preview_template_csv(
    db,
    content: bytes,
    *,
    category_name: str,
    category_path: str,
    template_name: str,
) -> Dict[str, object]:
    parsed_fields, parse_report = parse_template_csv(content)
    full_path = clean_text(category_path or category_name)
    category = db.scalar(select(AttributeCategory).where(AttributeCategory.full_path == full_path))
    template = None
    if category is not None:
        template = db.scalar(
            select(AttributeTemplate)
            .where(AttributeTemplate.category_id == category.id, AttributeTemplate.name == clean_text(template_name))
            .options(*_template_options())
        )
    used_attributes: List[Dict[str, object]] = []
    if template is not None:
        usage_rows = db.execute(
            select(
                AttributeProductValue.template_field_id,
                func.count(AttributeProductValue.id),
            )
            .where(AttributeProductValue.template_field_id.is_not(None))
            .group_by(AttributeProductValue.template_field_id)
        ).all()
        usage = {int(field_id): int(count) for field_id, count in usage_rows if field_id is not None}
        used_attributes = [
            {
                "field_id": field.id,
                "attribute": field.name,
                "products_count": usage[field.id],
            }
            for field in template.fields or []
            if usage.get(field.id)
        ]
    return {
        **parse_report,
        **_template_diff(template, parsed_fields),
        "template_exists": template is not None,
        "fields_count": len(parsed_fields),
        "used_attributes": used_attributes,
    }


def import_template_csv(
    db,
    content: bytes,
    *,
    category_name: str,
    category_path: str,
    template_name: str,
    mode: str = "merge",
    load_result: bool = True,
    product_type: str = "",
    is_default: bool = False,
    external_key: str = "",
) -> Tuple[AttributeTemplate, Dict[str, object]]:
    if mode not in {"merge", "replace", "update_values"}:
        raise ValueError("Неизвестный режим обновления шаблона")
    parsed_fields, parse_report = parse_template_csv(content)
    name = clean_text(template_name)[:255]
    if not name:
        raise ValueError("Укажите название шаблона")
    category = _category_for_template(
        db,
        category_name,
        category_path,
        external_key=external_key,
    )
    template = db.scalar(
        select(AttributeTemplate)
        .where(AttributeTemplate.category_id == category.id, AttributeTemplate.name == name)
        .options(*_template_options())
    )
    created = template is None
    if template is None:
        template = AttributeTemplate(
            category=category,
            name=name,
            product_type=clean_text(product_type),
            is_active=True,
            is_default=is_default,
        )
        db.add(template)
        db.flush()
    else:
        diff = _template_diff(template, parsed_fields)
        _save_template_revision(db, template, f"before_{mode}", diff)
        template.version += 1
        template.product_type = clean_text(product_type) or template.product_type
        template.is_default = is_default
    if is_default:
        for other in db.scalars(
            select(AttributeTemplate).where(
                AttributeTemplate.category_id == category.id,
                AttributeTemplate.id != template.id,
            )
        ):
            other.is_default = False

    diff = _template_diff(None if created else template, parsed_fields)
    if mode == "replace" and not created:
        template.fields.clear()
        db.flush()
    existing_fields = {
        _attribute_key(field.group_name, field.name): field for field in template.fields or []
    }
    report: Dict[str, object] = {
        **parse_report,
        **diff,
        "created": created,
        "mode": mode,
        "new_fields": 0,
        "updated_fields": 0,
        "new_values": 0,
    }
    for parsed in parsed_fields:
        key = _attribute_key(str(parsed["group_name"]), str(parsed["name"]))
        field = existing_fields.get(key)
        if field is None:
            if mode == "update_values":
                continue
            field = AttributeTemplateField(
                template=template,
                group_name=str(parsed["group_name"]),
                name=str(parsed["name"]),
                value_type=str(parsed["value_type"]),
                is_composite=bool(parsed["is_composite"]),
                separator=str(parsed["separator"]),
                sort_order=int(parsed["sort_order"]),
            )
            db.add(field)
            db.flush()
            existing_fields[key] = field
            report["new_fields"] = int(report["new_fields"]) + 1
        else:
            field.sort_order = int(parsed["sort_order"])
            field.value_type = str(parsed["value_type"])
            field.is_composite = bool(parsed["is_composite"])
            field.is_active = True
            report["updated_fields"] = int(report["updated_fields"]) + 1
        existing_values = {item.normalized_value for item in field.allowed_values or []}
        for value_index, canonical in enumerate(parsed["values"]):
            normalized = normalized_lookup_value(canonical, field.value_type, field.separator)
            if normalized in existing_values:
                continue
            db.add(
                AttributeAllowedValue(
                    field=field,
                    value=canonical,
                    normalized_value=normalized,
                    value_type="template" if field.is_composite and field.separator in canonical else "value",
                    is_recommended=True,
                    source="import",
                    sort_order=value_index,
                )
            )
            existing_values.add(normalized)
            report["new_values"] = int(report["new_values"]) + 1
    db.flush()
    if created:
        _save_template_revision(db, template, "created", report)
    db.flush()
    return (load_template(db, template.id) or template, report) if load_result else (template, report)


def create_empty_template(
    db,
    *,
    category_name: str,
    category_path: str,
    template_name: str,
    product_type: str = "",
    is_default: bool = False,
) -> AttributeTemplate:
    name = clean_text(template_name)
    if not name:
        raise ValueError("Укажите название шаблона")
    category = _category_for_template(db, category_name, category_path)
    existing = db.scalar(
        select(AttributeTemplate).where(
            AttributeTemplate.category_id == category.id,
            AttributeTemplate.name == name,
        )
    )
    if existing:
        raise ValueError("Шаблон с таким названием уже существует в категории")
    template = AttributeTemplate(
        category=category,
        name=name,
        product_type=clean_text(product_type),
        is_default=is_default,
    )
    db.add(template)
    db.flush()
    if is_default:
        for other in db.scalars(
            select(AttributeTemplate).where(
                AttributeTemplate.category_id == category.id,
                AttributeTemplate.id != template.id,
            )
        ):
            other.is_default = False
    _save_template_revision(db, template, "created")
    return load_template(db, template.id) or template


def copy_template(db, template: AttributeTemplate, name: str) -> AttributeTemplate:
    new_name = clean_text(name)
    if not new_name:
        raise ValueError("Укажите название копии")
    if db.scalar(
        select(AttributeTemplate.id).where(
            AttributeTemplate.category_id == template.category_id,
            AttributeTemplate.name == new_name,
        )
    ):
        raise ValueError("Шаблон с таким названием уже существует")
    copy = AttributeTemplate(
        category_id=template.category_id,
        name=new_name,
        description=template.description,
        product_type=template.product_type,
        is_active=template.is_active,
        is_default=False,
    )
    db.add(copy)
    db.flush()
    for field in template.fields or []:
        next_field = AttributeTemplateField(
            template=copy,
            group_name=field.group_name,
            name=field.name,
            is_required=field.is_required,
            value_type=field.value_type,
            is_composite=field.is_composite,
            separator=field.separator,
            sort_order=field.sort_order,
            use_dash_if_empty=field.use_dash_if_empty,
            is_active=field.is_active,
        )
        db.add(next_field)
        db.flush()
        for value in field.allowed_values or []:
            next_value = AttributeAllowedValue(
                field=next_field,
                value=value.value,
                normalized_value=value.normalized_value,
                value_type=value.value_type,
                is_global=value.is_global,
                is_recommended=value.is_recommended,
                is_active=value.is_active,
                source="copy",
                sort_order=value.sort_order,
            )
            db.add(next_value)
            db.flush()
            for synonym in value.synonyms or []:
                db.add(
                    AttributeValueSynonym(
                        allowed_value=next_value,
                        synonym=synonym.synonym,
                        normalized_synonym=synonym.normalized_synonym,
                    )
                )
    db.flush()
    _save_template_revision(db, copy, "copied", {"source_template_id": template.id})
    return load_template(db, copy.id) or copy


def update_template_field(db, field: AttributeTemplateField, payload: Dict[str, object]) -> AttributeTemplateField:
    template = load_template(db, field.template_id)
    next_group = clean_text(payload.get("group_name")) if "group_name" in payload else field.group_name
    next_name = clean_text(payload.get("name")) if "name" in payload else field.name
    if not next_group or not next_name:
        raise ValueError("Группа и название атрибута не могут быть пустыми")
    if template and any(
        item.id != field.id
        and _attribute_key(item.group_name, item.name) == _attribute_key(next_group, next_name)
        for item in template.fields or []
    ):
        raise ValueError("Такой атрибут уже есть в шаблоне")
    if template:
        _save_template_revision(db, template, "before_field_update", {"field_id": field.id})
        template.version += 1
    if "group_name" in payload:
        field.group_name = next_group
    if "name" in payload:
        field.name = next_name
    if payload.get("value_type") in VALUE_TYPES:
        field.value_type = str(payload["value_type"])
    for key in ("is_required", "is_composite", "use_dash_if_empty", "is_active"):
        if key in payload:
            setattr(field, key, _parse_bool(payload[key], getattr(field, key)))
    if "separator" in payload:
        field.separator = clean_text(payload["separator"])[:16] or "/"
    if "sort_order" in payload:
        field.sort_order = int(payload["sort_order"])
    db.flush()
    return field


def create_template_field(
    db,
    template: AttributeTemplate,
    payload: Dict[str, object],
) -> AttributeTemplateField:
    group_name = clean_text(payload.get("group_name"))
    name = clean_text(payload.get("name"))
    if not group_name or not name:
        raise ValueError("Укажите группу и название атрибута")
    key = _attribute_key(group_name, name)
    if any(_attribute_key(field.group_name, field.name) == key for field in template.fields or []):
        raise ValueError("Такой атрибут уже есть в шаблоне")
    _save_template_revision(db, template, "before_field_add", {"attribute": name})
    template.version += 1
    value_type = str(payload.get("value_type") or "select")
    field = AttributeTemplateField(
        template=template,
        group_name=group_name,
        name=name,
        is_required=_parse_bool(payload.get("is_required"), True),
        value_type=value_type if value_type in VALUE_TYPES else "select",
        is_composite=_parse_bool(payload.get("is_composite")),
        separator=clean_text(payload.get("separator"))[:16] or "/",
        sort_order=max((item.sort_order for item in template.fields or []), default=-1) + 1,
        use_dash_if_empty=_parse_bool(payload.get("use_dash_if_empty"), True),
    )
    db.add(field)
    db.flush()
    _save_template_revision(db, template, "field_added", {"field_id": field.id, "attribute": name})
    return field


def delete_template_field(db, template: AttributeTemplate, field: AttributeTemplateField) -> None:
    _save_template_revision(db, template, "before_field_delete", {"field_id": field.id})
    template.version += 1
    db.delete(field)
    db.flush()


def reorder_template_fields(
    db,
    template: AttributeTemplate,
    field_ids: Sequence[object],
) -> AttributeTemplate:
    try:
        parsed_ids = [int(value) for value in field_ids]
    except (TypeError, ValueError) as error:
        raise ValueError("Некорректный порядок атрибутов") from error
    current_ids = {field.id for field in template.fields or []}
    if len(parsed_ids) != len(current_ids) or set(parsed_ids) != current_ids:
        raise ValueError("Передан неполный список атрибутов шаблона")
    _save_template_revision(db, template, "before_fields_reorder")
    template.version += 1
    by_id = {field.id: field for field in template.fields or []}
    for index, field_id in enumerate(parsed_ids):
        by_id[field_id].sort_order = index
    db.flush()
    db.expire(template, ["fields"])
    return load_template(db, template.id) or template


def create_allowed_value(db, field: AttributeTemplateField, payload: Dict[str, object]) -> AttributeAllowedValue:
    raw = clean_text(payload.get("value"))
    canonical = normalize_attribute_value(raw, field.value_type, field.separator)
    if not _is_valid_dictionary_value(canonical, field.value_type, field.separator):
        raise ValueError("Значение имеет некорректный формат для типа атрибута")
    normalized = normalized_lookup_value(canonical, field.value_type, field.separator)
    existing = db.scalar(
        select(AttributeAllowedValue).where(
            AttributeAllowedValue.field_id == field.id,
            AttributeAllowedValue.normalized_value == normalized,
        )
    )
    if existing:
        if not existing.is_active:
            existing.is_active = True
            return existing
        raise ValueError("Такое разрешённое значение уже существует")
    value = AttributeAllowedValue(
        field=field,
        value=canonical,
        normalized_value=normalized,
        value_type=str(payload.get("value_type") or "value")[:32],
        is_global=_parse_bool(payload.get("is_global")),
        is_recommended=_parse_bool(payload.get("is_recommended"), True),
        source="manual",
        sort_order=len(field.allowed_values or []),
    )
    db.add(value)
    db.flush()
    for synonym in payload.get("synonyms") or []:
        add_value_synonym(db, value, synonym)
    template = load_template(db, field.template_id)
    if template:
        template.version += 1
        _save_template_revision(db, template, "value_added", {"field_id": field.id, "value": canonical})
    return value


def add_value_synonym(
    db,
    value: AttributeAllowedValue,
    synonym: object,
    *,
    record_revision: bool = False,
) -> AttributeValueSynonym:
    text = clean_text(synonym)
    if not text:
        raise ValueError("Синоним не может быть пустым")
    normalized = normalized_lookup_value(
        text,
        value.field.value_type if value.field else "select",
        value.field.separator if value.field else "/",
    )
    existing = db.scalar(
        select(AttributeValueSynonym).where(
            AttributeValueSynonym.allowed_value_id == value.id,
            AttributeValueSynonym.normalized_synonym == normalized,
        )
    )
    if existing:
        return existing
    if record_revision and value.field:
        template = load_template(db, value.field.template_id)
        if template:
            _save_template_revision(db, template, "before_synonym_add", {"value_id": value.id})
            template.version += 1
    item = AttributeValueSynonym(
        allowed_value=value,
        synonym=text,
        normalized_synonym=normalized,
    )
    db.add(item)
    db.flush()
    return item


def update_allowed_value_settings(
    db,
    value: AttributeAllowedValue,
    payload: Dict[str, object],
) -> AttributeAllowedValue:
    if value.field:
        template = load_template(db, value.field.template_id)
        if template:
            _save_template_revision(db, template, "before_value_update", {"value_id": value.id})
            template.version += 1
    for key in ("is_active", "is_recommended", "is_global"):
        if key in payload:
            setattr(value, key, _parse_bool(payload[key], getattr(value, key)))
    db.flush()
    return value


def delete_value_synonym(db, synonym: AttributeValueSynonym) -> None:
    value = synonym.allowed_value
    if value and value.field:
        template = load_template(db, value.field.template_id)
        if template:
            _save_template_revision(db, template, "before_synonym_delete", {"synonym_id": synonym.id})
            template.version += 1
    db.delete(synonym)
    db.flush()


def export_template_csv(template: AttributeTemplate) -> bytes:
    buffer = io.StringIO(newline="")
    fields = [field for field in template.fields or [] if field.is_active]
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow([f"{field.name} ({field.group_name})" for field in fields])
    max_values = max((len([value for value in field.allowed_values if value.is_active]) for field in fields), default=0)
    for index in range(max_values):
        row = []
        for field in fields:
            values = [value.value for value in field.allowed_values if value.is_active]
            row.append(values[index] if index < len(values) else "")
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8-sig")


def parse_attributes_block(value: object) -> List[Tuple[str, str, str]]:
    text = str(value or "").replace("\r\n", "\n").replace("\r", "\n")
    result: List[Tuple[str, str, str]] = []
    for raw_line in text.split("\n"):
        line = raw_line.strip()
        if not line:
            continue
        parts = line.split("|", 2)
        if len(parts) != 3:
            continue
        group, name, current = (clean_text(part) for part in parts)
        if group and name:
            result.append((group, name, current))
    return result


def _header_index(headers: Sequence[str], name: str, required: bool = False) -> Optional[int]:
    expected = name.casefold()
    for index, header in enumerate(headers):
        if header.strip().casefold() == expected:
            return index
    if required:
        raise ValueError(f"В CSV отсутствует обязательный столбец {name}")
    return None


def _row_value(row: Sequence[str], index: Optional[int]) -> str:
    return clean_text(row[index]) if index is not None and index < len(row) else ""


def _active_allowed_values(field: AttributeTemplateField) -> List[AttributeAllowedValue]:
    return [value for value in field.allowed_values or [] if value.is_active]


def _global_allowed_values(db) -> Dict[str, List[AttributeAllowedValue]]:
    result: Dict[str, List[AttributeAllowedValue]] = {}
    values = db.scalars(
        select(AttributeAllowedValue)
        .where(
            AttributeAllowedValue.is_active.is_(True),
            AttributeAllowedValue.is_global.is_(True),
        )
        .options(
            joinedload(AttributeAllowedValue.field),
            selectinload(AttributeAllowedValue.synonyms),
        )
    ).unique()
    for value in values:
        if value.field:
            result.setdefault(normalized_lookup_value(value.field.name), []).append(value)
    return result


def _effective_allowed_values(
    db,
    field: AttributeTemplateField,
    global_values: Optional[Dict[str, List[AttributeAllowedValue]]] = None,
) -> List[AttributeAllowedValue]:
    """Combine local values with reusable global values for the same attribute name."""
    result = list(_active_allowed_values(field))
    seen = {value.normalized_value for value in result}
    field_name = normalized_lookup_value(field.name)
    reusable_map = global_values if global_values is not None else _global_allowed_values(db)
    reusable = reusable_map.get(field_name, [])
    for value in reusable:
        if value.field and value.field.value_type != field.value_type:
            continue
        if value.normalized_value not in seen:
            result.append(value)
            seen.add(value.normalized_value)
    return result


def _candidate_lookup_variants(
    field: AttributeTemplateField,
    raw_value: object,
) -> List[str]:
    raw = clean_text(raw_value)
    canonical = normalize_attribute_value(raw, field.value_type, field.separator)
    variants = [normalized_lookup_value(canonical, field.value_type, field.separator)]
    number_match = re.search(r"[+-]?\d+(?:[.,]\d+)?", raw)
    if field.value_type == "number" and number_match:
        numeric = number_match.group(0).replace(",", ".")
        variants.append(normalized_lookup_value(numeric, "number"))
        field_name = normalized_lookup_value(field.name)
        raw_name = normalized_lookup_value(raw)
        if re.search(r"(?:^|\s)(?:квт|kw)(?:$|[/\s])", raw_name):
            if ("вт" in field_name or "w" in field_name) and "квт" not in field_name and "kw" not in field_name:
                watts = float(numeric) * 1000
                variants.append(str(int(watts)) if watts.is_integer() else str(watts))
    month_match = re.search(r"(\d+)\s*(?:месяц|месяца|месяцев|мес\.?|months?)", raw, re.I)
    if month_match and int(month_match.group(1)) % 12 == 0:
        years = int(month_match.group(1)) // 12
        if years % 10 == 1 and years % 100 != 11:
            suffix = "год"
        elif years % 10 in {2, 3, 4} and years % 100 not in {12, 13, 14}:
            suffix = "года"
        else:
            suffix = "лет"
        variants.append(normalized_lookup_value(f"{years} {suffix}"))
    return list(dict.fromkeys(value for value in variants if value))


def _match_allowed_value(
    field: AttributeTemplateField,
    raw_value: object,
    allowed_values: Optional[Sequence[AttributeAllowedValue]] = None,
) -> Tuple[Optional[str], int, str, Optional[str]]:
    """Return canonical value, confidence, match type and closest suggestion."""
    value = normalize_attribute_value(raw_value, field.value_type, field.separator)
    if not value:
        return None, 0, "empty", None
    variants = _candidate_lookup_variants(field, raw_value)
    normalized = variants[0]
    active = list(allowed_values) if allowed_values is not None else _active_allowed_values(field)
    if not active:
        return value, 100, "unrestricted", None
    by_normalized = {item.normalized_value: item for item in active}
    for variant in variants:
        if variant in by_normalized:
            confidence = 100 if variant == normalized else 97
            match_type = "exact" if variant == normalized else "unit_conversion"
            return by_normalized[variant].value, confidence, match_type, None
    for allowed in active:
        if any(synonym.normalized_synonym in variants for synonym in allowed.synonyms or []):
            return allowed.value, 96, "synonym", None
    if field.is_composite or field.value_type == "composite":
        parts = [clean_text(part) for part in value.split(field.separator or "/") if clean_text(part)]
        canonical_parts: List[str] = []
        atomic = [item for item in active if (field.separator or "/") not in item.value]
        atomic_lookup = {item.normalized_value: item.value for item in atomic}
        synonym_lookup = {
            synonym.normalized_synonym: item.value
            for item in atomic
            for synonym in item.synonyms or []
        }
        for part in parts:
            key = normalized_lookup_value(part, "select")
            matched = atomic_lookup.get(key) or synonym_lookup.get(key)
            if not matched:
                canonical_parts = []
                break
            canonical_parts.append(matched)
        if canonical_parts:
            canonical = (field.separator or "/").join(sorted(set(canonical_parts), key=str.casefold))
            return canonical, 94, "composite", None
    best: Optional[AttributeAllowedValue] = None
    best_ratio = 0.0
    for allowed in active:
        ratio = SequenceMatcher(None, normalized, allowed.normalized_value).ratio()
        if ratio > best_ratio:
            best_ratio = ratio
            best = allowed
    suggestion = best.value if best is not None and best_ratio >= 0.62 else None
    if best is not None and best_ratio >= 0.88:
        return best.value, int(65 + best_ratio * 25), "fuzzy", best.value
    return None, 0, "not_allowed", suggestion


def _similar_product_suggestion(
    db,
    template_id: int,
    field: AttributeTemplateField,
    *,
    model: str = "",
    name: str = "",
    brand: str = "",
) -> Tuple[str, int]:
    if field.value_type in {"number", "dimensions"}:
        return "", 0
    rows = db.execute(
        select(
            AttributeProductValue.final_value,
            AttributeProduct.model,
            AttributeProduct.name,
            AttributeProduct.brand,
        )
        .join(AttributeProduct)
        .join(AttributeBatch)
        .where(
            AttributeBatch.template_id == template_id,
            AttributeProductValue.template_field_id == field.id,
            AttributeProductValue.final_value.not_in(("", "-")),
            AttributeProductValue.status.in_(("filled", "accepted")),
        )
        .limit(500)
    ).all()
    if not rows:
        return "", 0
    target_brand = normalized_lookup_value(brand)
    if not target_brand:
        brand_match = re.search(r"\b([A-ZА-ЯЁ][A-ZА-ЯЁ0-9-]{1,})\b", name)
        target_brand = normalized_lookup_value(brand_match.group(1)) if brand_match else ""
    target_series = re.match(r"[A-ZА-ЯЁ]+\d{0,2}", clean_text(model), re.I)
    series = normalized_lookup_value(target_series.group(0)) if target_series else ""
    name_tokens = {
        token for token in re.findall(r"[a-zа-яё0-9]{3,}", normalized_lookup_value(name))
        if token not in {"машина", "шкаф", "холодильник", "встраиваемый", "отдельностоящий"}
    }
    weights: Counter[str] = Counter()
    counts: Counter[str] = Counter()
    display_values: Dict[str, str] = {}
    for value, candidate_model, candidate_name, candidate_brand in rows:
        key = normalized_lookup_value(value, field.value_type, field.separator)
        display_values.setdefault(key, str(value))
        score = 1
        known_brand = normalized_lookup_value(candidate_brand)
        if not known_brand:
            match = re.search(r"\b([A-ZА-ЯЁ][A-ZА-ЯЁ0-9-]{1,})\b", str(candidate_name or ""))
            known_brand = normalized_lookup_value(match.group(1)) if match else ""
        if target_brand and known_brand == target_brand:
            score += 4
        if series and normalized_lookup_value(candidate_model).startswith(series):
            score += 3
        candidate_tokens = set(re.findall(r"[a-zа-яё0-9]{3,}", normalized_lookup_value(candidate_name)))
        score += min(3, len(name_tokens & candidate_tokens))
        weights[key] += score
        counts[key] += 1
    best_key, best_weight = weights.most_common(1)[0]
    total_weight = sum(weights.values())
    confidence = min(
        85,
        58 + int((best_weight / max(total_weight, 1)) * 18) + min(counts[best_key], 6),
    )
    return display_values[best_key], confidence


def _should_auto_accept(mode: str, confidence: int, match_type: str) -> bool:
    if mode == "auto_all":
        return confidence >= 70 and match_type not in {"not_allowed", "empty"}
    if mode == "auto_high":
        return confidence >= 95 and match_type in {"exact", "synonym", "composite", "unit_conversion"}
    return False


def _new_product_values(
    db,
    template: AttributeTemplate,
    current_attributes: Sequence[Tuple[str, str, str]],
    processing_mode: str,
    global_values: Optional[Dict[str, List[AttributeAllowedValue]]] = None,
    *,
    model: str = "",
    name: str = "",
    brand: str = "",
) -> List[AttributeProductValue]:
    current_by_key: Dict[Tuple[str, str], Tuple[str, str, str]] = {}
    current_order: List[Tuple[str, str]] = []
    for group_name, attribute_name, current_value in current_attributes:
        key = _attribute_key(group_name, attribute_name)
        current_order.append(key)
        existing = current_by_key.get(key)
        if existing is None or (not existing[2] and current_value):
            current_by_key[key] = (group_name, attribute_name, current_value)

    fields = [field for field in template.fields or [] if field.is_active]
    used_keys = set()
    result: List[AttributeProductValue] = []
    for field in fields:
        key = _attribute_key(field.group_name, field.name)
        used_keys.add(key)
        current = current_by_key.get(key)
        current_value = current[2] if current else ""
        has_value = bool(current_value and current_value != "-")
        proposed_value = ""
        source_details: Dict[str, object] = {}
        if has_value:
            canonical, confidence, match_type, closest = _match_allowed_value(
                field,
                current_value,
                _effective_allowed_values(db, field, global_values),
            )
            if canonical:
                final_value = canonical
                status = "filled"
                reason = "" if match_type in {"exact", "unrestricted"} else "Значение нормализовано по справочнику"
                source = "current"
            else:
                final_value = current_value
                status = "conflict"
                confidence = 100
                source = "current"
                reason = "Текущее значение отсутствует в справочнике; оно сохранено до решения пользователя"
                if closest:
                    proposed_value = closest
                    source_details["closest_allowed"] = closest
        else:
            final_value = "-"
            status = "dash"
            confidence = 0
            source = ""
            reason = "Исходное значение не заполнено" if current else "Атрибут отсутствует в исходном файле"
            if processing_mode != "check":
                similar, similar_confidence = _similar_product_suggestion(
                    db,
                    template.id,
                    field,
                    model=model,
                    name=name,
                    brand=brand,
                )
                if similar:
                    proposed_value = similar
                    source = "similar_products"
                    confidence = similar_confidence
                    status = "proposed"
                    reason = "Предложено по ранее обработанным товарам этой категории"
                    source_details["candidates"] = [
                        {"value": similar, "source": "similar_products", "confidence": similar_confidence}
                    ]
                    if _should_auto_accept(processing_mode, confidence, "similar"):
                        final_value = similar
                        status = "accepted"
        result.append(
            AttributeProductValue(
                template_field_id=field.id,
                group_name=field.group_name,
                attribute_name=field.name,
                current_value=current_value,
                proposed_value=proposed_value,
                final_value=final_value,
                source=source,
                confidence=confidence,
                status=status,
                is_in_template=True,
                is_extra_attribute=False,
                reason=reason,
                source_details=source_details,
                sort_order=field.sort_order,
            )
        )
    seen_extra = set()
    for key in current_order:
        if key in used_keys or key in seen_extra:
            continue
        seen_extra.add(key)
        group_name, attribute_name, current_value = current_by_key[key]
        result.append(
            AttributeProductValue(
                group_name=group_name,
                attribute_name=attribute_name,
                current_value=current_value,
                final_value=current_value or "-",
                source="current",
                confidence=100,
                status="extra",
                is_in_template=False,
                is_extra_attribute=True,
                reason="Атрибут отсутствует в шаблоне и будет сохранён без изменений",
                sort_order=len(fields) + len(seen_extra),
            )
        )
    return result


def _product_status(values: Iterable[AttributeProductValue]) -> str:
    return "needs_review" if any(item.status in REVIEW_STATUSES for item in values) else "ready"


def _summary_from_products(products: Sequence[AttributeProduct]) -> Dict[str, int]:
    values = [value for product in products for value in product.values]
    return {
        "filled": sum(value.status in {"filled", "accepted"} for value in values),
        "needs_review": sum(value.status in REVIEW_STATUSES for value in values),
        "conflicts": sum(value.status == "conflict" for value in values),
        "dash": sum((value.final_value or "-") == "-" for value in values),
        "proposed": sum(value.status == "proposed" for value in values),
        "extra": sum(value.is_extra_attribute for value in values),
        "ready_products": sum(product.status == "ready" for product in products),
    }


def _add_product(
    db,
    batch: AttributeBatch,
    template: AttributeTemplate,
    *,
    external_id: str,
    model: str,
    name: str,
    current_attributes: Sequence[Tuple[str, str, str]],
    sort_order: int,
    source_url: str = "",
    category_name: str = "",
    brand: str = "",
    global_values: Optional[Dict[str, List[AttributeAllowedValue]]] = None,
) -> AttributeProduct:
    product = AttributeProduct(
        batch=batch,
        external_id=external_id,
        model=model,
        name=name,
        source_url=source_url,
        category_name=category_name or template.category.name,
        brand=brand,
        sort_order=sort_order,
    )
    db.add(product)
    values = _new_product_values(
        db,
        template,
        current_attributes,
        batch.processing_mode,
        global_values,
        model=model,
        name=name,
        brand=brand,
    )
    for value in values:
        value.product = product
        db.add(value)
    product.status = _product_status(values)
    return product


def import_products_csv(
    db,
    template: AttributeTemplate,
    content: bytes,
    *,
    source_filename: str,
    stored_filename: str,
    processing_mode: str = "suggest",
) -> AttributeBatch:
    if processing_mode not in PROCESSING_MODES:
        raise ValueError("Неизвестный режим обработки")
    headers, rows, encoding = read_semicolon_csv(content)
    model_index = _header_index(headers, "_MODEL_", required=True)
    attributes_index = _header_index(headers, "_ATTRIBUTES_", required=True)
    id_index = _header_index(headers, "_ID_")
    name_index = _header_index(headers, "_NAME_")
    batch = AttributeBatch(
        template_id=template.id,
        source_filename=source_filename,
        stored_filename=stored_filename,
        status="ready",
        input_mode="csv",
        processing_mode=processing_mode,
        summary={"encoding": encoding},
    )
    db.add(batch)
    db.flush()
    global_values = _global_allowed_values(db)
    for row_index, row in enumerate(rows, start=1):
        model = _row_value(row, model_index)
        if not model:
            continue
        block = row[attributes_index] if attributes_index is not None and attributes_index < len(row) else ""
        _add_product(
            db,
            batch,
            template,
            external_id=_row_value(row, id_index),
            model=model,
            name=_row_value(row, name_index),
            current_attributes=parse_attributes_block(block),
            sort_order=row_index,
            global_values=global_values,
        )
    db.flush()
    if not batch.products:
        db.delete(batch)
        raise ValueError("В CSV не найдено ни одной строки с заполненным _MODEL_")
    batch.products_count = len(batch.products)
    batch.attributes_count = sum(len(product.values) for product in batch.products)
    batch.summary = {"encoding": encoding, **_summary_from_products(batch.products)}
    db.add(
        AttributeProcessingLog(
            batch_id=batch.id,
            action="products_imported",
            details={**dict(batch.summary), "processing_mode": processing_mode},
        )
    )
    db.flush()
    return batch


def _validate_http_url(url: object) -> str:
    value = clean_text(url)
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ValueError(f"Некорректный URL: {value}")
    hostname = parsed.hostname.casefold()
    if hostname in {"localhost", "localhost.localdomain"}:
        raise ValueError("Локальные адреса запрещены")
    try:
        addresses = socket.getaddrinfo(hostname, parsed.port or (443 if parsed.scheme == "https" else 80))
    except socket.gaierror as error:
        raise ValueError(f"Не удалось определить адрес сайта {hostname}") from error
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError("Запросы к локальным и служебным адресам запрещены")
    return value


def _decode_html_content(
    content: bytes,
    *,
    content_type: object = "",
    apparent_encoding: object = "",
) -> str:
    """Decode HTML while respecting explicit server and document charsets first."""
    candidates: List[str] = []

    if content.startswith(b"\xef\xbb\xbf"):
        candidates.append("utf-8-sig")
    elif content.startswith((b"\xff\xfe", b"\xfe\xff")):
        candidates.append("utf-16")

    header_match = HTML_CHARSET_RE.search(str(content_type or ""))
    if header_match:
        candidates.append(header_match.group(1))

    meta_match = HTML_META_CHARSET_RE.search(content[:16384])
    if meta_match:
        candidates.append(meta_match.group(1).decode("ascii", errors="ignore"))

    # UTF-8 is overwhelmingly common on current product pages. Detection
    # libraries can mistake short Cyrillic documents for MacRoman/cp1251, so
    # their guess is only a fallback when no explicit charset is available.
    try:
        content.decode("utf-8")
    except UnicodeDecodeError:
        pass
    else:
        candidates.append("utf-8")
    candidates.extend((clean_text(apparent_encoding), "cp1251", "latin-1"))

    tried = set()
    for encoding in candidates:
        key = encoding.casefold().replace("_", "-")
        if not key or key in tried:
            continue
        tried.add(key)
        try:
            return content.decode(encoding)
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", errors="replace")


def fetch_product_html(url: object, timeout: int = 25) -> Tuple[str, str]:
    safe_url = _validate_http_url(url)
    response = None
    for _redirect in range(6):
        response = requests.get(
            safe_url,
            headers=DEFAULT_HTTP_HEADERS,
            timeout=timeout,
            allow_redirects=False,
        )
        if response.is_redirect or response.is_permanent_redirect:
            location = response.headers.get("Location")
            if not location:
                break
            safe_url = _validate_http_url(urljoin(safe_url, location))
            continue
        break
    else:
        raise ValueError("Слишком много перенаправлений при загрузке страницы")
    if response is None:
        raise ValueError("Не удалось загрузить страницу товара")
    response.raise_for_status()
    final_url = _validate_http_url(response.url or safe_url)
    if len(response.content) > 15 * 1024 * 1024:
        raise ValueError("Страница товара слишком большая")
    return final_url, _decode_html_content(
        response.content,
        content_type=response.headers.get("Content-Type"),
        apparent_encoding=response.apparent_encoding,
    )


def _selector_text(soup: BeautifulSoup, selector: str) -> str:
    if not selector:
        return ""
    node = soup.select_one(selector)
    return clean_text(node.get_text(" ", strip=True)) if node else ""


def _meta_content(soup: BeautifulSoup, selector: str) -> str:
    node = soup.select_one(selector)
    return clean_text(node.get("content")) if node else ""


def _structured_value_text(value: object) -> str:
    if isinstance(value, dict):
        return clean_text(value.get("value") or value.get("name") or value.get("@value"))
    if isinstance(value, list):
        return ", ".join(filter(None, (_structured_value_text(item) for item in value)))
    return clean_text(value)


def _model_from_name_and_url(name: str, url: str) -> str:
    """Use a code-like title token only when the same token occurs in the URL."""
    path_key = re.sub(r"[^a-zа-яё0-9]", "", unquote(urlparse(url).path).casefold())
    if not path_key:
        return ""
    for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+(?:[._/+\-][A-Za-zА-Яа-яЁё0-9]+)*", name):
        if len(token) < 4 or not any(char.isalpha() for char in token) or not any(char.isdigit() for char in token):
            continue
        token_key = re.sub(r"[^a-zа-яё0-9]", "", token.casefold())
        if len(token_key) >= 4 and token_key in path_key:
            return clean_text(token)
    return ""


def _append_attribute(
    attributes: List[Tuple[str, str, str]],
    seen: set,
    group: object,
    name: object,
    value: object,
) -> None:
    group_text = clean_text(group) or "Характеристики"
    name_text = clean_text(name).rstrip(":")
    value_text = clean_text(value)
    if (
        not name_text
        or not value_text
        or name_text == value_text
        or len(name_text) > 250
        or len(value_text) > 2000
    ):
        return
    key = _attribute_key(group_text, name_text)
    if key in seen:
        return
    seen.add(key)
    attributes.append((group_text, name_text, value_text))


def _semantic_tokens(node: Tag) -> set[str]:
    parts: List[str] = []
    classes = node.get("class") or []
    parts.extend(str(item) for item in classes)
    for attribute in ("id", "itemprop", "data-role", "data-type"):
        value = node.get(attribute)
        if value:
            parts.append(str(value))
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", " ".join(parts))
        if token
    }


def _attribute_context_near(node: Tag, levels: int = 4) -> bool:
    current: Optional[Tag] = node
    for _ in range(levels + 1):
        if current is None:
            break
        if _semantic_tokens(current) & ATTRIBUTE_CONTEXT_HINTS:
            return True
        parent = current.parent
        current = parent if isinstance(parent, Tag) else None
    return False


def _attribute_group_for_node(node: Tag) -> str:
    heading = node.find_previous(["h2", "h3", "h4"])
    if heading is None:
        return "Характеристики"
    text = clean_text(heading.get_text(" ", strip=True))
    return text if 0 < len(text) <= 150 else "Характеристики"


def _semantic_div_attribute_rows(soup: BeautifulSoup) -> Iterator[Tuple[str, str, str]]:
    """Yield common BEM/name-value rows without depending on a shop's classes."""
    for row in soup.find_all(["div", "li", "p", "section"]):
        children = [child for child in row.children if isinstance(child, Tag)]
        if not 2 <= len(children) <= 4:
            continue
        row_text = clean_text(row.get_text(" ", strip=True))
        if not row_text or len(row_text) > 2500:
            continue

        name_node = next(
            (child for child in children if _semantic_tokens(child) & ATTRIBUTE_NAME_HINTS),
            None,
        )
        value_node = next(
            (child for child in children if _semantic_tokens(child) & ATTRIBUTE_VALUE_HINTS),
            None,
        )
        if name_node is not None and value_node is not None and name_node is not value_node:
            yield (
                _attribute_group_for_node(row),
                clean_text(name_node.get("content") or name_node.get_text(" ", strip=True)),
                clean_text(value_node.get("content") or value_node.get_text(" ", strip=True)),
            )
            continue

        # Some themes use two anonymous columns inside a clearly named
        # specifications/characteristics block.
        row_has_context = bool(_semantic_tokens(row) & ATTRIBUTE_CONTEXT_HINTS)
        if len(children) != 2 or (
            not row_has_context
            and not (row.name == "li" and _attribute_context_near(row, levels=2))
        ):
            continue
        first = clean_text(children[0].get_text(" ", strip=True))
        second = clean_text(children[1].get_text(" ", strip=True))
        if not first or not second:
            continue
        if (
            len(first) <= 80
            and any(char.isdigit() for char in first)
            and any(char.isalpha() for char in second)
            and not any(char.isdigit() for char in second)
        ):
            first, second = second, first
        yield (_attribute_group_for_node(row), first, second)


def _colon_attribute_rows(soup: BeautifulSoup) -> Iterator[Tuple[str, str, str]]:
    for row in soup.find_all(["li", "p", "div"]):
        if not _attribute_context_near(row):
            continue
        if row.find(["li", "p", "div"], recursive=False) is not None:
            continue
        text = clean_text(row.get_text(" ", strip=True))
        if not text or len(text) > 1200 or ":" not in text:
            continue
        name, value = (clean_text(part) for part in text.split(":", 1))
        if 1 < len(name) <= 250 and value:
            yield (_attribute_group_for_node(row), name, value)


def _json_key_tokens(value: object) -> set[str]:
    return {
        token.casefold()
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", str(value or ""))
        if token
    }


def _json_attribute_rows(data: object, in_attribute_context: bool = False) -> Iterator[Tuple[str, str, str]]:
    if isinstance(data, list):
        for item in data:
            yield from _json_attribute_rows(item, in_attribute_context)
        return
    if not isinstance(data, dict):
        return

    name = next(
        (data.get(key) for key in ("name", "title", "label", "key", "property") if data.get(key) not in (None, "")),
        None,
    )
    value = next(
        (data.get(key) for key in ("value", "val", "text", "content", "description") if data.get(key) not in (None, "")),
        None,
    )
    if in_attribute_context and name is not None and value is not None and not isinstance(value, (dict, list)):
        yield ("Характеристики", clean_text(name), clean_text(value))

    for key, child in data.items():
        child_context = in_attribute_context or bool(_json_key_tokens(key) & ATTRIBUTE_CONTEXT_HINTS)
        yield from _json_attribute_rows(child, child_context)


def _script_attribute_rows(soup: BeautifulSoup) -> Iterator[Tuple[str, str, str]]:
    for script in soup.select('script[type="application/json"], script[type="application/ld+json"]'):
        raw = script.string or script.get_text() or ""
        if not raw.strip():
            continue
        try:
            data = json.loads(raw)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        yield from _json_attribute_rows(data)


def _json_ld_products(soup: BeautifulSoup) -> Iterable[Dict[str, object]]:
    for script in soup.select('script[type="application/ld+json"]'):
        try:
            data = json.loads(script.string or script.get_text() or "null")
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        queue = data if isinstance(data, list) else [data]
        while queue:
            item = queue.pop(0)
            if not isinstance(item, dict):
                continue
            graph = item.get("@graph")
            if isinstance(graph, list):
                queue.extend(graph)
            kind = item.get("@type")
            kinds = kind if isinstance(kind, list) else [kind]
            if "Product" in kinds:
                yield item


def parse_product_page(html: str, url: str, selectors: Optional[Dict[str, object]] = None) -> Dict[str, object]:
    selectors = dict(selectors or {})
    soup = BeautifulSoup(html, "html.parser")
    name = _selector_text(soup, str(selectors.get("name_selector") or ""))
    model = _selector_text(soup, str(selectors.get("model_selector") or ""))
    brand = _selector_text(soup, str(selectors.get("brand_selector") or ""))
    description = _selector_text(soup, str(selectors.get("description_selector") or ""))
    structured_attributes: List[Tuple[str, str, str]] = []
    structured_sku = ""
    for product_data in _json_ld_products(soup):
        name = name or clean_text(product_data.get("name"))
        model = model or clean_text(product_data.get("model") or product_data.get("mpn"))
        structured_sku = structured_sku or clean_text(product_data.get("sku"))
        description = description or clean_text(product_data.get("description"))
        raw_brand = product_data.get("brand")
        if isinstance(raw_brand, dict):
            brand = brand or clean_text(raw_brand.get("name"))
        else:
            brand = brand or clean_text(raw_brand)
        raw_properties = product_data.get("additionalProperty") or product_data.get("additionalProperties")
        if isinstance(raw_properties, dict):
            raw_properties = [raw_properties]
        if isinstance(raw_properties, list):
            for raw_property in raw_properties:
                if not isinstance(raw_property, dict):
                    continue
                property_name = clean_text(raw_property.get("name") or raw_property.get("propertyID"))
                property_value = _structured_value_text(raw_property.get("value"))
                if property_name and property_value:
                    structured_attributes.append(("Характеристики", property_name, property_value))
    name = (
        name
        or _selector_text(soup, "h1")
        or _meta_content(soup, 'meta[property="og:title"]')
        or _meta_content(soup, 'meta[name="twitter:title"]')
    )
    if not name and soup.title:
        name = clean_text(soup.title.get_text(" ", strip=True))
    description = (
        description
        or _meta_content(soup, 'meta[name="description"]')
        or _meta_content(soup, 'meta[property="og:description"]')
    )
    brand = brand or _meta_content(soup, 'meta[property="product:brand"]')
    if not model:
        for selector in (
            '[itemprop="sku"]',
            '[itemprop="model"]',
            'meta[property="product:retailer_item_id"]',
            '[data-model]',
            '.product-model',
            '.model',
        ):
            node = soup.select_one(selector)
            if node:
                model = clean_text(node.get("content") or node.get("data-model") or node.get_text(" ", strip=True))
                if model:
                    break
    model = model or _model_from_name_and_url(name, url)
    if not model:
        page_text = soup.get_text(" ", strip=True)
        for label in ("модель", "артикул", "код товара"):
            match = re.search(
                rf"{label}\s*[:№]?\s*([A-ZА-Я0-9][A-ZА-Я0-9._/+\-]{{2,}}(?:\s+Inverter)?)",
                page_text,
                re.I,
            )
            if match:
                model = clean_text(match.group(1))
                break
    model = model or structured_sku

    breadcrumbs = [
        clean_text(node.get_text(" ", strip=True))
        for node in soup.select(
            str(
                selectors.get("breadcrumb_selector")
                or "[class*='breadcrumb' i] a, [aria-label*='breadcrumb' i] a"
            )
        )
        if clean_text(node.get_text(" ", strip=True))
    ]
    category = breadcrumbs[-1] if breadcrumbs else ""
    attributes: List[Tuple[str, str, str]] = []
    seen = set()

    row_selector = str(selectors.get("attribute_row_selector") or "")
    name_selector = str(selectors.get("attribute_name_selector") or "")
    value_selector = str(selectors.get("attribute_value_selector") or "")
    group_selector = str(selectors.get("attribute_group_selector") or "")
    if row_selector and name_selector and value_selector:
        for row in soup.select(row_selector):
            name_node = row.select_one(name_selector)
            value_node = row.select_one(value_selector)
            group_node = row.select_one(group_selector) if group_selector else None
            attr_name = clean_text(name_node.get_text(" ", strip=True)) if name_node else ""
            attr_value = clean_text(value_node.get_text(" ", strip=True)) if value_node else ""
            group = clean_text(group_node.get_text(" ", strip=True)) if group_node else "Характеристики"
            _append_attribute(attributes, seen, group, attr_name, attr_value)

    for group, attr_name, attr_value in structured_attributes:
        _append_attribute(attributes, seen, group, attr_name, attr_value)

    for row in soup.select("table tr"):
        cells = row.select("th, td")
        if len(cells) < 2:
            continue
        attr_name = clean_text(cells[0].get_text(" ", strip=True)).rstrip(":")
        attr_value = clean_text(cells[-1].get_text(" ", strip=True))
        group_node = row.find_previous(["h2", "h3", "h4"])
        group = clean_text(group_node.get_text(" ", strip=True)) if group_node else "Характеристики"
        _append_attribute(attributes, seen, group, attr_name, attr_value)
    for term in soup.select("dl dt"):
        value_node = term.find_next_sibling("dd")
        if not value_node:
            continue
        attr_name = clean_text(term.get_text(" ", strip=True)).rstrip(":")
        attr_value = clean_text(value_node.get_text(" ", strip=True))
        group_node = term.find_previous(["h2", "h3", "h4"])
        group = clean_text(group_node.get_text(" ", strip=True)) if group_node else "Характеристики"
        _append_attribute(attributes, seen, group, attr_name, attr_value)

    # Many storefronts use semantic name/value divs instead of table/dl markup.
    # Match the vocabulary of a characteristic row, not a particular shop's CSS.
    for row in soup.select(GENERIC_ATTRIBUTE_ROW_SELECTOR):
        name_node = row.select_one(GENERIC_ATTRIBUTE_NAME_SELECTOR)
        value_node = row.select_one(GENERIC_ATTRIBUTE_VALUE_SELECTOR)
        if not name_node or not value_node or name_node is value_node:
            continue
        group_node = row.find_previous(["h2", "h3", "h4"])
        group = clean_text(group_node.get_text(" ", strip=True)) if group_node else "Характеристики"
        _append_attribute(
            attributes,
            seen,
            group,
            name_node.get("content") or name_node.get_text(" ", strip=True),
            value_node.get("content") or value_node.get_text(" ", strip=True),
        )

    for group, attr_name, attr_value in _semantic_div_attribute_rows(soup):
        _append_attribute(attributes, seen, group, attr_name, attr_value)
    for group, attr_name, attr_value in _colon_attribute_rows(soup):
        _append_attribute(attributes, seen, group, attr_name, attr_value)
    for group, attr_name, attr_value in _script_attribute_rows(soup):
        _append_attribute(attributes, seen, group, attr_name, attr_value)
    return {
        "url": url,
        "name": name,
        "model": model,
        "brand": brand,
        "description": description,
        "category": category,
        "breadcrumbs": breadcrumbs,
        "attributes": [
            {"group_name": group, "name": attr_name, "value": value}
            for group, attr_name, value in attributes
        ],
    }


class AttributeProductPageLoader:
    """Load static pages first and lazily reuse one browser for JS storefronts."""

    def __init__(self) -> None:
        self._browser_session = None
        self._allowed_browser_origins: Dict[str, bool] = {}

    def __enter__(self) -> "AttributeProductPageLoader":
        return self

    def __exit__(self, _exc_type, _exc_value, _traceback) -> None:
        self.close()

    @staticmethod
    def _parsed_score(parsed: Dict[str, object]) -> Tuple[int, int, int, int]:
        attributes = parsed.get("attributes") or []
        return (
            len(attributes) if isinstance(attributes, list) else 0,
            1 if clean_text(parsed.get("model")) else 0,
            1 if clean_text(parsed.get("name")) else 0,
            len(clean_text(parsed.get("description"))),
        )

    @staticmethod
    def _needs_browser(parsed: Dict[str, object], require_identity: bool) -> bool:
        return not parsed.get("attributes") or (
            require_identity
            and (not clean_text(parsed.get("name")) or not clean_text(parsed.get("model")))
        )

    def _browser_url_allowed(self, url: str) -> bool:
        parsed = urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.hostname:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._allowed_browser_origins:
            try:
                _validate_http_url(f"{origin}/")
            except ValueError:
                self._allowed_browser_origins[origin] = False
            else:
                self._allowed_browser_origins[origin] = True
        return self._allowed_browser_origins[origin]

    def _render(self, url: str, selectors: Dict[str, object]) -> str:
        if self._browser_session is None:
            try:
                from services.scraping.browser import PlaywrightBrowserSession

                self._browser_session = PlaywrightBrowserSession(
                    max_pages=1,
                    request_url_validator=self._browser_url_allowed,
                )
            except Exception:
                return ""
        ready_selector = clean_text(selectors.get("model_selector")) or (
            "h1, table tr, dl dt, [itemprop='additionalProperty'], "
            "[class*='characteristic' i], [class*='feature' i], "
            "[class*='spec' i], [class*='attribute' i], span.name"
        )
        rendered = self._browser_session.fetch(
            url,
            "playwright",
            {"model_selector": ready_selector},
            allow_empty_price=True,
        )
        return rendered if isinstance(rendered, str) else ""

    def load(
        self,
        url: object,
        selectors: Optional[Dict[str, object]] = None,
        *,
        require_identity: bool = True,
    ) -> Tuple[str, str, Dict[str, object]]:
        selector_values = dict(selectors or {})
        final_url, html = fetch_product_html(url)
        parsed = parse_product_page(html, final_url, selector_values)
        if not self._needs_browser(parsed, require_identity):
            return final_url, html, parsed

        rendered_html = self._render(final_url, selector_values)
        if not rendered_html:
            return final_url, html, parsed
        rendered_parsed = parse_product_page(rendered_html, final_url, selector_values)
        if self._parsed_score(rendered_parsed) > self._parsed_score(parsed):
            return final_url, rendered_html, rendered_parsed
        return final_url, html, parsed

    def close(self) -> None:
        browser_session = self._browser_session
        self._browser_session = None
        if browser_session is not None:
            browser_session.close()


def load_product_page(
    url: object,
    selectors: Optional[Dict[str, object]] = None,
    *,
    loader: Optional[AttributeProductPageLoader] = None,
    require_identity: bool = True,
) -> Tuple[str, str, Dict[str, object]]:
    if loader is not None:
        return loader.load(url, selectors, require_identity=require_identity)
    with AttributeProductPageLoader() as own_loader:
        return own_loader.load(url, selectors, require_identity=require_identity)


def detect_template_for_page(db, parsed: Dict[str, object]) -> Optional[AttributeTemplate]:
    category = normalized_lookup_value(parsed.get("category"))
    breadcrumbs = [normalized_lookup_value(item) for item in parsed.get("breadcrumbs") or []]
    page_hints = {value for value in [category, *breadcrumbs] if value}
    if not page_hints:
        return None
    ranked: List[Tuple[int, int, AttributeTemplate]] = []
    for template in list_templates(db):
        category_name = normalized_lookup_value(template.category.name)
        path_parts = {
            normalized_lookup_value(part)
            for part in re.split(r"\s*(?:→|>|/|\\)\s*", template.category.full_path)
            if clean_text(part)
        }
        score = 0
        if category_name in page_hints:
            score = 100
        elif any(category_name in hint or hint in category_name for hint in page_hints):
            score = 88
        else:
            overlap = len(path_parts & page_hints)
            score = min(82, overlap * 35)
        ranked.append((score, 1 if template.is_default else 0, template))
    ranked.sort(key=lambda item: (item[0], item[1], item[2].id), reverse=True)
    return ranked[0][2] if ranked and ranked[0][0] >= 60 else None


def import_products_from_urls(
    db,
    template: Optional[AttributeTemplate],
    urls: Sequence[str],
    *,
    processing_mode: str = "suggest",
) -> AttributeBatch:
    unique_urls = list(dict.fromkeys(clean_text(url) for url in urls if clean_text(url)))
    if not unique_urls:
        raise ValueError("Укажите хотя бы одну ссылку на товар")
    if len(unique_urls) > 100:
        raise ValueError("За один раз можно добавить не более 100 ссылок")
    parsed_pages: List[Tuple[int, str, Dict[str, object]]] = []
    errors = []
    detected_templates: Dict[int, AttributeTemplate] = {}
    with AttributeProductPageLoader() as page_loader:
        for index, raw_url in enumerate(unique_urls, start=1):
            try:
                final_url, _html, parsed = page_loader.load(raw_url)
                if not clean_text(parsed.get("model")):
                    raise ValueError("На странице не удалось определить модель")
                if template is None:
                    detected = detect_template_for_page(db, parsed)
                    if detected is None:
                        raise ValueError(
                            "Не удалось автоматически определить шаблон по категории страницы; выберите его вручную"
                        )
                    detected_templates[detected.id] = detected
                parsed_pages.append((index, final_url, parsed))
            except (ValueError, requests.RequestException) as error:
                errors.append({"url": raw_url, "error": str(error)})
    if not parsed_pages:
        message = errors[0]["error"] if errors else "Товары не найдены"
        raise ValueError(f"Не удалось получить ни одного товара: {message}")
    if template is None:
        if len(detected_templates) != 1:
            raise ValueError(
                "Ссылки относятся к разным категориям. Разделите их на обработки по одному шаблону"
            )
        template = next(iter(detected_templates.values()))

    batch = AttributeBatch(
        template_id=template.id,
        source_filename=f"Ссылки_{datetime.now(MSK_TZ):%Y%m%d_%H%M%S}",
        input_mode="url",
        processing_mode=processing_mode if processing_mode in PROCESSING_MODES else "suggest",
        source_urls=unique_urls,
        status="ready",
        summary={"encoding": "html"},
    )
    db.add(batch)
    db.flush()
    global_values = _global_allowed_values(db)
    for index, final_url, parsed in parsed_pages:
        attributes = [
            (item["group_name"], item["name"], item["value"])
            for item in parsed["attributes"]
        ]
        _add_product(
            db,
            batch,
            template,
            external_id="",
            model=clean_text(parsed["model"]),
            name=clean_text(parsed["name"]),
            current_attributes=attributes,
            sort_order=index,
            source_url=final_url,
            category_name=clean_text(parsed["category"]),
            brand=clean_text(parsed["brand"]),
            global_values=global_values,
        )
    db.flush()
    batch.products_count = len(batch.products)
    batch.attributes_count = sum(len(product.values) for product in batch.products)
    batch.summary = {"encoding": "html", "url_errors": errors, **_summary_from_products(batch.products)}
    db.add(
        AttributeProcessingLog(
            batch_id=batch.id,
            action="product_urls_imported",
            details={"urls_count": len(unique_urls), "errors": errors},
        )
    )
    db.flush()
    return batch


def batch_summary(batch: AttributeBatch) -> Dict[str, object]:
    return {
        "id": batch.id,
        "template_id": batch.template_id,
        "template_name": output_text(batch.template.name) if batch.template else "Удалённый шаблон",
        "category_name": output_text(batch.template.category.name) if batch.template and batch.template.category else "",
        "source_filename": output_text(batch.source_filename),
        "input_mode": batch.input_mode,
        "processing_mode": batch.processing_mode,
        "status": batch.status,
        "products_count": batch.products_count,
        "attributes_count": batch.attributes_count,
        "summary": dict(batch.summary or {}),
        "result_ready": bool(batch.export_filename),
        "report_ready": bool(batch.report_filename),
        "created_at": db_datetime_iso(batch.created_at),
        "updated_at": db_datetime_iso(batch.updated_at),
    }


def list_batches(db, limit: int = 30) -> List[AttributeBatch]:
    return list(
        db.scalars(
            select(AttributeBatch)
            .options(joinedload(AttributeBatch.template).joinedload(AttributeTemplate.category))
            .order_by(AttributeBatch.id.desc())
            .limit(limit)
        ).unique()
    )


def load_batch(db, batch_id: object, include_products: bool = False) -> Optional[AttributeBatch]:
    try:
        parsed_id = int(batch_id)
    except (TypeError, ValueError):
        return None
    options = [joinedload(AttributeBatch.template).joinedload(AttributeTemplate.category)]
    if include_products:
        options.append(selectinload(AttributeBatch.products))
    return db.scalar(select(AttributeBatch).where(AttributeBatch.id == parsed_id).options(*options))


def product_summary(product: AttributeProduct) -> Dict[str, object]:
    return {
        "id": product.id,
        "external_id": output_text(product.external_id),
        "model": output_text(product.model),
        "name": output_text(product.name),
        "source_url": output_text(product.source_url),
        "category_name": output_text(product.category_name),
        "brand": output_text(product.brand),
        "status": product.status,
        "sort_order": product.sort_order,
    }


def public_batch(batch: AttributeBatch) -> Dict[str, object]:
    return {**batch_summary(batch), "products": [product_summary(product) for product in batch.products or []]}


def load_product(db, product_id: object, *, include_allowed_values: bool = True) -> Optional[AttributeProduct]:
    try:
        parsed_id = int(product_id)
    except (TypeError, ValueError):
        return None
    values_option = selectinload(AttributeProduct.values).joinedload(AttributeProductValue.template_field)
    if include_allowed_values:
        values_option = values_option.selectinload(AttributeTemplateField.allowed_values).selectinload(
            AttributeAllowedValue.synonyms
        )
    return db.scalar(
        select(AttributeProduct)
        .where(AttributeProduct.id == parsed_id)
        .options(
            joinedload(AttributeProduct.batch),
            values_option,
            selectinload(AttributeProduct.donor_sources).joinedload(AttributeDonorProductSource.donor),
        )
    )


def allowed_value_field_ids(db, field_ids: Iterable[object]) -> set[int]:
    parsed_ids = {int(value) for value in field_ids if value is not None and str(value).isdigit()}
    if not parsed_ids:
        return set()
    direct = set(
        db.scalars(
            select(AttributeAllowedValue.field_id)
            .where(AttributeAllowedValue.field_id.in_(parsed_ids), AttributeAllowedValue.is_active.is_(True))
            .distinct()
        )
    )
    fields = list(db.scalars(select(AttributeTemplateField).where(AttributeTemplateField.id.in_(parsed_ids))))
    global_names = {
        normalized_lookup_value(field.name)
        for field in db.scalars(
            select(AttributeTemplateField)
            .join(AttributeAllowedValue)
            .where(
                AttributeAllowedValue.is_active.is_(True),
                AttributeAllowedValue.is_global.is_(True),
            )
        ).unique()
    }
    direct.update(field.id for field in fields if normalized_lookup_value(field.name) in global_names)
    return direct


def field_allowed_values(db, field_id: object) -> Optional[Dict[str, object]]:
    try:
        parsed_id = int(field_id)
    except (TypeError, ValueError):
        return None
    field = db.scalar(
        select(AttributeTemplateField)
        .where(AttributeTemplateField.id == parsed_id)
        .options(selectinload(AttributeTemplateField.allowed_values).selectinload(AttributeAllowedValue.synonyms))
    )
    if field is None:
        return None
    return {
        "field_id": parsed_id,
        "allowed_values": [
            _allowed_value_payload(value)
            for value in _effective_allowed_values(db, field)
        ],
    }


def public_product(product: AttributeProduct, *, allowed_fields: Optional[set[int]] = None) -> Dict[str, object]:
    payload = {**product_summary(product), "batch_id": product.batch_id}
    values_payload = []
    for item in product.values or []:
        if allowed_fields is None:
            allowed_values = _active_allowed_values(item.template_field) if item.template_field else []
            has_allowed_values = bool(allowed_values)
        else:
            allowed_values = []
            has_allowed_values = bool(item.template_field_id and item.template_field_id in allowed_fields)
        values_payload.append(
            {
                "id": item.id,
                "template_field_id": item.template_field_id,
                "group_name": output_text(item.group_name),
                "attribute_name": output_text(item.attribute_name),
                "current_value": output_text(item.current_value),
                "proposed_value": output_text(item.proposed_value),
                "final_value": output_text(item.final_value),
                "source": item.source,
                "confidence": item.confidence,
                "status": item.status,
                "is_in_template": bool(item.is_in_template),
                "is_extra_attribute": bool(item.is_extra_attribute),
                "reason": output_text(item.reason),
                "source_details": item.source_details or {},
                "sort_order": item.sort_order,
                "has_allowed_values": has_allowed_values,
                "allowed_values": [_allowed_value_payload(value, include_synonyms=False) for value in allowed_values],
            }
        )
    payload["values"] = values_payload
    payload["donor_sources"] = [
        {
            "id": source.id,
            "donor_id": source.donor_id,
            "donor_name": source.donor.name if source.donor else "",
            "url": source.url,
            "priority": source.priority,
            "status": source.status,
            "error": source.error,
            "parsed_data": source.parsed_data or {},
        }
        for source in product.donor_sources or []
    ]
    return payload


def _refresh_batch_summary(db, batch: AttributeBatch) -> None:
    products = list(
        db.scalars(
            select(AttributeProduct)
            .where(AttributeProduct.batch_id == batch.id)
            .options(selectinload(AttributeProduct.values))
        )
    )
    for product in products:
        product.status = _product_status(product.values)
    previous = dict(batch.summary or {})
    batch.summary = {
        **{key: value for key, value in previous.items() if key in {"encoding", "url_errors"}},
        **_summary_from_products(products),
    }


def update_product_value(
    db,
    product: AttributeProduct,
    value_id: object,
    final_value: object,
    *,
    refresh: bool = True,
) -> AttributeProductValue:
    try:
        parsed_id = int(value_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Некорректный идентификатор атрибута") from error
    item = next((value for value in product.values if value.id == parsed_id), None)
    if item is None:
        raise LookupError("Атрибут товара не найден")
    value = clean_text(str(final_value or "")) or "-"
    old = {
        "final_value": item.final_value,
        "status": item.status,
        "source": item.source,
        "confidence": item.confidence,
        "reason": item.reason,
    }
    field = item.template_field
    if value not in {"-", item.current_value} and field is not None and _active_allowed_values(field):
        canonical, _confidence, match_type, _closest = _match_allowed_value(
            field,
            value,
            _effective_allowed_values(db, field),
        )
        if canonical is None or match_type == "fuzzy":
            raise ValueError(
                f"Значение «{value}» отсутствует в справочнике для атрибута «{item.attribute_name}»"
            )
        value = canonical
    if value == "-":
        item.status = "dash"
        item.source = "manual"
        item.confidence = 100
        item.reason = "Пользователь оставил технический пропуск"
    elif value == item.current_value and item.current_value not in {"", "-"}:
        item.status = "filled" if item.is_in_template else "extra"
        item.source = "current"
        item.confidence = 100
        item.reason = "Текущее значение сохранено пользователем"
    else:
        item.status = "accepted"
        item.source = "manual"
        item.confidence = 100
        item.reason = "Значение подтверждено пользователем"
    item.final_value = value
    db.add(
        AttributeProcessingLog(
            batch_id=product.batch_id,
            product_id=product.id,
            action="value_updated",
            details={"value_id": item.id, "before": old, "after": {
                "final_value": value,
                "status": item.status,
                "source": item.source,
                "confidence": item.confidence,
                "reason": item.reason,
            }},
        )
    )
    db.flush()
    if refresh:
        _refresh_batch_summary(db, product.batch)
    return item


def bulk_update_values(
    db,
    batch: AttributeBatch,
    *,
    action: str,
    value_ids: Optional[Sequence[int]] = None,
    threshold: int = 95,
) -> Dict[str, int]:
    products = list(
        db.scalars(
            select(AttributeProduct)
            .where(AttributeProduct.batch_id == batch.id)
            .options(
                selectinload(AttributeProduct.values)
                .joinedload(AttributeProductValue.template_field)
                .selectinload(AttributeTemplateField.allowed_values)
                .selectinload(AttributeAllowedValue.synonyms)
            )
        )
    )
    selected = set(value_ids or [])
    changed = 0
    skipped = 0
    for product in products:
        for item in product.values:
            if item.is_extra_attribute or (selected and item.id not in selected):
                continue
            target = None
            if action == "accept_confident" and item.proposed_value and item.confidence >= threshold:
                target = item.proposed_value
            elif action == "accept_primary" and item.proposed_value and item.source == "primary_donor":
                target = item.proposed_value
            elif action == "accept_exact" and item.proposed_value and item.source_details.get("match_type") == "exact":
                target = item.proposed_value
            elif action == "keep_current" and item.current_value not in {"", "-"}:
                target = item.current_value
            elif action == "dash":
                target = "-"
            if target is None:
                skipped += 1
                continue
            try:
                update_product_value(db, product, item.id, target, refresh=False)
                changed += 1
            except ValueError:
                skipped += 1
    _refresh_batch_summary(db, batch)
    db.add(
        AttributeProcessingLog(
            batch_id=batch.id,
            action="bulk_update",
            details={"bulk_action": action, "changed": changed, "skipped": skipped},
        )
    )
    db.flush()
    return {"changed": changed, "skipped": skipped}


def public_donor(donor: AttributeDonor) -> Dict[str, object]:
    return {
        "id": donor.id,
        "name": output_text(donor.name),
        "domain": donor.domain,
        "base_url": donor.base_url,
        "selectors": donor.selectors or {},
        "is_active": bool(donor.is_active),
        "mapping_rules": [
            {
                "id": rule.id,
                "template_id": rule.template_id,
                "template_field_id": rule.template_field_id,
                "donor_attribute_name": output_text(rule.donor_attribute_name),
                "confidence": rule.confidence,
                "is_active": bool(rule.is_active),
            }
            for rule in donor.mapping_rules or []
        ],
        "updated_at": db_datetime_iso(donor.updated_at),
    }


def list_attribute_donors(db) -> List[Dict[str, object]]:
    return [
        public_donor(donor)
        for donor in db.scalars(
            select(AttributeDonor)
            .options(selectinload(AttributeDonor.mapping_rules))
            .order_by(AttributeDonor.name)
        )
    ]


def save_attribute_donor(db, payload: Dict[str, object], donor_id: object = None) -> AttributeDonor:
    donor = db.get(AttributeDonor, int(donor_id)) if donor_id not in (None, "") else None
    name = clean_text(payload.get("name"))[:255]
    base_url = clean_text(payload.get("base_url"))
    domain = clean_text(payload.get("domain"))
    if base_url:
        parsed = urlparse(base_url if "://" in base_url else f"https://{base_url}")
        domain = domain or str(parsed.hostname or "")
        base_url = f"{parsed.scheme or 'https'}://{parsed.netloc or domain}"
    domain = domain.casefold().removeprefix("www.")[:255]
    if not name or not domain:
        raise ValueError("Укажите название и домен донора")
    duplicate = db.scalar(select(AttributeDonor).where(AttributeDonor.domain == domain))
    if duplicate is not None and (donor is None or duplicate.id != donor.id):
        raise ValueError("Донор с таким доменом уже существует")
    if donor is None:
        donor = AttributeDonor(name=name, domain=domain)
        db.add(donor)
    donor.name = name
    donor.domain = domain
    donor.base_url = base_url
    donor.selectors = dict(payload.get("selectors") or {})
    donor.is_active = _parse_bool(payload.get("is_active"), True)
    db.flush()
    return donor


def _donor_for_url(db, url: str, donor_id: object = None) -> Optional[AttributeDonor]:
    if donor_id not in (None, ""):
        try:
            return db.get(AttributeDonor, int(donor_id))
        except (TypeError, ValueError):
            return None
    domain = str(urlparse(url).hostname or "").casefold().removeprefix("www.")
    return db.scalar(select(AttributeDonor).where(AttributeDonor.domain == domain))


def save_mapping_rule(
    db,
    *,
    donor: AttributeDonor,
    template: AttributeTemplate,
    donor_attribute_name: str,
    field: AttributeTemplateField,
) -> AttributeMappingRule:
    normalized = normalized_lookup_value(donor_attribute_name)
    if not normalized:
        raise ValueError("Укажите название атрибута на сайте донора")
    rule = db.scalar(
        select(AttributeMappingRule).where(
            AttributeMappingRule.donor_id == donor.id,
            AttributeMappingRule.template_id == template.id,
            AttributeMappingRule.normalized_donor_name == normalized,
        )
    )
    if rule is None:
        rule = AttributeMappingRule(
            donor=donor,
            template=template,
            donor_attribute_name=clean_text(donor_attribute_name),
            normalized_donor_name=normalized,
            template_field=field,
            confidence=100,
        )
        db.add(rule)
    else:
        rule.template_field = field
        rule.donor_attribute_name = clean_text(donor_attribute_name)
        rule.is_active = True
    db.flush()
    return rule


def _mapped_field(
    db,
    donor: Optional[AttributeDonor],
    template: AttributeTemplate,
    donor_name: str,
) -> Tuple[Optional[AttributeTemplateField], int, str]:
    normalized = normalized_lookup_value(donor_name)
    if donor:
        rule = db.scalar(
            select(AttributeMappingRule)
            .where(
                AttributeMappingRule.donor_id == donor.id,
                AttributeMappingRule.template_id == template.id,
                AttributeMappingRule.normalized_donor_name == normalized,
                AttributeMappingRule.is_active.is_(True),
            )
            .options(joinedload(AttributeMappingRule.template_field))
        )
        if rule:
            return rule.template_field, rule.confidence, "saved_rule"
    best = None
    best_ratio = 0.0
    for field in template.fields or []:
        ratio = SequenceMatcher(None, normalized, normalized_lookup_value(field.name)).ratio()
        if ratio > best_ratio:
            best, best_ratio = field, ratio
    if best is not None and best_ratio >= 0.74:
        return best, int(best_ratio * 90), "name_similarity"
    return None, 0, "unmapped"


def parse_donor_for_product(
    db,
    product: AttributeProduct,
    *,
    url: str,
    donor_id: object = None,
    priority: int = 0,
) -> AttributeDonorProductSource:
    initial_url = clean_text(url)
    donor = _donor_for_url(db, initial_url, donor_id)
    final_url, html, parsed = load_product_page(
        initial_url,
        donor.selectors if donor else None,
        require_identity=False,
    )
    donor = donor or _donor_for_url(db, final_url, donor_id)
    source = AttributeDonorProductSource(
        product=product,
        donor=donor,
        url=final_url,
        priority=max(0, int(priority)),
        status="parsed",
        parsed_data=parsed,
    )
    db.add(source)
    db.flush()
    raw_dir = assistant_subdir("donor-html")
    raw_name = f"product_{product.id}_source_{source.id}.html"
    (raw_dir / raw_name).write_text(html, encoding="utf-8")
    source.raw_html_path = raw_name
    template = load_template(db, product.batch.template_id)
    if template is None:
        raise ValueError("Шаблон обработки удалён")
    values_by_field = {
        item.template_field_id: item for item in product.values if item.template_field_id is not None
    }
    for donor_attribute in parsed["attributes"]:
        field, mapping_confidence, mapping_type = _mapped_field(
            db,
            donor,
            template,
            donor_attribute["name"],
        )
        if field is None or field.id not in values_by_field:
            continue
        item = values_by_field[field.id]
        canonical, value_confidence, match_type, closest = _match_allowed_value(
            field,
            donor_attribute["value"],
            _effective_allowed_values(db, field),
        )
        candidate_value = canonical or closest or clean_text(donor_attribute["value"])
        confidence = min(
            98,
            int((90 if priority == 0 else 80) * (mapping_confidence / 100) * (max(value_confidence, 60) / 100)),
        )
        details = dict(item.source_details or {})
        candidates = list(details.get("candidates") or [])
        candidates.append(
            {
                "value": candidate_value,
                "raw_value": donor_attribute["value"],
                "source": "primary_donor" if priority == 0 else "additional_donor",
                "source_id": source.id,
                "url": final_url,
                "confidence": confidence,
                "mapping_type": mapping_type,
                "match_type": match_type,
            }
        )
        details["candidates"] = candidates
        details["match_type"] = match_type
        item.source_details = details
        canonical_candidates = {
            normalized_lookup_value(candidate["value"], field.value_type, field.separator): candidate
            for candidate in candidates
            if candidate.get("value")
        }
        if item.current_value not in {"", "-"}:
            current_normalized = normalized_lookup_value(item.current_value, field.value_type, field.separator)
            different = any(key != current_normalized for key in canonical_candidates)
            if different:
                item.status = "conflict"
                item.reason = "Донор противоречит текущему значению; текущее значение сохранено"
            continue
        if len(canonical_candidates) > 1:
            item.status = "conflict"
            item.proposed_value = ""
            item.reason = "Доноры предложили разные значения"
            item.source = "donors"
            item.confidence = max(candidate["confidence"] for candidate in candidates)
        elif canonical_candidates:
            candidate = next(iter(canonical_candidates.values()))
            item.proposed_value = str(candidate["value"])
            item.source = str(candidate["source"])
            item.confidence = min(98, int(candidate["confidence"]) + (5 if len(candidates) > 1 else 0))
            item.status = "proposed"
            item.reason = "Предложено по данным донора"
            if _should_auto_accept(product.batch.processing_mode, item.confidence, str(candidate["match_type"])):
                item.final_value = item.proposed_value
                item.status = "accepted"
    db.add(
        AttributeProcessingLog(
            batch_id=product.batch_id,
            product_id=product.id,
            action="donor_parsed",
            details={"source_id": source.id, "url": final_url, "attributes": len(parsed["attributes"])},
        )
    )
    _refresh_batch_summary(db, product.batch)
    db.flush()
    return source


def batch_report(db, batch: AttributeBatch) -> Dict[str, object]:
    products = list(
        db.scalars(
            select(AttributeProduct)
            .where(AttributeProduct.batch_id == batch.id)
            .options(selectinload(AttributeProduct.values))
            .order_by(AttributeProduct.sort_order)
        )
    )
    rows = []
    for product in products:
        for value in product.values:
            rows.append(
                {
                    "product_id": product.id,
                    "model": product.model,
                    "name": product.name,
                    "group_name": value.group_name,
                    "attribute_name": value.attribute_name,
                    "current_value": value.current_value,
                    "proposed_value": value.proposed_value,
                    "final_value": value.final_value,
                    "source": value.source,
                    "confidence": value.confidence,
                    "status": value.status,
                    "reason": value.reason,
                }
            )
    sources = Counter(str(row["source"] or "not_found") for row in rows)
    statuses = Counter(str(row["status"] or "unknown") for row in rows)
    return {
        "batch": batch_summary(batch),
        "summary": _summary_from_products(products),
        "source_summary": dict(sources),
        "status_summary": dict(statuses),
        "rows": rows,
        "export_warning": (
            "Будет сформирован CSV для обновления товаров по полю _MODEL_. "
            "Файл содержит полный стек атрибутов; атрибуты вне шаблона сохраняются."
        ),
    }


def export_batch_report_csv(db, batch: AttributeBatch) -> Path:
    report = batch_report(db, batch)
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n")
    writer.writerow(
        [
            "Модель",
            "Товар",
            "Группа",
            "Атрибут",
            "Текущее значение",
            "Предложение",
            "Итог",
            "Источник",
            "Уверенность",
            "Статус",
            "Причина",
        ]
    )
    for row in report["rows"]:
        writer.writerow(
            [
                row["model"],
                row["name"],
                row["group_name"],
                row["attribute_name"],
                row["current_value"],
                row["proposed_value"],
                row["final_value"],
                row["source"],
                row["confidence"],
                row["status"],
                row["reason"],
            ]
        )
    report_dir = assistant_subdir("reports")
    timestamp = datetime.now(MSK_TZ).strftime("%Y%m%d_%H%M%S")
    filename = f"Отчёт_{safe_filename(Path(batch.source_filename).stem)}_{timestamp}.csv"
    path = report_dir / filename
    path.write_bytes(buffer.getvalue().encode("cp1251", errors="replace"))
    if batch.report_filename:
        previous = report_dir / Path(batch.report_filename).name
        if previous.is_file():
            previous.unlink(missing_ok=True)
    batch.report_filename = filename
    db.flush()
    return path


def export_batch_csv(db, batch: AttributeBatch, *, only_ready: bool = False) -> Path:
    products = list(
        db.scalars(
            select(AttributeProduct)
            .where(AttributeProduct.batch_id == batch.id)
            .options(selectinload(AttributeProduct.values))
            .order_by(AttributeProduct.sort_order, AttributeProduct.id)
        )
    )
    if only_ready:
        products = [product for product in products if product.status == "ready"]
    if not products:
        raise ValueError("В обработке нет подходящих товаров для экспорта")
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, delimiter=";", lineterminator="\r\n", quoting=csv.QUOTE_MINIMAL)
    writer.writerow(["_MODEL_", "_ATTRIBUTES_"])
    for product in products:
        lines = [
            f"{item.group_name}|{item.attribute_name}|{item.final_value or '-'}"
            for item in sorted(product.values, key=lambda value: (value.sort_order, value.id))
        ]
        writer.writerow([product.model, "\n".join(lines)])
    try:
        encoded = buffer.getvalue().encode("cp1251")
    except UnicodeEncodeError as error:
        raise ValueError(
            "Итоговый файл содержит символы, которые нельзя записать в CP1251. Исправьте значения и повторите экспорт."
        ) from error
    export_dir = assistant_subdir("exports")
    if batch.export_filename:
        previous = export_dir / Path(batch.export_filename).name
        if previous.is_file():
            previous.unlink(missing_ok=True)
    timestamp = datetime.now(MSK_TZ).strftime("%Y%m%d_%H%M%S")
    filename = f"Атрибуты_{safe_filename(Path(batch.source_filename).stem or f'batch_{batch.id}')}_{timestamp}.csv"
    path = export_dir / filename
    path.write_bytes(encoded)
    batch.export_filename = filename
    batch.status = "exported"
    db.add(
        AttributeProcessingLog(
            batch_id=batch.id,
            action="export_created",
            details={"filename": filename, "products_count": len(products), "only_ready": only_ready},
        )
    )
    db.flush()
    return path


def _safe_stored_file(subdir: str, filename: str) -> Optional[Path]:
    name = Path(str(filename or "")).name
    if not name:
        return None
    root = assistant_subdir(subdir).resolve()
    path = (root / name).resolve()
    return path if root in path.parents and path.is_file() else None


def resolve_batch_export(batch: AttributeBatch) -> Optional[Path]:
    return _safe_stored_file("exports", batch.export_filename)


def resolve_batch_report(batch: AttributeBatch) -> Optional[Path]:
    return _safe_stored_file("reports", batch.report_filename)


def delete_batch_files(batch: AttributeBatch) -> None:
    candidates = [
        _safe_stored_file("batches", batch.stored_filename),
        _safe_stored_file("exports", batch.export_filename),
        _safe_stored_file("reports", batch.report_filename),
    ]
    for path in candidates:
        if path:
            path.unlink(missing_ok=True)
    for source in batch.products or []:
        for donor_source in source.donor_sources or []:
            raw = _safe_stored_file("donor-html", donor_source.raw_html_path)
            if raw:
                raw.unlink(missing_ok=True)


def product_logs(db, product_id: int) -> List[Dict[str, object]]:
    logs = list(
        db.scalars(
            select(AttributeProcessingLog)
            .where(AttributeProcessingLog.product_id == product_id)
            .order_by(AttributeProcessingLog.id.desc())
            .limit(100)
        )
    )
    return [
        {
            "id": log.id,
            "action": log.action,
            "details": log.details or {},
            "created_at": db_datetime_iso(log.created_at),
        }
        for log in logs
    ]


def rollback_value_change(db, product: AttributeProduct, log_id: object) -> AttributeProductValue:
    try:
        parsed_id = int(log_id)
    except (TypeError, ValueError) as error:
        raise ValueError("Некорректная запись истории") from error
    log = db.scalar(
        select(AttributeProcessingLog).where(
            AttributeProcessingLog.id == parsed_id,
            AttributeProcessingLog.product_id == product.id,
            AttributeProcessingLog.action == "value_updated",
        )
    )
    if log is None:
        raise LookupError("Изменение для отката не найдено")
    details = log.details or {}
    before = details.get("before") or {}
    value_id = details.get("value_id")
    item = next((value for value in product.values if value.id == value_id), None)
    if item is None:
        raise LookupError("Атрибут из истории больше не существует")
    current = {
        "final_value": item.final_value,
        "status": item.status,
        "source": item.source,
        "confidence": item.confidence,
        "reason": item.reason,
    }
    for key in current:
        if key in before:
            setattr(item, key, before[key])
    db.add(
        AttributeProcessingLog(
            batch_id=product.batch_id,
            product_id=product.id,
            action="value_rolled_back",
            details={"source_log_id": log.id, "value_id": item.id, "before_rollback": current},
        )
    )
    _refresh_batch_summary(db, product.batch)
    db.flush()
    return item


def workspace_payload(db) -> Dict[str, object]:
    templates = compact_template_summaries(db)
    batches = list_batches(db)
    products_count = db.scalar(select(func.count(AttributeProduct.id))) or 0
    filled_count = db.scalar(
        select(func.count(AttributeProductValue.id)).where(
            AttributeProductValue.status.in_(("filled", "accepted"))
        )
    ) or 0
    needs_review_count = db.scalar(
        select(func.count(AttributeProductValue.id)).where(AttributeProductValue.status.in_(REVIEW_STATUSES))
    ) or 0
    conflicts_count = db.scalar(
        select(func.count(AttributeProductValue.id)).where(AttributeProductValue.status == "conflict")
    ) or 0
    ready_products = db.scalar(
        select(func.count(AttributeProduct.id)).where(AttributeProduct.status == "ready")
    ) or 0
    return {
        "templates": templates,
        "batches": [batch_summary(batch) for batch in batches],
        "donors": list_attribute_donors(db),
        "metrics": {
            "templates": len(templates),
            "batches": int(db.scalar(select(func.count(AttributeBatch.id))) or 0),
            "products": int(products_count),
            "filled": int(filled_count),
            "needs_review": int(needs_review_count),
            "conflicts": int(conflicts_count),
            "ready_products": int(ready_products),
        },
    }
