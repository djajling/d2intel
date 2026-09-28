"""Hermes-мост: опциональный провайдер LLM-аналитика через Android-хост.

Прямой вызов Atria в `analyst.py` НЕ трогаем — этот модуль идёт рядом.
Выбор провайдера: `analyze(ev, provider="hermes")` или env `LLM_PROVIDER=hermes`.
По умолчанию — `atria`.

Протокол моста (подпись V2, обязательна):
- POST на `HERMES_BRIDGE_URL` с JSON-телом;
- заголовки `X-Webhook-Timestamp: <unix>` и `X-Webhook-Signature-V2:
  hex(HMAC-SHA256(key, timestamp + "." + body))` — точка-разделитель
  ОБЯЗАТЕЛЬНА (исправление спеки от 2026-09-28: без точки сервер даёт 401),
  body — сырые байты, ровно как уходят в запрос;
- ответ асинхронный: `202 {"status": "accepted", "delivery_id": ...}`,
  сам разбор приходит в Telegram, не в HTTP-ответе.

Секреты: ключ маршрута — ТОЛЬКО env `HERMES_BRIDGE_SECRET`, в git/коде/логах
никогда не пишется. URL — env `HERMES_BRIDGE_URL` (дефолт ниже временный:
trycloudflare-туннель меняется при перезапуске на Android).
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
import urllib.error
import urllib.request

#: Временный URL trycloudflare-туннеля. При перезапуске туннеля на Android
#: меняется — для продакшена нужен named tunnel; переопределяется env.
DEFAULT_BRIDGE_URL = "https://smoke-apparent-manhattan-weight.trycloudflare.com/webhooks/opencode-agent"

TASK_ANALYZE = "analyze_match"


def bridge_url() -> str:
    """URL моста: env `HERMES_BRIDGE_URL` или временный дефолт."""
    return os.environ.get("HERMES_BRIDGE_URL", DEFAULT_BRIDGE_URL)


def sign(timestamp: str, body: bytes, secret: str) -> str:
    """Подпись V2: hex HMAC-SHA256 от `<timestamp>.<body>` (точка обязательна)."""
    return hmac.new(secret.encode(), timestamp.encode() + b"." + body, hashlib.sha256).hexdigest()


def build_payload(ev: dict, messages: list[dict], prompt_version: str) -> dict:
    """Payload моста: агент видит весь контекст (evidence + messages)."""
    return {
        "task": TASK_ANALYZE,
        "input": {
            "match_id": ev.get("match_id"),
            "league": ev.get("league"),
            "prompt_version": prompt_version,
            "messages": messages,
            "evidence": ev,
        },
        "expect_reply": True,
    }


def post_to_bridge(payload: dict, timeout: int = 60) -> dict:
    """Отправка payload в мост. Сеть — единственное место с побочным эффектом."""
    secret = os.environ.get("HERMES_BRIDGE_SECRET")
    if not secret:
        return {"ok": False, "provider": "hermes", "reason": "HERMES_BRIDGE_SECRET не задан"}
    url = bridge_url()
    if not url:
        return {"ok": False, "provider": "hermes", "reason": "HERMES_BRIDGE_URL пуст"}
    body = json.dumps(payload, ensure_ascii=False).encode()
    ts = str(int(time.time()))
    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Content-Type": "application/json",
            "X-Webhook-Timestamp": ts,
            "X-Webhook-Signature-V2": sign(ts, body, secret),
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            status = resp.status
            raw = resp.read().decode()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode(errors="replace")[:200]
        return {
            "ok": False,
            "provider": "hermes",
            "reason": f"мост HTTP {exc.code}: {detail}",
        }
    except (urllib.error.URLError, TimeoutError) as exc:
        return {"ok": False, "provider": "hermes", "reason": f"мост недоступен: {exc}"}
    if status == 202:
        try:
            data = json.loads(raw) if raw else {}
        except json.JSONDecodeError:
            data = {}
        return {
            "ok": True,
            "provider": "hermes",
            "pending": True,
            "delivery_id": data.get("delivery_id"),
            "reason": "запрос принят мостом, ответ придёт в Telegram",
        }
    return {"ok": False, "provider": "hermes", "reason": f"мост вернул {status}: {raw[:200]}"}


def analyze_via_hermes(ev: dict, messages: list[dict], prompt_version: str) -> dict:
    """Точка входа провайдера: evidence+messages уже собраны вызывателем."""
    return post_to_bridge(build_payload(ev, messages, prompt_version))
