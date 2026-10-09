"""Dictionary-based normalization shared by parser and ChatGPT program lists."""

from __future__ import annotations

import html
import re
import unicodedata
from typing import Any


def program_value_key(value: Any) -> str:
    text = html.unescape(unicodedata.normalize("NFKC", str(value or "")))
    text = text.casefold().replace("ё", "е")
    text = text.translate(str.maketrans({"’": "'", "′": "'", "`": "'", "–": "-", "−": "-"}))
    text = re.sub(r"(\d)\s*°\s*[cс]", r"\1°c", text)
    text = re.sub(r"(\d)\s*-\s*(?=\d)", r"\1-", text)
    text = re.sub(r"\b(\d+)\s*(?:минут(?:а|ы)?|мин)\.?(?!\w)", r"\1'", text)
    text = re.sub(r"(\d)\s*'", r"\1'", text)
    return " ".join(text.split()).strip()


def is_program_list(field: Any) -> bool:
    """Recognize lists even in historical imports without is_composite."""
    if field is None or getattr(field, "value_type", "select") in {"number", "dimensions", "boolean"}:
        return False
    name = program_value_key(field.name)
    group = program_value_key(getattr(field, "group_name", ""))
    if re.search(r"количеств|число|сигнал|индикац|длительност|время|наличие", name):
        return False
    if not (re.search(r"программ", name) or re.fullmatch(r"программы(?:\s+.*)?", group)):
        return False
    values = [item.value for item in field.allowed_values if item.is_active]
    if values and all(program_value_key(value) in {"да", "нет", "есть", "yes", "no", "-"}
                      or re.fullmatch(r"\d+(?:[.,]\d+)?", str(value).strip()) for value in values):
        return False
    return True


def _parts(field: Any, value: str) -> list[str]:
    separator = getattr(field, "separator", "/") or "/"
    # Remote dictionaries traditionally use '/', including when the local
    # field has a custom separator. Parentheses can contain literal slashes.
    result, buffer, depth = [], [], 0
    index = 0
    while index < len(value):
        char = value[index]
        if char == "(":
            depth += 1
        elif char == ")":
            depth = max(0, depth - 1)
        delimiter = next((item for item in {separator, "/"} if not depth and value.startswith(item, index)), "")
        if delimiter:
            part = " ".join("".join(buffer).split()).strip()
            if part and part not in {"-", "–", "—"}:
                result.append(part)
            buffer = []
            index += len(delimiter)
        else:
            buffer.append(char)
            index += 1
    part = " ".join("".join(buffer).split()).strip()
    if part and part not in {"-", "–", "—"}:
        result.append(part)
    return result


def _capitalize(value: str) -> str:
    # Preserve the rest of a compound name and brand/technology acronyms.
    return re.sub(r"[a-zа-яё]", lambda match: match.group().upper(), value, count=1, flags=re.IGNORECASE)


def _program_registry(field: Any):
    components: dict[str, str] = {}
    active = [item for item in field.allowed_values if item.is_active]
    for item in active:
        for part in _parts(field, item.value):
            components.setdefault(program_value_key(part), _capitalize(part))
    aliases = dict(components)
    # Allow the unit-less spelling of an explicitly allowed temperature program.
    for key, canonical in components.items():
        if key.endswith("°c"):
            aliases.setdefault(key[:-2].rstrip(), canonical)
    explicit: dict[str, set[str]] = {}
    whole: dict[str, set[str]] = {}
    # Read synonyms from the current active records on every match. A sync,
    # rename, deactivation or synonym edit needs no code change or cache reset.
    for item in active:
        parts = _parts(field, item.value)
        canonical = "/".join(sorted({aliases[program_value_key(part)] for part in parts}, key=program_value_key))
        for synonym in item.synonyms:
            key = program_value_key(synonym.synonym)
            if key:
                (explicit if len(parts) == 1 else whole).setdefault(key, set()).add(canonical)
    for key, targets in explicit.items():
        if len(targets) == 1:
            aliases[key] = next(iter(targets))
        else:
            aliases[key] = ""
    return aliases, whole


