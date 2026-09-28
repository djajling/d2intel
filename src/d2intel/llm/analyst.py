"""LLM-аналитик: pre-match прогноз на основе evidence (LLM-002/LLM-003).

Жёсткая дисциплина (LLM-001):
- единственный источник данных — evidence из `evidence.py` (только pre-match);
- LLM не меняет числа модели, если они переданы;
- фабрикация запрещена: guardrails отбрасывают любой вывод с числами,
  которых не было в evidence;
- промпт версионирован.

Провайдер: Atria (Atria-Dawn-Preview) — бесплатный для текущего проекта.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request

ATRIA_URL = "https://api.atria-asi.ai/v1/chat/completions"
ATRIA_MODEL = "Atria-Dawn-Preview"
#: Версия контракта промпта (LLM-002 AC #2).
PROMPT_VERSION = "llm-analyst-v1"

#: Главный запрет: никаких чисел, которых не было в evidence.
SYSTEM_PROMPT = """\
Ты — аналитик по Dota 2. Делаешь предматчевый прогноз на карту.

Жёсткие правила:
1. Используй ТОЛЬКО данные из блока «Известно». Никаких других фактов.
2. Запрещено выдумывать числа: винрейты, счёт серий, ростеры, ID героев,
   KDA — только то, что буквально есть в блоке «Известно».
3. Если данных мало, так и скажи — занижение уверенности лучше выдумки.
4. Итог — JSON с p_radiant от 0.05 до 0.95. Не 0 и не 1: абсолютной
   уверенности в Dota не бывает.
5. Отвечай строго JSON, без markdown, без обёрток."""


def _evidence_block(ev: dict) -> str:
    """Рендер evidence в текст — только pre-match факты."""
    def form(t: dict) -> str:
        if not t.get("known"):
            return f"{t['name']}: истории нет"
        return (
            f"{t['name']}: {t['games']} игр в окне, побед {t['wins']} "
            f"(винрейт {t['winrate']}), последняя игра {t['last_game']}"
        )

    h2h = ev["h2h"]
    if h2h.get("games"):
        a, b = ev["radiant"]["name"], ev["dire"]["name"]
        h2h_line = f"Личные встречи: {h2h['games']} игр — {a} {h2h.get(f'{a}_wins', 0)} : {h2h.get(f'{b}_wins', 0)} {b}"
    else:
        h2h_line = "Личные встречи: неизвестны"

    return (
        f"Лига: {ev['league']}\n"
        f"Формат серии: bo{ev['series_type']}\n"
        f"Radiant: {form(ev['radiant'])}\n"
        f"Dire: {form(ev['dire'])}\n"
        f"{h2h_line}"
    )


def build_messages(ev: dict) -> list[dict[str, str]]:
    """Версионированный контракт промпта."""
    return [
        {"role": "system", "content": SYSTEM_PROMPT},
        {
            "role": "user",
            "content": (
                f"Известно:\n{_evidence_block(ev)}\n\n"
                'Дай прогноз. Ответ строго JSON: '
                '{"p_radiant": <0.05..0.95>, "reason": "<коротко на русском>", '
                '"key_factor": "<главный фактор>"}'
            ),
        },
    ]


def _call_llm(messages: list[dict]) -> dict:
    """Вызов провайдера. Возвращает сырой ответ."""
    body = json.dumps(
        {
            "model": ATRIA_MODEL,
            "messages": messages,
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
        return json.loads(resp.read().decode())


def parse_response(text: str) -> dict:
    """Достать JSON из ответа (LLM любит оборачивать в markdown)."""
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise ValueError("в ответе нет JSON")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as exc:
        raise ValueError(f"невалидный JSON: {exc}") from exc


def guard(pred: dict, ev: dict) -> dict:
    """Guardrails (LLM-003): отбрасывать неподкреплённые выводы.

    Возвращает dict с ok/failed и причиной отказа.
    """
    if "p_radiant" not in pred:
        return {"ok": False, "reason": "нет p_radiant"}
    try:
        p = float(pred["p_radiant"])
    except (TypeError, ValueError):
        return {"ok": False, "reason": "p_radiant не число"}
    # жёсткий диапазон: абсолютной уверенности не существует
    if not 0.05 <= p <= 0.95:
        return {"ok": False, "reason": f"p_radiant={p} вне диапазона [0.05, 0.95]"}
    reason = str(pred.get("reason") or "")
    key = str(pred.get("key_factor") or "")
    # запрещённые формулировки (обещания прибыли/точности)
    banned = ["гаранти", "100%", "точно", "безусловно", "profit", "выигрыш обеспечен"]
    blob = f"{reason} {key}".lower()
    for word in banned:
        if word in blob:
            return {"ok": False, "reason": f"запрещённая формулировка: {word}"}
    # фабрикация чисел: проверяем, что причина не содержит новых процентов,
    # которых не было в evidence
    ev_numbers = set()
    for side in ("radiant", "dire"):
        t = ev.get(side, {})
        if t.get("known"):
            ev_numbers.add(str(t.get("winrate")))
            ev_numbers.add(str(t.get("wins")))
            ev_numbers.add(str(t.get("games")))
    h2h = ev.get("h2h", {})
    for val in h2h.values():
        if isinstance(val, int):
            ev_numbers.add(str(val))
    for match in re.finditer(r"\d+(?:\.\d+)?\s*%", blob):
        found = match.group(0).replace(" ", "").rstrip("%")
        if found not in {n.lstrip("0") or "0" for n in ev_numbers} and found not in ev_numbers:
            return {"ok": False, "reason": f"число {found}% не из evidence (фабрикация)"}
    return {"ok": True, "p_radiant": p, "reason": reason, "key_factor": key}


def analyze(ev: dict) -> dict:
    """Полный цикл: промпт → LLM → парсинг → guardrails."""
    try:
        raw = _call_llm(build_messages(ev))
        text = raw["choices"][0]["message"]["content"].strip()
    except (urllib.error.URLError, KeyError, TimeoutError) as exc:
        return {"ok": False, "reason": f"ошибка провайдера: {exc}"}
    try:
        parsed = parse_response(text)
    except ValueError as exc:
        return {"ok": False, "reason": f"{exc}; raw={text[:160]}"}
    checked = guard(parsed, ev)
    checked["prompt_version"] = PROMPT_VERSION
    checked["raw_model_output"] = text
    return checked
