"""Онлайн-эксперимент: LLM-аналитик делает pre-match прогноз на Dota 2.

Источник: публичный OpenDota API (без ключа).
Сценарий: берём сыгранный матч, отдаём LLM только pre-match данные
(команды, патч, лига, формат серии, история встреч), получаем прогноз,
сверяем с реальным результатом. Никаких post-match данных в промпте —
эксперимент честный.

Запуск: python3 scripts/llm_predict_experiment.py [--limit N]
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime

OPENODTA_BASE = "https://api.opendota.com/api"
ATRIA_URL = "https://api.atria-asi.ai/v1/chat/completions"
ATRIA_MODEL = "Atria-Dawn-Preview"
TIMEOUT = 60

#: Pre-match контекст: только то, что известно до начала карты.
PRE_MATCH_TEMPLATE = """\
Ты — аналитик по Dota 2. Дай предматчевый прогноз на исход карты.

Известно до матча:
- Лига: {league}
- Формат серии: bo{series_type}
- Патч: {patch}
- Светлая сторона (Radiant): {radiant}
- Тёмная сторона (Dire): {dire}

Оцени chances. Ответь строго JSON, без markdown:
{{"p_radiant": <float 0..1>, "reason": "<одна-две фразы на русском>", "key_factor": "<главный фактор>"}}
"""


def api_get(path: str, cache: dict[str, any], cache_key: str | None = None) -> dict:
    """GET к OpenDota с简易 кэшем, чтобы не дёргать API повторно."""
    key = cache_key or path
    if key in cache:
        return cache[key]
    url = OPENODTA_BASE + path
    req = urllib.request.Request(url, headers={"User-Agent": "d2intel-experiment/1.0"})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as resp:
        data = json.loads(resp.read().decode())
    cache[key] = data
    return data


def llm_predict(radiant: str, dire: str, league: str, series_type: int, patch: int) -> dict:
    """Вызов Atria с pre-match контекстом. Возвращает распарсенный JSON."""
    prompt = PRE_MATCH_TEMPLATE.format(
        league=league,
        series_type=series_type,
        patch=patch,
        radiant=radiant,
        dire=dire,
    )
    body = json.dumps(
        {
            "model": ATRIA_MODEL,
            "messages": [{"role": "user", "content": prompt}],
            "max_tokens": 4000,
            "temperature": 0.4,
        }
    ).encode()
    req = urllib.request.Request(
        ATRIA_URL,
        data=body,
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {os.environ['ATRIA_API_KEY']}",
        },
    )
    with urllib.request.urlopen(req, timeout=180) as resp:
        data = json.loads(resp.read().decode())
    text = data["choices"][0]["message"]["content"].strip()
    # LLM может обернуть JSON в markdown — вытащить фигурные скобки.
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        return {"ok": False, "raw": text}
    try:
        parsed = json.loads(text[start : end + 1])
        return {"ok": True, **parsed, "raw": text}
    except json.JSONDecodeError:
        return {"ok": False, "raw": text}


def experiment(limit: int, league_filter: str | None) -> int:
    cache: dict[str, any] = {}
    matches = api_get("/proMatches", cache)
    print(f"всего про-матчей в ленте: {len(matches)}")
    if league_filter:
        matches = [m for m in matches if league_filter.lower() in (m.get("league_name") or "").lower()]
        print(f"после фильтра по лиге «{league_filter}»: {len(matches)}")

    results = []
    for m in matches[:limit]:
        radiant = m.get("radiant_name") or "Radiant"
        dire = m.get("dire_name") or "Dire"
        if not m.get("radiant_name") or not m.get("dire_name"):
            print(f"  skip {m['match_id']}: нет названия команды")
            continue
        print(f"\n[{len(results)+1}] {radiant} vs {dire} ({m.get('league_name')})")
        try:
            pred = llm_predict(radiant, dire, m.get("league_name", "?"), m.get("series_type", 1), m.get("patch", 0))
        except (urllib.error.URLError, KeyError, TimeoutError) as exc:
            print(f"  LLM error: {exc}")
            continue
        time.sleep(1)  # мягкий rate-limit
        if not pred.get("ok"):
            print(f"  не удалось распарсить ответ: {(pred.get('raw') or '')[:120]}")
            continue
        p_r = float(pred["p_radiant"])
        p_r = min(max(p_r, 0.0), 1.0)
        actual = bool(m.get("radiant_win"))
        hit = (p_r >= 0.5) == actual
        brier = (p_r - (1.0 if actual else 0.0)) ** 2
        results.append(
            {
                "match_id": m["match_id"],
                "radiant": radiant,
                "dire": dire,
                "p_radiant": p_r,
                "actual_radiant_win": actual,
                "hit": hit,
                "brier": brier,
                "reason": pred.get("reason"),
                "key_factor": pred.get("key_factor"),
            }
        )
        print(f"  p_radiant={p_r:.2f} actual={actual} hit={hit} brier={brier:.3f}")
        print(f"  reason: {pred.get('reason')}")

    if not results:
        print("\nнет результатов для подсчёта")
        return 1

    n = len(results)
    acc = sum(r["hit"] for r in results) / n
    brier = sum(r["brier"] for r in results) / n
    print(f"\n{'='*60}")
    print(f"N={n}  accuracy={acc:.3f}  mean_brier={brier:.3f}")

    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    out = f"reports/llm_experiment_{stamp}.json"
    os.makedirs("reports", exist_ok=True)
    with open(out, "w", encoding="utf-8") as fh:
        json.dump({"stamp": stamp, "n": n, "accuracy": acc, "brier": brier, "results": results}, fh, ensure_ascii=False, indent=2)
    print(f"отчёт: {out}")
    return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=5, help="сколько матчей прогнать")
    parser.add_argument("--league", default=None, help="подстрока для фильтра лиги")
    args = parser.parse_args()
    if not os.environ.get("ATRIA_API_KEY"):
        print("ATRIA_API_KEY не задан", file=sys.stderr)
        sys.exit(2)
    sys.exit(experiment(args.limit, args.league))


if __name__ == "__main__":
    main()