def program_dictionary(field: Any, source_text: str = "") -> dict[str, Any]:
    """Expose current components as hints; validation always uses the full registry."""
    aliases, whole = _program_registry(field)
    components = sorted({value for value in aliases.values() if value}, key=program_value_key)
    total = len(components)
    if total > 30:
        text = program_value_key(source_text)
        relevant: set[str] = set()
        for key, value in aliases.items():
            if value and re.search(r"(?<![\w+-])" + re.escape(key) + r"(?![\w+-])", text):
                relevant.add(value)
        for key, values in whole.items():
            if len(values) == 1 and re.search(r"(?<![\w+-])" + re.escape(key) + r"(?![\w+-])", text):
                relevant.update(_parts(field, next(iter(values))))
        components = [value for value in components if value in relevant]
    selected = set(components)
    synonyms = {
        key: value for key, value in aliases.items()
        if value in selected and key != program_value_key(value)
    }
    synonyms.update({key: next(iter(values)) for key, values in whole.items()
                     if len(values) == 1 and set(_parts(field, next(iter(values)))) <= selected})
    result: dict[str, Any] = {"program_components": components}
    if total > len(components):
        result["program_components_total"] = total
    if synonyms:
        result["program_synonyms"] = synonyms
    return result


def match_programs(field: Any, raw_value: Any) -> tuple[str, int, str, list[str]]:
    raw = program_value_key(raw_value)
    if not raw or raw in {"да", "нет", "есть", "yes", "no", "-"}:
        return "", 0, "Список программ не заполнен", []
    aliases, whole = _program_registry(field)
    if raw in whole and len(whole[raw]) == 1:
        return next(iter(whole[raw])), 98, "Синоним списка программ; состав проверен по справочнику", []
    if (raw in whole and len(whole[raw]) > 1) or (raw in aliases and not aliases[raw]):
        return "", 0, "Неоднозначный синоним программы", []
    if not aliases:
        return "", 0, "В шаблоне нет допустимых программ", []
    # Longest phrase wins: Полоскание и отжим must remain one component.
    phrases = sorted(aliases, key=lambda key: (-len(key), key))
    patterns = []
    for key in phrases:
        phrase = re.escape(key).replace(r"\ ", r"\s+")
        # A base program can carry a source-only temperature/duration; an
        # explicitly listed detailed variant wins through longest matching.
        if not re.search(r"\d", key):
            phrase += r"(?:\s+\d+(?:-\d+)?\s*(?:°c?|c|с|'|мин\.?)?)?"
        patterns.append(phrase)
    pattern = re.compile(r"(?<![\w+-])(?:" + "|".join(patterns) + r")(?![\w+-])")
    values, unknown = set(), []
    for part in _parts(field, raw):
        # Preserve commas/parentheses inside an allowed compound name.
        exact = aliases.get(part)
        if exact:
            values.add(exact)
            continue
        if re.search(r"\b(?:не|без|нет|no|without)\b", part):
            unknown.append(part)
            continue
        previous = 0
        for match in pattern.finditer(part):
            leftover = part[previous:match.start()].strip(" ,;|\n\t")
            if leftover:
                unknown.append(leftover)
            matched = match.group()
            key = next((key for key in phrases if matched == key or
                        (matched.startswith(key + " ") and re.fullmatch(
                            r"\d+(?:-\d+)?\s*(?:°c?|c|с|'|мин\.?)?", matched[len(key):].strip()))), "")
            if key and aliases[key]:
                values.add(aliases[key])
            else:
                unknown.append(matched)
            previous = match.end()
        leftover = part[previous:].strip(" ,;|\n\t")
        if leftover:
            unknown.append(leftover)
    result = "/".join(sorted(values, key=program_value_key))
    reason = ("Программы приведены к справочнику, повторы удалены, порядок алфавитный"
              if result else "В источнике не найдены допустимые программы")
    if unknown:
        reason += "; исключены названия вне набора: " + ", ".join(dict.fromkeys(unknown))
    return result, (90 if unknown else 100) if result else 0, reason, []
