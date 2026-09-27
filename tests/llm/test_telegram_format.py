"""Тесты форматирования Telegram-инфоповода LLM-аналитика."""

from __future__ import annotations

from d2intel.llm.telegram_format import FOOTER, format_llm_brief


def _evidence() -> dict:
    return {
        "league": "PGL Wallachia 2026 Season 9",
        "series_type": 2,
        "radiant": {
            "name": "Team Yandex",
            "known": True,
            "games": 16,
            "wins": 14,
            "winrate": 0.875,
            "last_game": "2026-09-27",
        },
        "dire": {
            "name": "Natus Vincere",
            "known": True,
            "games": 36,
            "wins": 26,
            "winrate": 0.722,
            "last_game": "2026-09-27",
        },
        "h2h": {
            "games": 4,
            "Team Yandex_wins": 4,
            "Natus Vincere_wins": 0,
            "last": "2026-09-27",
        },
    }


def test_brief_has_teams_and_league() -> None:
    msg = format_llm_brief(_evidence(), {"ok": True, "p_radiant": 0.68, "reason": "x", "key_factor": "y"})
    assert "Team Yandex" in msg
    assert "Natus Vincere" in msg
    assert "PGL Wallachia 2026 Season 9" in msg
    assert "bo2" in msg


def test_brief_shows_favourite_and_probability() -> None:
    msg = format_llm_brief(_evidence(), {"ok": True, "p_radiant": 0.68, "reason": "x", "key_factor": "y"})
    assert "Team Yandex" in msg
    assert "68%" in msg


def test_brief_inverts_favourite_when_p_low() -> None:
    msg = format_llm_brief(_evidence(), {"ok": True, "p_radiant": 0.30, "reason": "x", "key_factor": "y"})
    assert "Natus Vincere" in msg.split("Оценка аналитика:")[1]
    assert "70%" in msg


def test_brief_shows_form_lines() -> None:
    msg = format_llm_brief(_evidence(), {"ok": True, "p_radiant": 0.68, "reason": "x", "key_factor": "y"})
    assert "14W / 2L" in msg
    assert "26W / 10L" in msg
    assert "0.875" in msg


def test_brief_shows_h2h() -> None:
    msg = format_llm_brief(_evidence(), {"ok": True, "p_radiant": 0.68, "reason": "x", "key_factor": "y"})
    assert "4 : 0" in msg


def test_brief_always_has_honest_footer() -> None:
    msg = format_llm_brief(_evidence(), {"ok": True, "p_radiant": 0.68, "reason": "x", "key_factor": "y"})
    assert FOOTER in msg
    assert "не финансовая рекомендация" in msg


def test_brief_handles_rejected_prediction() -> None:
    msg = format_llm_brief(_evidence(), {"ok": False, "reason": "фабрикация числа 95%"})
    assert "не дал прогноз" in msg
    assert "фабрикация числа 95%" in msg
    assert FOOTER in msg


def test_brief_handles_unknown_team() -> None:
    ev = _evidence()
    ev["dire"] = {"name": "NoName", "known": False, "games": 0}
    msg = format_llm_brief(ev, {"ok": True, "p_radiant": 0.9, "reason": "x", "key_factor": "y"})
    assert "истории нет" in msg


def test_brief_handles_no_h2h() -> None:
    ev = _evidence()
    ev["h2h"] = {"games": 0}
    msg = format_llm_brief(ev, {"ok": True, "p_radiant": 0.6, "reason": "x", "key_factor": "y"})
    assert "личных встреч не найдено" in msg
