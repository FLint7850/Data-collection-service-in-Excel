"""Explicit per-scan proxy policy for site parsers."""

from __future__ import annotations

import re
from typing import Dict, Optional
from urllib.parse import unquote, urlsplit, urlunsplit

from config import env_str


PROXY_ENV_NAME = "ATTRIBUTE_CHATGPT_PROXY_URL"
SUPPORTED_PROXY_SCHEMES = frozenset({"http", "https"})


def _parse_proxy_url(proxy_url: str):
    raw_url = str(proxy_url or "").strip()
    try:
        parsed = urlsplit(raw_url)
        port = parsed.port
    except ValueError as error:
        raise RuntimeError("В настройке прокси указан некорректный порт.") from error
    if parsed.scheme.lower() not in SUPPORTED_PROXY_SCHEMES:
        raise RuntimeError("Прокси для парсинга должен использовать схему http:// или https://.")
    if not parsed.hostname:
        raise RuntimeError("В настройке прокси не указан адрес сервера.")
    if port is None:
        raise RuntimeError("В настройке прокси не указан порт.")
    if parsed.path not in {"", "/"} or parsed.query or parsed.fragment:
        raise RuntimeError("Адрес прокси не должен содержать путь, параметры или фрагмент.")
    return parsed


def resolve_scraping_proxy_url(use_proxy: object) -> Optional[str]:
    """Return the configured proxy only when the persisted switch is enabled."""
    if not bool(use_proxy):
        return None
    proxy_url = env_str(PROXY_ENV_NAME)
    if not proxy_url:
        raise RuntimeError(
            f"Прокси включён, но переменная {PROXY_ENV_NAME} не настроена."
        )
    _parse_proxy_url(proxy_url)
    return proxy_url


def browser_proxy_config(proxy_url: Optional[str]) -> Optional[Dict[str, str]]:
    """Convert an authenticated URL to Playwright/Crawl4AI proxy settings."""
    if not proxy_url:
        return None
    parsed = _parse_proxy_url(proxy_url)
    hostname = parsed.hostname or ""
    if ":" in hostname and not hostname.startswith("["):
        hostname = f"[{hostname}]"
    config = {
        "server": urlunsplit(
            (parsed.scheme.lower(), f"{hostname}:{parsed.port}", "", "", "")
        )
    }
    if parsed.username is not None:
        config["username"] = unquote(parsed.username)
    if parsed.password is not None:
        config["password"] = unquote(parsed.password)
    return config


def redact_proxy_credentials(value: object) -> str:
    """Keep proxy credentials out of application logs and user-facing errors."""
    text = str(value or "")
    configured = env_str(PROXY_ENV_NAME)
    if configured:
        try:
            proxy = browser_proxy_config(configured)
        except RuntimeError:
            proxy = None
        replacement = str((proxy or {}).get("server") or "[proxy]")
        text = text.replace(configured, replacement)
    return re.sub(r"(?i)(https?://)[^/@\s]+@", r"\1***@", text)
