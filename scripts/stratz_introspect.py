#!/usr/bin/env python3
"""Одноразовый entrypoint: диагностика GraphQL STRATZ (интроспекция live-схемы).

Нужен, чтобы починить `_stratz_live_match`: запрос получает 400, а тело ответа
с GraphQL `errors` в коде теряется. Здесь тело печатается целиком (без ключа).

Лимит free-tier жёсткий: **один запрос за запуск, не долбить**, после ошибки
ждать ~15 минут.

Запуск:
    python scripts/stratz_introspect.py                 # интроспекция live-типов
    python scripts/stratz_introspect.py --q '{live { matches { matchId }}}'
Возвращает код 0 при HTTP 200, 1 при ошибке.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from typing import Any

import httpx

from d2intel.api.schedule import _stratz_key

ENDPOINT = "https://api.stratz.com/graphql"

# Один запрос — несколько типов через алиасы. Неизвестное имя вернёт null,
# но не уронит весь запрос, поэтому можно угадывать смело.
INTROSPECTION = """
{
  q:   __type(name: "Query")              { name fields { name type { kind name ofType { kind name } } } }
  m:   __type(name: "MatchLiveType")      { name fields { name type { kind name ofType { kind name } } } }
  p:   __type(name: "MatchLivePlayerType") { name fields { name type { kind name ofType { kind name } } } }
  l:   __type(name: "MatchLiveLeagueType") { name fields { name type { kind name ofType { kind name } } } }
}
"""

SHOW_LIMIT = 6000


def _fields(node: dict[str, Any]) -> list[str]:
    out: list[str] = []
    for f in node.get("fields") or []:
        t = f.get("type") or {}
        inner = t.get("ofType") or {}
        kind = inner.get("kind") or t.get("kind")
        name = inner.get("name") or t.get("name")
        out.append(f"{f['name']}: {kind} {name}".strip())
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description="Диагностика GraphQL STRATZ")
    parser.add_argument("--q", default=None, help="произвольный GraphQL-запрос вместо интроспекции")
    args = parser.parse_args()

    key = _stratz_key()
    if key is None:
        print("STRATZ_API_KEY не найден в .env — пропуск (без запроса).")
        return 1

    started = time.monotonic()
    try:
        response = httpx.post(
            ENDPOINT,
            json={"query": args.q or INTROSPECTION},
            headers={
                "Authorization": f"Bearer {key}",
                "User-Agent": "STRATZ_API",
                "Content-Type": "application/json",
            },
            timeout=30,
        )
    except httpx.HTTPError as exc:
        print(f"СЕТЬ: {type(exc).__name__}: {exc}")
        return 1

    elapsed = time.monotonic() - started
    print(f"HTTP {response.status_code} за {elapsed:.2f}s")
    print(f"{'=' * 60}")

    body = response.text
    if response.status_code != 200:
        # Именно это и теряется при raise_for_status(): причина 400/403.
        print(body[:SHOW_LIMIT])
        return 1

    try:
        payload = response.json()
    except json.JSONDecodeError:
        print(body[:SHOW_LIMIT])
        return 1

    errors = payload.get("errors") or []
    if errors:
        print("GraphQL errors:")
        for err in errors:
            print("  -", json.dumps(err, ensure_ascii=False)[:600])

    data = payload.get("data") or {}
    if args.q:
        print(json.dumps(data, ensure_ascii=False, indent=2)[:SHOW_LIMIT])
        return 1 if errors else 0

    if not any(data.values()):
        print("Все типы не найдены — имена типов в запросе не совпали со схемой.")
        print("Ответ сервера:", json.dumps(payload, ensure_ascii=False)[:1000])
        return 1

    for alias in ("q", "m", "p", "l"):
        node = data.get(alias)
        if not node:
            print(f"\n[{alias}] тип не найден")
            continue
        print(f"\n[{alias}] {node.get('name')}")
        for line in _fields(node):
            print(f"    {line}")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
