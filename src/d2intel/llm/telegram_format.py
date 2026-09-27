"""Форматирование прогноза LLM-аналитика в Telegram-сообщение (инфоповод).

Честные пометки — принцип проекта: никакой уверенности, которой нет.
Модель не заменяет числовой прогноз, а дополняет его аналитикой.
"""

from __future__ import annotations

#: Обязательная подпись: LLM-аналитик — эксперимент, не принятая модель.
FOOTER = (
    "\n\n⚠️ LLM-аналитик — экспериментальный модуль, не принятая модель. "
    "Числа — оценка на основе pre-match данных OpenDota, не финансовая рекомендация."
)


def format_llm_brief(ev: dict, pred: dict) -> str:
    """Собрать сообщение-инфоповод из evidence и прогноза аналитика."""
    radiant = ev["radiant"]
    dire = ev["dire"]

    def side_line(team: dict) -> str:
        if not team.get("known"):
            return f"• {team['name']}: истории нет в OpenDota"
        return (
            f"• {team['name']}: {team['wins']}W / {team['games'] - team['wins']}L "
            f"в окне 30 дней (винрейт {team['winrate']})"
        )

    h2h = ev.get("h2h", {})
    if h2h.get("games"):
        a, b = ev["radiant"]["name"], ev["dire"]["name"]
        h2h_line = (
            f"Личные встречи: {h2h['games']} игр — {a} {h2h.get(f'{a}_wins', 0)} : "
            f"{h2h.get(f'{b}_wins', 0)} {b}"
        )
    else:
        h2h_line = "交叉战绩: личных встреч не найдено"

    if not pred.get("ok"):
        return (
            f"🔮 {ev['radiant']['name']} vs {ev['dire']['name']}\n"
            f"Лига: {ev['league']} (bo{ev['series_type']})\n\n"
            f"Аналитик не дал прогноз: {pred.get('reason', 'неизвестно')}\n"
            "Данных недостаточно для честной оценки." + FOOTER
        )

    p = pred["p_radiant"]
    a_name = ev["radiant"]["name"]
    b_name = ev["dire"]["name"]
    fav = a_name if p >= 0.5 else b_name
    p_fav = max(p, 1 - p)
    return (
        f"🔮 {a_name} vs {b_name}\n"
        f"Лига: {ev['league']} (bo{ev['series_type']})\n\n"
        f"Форма команд:\n"
        f"{side_line(radiant)}\n"
        f"{side_line(dire)}\n\n"
        f"{h2h_line}\n\n"
        f"Оценка аналитика: {fav} — {p_fav:.0%}\n"
        f"Ключевой фактор: {pred.get('key_factor', '—')}\n\n"
        f"Почему: {pred.get('reason', '—')}{FOOTER}"
    )
