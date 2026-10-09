"""ChatGPT analysis for one Attribute Assistant product.

The model may only propose values that already exist in the selected template.
When the application can download the product page itself, the page text is
embedded into the prompt and later used to validate returned evidence.
"""

from __future__ import annotations

import json
import re
import time
from pathlib import Path
from typing import Any
from difflib import SequenceMatcher

from bs4 import BeautifulSoup
from sqlalchemy.orm import Session

from config import ATTRIBUTE_ASSISTANT_DIR
from models import AttributeProduct, AttributeProductSource, Donor
from services.attribute_programs import is_program_list, match_programs, program_dictionary
from services.attribute_assistant import (
    _is_presence_marker,
    _candidate_value_key,
    _has_confirmed_decision,
    apply_candidate,
    record_unknown_value,
    _allowed_match,
    _mapping_score,
    _name_tokens,
    _recalculate_candidate_state,
    _dimension_component_axis,
    _assemble_dimension_value,
    clean_text,
    fetch_donor_product_html,
    fetch_public_html,
    normalize_key,
    dictionary_value_key,
    value_match_key,
    _canonical_matching_value,
    exact_value_key,
    parse_product_html,
    parse_product_html_for_donor,
    product_template,
    refresh_batch_summary,
    refresh_product_status,
    resolve_donor_url,
    snapshot_product,
)


ATTRIBUTE_AI_PROMPT_VERSION = "attribute-assistant-chatgpt-v17-compact-dynamic-template"
ATTRIBUTE_AI_MAX_ALLOWED_PER_FIELD = 30
ATTRIBUTE_AI_MAX_PAGE_CHARS = 60_000
ATTRIBUTE_AI_MAX_RESPONSE_CHARS = 2_000_000
ATTRIBUTE_AI_MAX_SOURCE_HINTS_PER_FIELD = 3
ATTRIBUTE_AI_MIN_SOURCE_HINT_SCORE = 0.55

UNIVERSAL_ATTRIBUTE_PROMPT = (
    Path(__file__).with_name("prompts") / "attribute_analysis.md"
).read_text(encoding="utf-8").strip()


def _compact_visible_text(html: str) -> str:
    soup = BeautifulSoup(html or "", "html.parser")
    for node in soup.select("script, style, svg, canvas, noscript, form, nav, footer, iframe"):
        node.decompose()
    # Repeated long paragraphs are often duplicated feature popups. Keep short
    # lines, especially repeated measurements belonging to different axes.
    seen_paragraphs: set[str] = set()
    lines: list[str] = []
    previous = ""
    for raw_line in soup.get_text("\n", strip=True).splitlines():
        line = clean_text(raw_line)
        if not line or line == previous:
            continue
        previous = line
        if len(line) >= 120:
            if line in seen_paragraphs:
                continue
            seen_paragraphs.add(line)
        lines.append(line)
    return "\n".join(lines)


def _page_evidence(visible_text: str, parsed: dict[str, Any]) -> str:
    attributes: list[str] = []
    for item in parsed.get("attributes") or []:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("name"))
        value = exact_value_key(item.get("value"))
        if name and value:
            attributes.append(f"{name}: {value}")
    identity = [
        clean_text(parsed.get("name")),
        clean_text(parsed.get("model")),
        clean_text(parsed.get("brand")),
        clean_text(parsed.get("category")),
    ]
    return "\n".join(
        [
            "ДАННЫЕ, НАЙДЕННЫЕ ПАРСЕРОМ:",
            *[item for item in identity if item],
            *attributes,
            "",
            "ВИДИМЫЙ ТЕКСТ СТРАНИЦЫ:",
            visible_text,
        ]
    )


