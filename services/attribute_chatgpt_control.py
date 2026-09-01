"""Authentication and analysis calls for the isolated Codex App Server bridge."""

from typing import Any

import requests

from config import env_int, env_str
from services.attribute_assistant import clean_text


BRIDGE_URL = env_str("ATTRIBUTE_CHATGPT_BRIDGE_URL", "http://127.0.0.1:4580").rstrip("/")
BRIDGE_TOKEN = env_str("ATTRIBUTE_CHATGPT_BRIDGE_TOKEN", "")
BRIDGE_ANALYZE_TIMEOUT = max(60, env_int("ATTRIBUTE_CHATGPT_TIMEOUT_MS", 600000, minimum=60000) // 1000)


def bridge_request(
    method: str,
    path: str,
    timeout: int = 30,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    session = requests.Session()
    session.trust_env = False
    headers = {"Authorization": f"Bearer {BRIDGE_TOKEN}"} if BRIDGE_TOKEN else {}
    try:
        response = session.request(
            method,
            f"{BRIDGE_URL}{path}",
            headers=headers,
            json=json_body,
            timeout=timeout,
        )
    except requests.RequestException as error:
        message = clean_text(str(error)) or "мост недоступен"
        raise RuntimeError(f"Codex bridge недоступен: {message}") from error
    try:
        data = response.json()
    except ValueError:
        data = {"error": clean_text(response.text) or "Некорректный ответ Codex bridge"}
    if not response.ok:
        raise RuntimeError(clean_text(data.get("error")) or f"Codex bridge: HTTP {response.status_code}")
    return data


def chatgpt_status() -> dict[str, Any]:
    try:
        return bridge_request("GET", "/status", timeout=20)
    except Exception as error:
        return {
            "available": False,
            "authenticated": False,
            "account": None,
            "proxy_enabled": False,
            "error": str(error),
        }


def start_device_login() -> dict[str, Any]:
    return bridge_request("POST", "/login/device", timeout=60)


def logout_chatgpt() -> dict[str, Any]:
    return bridge_request("POST", "/logout", timeout=30)


def analyze_with_chatgpt(prompt: str) -> dict[str, Any]:
    return bridge_request(
        "POST",
        "/analyze",
        timeout=BRIDGE_ANALYZE_TIMEOUT,
        json_body={"prompt": prompt},
    )
