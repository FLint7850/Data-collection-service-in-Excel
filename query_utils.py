from __future__ import annotations

import re
import unicodedata


def normalize_search_text(value: object) -> str:
    text = unicodedata.normalize("NFKC", str(value or "")).casefold().strip()
    return re.sub(r"\s+", " ", text)