def _parsed_attributes(parsed: dict[str, Any]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for item in parsed.get("attributes") or []:
        if not isinstance(item, dict):
            continue
        name = clean_text(item.get("name"))
        value = exact_value_key(item.get("value"))
        if name and value:
            result.append({"name": name, "value": value})
    return result


def _field_source_hints(field, target, parsed: dict[str, Any]) -> list[dict[str, str]]:
    hints: list[dict[str, str]] = []
    ranked_page_hints: list[tuple[float, dict[str, str]]] = []
    for item in parsed.get("attributes") or []:
        if not isinstance(item, dict):
            continue
        source_name = clean_text(item.get("name"))
        value = exact_value_key(item.get("value"))
        if not source_name or not value:
            continue
        score = _mapping_score(source_name, field)
        if score >= ATTRIBUTE_AI_MIN_SOURCE_HINT_SCORE:
            ranked_page_hints.append((score, {"name": source_name, "value": value}))
    ranked_page_hints.sort(key=lambda item: item[0], reverse=True)
    hints.extend(
        item
        for _score, item in ranked_page_hints[:ATTRIBUTE_AI_MAX_SOURCE_HINTS_PER_FIELD]
    )
    details = dict(target.source_details or {}) if target else {}
    for item in [*(details.get("candidates") or []), *(details.get("unknown_values") or [])]:
        if not isinstance(item, dict):
            continue
        value = exact_value_key(item.get("raw_value") or item.get("value"))
        if value:
            hints.append({
                "name": clean_text(item.get("source_name")) or field.name,
                "value": value,
            })
    if target:
        for value in (target.final_value, target.current_value, target.proposed_value):
            cleaned = clean_text(value)
            if cleaned:
                hints.append({"name": field.name, "value": cleaned})
    unique: dict[tuple[str, str], dict[str, str]] = {}
    for item in hints:
        unique[(normalize_key(item["name"]), dictionary_value_key(item["value"], field.value_type))] = item
    return list(unique.values())


def _shortlist_allowed_values(
    field,
    hints: list[dict[str, str]],
    evidence: str,
    *,
    limit: int = ATTRIBUTE_AI_MAX_ALLOWED_PER_FIELD,
    evidence_tokens: set[str] | None = None,
) -> list[str]:
    active = [item for item in field.allowed_values if item.is_active]
    limit = max(1, int(limit))
    if len(active) <= limit:
        return [item.value for item in active]

    selected: list[str] = []
    for hint in hints:
        canonical, _confidence, _reason, suggestions = _allowed_match(
            field, hint["value"], hint["name"]
        )
        for value in [canonical, *suggestions]:
            if value and value not in selected:
                selected.append(value)

    hint_keys = list(dict.fromkeys(value_match_key(item["value"]) for item in hints if clean_text(item["value"])))
    if evidence_tokens is None:
        evidence_tokens = set(normalize_key(evidence).split())
    ranked: list[tuple[float, int, str]] = []
    for item in active:
        if item.value in selected:
            continue
        key = value_match_key(item.value)
        tokens = set(key.split())
        score = 0.0
        if any(key == hint_key or key in hint_key or hint_key in key for hint_key in hint_keys):
            score = max(score, 0.94)
        if tokens and tokens <= evidence_tokens:
            score = max(score, 0.76)
        for hint_key in hint_keys:
            matcher = SequenceMatcher(None, hint_key, key)
            # These are upper bounds, so skipping cannot drop a candidate
            # that would enter the previous ranking or beat its existing score.
            threshold = max(score, 0.48)
            if matcher.real_quick_ratio() < threshold or matcher.quick_ratio() < threshold:
                continue
            score = max(score, matcher.ratio())
        if score >= 0.48:
            ranked.append((score, -item.sort_order, item.value))
    ranked.sort(reverse=True)
    for _score, _order, value in ranked:
        if value not in selected:
            selected.append(value)
        if len(selected) >= limit:
            break
    return selected[:limit]


def _template_context(
    product: AttributeProduct,
    parsed: dict[str, Any],
    evidence: str,
) -> list[dict[str, Any]]:
    values_by_field = {
        item.template_field_id: item
        for item in product.values
        if item.template_field_id is not None
    }
    result: list[dict[str, Any]] = []
    template = product_template(product)
    if template is None:
        return result
    facts = parsed_attribute_facts(parsed)
    source_ids = {(normalize_key(fact["name"]), dictionary_value_key(fact["value"])): fact["source_id"] for fact in facts}
    evidence_tokens = set(normalize_key(evidence).split())
    for field in template.fields:
        target = values_by_field.get(field.id)
        current = exact_value_key(target.current_value if target else "")
        proposed = exact_value_key(target.proposed_value if target else "")
        final = exact_value_key(target.final_value if target else "")
        hints = _field_source_hints(field, target, parsed)
        item: dict[str, Any] = {"id": field.id}
        if final or current or proposed:
            item["current_value"] = final or current or proposed
        ids = list(dict.fromkeys(
            source_ids[key] for hint in hints[:8]
            if (key := (normalize_key(hint["name"]), dictionary_value_key(hint["value"]))) in source_ids
        ))
        if ids:
            item["source_ids"] = ids
        if is_program_list(field):
            item.update(program_dictionary(field, evidence))
        else:
            allowed = _shortlist_allowed_values(field, hints, evidence, evidence_tokens=evidence_tokens)
            if allowed:
                item["allowed_values"] = allowed
                total = sum(value.is_active for value in field.allowed_values)
                if total > len(allowed):
                    item["allowed_values_total"] = total
        if len(item) > 1:
            result.append(item)
    return result


def parsed_attribute_facts(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    """Return stable IDs used by ChatGPT to reference parser facts compactly."""

    return [
        {"source_id": index, **item}
        for index, item in enumerate(_parsed_attributes(parsed), start=1)
    ]


def _template_field_catalog(product: AttributeProduct) -> list[dict[str, Any]]:
    template = product_template(product)
    if template is None:
        return []
    return [
        {
            "id": field.id,
            "group": field.group_name,
            "name": field.name,
            "value_type": field.value_type,
            **({"synonyms": list(field.synonyms)} if field.synonyms else {}),
        }
        for field in template.fields
    ]


def build_product_prompt(
    product: AttributeProduct,
    *,
    source_url: str,
    html: str = "",
    parsed: dict[str, Any] | None = None,
) -> tuple[str, str]:
    parsed = parsed or {}
    visible = _compact_visible_text(html)
    truncated = len(visible) > ATTRIBUTE_AI_MAX_PAGE_CHARS
    visible = visible[:ATTRIBUTE_AI_MAX_PAGE_CHARS]
    evidence = _page_evidence(visible, parsed) if html or parsed.get("attributes") else ""
    template = product_template(product)
    context = {
        # The shared template prefix precedes per-product facts; no mutable
        # dictionary data or analysis results are cached in the application.
        "template_field_catalog": _template_field_catalog(product),
        "product": {
            "name": product.name,
            "model": product.model,
            "brand": product.brand,
            "category": product.category_name or (template.category.full_path if template else ""),
        },
        "official_product_url": source_url,
        "parser_attributes": parsed_attribute_facts(parsed),
        "template_fields": _template_context(product, parsed, evidence),
        "page_evidence": visible,
        **({"page_evidence_truncated": True} if truncated else {}),
    }
    prompt = UNIVERSAL_ATTRIBUTE_PROMPT + "\n\nКОНТЕКСТ ДЛЯ АНАЛИЗА:\n" + json.dumps(
        context,
        ensure_ascii=False,
        separators=(",", ":"),
    )
    return prompt, evidence


def _parse_json_response(value: object) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    text = clean_text(value)
    if not text:
        raise ValueError("ChatGPT вернул пустой ответ")
    if len(text) > ATTRIBUTE_AI_MAX_RESPONSE_CHARS:
        raise ValueError("Ответ ChatGPT слишком большой")
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].strip().startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        start = text.find("{")
        if start < 0:
            raise ValueError("Ответ ChatGPT не содержит JSON-объект") from None
        try:
            parsed, _end = json.JSONDecoder().raw_decode(text[start:])
        except json.JSONDecodeError as error:
            raise ValueError(
                f"Не удалось разобрать JSON-ответ ChatGPT: строка {error.lineno}, столбец {error.colno}"
            ) from error
    if not isinstance(parsed, dict):
        raise ValueError("Ответ ChatGPT должен быть JSON-объектом")
    return parsed


def _evidence_present(quote: str, evidence: str, *, exact: bool = False) -> bool:
    if exact:
        key = exact_value_key(quote)
        return bool(key) and re.search(
            r"(?<![\w+./%−-])" + re.escape(key) + r"(?![\w+./%−-])", exact_value_key(evidence),
        ) is not None
    return bool(normalize_key(quote)) and normalize_key(quote) in normalize_key(evidence)


def _canonical_allowed(field, proposed: object) -> str:
    if is_program_list(field):
        return match_programs(field, proposed)[0]
    return _canonical_matching_value(field.allowed_values, proposed)


def _current_value_supported_by_source_name(field, target, source_name: str) -> str:
    """Confirm an existing semantic value when a presence row names its options."""

    current = exact_value_key(target.final_value or target.current_value or target.proposed_value)
    if not current or _is_presence_marker(field, current):
        return ""
    canonical, _confidence, _reason, _alternatives = _allowed_match(
        field,
        current,
        field.name,
    )
    if not canonical:
        return ""
    source_tokens = _name_tokens(source_name) - _name_tokens(field.name)
    if not source_tokens:
        return ""
    separator = clean_text(field.separator) or "/"
    parts = (
        [clean_text(part) for part in canonical.split(separator) if clean_text(part)]
        if field.is_composite
        else [canonical]
    )
    for part in parts:
        variants = [part]
        part_key = value_match_key(part)
        allowed = next(
            (
                item
                for item in field.allowed_values
                if item.is_active and value_match_key(item.value) == part_key
            ),
            None,
        )
        if allowed is not None:
            variants.extend(synonym.synonym for synonym in allowed.synonyms)
        supported = False
        for variant in variants:
            variant_tokens = _name_tokens(variant)
            if not variant_tokens:
                continue
            overlap = source_tokens & variant_tokens
            if overlap and len(overlap) / len(variant_tokens) >= 0.5:
                supported = True
                break
        if not supported:
            return ""
    return canonical


def _clear_replaceable_chatgpt_evidence(product: AttributeProduct) -> None:
    """Discard stale, unapproved ChatGPT evidence before applying a fresh result."""

    for target in product.values:
        if _has_confirmed_decision(target):
            continue
        details = dict(target.source_details or {})
        previous = list(details.get("candidates") or [])
        candidates = [
            item
            for item in previous
            if not (isinstance(item, dict) and clean_text(item.get("source")) == "ChatGPT")
        ]
        previous_unknown = list(details.get("unknown_values") or [])
        unknown = [item for item in previous_unknown
                   if not (isinstance(item, dict) and clean_text(item.get("source")) == "ChatGPT")]
        if len(candidates) == len(previous) and len(unknown) == len(previous_unknown) and "chatgpt" not in details:
            continue
        details["unknown_values"] = unknown
        details["candidates"] = candidates
        details.pop("chatgpt", None)
        target.source_details = details
        if clean_text(target.source) == "ChatGPT" and not target.current_value:
            target.proposed_value = ""
            target.final_value = ""
            target.source = ""
        _recalculate_candidate_state(product, target)


def validate_analysis(
    product: AttributeProduct,
    response: object,
    *,
    page_evidence: str = "",
    source_facts: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    raw = _parse_json_response(response)
    attributes = raw.get("attributes")
    if not isinstance(attributes, list):
        raise ValueError("Ответ ChatGPT должен содержать массив attributes. Повторите анализ")
    warnings = [clean_text(item) for item in raw.get("warnings") or [] if clean_text(item)]
    template = product_template(product)
    if template is None:
        raise ValueError("Для товара не выбран шаблон атрибутов")
    fields = {field.id: field for field in template.fields}
    values = {
        item.template_field_id: item
        for item in product.values
        if item.template_field_id is not None
    }
    indexed_source_facts: dict[int, dict[str, str]] = {}
    for index, fact in enumerate(source_facts or [], start=1):
        if not isinstance(fact, dict):
            continue
        source_id = fact.get("source_id", index)
        if type(source_id) is not int or source_id <= 0:
            continue
        name = clean_text(fact.get("name"))
        value = exact_value_key(fact.get("value"))
        if name and value:
            indexed_source_facts[source_id] = {"name": name, "value": value}
    indexed_fact_keys = {
        (normalize_key(fact["name"]), exact_value_key(fact["value"]))
        for fact in indexed_source_facts.values()
    }

    observed: list[dict[str, str]] = []
    seen_observed: set[tuple[str, str]] = set()
    suggestions: list[dict[str, Any]] = []
    unmatched: list[dict[str, Any]] = []
    seen_fields: set[int] = set()
    seen_source_ids: set[int] = set()
    dimension_facts: dict[int, list[dict]] = {}
    for item in attributes:
        if isinstance(item, list) and len(item) in {3, 4}:
            item = dict(zip(("source_id", "field_id", "confidence", "allowed_value"), item))
        if not isinstance(item, dict):
            warnings.append("Одна характеристика ChatGPT отклонена: некорректная запись")
            continue
        source_id = item.get("source_id")
        if source_id is not None:
            if type(source_id) is not int or source_id not in indexed_source_facts:
                warnings.append("Одна характеристика ChatGPT отклонена: неизвестный source_id")
                continue
            if source_id in seen_source_ids:
                warnings.append("Одна характеристика ChatGPT отклонена: повторный source_id")
                continue
            seen_source_ids.add(source_id)
            source_fact = indexed_source_facts[source_id]
            name = source_fact["name"]
            value = source_fact["value"]
            quote = f"{name}: {value}"
        else:
            name = clean_text(item.get("name"))
            value = exact_value_key(item.get("value"))
            quote = exact_value_key(item.get("evidence"))
        key = (normalize_key(name), exact_value_key(value))
        if not name or not value:
            warnings.append("Одна характеристика ChatGPT отклонена: нет названия или значения")
            continue
        if source_id is None and key in indexed_fact_keys:
            warnings.append(f"Характеристика «{name}» отклонена: используйте source_id")
            continue
        if source_id is None and not quote:
            warnings.append(f"Характеристика «{name}» отклонена: нет цитаты")
            continue
        if source_id is None and page_evidence and not _evidence_present(quote, page_evidence):
            warnings.append(f"Характеристика «{name}» отклонена: цитата не найдена на странице")
            continue
        if key not in seen_observed:
            seen_observed.add(key)
            observed.append({"name": name, "value": value, "evidence": quote})

        field_id = item.get("field_id")
        if field_id is None:
            continue
        if type(field_id) is not int or field_id <= 0:
            warnings.append(f"Сопоставление «{name}» отклонено: некорректный ID поля")
            continue
        try:
            confidence = max(50, min(85, int(item.get("confidence") or 50)))
        except (TypeError, ValueError):
            warnings.append(f"Сопоставление «{name}» отклонено: некорректная уверенность")
            continue
        field = fields.get(field_id)
        target = values.get(field_id)
        if field is None or target is None:
            warnings.append(f"Сопоставление «{name}» отклонено: поля нет в шаблоне товара")
            continue
        if field_id in seen_fields:
            continue
        if source_id is None and (
            (page_evidence and not _evidence_present(quote, page_evidence, exact=True))
            or not _evidence_present(value, quote, exact=True)
        ):
            warnings.append(f"Сопоставление «{name}» отклонено: цитата не подтверждает точное значение")
            continue
        if _dimension_component_axis(field, name):
            dimension_facts.setdefault(field_id, []).append({
                "name": name, "value": value, "evidence": quote, "confidence": confidence,
            })
            continue
        presence_marker = _is_presence_marker(field, value, name)
        canonical = ""
        explanation = ""
        alternatives: list[str] = []
        match_reason = "Логическое значение описывает наличие характеристики, а не значение справочника"
        if presence_marker and item.get("allowed_value"):
            allowed_value = _canonical_allowed(field, item["allowed_value"])
            if allowed_value and not _is_presence_marker(field, allowed_value):
                canonical = allowed_value
                explanation = (
                    "Название характеристики раскрыто ChatGPT; "
                    "значение проверено по справочнику"
                )
        if presence_marker and not canonical:
            canonical = _current_value_supported_by_source_name(field, target, name)
            if canonical:
                explanation = (
                    "Исходное значение подтверждено названием характеристики; "
                    "маркер наличия не использован как итог"
                )
        if not presence_marker:
            canonical, _match_confidence, match_reason, alternatives = _allowed_match(
                field,
                value,
                name,
            )
            explanation = f"Семантически сопоставлено ChatGPT; {match_reason}"
        if not canonical:
            model_proposal = _canonical_allowed(field, item.get("allowed_value"))
            if model_proposal and not presence_marker:
                alternatives = list(dict.fromkeys([model_proposal, *alternatives]))[:3]
            unmatched.append({
                "template_field_id": field_id, "source_name": name, "value": value,
                "suggestions": alternatives, "reason": match_reason, "evidence": quote,
            })
            warnings.append(
                f"Сопоставление «{name}» → «{field.name}» проверено, "
                "но значения нет в справочнике"
            )
            continue
        seen_fields.add(field_id)
        suggestions.append(
            {
                "template_field_id": field_id,
                "group_name": field.group_name,
                "attribute_name": field.name,
                "source_name": name,
                "proposed_value": canonical,
                "raw_value": value,
                "confidence": confidence,
                "explanation": explanation,
                "evidence": quote,
            }
        )

    missing_ids = indexed_source_facts.keys() - seen_source_ids
    if missing_ids:
        raise ValueError(
            f"ChatGPT пропустил {len(missing_ids)} из {len(indexed_source_facts)} исходных характеристик. "
            "Неполный анализ не применён; повторите анализ"
        )

    for field_id, facts in dimension_facts.items():
        if field_id in seen_fields:
            continue
        field = fields[field_id]
        combined = _assemble_dimension_value(field, facts)
        canonical, _, reason, alternatives = _allowed_match(field, combined, field.name) if combined else (
            "", 0, "Не хватает однозначных значений всех осей габаритов", []
        )
        evidence = "\n".join(fact["evidence"] for fact in facts)
        raw_value = "; ".join(f'{fact["name"]}: {fact["value"]}' for fact in facts)
        if canonical:
            suggestions.append({
                "template_field_id": field_id, "group_name": field.group_name, "attribute_name": field.name,
                "source_name": field.name, "proposed_value": canonical, "raw_value": raw_value,
                "confidence": min(fact["confidence"] for fact in facts),
                "explanation": "Габариты собраны из отдельных осей в порядке целевого поля; " + reason,
                "evidence": evidence,
            })
        else:
            unmatched.append({"template_field_id": field_id, "source_name": field.name, "value": raw_value,
                              "suggestions": alternatives, "reason": reason, "evidence": evidence})

    return {
        "observed_attributes": observed,
        "unmatched_attributes": unmatched,
        "suggestions": suggestions,
        "warnings": list(dict.fromkeys(warnings)),
        "prompt_version": ATTRIBUTE_AI_PROMPT_VERSION,
    }


def record_analysis_metrics(
    analysis: dict[str, Any],
    prompt: str | int,
    response: dict[str, Any],
    *,
    preparation_seconds: float,
    request_seconds: float,
    validation_seconds: float,
) -> None:
    """Record phase timings/sizes, without persisting prompts or product text."""
    analysis["metrics"] = {
        "preparation_ms": round(preparation_seconds * 1000),
        "request_ms": round(request_seconds * 1000),
        "validation_ms": round(validation_seconds * 1000),
        "prompt_chars": len(prompt) if isinstance(prompt, str) else prompt,
        "response_chars": len(response.get("text") or ""),
        "observed_facts": len(analysis["observed_attributes"]),
        **({"bridge": response["metrics"]} if isinstance(response.get("metrics"), dict) else {}),
    }


def apply_analysis(db: Session, product: AttributeProduct, analysis: dict[str, Any], *, source_url: str) -> int:
    _clear_replaceable_chatgpt_evidence(product)
    values = {
        item.template_field_id: item
        for item in product.values
        if item.template_field_id is not None
    }
    changed = 0
    unmatched_count = 0
    for fact in analysis.get("unmatched_attributes") or []:
        target = values.get(fact.get("template_field_id"))
        if target is None:
            continue
        record_unknown_value(
            product, target, raw_value=fact["value"], source="ChatGPT",
            source_name=fact["source_name"], source_url=source_url, role="ChatGPT",
            suggestions=fact.get("suggestions") or [], reason=fact["reason"],
        )
        unmatched_count += 1
    for suggestion in analysis.get("suggestions") or []:
        if not isinstance(suggestion, dict):
            continue
        target = values.get(suggestion.get("template_field_id"))
        if target is None:
            continue
        proposed = exact_value_key(suggestion.get("proposed_value"))
        if not proposed:
            continue
        confidence = max(50, min(85, int(suggestion.get("confidence") or 50)))
        protected_final = exact_value_key(target.final_value) if not exact_value_key(target.current_value) else ""
        protected_state = {
            "proposed_value": target.proposed_value,
            "source": target.source,
            "confidence": target.confidence,
            "status": target.status,
        }
        apply_candidate(
            product,
            target,
            value=proposed,
            confidence=confidence,
            source="ChatGPT",
            reason=clean_text(suggestion.get("explanation")) or "Предложено ChatGPT по странице товара",
            priority=90,
            source_name=clean_text(suggestion.get("source_name")) or target.attribute_name,
            source_url=source_url,
            raw_value=exact_value_key(suggestion.get("raw_value")),
        )
        if protected_final:
            target.final_value = protected_final
            target.proposed_value = protected_state["proposed_value"]
            target.source = protected_state["source"]
            target.confidence = protected_state["confidence"]
            if _candidate_value_key(target, protected_final) == _candidate_value_key(target, proposed):
                target.status = protected_state["status"] or "approved"
                target.reason = "ChatGPT подтверждает выбранное значение"
            else:
                target.status = "conflict"
                target.reason = "ChatGPT предлагает значение, отличающееся от выбранного пользователем"
        details = dict(target.source_details or {})
        details["chatgpt"] = {
            "url": source_url,
            "evidence": exact_value_key(suggestion.get("evidence")),
            "explanation": clean_text(suggestion.get("explanation")),
            "confidence": confidence,
            "prompt_version": ATTRIBUTE_AI_PROMPT_VERSION,
        }
        target.source_details = details
        changed += 1

    observed_attributes = [
        {
            "name": clean_text(item.get("name")),
            "value": exact_value_key(item.get("value")),
            "evidence": clean_text(item.get("evidence")),
        }
        for item in analysis.get("observed_attributes") or []
        if isinstance(item, dict) and clean_text(item.get("name")) and exact_value_key(item.get("value"))
    ]
    suggestions_count = len(analysis.get("suggestions") or [])
    chatgpt_source = next((source for source in product.sources if source.role == "chatgpt"), None)
    if chatgpt_source is None:
        chatgpt_source = AttributeProductSource(
            url=source_url,
            priority=90,
            role="chatgpt",
        )
        product.sources.append(chatgpt_source)
    chatgpt_source.url = source_url
    chatgpt_source.priority = 90
    chatgpt_source.role = "chatgpt"
    chatgpt_source.status = "parsed"
    chatgpt_source.parsed_data = {
        "message": f"ChatGPT: найдено {len(observed_attributes)}, применено {changed}",
        "attributes": observed_attributes,
        "processing_stats": {
            "mapped": changed,
            "unknown": unmatched_count,
            "ambiguous": max(0, suggestions_count - changed),
            "already_filled": 0,
        },
        "prompt_version": analysis.get("prompt_version") or ATTRIBUTE_AI_PROMPT_VERSION,
        "analysis_metrics": analysis.get("metrics") or {},
    }

    refresh_product_status(product)
    refresh_batch_summary(product.batch)
    return changed


def _upsert_source(
    product: AttributeProduct,
    donor: Donor | None,
    *,
    url: str,
    priority: int,
    role: str,
    status: str,
    message: str,
    raw_html_path: str = "",
    parsed: dict[str, Any] | None = None,
) -> AttributeProductSource:
    donor_id = donor.id if donor else None
    existing = next(
        (
            source
            for source in product.sources
            if (source.donor_id if source.donor_id is not None else (source.donor.id if source.donor else None)) == donor_id
            and clean_text(source.url) == clean_text(url)
        ),
        None,
    )
    payload = dict(parsed or {})
    payload["message"] = message
    if existing is None:
        existing = AttributeProductSource(
            donor=donor,
            url=url,
            priority=priority,
            role=role,
        )
        # Append from the persistent parent side so SQLAlchemy save-update cascade adds it to the session.
        product.sources.append(existing)
    existing.priority = priority
    existing.role = role
    existing.status = status
    existing.raw_html_path = raw_html_path
    existing.parsed_data = payload
    return existing


def prepare_product_source(
    db: Session,
    product: AttributeProduct,
    donor_ids: list[int] | None,
    *,
    url_overrides: dict[str, str] | None = None,
    fetcher: Any | None = None,
) -> tuple[str, str, dict[str, Any], str]:
    """Resolve one exact product URL and, where possible, download its page for ChatGPT."""

    selected_input = product.selected_donor_ids or [] if donor_ids is None else donor_ids
    selected = list(dict.fromkeys(int(item) for item in selected_input))
    effective_overrides = {
        str(key): clean_text(value)
        for key, value in (
            (product.donor_url_overrides or {}) if url_overrides is None else url_overrides
        ).items()
        if clean_text(value)
    }
    product.selected_donor_ids = selected
    product.donor_url_overrides = effective_overrides
    selected_order = {donor_id: index for index, donor_id in enumerate(selected)}

    def source_donor_id(source: AttributeProductSource) -> int | None:
        return source.donor_id if source.donor_id is not None else (source.donor.id if source.donor else None)

    existing: AttributeProductSource | None = None
    donor: Donor | None = None
    source_url = ""
    resolved_by = ""

    # The URL currently entered in the interface is authoritative even when an
    # older parser snapshot exists for the same donor.
    for priority, donor_id in enumerate(selected):
        manual_url = effective_overrides.get(str(donor_id), "")
        if not manual_url:
            continue
        candidate = db.get(Donor, donor_id)
        if candidate is None:
            continue
        donor = candidate
        source_url = manual_url
        resolved_by = "Ссылка задана пользователем"
        existing = next(
            (
                source
                for source in product.sources
                if source_donor_id(source) == donor_id
                and clean_text(source.url) == source_url
            ),
            None,
        )
        if existing is None:
            existing = _upsert_source(
                product,
                donor,
                url=source_url,
                priority=priority,
                role="primary" if priority == 0 else "verification",
                status="resolved",
                message=resolved_by,
            )
        else:
            existing.priority = priority
            existing.role = "primary" if priority == 0 else "verification"
            payload = dict(existing.parsed_data or {})
            payload["message"] = resolved_by
            existing.parsed_data = payload
        break

    available_sources = [
        source
        for source in product.sources
        if source.status in {"parsed", "resolved", "no_attributes"} and clean_text(source.url)
    ]
    if not source_url:
        if selected:
            available_sources = [source for source in available_sources if source_donor_id(source) in selected_order]
            existing = min(
                available_sources,
                key=lambda source: (selected_order.get(source_donor_id(source), len(selected)), source.priority),
                default=None,
            )
        else:
            role_order = {"primary": 0, "verification": 1, "own_site": 2}
            existing = min(
                available_sources,
                key=lambda source: (role_order.get(source.role, 3), source.priority),
                default=None,
            )
        donor = existing.donor if existing else None
        source_url = clean_text(existing.url if existing else "")
        resolved_by = clean_text((existing.parsed_data or {}).get("message")) if existing else ""

    if not source_url and selected:
        errors: list[str] = []
        for priority, donor_id in enumerate(selected):
            candidate = db.get(Donor, donor_id)
            if candidate is None:
                continue
            template = product_template(product)
            found, reason = resolve_donor_url(
                candidate,
                product.model,
                product_name=product.name,
                category=product.category_name or (template.category.full_path if template else ""),
            )
            if found:
                donor = candidate
                source_url = found
                resolved_by = reason
                _upsert_source(
                    product,
                    donor,
                    url=source_url,
                    priority=priority,
                    role="primary" if priority == 0 else "verification",
                    status="resolved",
                    message=resolved_by,
                )
                break
            errors.append(f"{candidate.brand.name}: {reason}")
        if not source_url and errors:
            raise ValueError("Не удалось найти ссылку на конкретный товар. " + "; ".join(errors))

    if not source_url and clean_text(product.source_url):
        source_url = clean_text(product.source_url)
        resolved_by = "Исходная ссылка товара"

    if not source_url:
        raise ValueError("Выберите донора или сначала найдите ссылку на конкретный товар")

    stored_parsed = dict(existing.parsed_data or {}) if existing else {}
    stored_html = ""
    if existing and clean_text(existing.raw_html_path):
        try:
            raw_path = Path(existing.raw_html_path)
            if raw_path.is_file():
                stored_html = raw_path.read_text(encoding="utf-8")
        except OSError:
            stored_html = ""

    # A regular parser run is the canonical page snapshot. Reuse its exact result
    # instead of downloading and parsing the page a second time for ChatGPT.
    if stored_parsed.get("attributes"):
        return source_url, stored_html, stored_parsed, resolved_by

    html = stored_html
    parsed: dict[str, Any] = stored_parsed
    try:
        downloaded_html, final_url = (
            fetch_donor_product_html(donor, source_url, fetcher=fetcher)
            if donor
            else fetch_public_html(source_url)
        )
        source_url = final_url
        downloaded_parsed = (
            parse_product_html_for_donor(downloaded_html, final_url, donor)
            if donor
            else parse_product_html(downloaded_html, final_url)
        )
        html = downloaded_html
        if downloaded_parsed.get("attributes") or not parsed.get("attributes"):
            parsed = downloaded_parsed
        raw_dir = ATTRIBUTE_ASSISTANT_DIR / "raw" / str(product.batch_id) / str(product.id)
        raw_dir.mkdir(parents=True, exist_ok=True)
        donor_part = donor.id if donor else "own"
        raw_path = raw_dir / f"chatgpt_{donor_part}.html"
        raw_path.write_text(html, encoding="utf-8")
        attribute_count = len(parsed.get("attributes") or [])
        source_status = "parsed" if attribute_count else "no_attributes"
        source_message = f"{resolved_by or 'Страница товара загружена'}; извлечено характеристик: {attribute_count}"
        _upsert_source(
            product,
            donor,
            url=source_url,
            priority=existing.priority if existing else 0,
            role=existing.role if existing else ("primary" if donor else "own_site"),
            status=source_status,
            message=source_message,
            raw_html_path=str(raw_path),
            parsed=parsed,
        )
    except Exception as error:
        # The bridge can still open the exact public URL itself (useful for anti-bot pages).
        if donor and not parsed.get("attributes"):
            _upsert_source(
                product,
                donor,
                url=source_url,
                priority=existing.priority if existing else 0,
                role=existing.role if existing else "primary",
                status="resolved",
                message=f"{resolved_by or 'Ссылка найдена'}; локальная загрузка: {clean_text(error)}",
            )
    db.flush()
    return source_url, html, parsed, resolved_by


def analyze_product_with_chatgpt(
    db: Session,
    product: AttributeProduct,
    donor_ids: list[int] | None,
    *,
    url_overrides: dict[str, str] | None = None,
    fetcher: Any | None = None,
) -> dict[str, Any]:
    """Analyze one product while keeping network waits outside a SQLite transaction."""

    from services.attribute_chatgpt_control import analyze_with_chatgpt

    preparation_started = time.perf_counter()
    product_id = product.id
    snapshot_product(db, product, "Перед анализом ChatGPT")
    source_url, html, parsed, _resolved_by = prepare_product_source(
        db,
        product,
        donor_ids,
        url_overrides=url_overrides,
        fetcher=fetcher,
    )
    prompt, page_evidence = build_product_prompt(
        product,
        source_url=source_url,
        html=html,
        parsed=parsed,
    )
    db.commit()
    request_started = time.perf_counter()
    response = analyze_with_chatgpt(prompt)
    response_received = time.perf_counter()
    db.expire_all()
    product = db.get(AttributeProduct, product_id)
    if product is None:
        raise ValueError("Товар был удалён во время анализа ChatGPT")
    analysis = validate_analysis(
        product,
        response.get("text", ""),
        page_evidence=page_evidence,
        source_facts=parsed_attribute_facts(parsed),
    )
    record_analysis_metrics(
        analysis, prompt, response,
        preparation_seconds=request_started - preparation_started,
        request_seconds=response_received - request_started,
        validation_seconds=time.perf_counter() - response_received,
    )
    changed = apply_analysis(db, product, analysis, source_url=source_url)
    db.flush()
    return {
        "changed": changed,
        "analysis": analysis,
        "source_url": source_url,
        "product": product,
    }
