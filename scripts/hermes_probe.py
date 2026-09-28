"""Проба Hermes-моста: один POST с подписью V2, без спама.

Секреты только из env, в коде/архиве их нет:
    HERMES_BRIDGE_SECRET — ключ маршрута (обязателен для live-пробы)
    HERMES_BRIDGE_URL    — URL моста (иначе временный дефолт из hermes.py)

Режимы:
    --dry-run   только собрать payload и посчитать подпись, сети нет
    (по умолчанию) один live-POST; ответ асинхронный (202 + delivery_id),
    сам разбор приходит в Telegram, не сюда.

Запуск:
    set HERMES_BRIDGE_SECRET=... && python scripts/hermes_probe.py --dry-run
    set HERMES_BRIDGE_SECRET=... && python scripts/hermes_probe.py
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time

sys.path.insert(0, "src")

from d2intel.llm.hermes import bridge_url, build_payload, post_to_bridge, sign


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="без сети")
    args = parser.parse_args()

    ev = {"match_id": 659245, "league": "probe", "radiant": {}, "dire": {}, "h2h": {}}
    messages = [{"role": "user", "content": "проба моста d2intel: ответь в Telegram"}]
    payload = build_payload(ev, messages, "hermes-probe-v1")

    if args.dry_run:
        body = json.dumps(payload, ensure_ascii=False).encode()
        secret = os.environ.get("HERMES_BRIDGE_SECRET", "<не задан>")
        ts = str(int(time.time()))
        sig = sign(ts, body, secret) if secret != "<не задан>" else "<нет секрета>"
        print(f"url: {bridge_url()}")
        print(f"body_bytes: {len(body)}")
        print(f"ts: {ts}")
        print(f"sig: {sig[:16]}… (длина {len(sig) if sig.startswith('<') is False else '?'})")
        print("dry-run: сеть не трогалась")
        return 0

    out = post_to_bridge(payload)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    raise SystemExit(main())
