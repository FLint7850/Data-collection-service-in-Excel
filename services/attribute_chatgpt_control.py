"""Authentication and analysis calls for the isolated Codex App Server bridge."""

from typing import Any
import time
import uuid

import requests

from config import env_str
from services.attribute_assistant import clean_text


BRIDGE_URL = env_str("ATTRIBUTE_CHATGPT_BRIDGE_URL", "http://127.0.0.1:4580").rstrip("/")
BRIDGE_TOKEN = env_str("ATTRIBUTE_CHATGPT_BRIDGE_TOKEN", "")
BRIDGE_ANALYSIS_REQUEST_TIMEOUT = (5, 30)
BRIDGE_POLL_INTERVAL = 2.0
BRIDGE_RECOVERY_TIMEOUT = 60.0


class BridgeTransportError(RuntimeError):
    """The HTTP connection failed; the remote analysis may still be running."""


class BridgeHttpError(RuntimeError):
    def __init__(self, message: str, status_code: int):
        super().__init__(message)
        self.status_code = status_code


def bridge_request(
    method: str,
    path: str,
    timeout: int | tuple[int, int] = 30,
    *,
    json_body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Authorization": f"Bearer {BRIDGE_TOKEN}"} if BRIDGE_TOKEN else {}
    try:
        with requests.Session() as session:
            session.trust_env = False
            response = session.request(
                method,
                f"{BRIDGE_URL}{path}",
                headers=headers,
                json=json_body,
                timeout=timeout,
            )
    except requests.Timeout as error:
        raise BridgeTransportError("Не удалось вовремя получить состояние Codex bridge") from error
    except requests.RequestException as error:
        message = clean_text(str(error)) or "мост недоступен"
        raise BridgeTransportError(f"Нет связи с Codex bridge: {message}") from error
    try:
        data = response.json()
    except ValueError:
        data = {"error": clean_text(response.text) or "Некорректный ответ Codex bridge"}
    if not isinstance(data, dict):
        raise RuntimeError("Codex bridge вернул некорректный ответ")
    if not response.ok:
        raise BridgeHttpError(
            clean_text(data.get("error")) or f"Codex bridge: HTTP {response.status_code}",
            response.status_code,
        )
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
    """Submit one prompt and retrieve that job's result over short HTTP requests."""
    request_id = uuid.uuid4().hex
    state: dict[str, Any] | None = None
    last_contact = time.monotonic()
    try:
        state = bridge_request(
            "POST",
            "/analyses",
            timeout=BRIDGE_ANALYSIS_REQUEST_TIMEOUT,
            json_body={"request_id": request_id, "prompt": prompt},
        )
        last_contact = time.monotonic()
    except BridgeHttpError as error:
        if error.status_code == 404:
            raise RuntimeError(
                "Обновите Docker-сервисы parser и attribute-ai: bridge не поддерживает фоновые анализы"
            ) from error
        raise
    except BridgeTransportError:
        # The POST may have succeeded remotely. Never send the prompt again;
        # recover the same operation using its preallocated identifier.
        pass

    while True:
        if state is not None:
            if state.get("id") != request_id:
                raise RuntimeError("Codex bridge вернул результат другой операции")
            status = state.get("status")
            if status == "completed":
                result = state.get("result")
                if not isinstance(result, dict) or not isinstance(result.get("text"), str):
                    raise RuntimeError("Codex bridge не вернул текст ответа ChatGPT")
                _release_analysis(request_id)
                return result
            if status == "failed":
                _release_analysis(request_id)
                raise RuntimeError(clean_text(state.get("error")) or "ChatGPT не смог выполнить анализ")
            if status not in {"queued", "running"}:
                raise RuntimeError("Codex bridge вернул неизвестное состояние анализа")
            time.sleep(BRIDGE_POLL_INTERVAL)
        try:
            state = bridge_request(
                "GET",
                f"/analyses/{request_id}",
                timeout=BRIDGE_ANALYSIS_REQUEST_TIMEOUT,
            )
            last_contact = time.monotonic()
        except BridgeTransportError as error:
            if time.monotonic() - last_contact >= BRIDGE_RECOVERY_TIMEOUT:
                raise RuntimeError(
                    f"Потеряна связь с bridge при ожидании анализа {request_id}. "
                    "Запрос не отправлялся повторно; его выполнение на bridge могло продолжиться"
                ) from error
            state = None
            time.sleep(BRIDGE_POLL_INTERVAL)


def _release_analysis(request_id: str) -> None:
    """Acknowledge a received result so long batches don't fill bridge storage."""
    try:
        bridge_request("DELETE", f"/analyses/{request_id}", timeout=(2, 2))
    except RuntimeError:
        # The result is already here. A failed acknowledgement must not lose it
        # or resubmit the prompt; the bridge's normal expiry remains a fallback.
        pass
