"""Small text helpers shared only by Attribute Assistant."""

import re
from typing import Any


_SPACE_RE = re.compile(r"\s+")
_WORD_RE = re.compile(r"[\w]+", re.UNICODE)


def product_search_text(*parts: Any) -> str:
    text = _SPACE_RE.sub(" ", " ".join(str(part or "") for part in parts)).strip()
    return " ".join(_WORD_RE.findall(text.casefold().replace("ё", "е")))


def mapping_value_key(value: Any) -> str:
    return _SPACE_RE.sub(" ", str(value or "").replace("\xa0", " ")).strip().casefold()
