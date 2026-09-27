"""Сбор драфтов доигранных карт (scripts/collect_drafts.py) — без сети.

Защищают три честных правила:

* номер карты не придумывается: `map_number = null` + `map_number_status`
  = unresolved, когда серия не закрыта (ADR-006, то же правило, что у
  prospective_reconcile);
* отсутствие picks_bans в источнике не подменяется пустым списком — это
  «нет данных», а не «драфта не было»;
* ручной ввод владельца в draft_observed не перетирается: добавляется только
  `maps`/`source`/`collected_at`.
"""

from __future__ import annotations

from datetime import datetime, timezone

from scripts.collect_drafts import build_map_entry, merge_maps

GAME = {
    "game_id": "d9dbec73-eb90-5bac-adad-206fb90a85d1",
    "map_number": None,
    "status": "map_index_unresolved",
    "provider_match_id": "9018736585",
    "event_time": datetime(2026, 9, 27, 15, 52, 7, tzinfo=timezone.utc),
    "winner_team_id": "b22c1f38-cd0d-5d89-a5c3-648f75d4bb03",
}


def _payload(picks: list[dict] | None) -> dict:
    payload = {
        "match_id": 9018736585,
        "radiant_win": False,
        "duration": 1510,
        "leagueid": 20279,
        "series_id": 1147599,
    }
    if picks is not None:
        payload["picks_bans"] = picks
    return payload


def test_unresolved_map_number_is_marked_not_invented() -> None:
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload([{"is_pick": False, "hero_id": 145, "team": 1, "order": 0}]),
        hero_names={145: "Kez"},
        cutoff_source="freeze_cutoff",
    )
    assert entry["map_number"] is None
    assert entry["map_number_status"] == "unresolved"
    assert entry["game_status"] == "map_index_unresolved"
    assert entry["draft_status"] == "ok"


def test_proven_map_number_is_kept() -> None:
    game = dict(GAME, map_number=1, status="completed")
    entry = build_map_entry(
        game=game,
        payload=_payload([{"is_pick": True, "hero_id": 1, "team": 0, "order": 1}]),
        hero_names={1: "Anti-Mage"},
        cutoff_source="freeze_cutoff",
    )
    assert entry["map_number"] == 1
    assert entry["map_number_status"] == "proven"


def test_absent_picks_bans_is_not_empty_list() -> None:
    """Нет данных ≠ пусто: draft остаётся null, а не []."""
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload(picks=None),
        hero_names={},
        cutoff_source="freeze_cutoff",
    )
    assert entry["draft"] is None
    assert entry["draft_status"] == "absent_in_source"


def test_empty_picks_bans_also_counts_as_absent() -> None:
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload(picks=[]),
        hero_names={},
        cutoff_source="freeze_cutoff",
    )
    assert entry["draft"] is None
    assert entry["draft_status"] == "absent_in_source"


def test_side_mapping_matches_opendota_convention() -> None:
    """team 0 = radiant, 1 = dire — сверено с ручным вводом владельца."""
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload(
            [
                {"is_pick": False, "hero_id": 145, "team": 1, "order": 0},
                {"is_pick": True, "hero_id": 1, "team": 0, "order": 1},
            ]
        ),
        hero_names={145: "Kez", 1: "Anti-Mage"},
        cutoff_source="freeze_cutoff",
    )
    assert [row["team"] for row in entry["draft"]] == ["dire", "radiant"]
    assert [row["hero"] for row in entry["draft"]] == ["Kez", "Anti-Mage"]


def test_unknown_hero_keeps_id_and_null_name() -> None:
    """Неизвестное имя героя не подменяется ни строкой, ни id."""
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload([{"is_pick": True, "hero_id": 987654, "team": 0, "order": 0}]),
        hero_names={},
        cutoff_source="freeze_cutoff",
    )
    assert entry["draft"][0]["hero"] is None
    assert entry["draft"][0]["hero_id"] == 987654


def test_merge_preserves_owner_manual_entry() -> None:
    manual = {
        "draft": [{"hero": "Kez", "team": "dire", "order": 0, "is_pick": False}],
        "match_id": "9018736585",
        "radiant_win": False,
    }
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload([{"is_pick": False, "hero_id": 145, "team": 1, "order": 0}]),
        hero_names={145: "Kez"},
        cutoff_source="freeze_cutoff",
    )
    merged = merge_maps(manual, [entry])
    assert merged["draft"] == manual["draft"]
    assert merged["match_id"] == "9018736585"
    assert merged["radiant_win"] is False
    assert merged["source"] == "opendota_matches_api"
    assert merged["collected_at"]
    assert len(merged["maps"]) == 1


def test_merge_is_idempotent_by_match_id() -> None:
    entry = build_map_entry(
        game=dict(GAME),
        payload=_payload([{"is_pick": False, "hero_id": 145, "team": 1, "order": 0}]),
        hero_names={145: "Kez"},
        cutoff_source="freeze_cutoff",
    )
    once = merge_maps({}, [entry])
    twice = merge_maps(once, [entry])
    assert len(twice["maps"]) == 1
    assert twice["maps"][0]["match_id"] == "9018736585"


def test_merge_keeps_existing_maps_and_orders_by_time() -> None:
    first = build_map_entry(
        game=dict(GAME, map_number=1, status="completed"),
        payload=_payload([{"is_pick": True, "hero_id": 1, "team": 0, "order": 1}]),
        hero_names={1: "Anti-Mage"},
        cutoff_source="freeze_cutoff",
    )
    second = build_map_entry(
        game=dict(
            GAME,
            game_id="703aaac9-cf93-5628-a9f2-4d9a84be93c4",
            provider_match_id="9018700000",
            map_number=2,
            status="completed",
            event_time=datetime(2026, 9, 27, 17, 0, 0, tzinfo=timezone.utc),
        ),
        payload=_payload([{"is_pick": True, "hero_id": 36, "team": 1, "order": 1}]),
        hero_names={36: "Necrophos"},
        cutoff_source="freeze_cutoff",
    )
    merged = merge_maps({}, [second, first])
    assert [item["match_id"] for item in merged["maps"]] == ["9018736585", "9018700000"]
    assert [item["map_number"] for item in merged["maps"]] == [1, 2]
