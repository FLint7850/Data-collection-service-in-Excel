"""Explicit proxy routing for all external HTTP(S) traffic.

The application never mutates the parent process' global HTTP_PROXY variables:
internal Flask/Nuxt/Docker traffic therefore remains direct.  Each external
client receives the proxy in its native format, while subprocess engines get a
dedicated environment.
"""

from __future__ import annotations

from dataclasses import dataclass
import ipaddress
import os
import re
from typing import Dict, Mapping, Optional
from urllib.parse import unquote, urlsplit

import requests

from config import env_str


_TRUE_VALUES = {"1", "true", "yes", "on"}
_PROXY_VARIABLES = (
    "HTTP_PROXY",
    "HTTPS_PROXY",
    "ALL_PROXY",
    "http_proxy",
    "https_proxy",
    "all_proxy",
)
_DEFAULT_BYPASS = (
    "localhost,127.0.0.1,::1,parser,frontend,nginx,"
    "10.0.0.0/8,172.16.0.0/12,192.168.0.0/16"
)


class OutboundProxyConfigurationError(RuntimeError):
    """Raised before an external request when required proxy setup is invalid."""


def _enabled(value: object) -> bool:
    return str(value or "").strip().casefold() in _TRUE_VALUES


def _safe_port(value: Optional[int]) -> int:
    if not value or not 1 <= int(value) <= 65535:
        raise OutboundProxyConfigurationError("Некорректный порт внешнего прокси")
    return int(value)


@dataclass(frozen=True)
class OutboundProxy:
    url: str
    scheme: str
    host: str
    port: int
    username: str = ""
    password: str = ""

    def requests(self) -> Dict[str, str]:
        return {"http": self.url, "https": self.url}

    def playwright(self) -> Dict[str, str]:
        host = f"[{self.host}]" if ":" in self.host else self.host
        settings = {
            "server": f"{self.scheme}://{host}:{self.port}",
            "bypass": proxy_bypass_value(),
        }
        if self.username:
            settings["username"] = self.username
            settings["password"] = self.password
        return settings

    def crawl4ai(self) -> Dict[str, str]:
        return self.playwright()


def configured_outbound_proxy(*, required: Optional[bool] = None) -> Optional[OutboundProxy]:
    """Read and validate the single external proxy without exposing credentials."""

    required = proxy_required() if required is None else bool(required)
    raw_url = env_str("OUTBOUND_PROXY_URL", "")
    if not raw_url:
        if required:
            raise OutboundProxyConfigurationError(
                "OUTBOUND_PROXY_REQUIRED=1, но OUTBOUND_PROXY_URL не задан"
            )
        return None
    if any(character.isspace() for character in raw_url):
        raise OutboundProxyConfigurationError("Некорректный адрес внешнего прокси")
    try:
        parsed = urlsplit(raw_url)
        port = _safe_port(parsed.port)
    except (TypeError, ValueError) as error:
        raise OutboundProxyConfigurationError("Некорректный адрес внешнего прокси") from error
    scheme = parsed.scheme.casefold()
    if scheme not in {"http", "https", "socks5", "socks5h"} or not parsed.hostname:
        raise OutboundProxyConfigurationError("Некорректный адрес внешнего прокси")
    username = unquote(parsed.username or "")
    password = unquote(parsed.password or "")
    if bool(username) != bool(password):
        raise OutboundProxyConfigurationError(
            "Логин и пароль внешнего прокси должны быть заданы вместе"
        )
    return OutboundProxy(
        url=raw_url,
        scheme=scheme,
        host=parsed.hostname,
        port=port,
        username=username,
        password=password,
    )


def proxy_required() -> bool:
    return _enabled(env_str("OUTBOUND_PROXY_REQUIRED", "0"))


def proxy_bypass_value() -> str:
    return env_str("OUTBOUND_PROXY_NO_PROXY", _DEFAULT_BYPASS) or _DEFAULT_BYPASS


def _bypass_tokens() -> list[str]:
    return [token.strip().casefold() for token in proxy_bypass_value().split(",") if token.strip()]


def is_internal_url(url: object) -> bool:
    """Return True only for localhost, private IPs, and explicit Docker hosts."""

    try:
        parsed = urlsplit(str(url or ""))
    except ValueError:
        return False
    host = (parsed.hostname or "").strip().casefold().rstrip(".")
    if not host:
        return False
    if host == "localhost" or host.endswith(".localhost"):
        return True
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        address = None
    if address is not None:
        if address.is_loopback or address.is_private or address.is_link_local:
            return True
    for token in _bypass_tokens():
        normalized = token.strip("[]")
        if not normalized or "/" in normalized:
            try:
                if address is not None and address in ipaddress.ip_network(normalized, strict=False):
                    return True
            except ValueError:
                pass
            continue
        if normalized.startswith("*.") and host.endswith(normalized[1:]):
            return True
        if normalized.startswith(".") and (host == normalized[1:] or host.endswith(normalized)):
            return True
        if host == normalized:
            return True
    return False


def _url_scheme(url: object) -> str:
    try:
        return urlsplit(str(url or "")).scheme.casefold()
    except ValueError:
        return ""


def proxy_for_external_url(url: object) -> Optional[OutboundProxy]:
    if _url_scheme(url) not in {"http", "https"}:
        return None
    if is_internal_url(url):
        return None
    return configured_outbound_proxy()


class OutboundProxySession(requests.Session):
    """Requests session that decides proxy/direct routing for every URL."""

    def __init__(self) -> None:
        super().__init__()
        self.trust_env = False

    def request(self, method, url, **kwargs):
        if "proxies" not in kwargs:
            proxy = proxy_for_external_url(url)
            kwargs["proxies"] = proxy.requests() if proxy is not None else {}
        try:
            return super().request(method, url, **kwargs)
        except requests.RequestException as error:
            safe_message = redact_proxy_secrets(error)
            if safe_message != str(error):
                raise requests.exceptions.ProxyError(safe_message) from error
            raise


def outbound_requests_session() -> OutboundProxySession:
    return OutboundProxySession()


def requests_get(url: object, **kwargs):
    """One-shot Requests GET with explicit external/internal routing."""

    session = outbound_requests_session()
    with session:
        return session.get(str(url), **kwargs)


def outbound_proxy_environment(
    base_environment: Optional[Mapping[str, str]] = None,
    *,
    external: bool = True,
) -> Dict[str, str]:
    """Build an isolated child environment; never mutate os.environ."""

    environment = dict(os.environ if base_environment is None else base_environment)
    for name in _PROXY_VARIABLES:
        environment.pop(name, None)
    bypass = proxy_bypass_value()
    environment["NO_PROXY"] = bypass
    environment["no_proxy"] = bypass
    if external:
        proxy = configured_outbound_proxy()
        if proxy is not None:
            for name in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy"):
                environment[name] = proxy.url
    return environment


def redact_proxy_secrets(value: object) -> str:
    """Remove configured credentials and userinfo from diagnostic messages."""

    text = str(value or "")
    try:
        proxy = configured_outbound_proxy(required=False)
    except OutboundProxyConfigurationError:
        proxy = None
    if proxy is not None:
        text = text.replace(proxy.url, f"{proxy.scheme}://{proxy.host}:{proxy.port}")
        if proxy.password:
            text = text.replace(proxy.password, "***")
    return re.sub(r"(?i)(https?://)[^\s/@:]+:[^\s/@]+@", r"\1***:***@", text)
