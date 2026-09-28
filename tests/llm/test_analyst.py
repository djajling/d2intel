"""Тесты guardrails LLM-аналитика (LLM-003) и retrieval-контракта (LLM-002).

Негативные тесты — ядро задачи: фабрикация чисел, запрещённые формулировки,
вывод без p_radiant, абсолютная уверенность. Провайдер не дёргается —
guard() чистая функция от (pred, evidence).
"""

from __future__ import annotations

import pytest

from d2intel.llm.analyst import (
    PROMPT_VERSION,
    _evidence_block,
    build_messages,
    guard,
    parse_response,
)
from d2intel.llm.evidence import build_evidence, head_to_head, team_form


def _evidence() -> dict:
    """Каноничный evidence-образец: Yandex 0.875, NaVi 0.722, h2h 4:0."""
    return {
        "match_id": 9018969340,
        "league": "PGL Wallachia 2026 Season 9",
        "series_type": 2,
        "radiant": {
            "name": "Team Yandex",
            "known": True,
            "games": 16,
            "wins": 14,
            "winrate": 0.875,
            "last_game": "2026-09-27",
            "leagues": ["PGL Wallachia 2026 Season 9"],
        },
        "dire": {
            "name": "Natus Vincere",
            "known": True,
            "games": 36,
            "wins": 26,
            "winrate": 0.722,
            "last_game": "2026-09-27",
            "leagues": ["PGL Wallachia 2026 Season 9"],
        },
        "h2h": {
            "games": 4,
            "Team Yandex_wins": 4,
            "Natus Vincere_wins": 0,
            "last": "2026-09-27",
        },
    }


# ── guardrails: корректный вывод проходит ──────────────────────────────────


def test_guard_accepts_grounded_prediction() -> None:
    out = guard({"p_radiant": 0.65, "reason": "Винрейт 0.875 сильнее", "key_factor": "h2h 4:0"}, _evidence())
    assert out["ok"] is True
    assert out["p_radiant"] == pytest.approx(0.65)


def test_guard_rejects_missing_p_radiant() -> None:
    out = guard({"reason": "нет числа"}, _evidence())
    assert out["ok"] is False
    assert "нет p_radiant" in out["reason"]


def test_guard_rejects_non_numeric_p() -> None:
    out = guard({"p_radiant": "скорее всего"}, _evidence())
    assert out["ok"] is False
    assert "не число" in out["reason"]


@pytest.mark.parametrize("p", [0.0, 0.02, 1.0, 0.99])
def test_guard_rejects_absolute_confidence(p: float) -> None:
    out = guard({"p_radiant": p, "reason": "уверен"}, _evidence())
    assert out["ok"] is False
    assert "вне диапазона" in out["reason"]


@pytest.mark.parametrize("word", ["гаранти", "100%", "точно", "безусловно", "profit"])
def test_guard_rejects_banned_phrases(word: str) -> None:
    out = guard({"p_radiant": 0.6, "reason": f"это {word} победа"}, _evidence())
    assert out["ok"] is False
    assert "запрещённая формулировка" in out["reason"]


def test_guard_detects_fabricated_numbers() -> None:
    """Число, которого не было в evidence — фабрикация."""
    out = guard({"p_radiant": 0.6, "reason": "у них винрейт 95% в последних 10 играх"}, _evidence())
    assert out["ok"] is False
    assert "фабрикация" in out["reason"]


def test_guard_allows_numbers_from_evidence() -> None:
    """0.875 и 4 были в evidence — пройти должна."""
    out = guard(
        {"p_radiant": 0.7, "reason": "Винрейт 0.875 при h2h 4:0", "key_factor": "форма"},
        _evidence(),
    )
    assert out["ok"] is True


# ── парсинг ответа ──────────────────────────────────────────────────────────


def test_parse_plain_json() -> None:
    out = parse_response('{"p_radiant": 0.6}')
    assert out["p_radiant"] == pytest.approx(0.6)


def test_parse_markdown_wrapped_json() -> None:
    out = parse_response('```json\n{"p_radiant": 0.6, "reason": "x"}\n```')
    assert out["p_radiant"] == pytest.approx(0.6)


def test_parse_rejects_garbage() -> None:
    with pytest.raises(ValueError):
        parse_response("никакого json тут нет")


# ── контракт промпта (LLM-002) ─────────────────────────────────────────────


def test_prompt_has_system_and_user_roles() -> None:
    msgs = build_messages(_evidence())
    roles = [m["role"] for m in msgs]
    assert roles == ["system", "user"]


def test_prompt_blocks_leakage_of_unknown_team() -> None:
    ev = _evidence()
    ev["dire"] = {"name": "NoName", "known": False, "games": 0, "note": "нет истории"}
    block = _evidence_block(ev)
    assert "истории нет" in block
    assert "NoName" in block


def test_prompt_mentions_only_pre_match_facts() -> None:
    block = _evidence_block(_evidence())
    # пост-матч данных в блоке быть не должно
    for bad in ["radiant_win", "final", "score 51", "KDA", "GPM"]:
        assert bad not in block


def test_prompt_versioned() -> None:
    assert PROMPT_VERSION.startswith("llm-analyst-")


# ── evidence: форма и h2h на синтетическом корпусе ──────────────────────────


def _corpus() -> list[dict]:
    """Три игры: A выиграла обе у B до cutoff, третья в будущем (отсеивается)."""
    return [
        # A на Radiant, выиграла
        {"match_id": 1, "start_time": 1000, "radiant_name": "A", "dire_name": "B", "radiant_win": True},
        # A на Dire, Radiant(B) проиграла → снова победа A
        {"match_id": 2, "start_time": 900, "radiant_name": "B", "dire_name": "A", "radiant_win": False},
        # игра после cutoff — утечка, не считается
        {"match_id": 3, "start_time": 2000, "radiant_name": "A", "dire_name": "B", "radiant_win": True},
    ]


def test_team_form_ignores_future_games() -> None:
    out = team_form(_corpus(), "A", cutoff_ts=1500, cache={})
    assert out["known"] is True
    # только игры 1 и 2 до cutoff: A выиграла обе
    assert out["games"] == 2
    assert out["winrate"] == pytest.approx(1.0)


def test_team_form_unknown_team() -> None:
    out = team_form(_corpus(), "Zzz", cutoff_ts=1500, cache={})
    assert out["known"] is False


def test_h2h_only_pre_cutoff() -> None:
    out = head_to_head(_corpus(), "A", "B", cutoff_ts=1500)
    assert out["games"] == 2
    assert out["A_wins"] == 2
    assert out["B_wins"] == 0


def test_h2h_no_games_returns_note() -> None:
    out = head_to_head(_corpus(), "A", "C", cutoff_ts=1500)
    assert out["games"] == 0


def test_build_evidence_shape() -> None:
    target = {
        "match_id": 999,
        "start_time": 1500,
        "league_name": "Test League",
        "series_type": 3,
        "patch": 60,
        "radiant_name": "A",
        "dire_name": "B",
    }
    ev = build_evidence(target, _corpus(), cache={})
    assert ev["match_id"] == 999
    assert ev["radiant"]["name"] == "A"
    assert ev["h2h"]["games"] == 2
