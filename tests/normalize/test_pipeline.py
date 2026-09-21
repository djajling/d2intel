"""DATA-001 — нормализация end-to-end на реальном raw-слое.

Тесты работают с настоящими `raw_payload`/`source_observation`, потому что
связность raw↔canonical — отдельное требование карточки (AC #1).
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.normalize.pipeline import normalize_once
from tests.normalize.helpers import (
    DEFAULT_OBSERVED,
    default_players,
    match_detail,
    patch_constants,
    pro_match,
    pro_match_at,
    seed_page,
)

BO3_MATCH_IDS = ("9000000001", "9000000002", "9000000003")


def seed_bo3(session: Session, offsets: tuple[int, ...] = (0, 60, 120)) -> None:
    """Полная Bo3: три карты одной серии."""
    payload = [
        pro_match_at(9000000001 + index, offset_minutes=offset)
        for index, offset in enumerate(offsets)
    ]
    seed_page(
        session,
        endpoint_kind="pro_matches",
        payload=payload,
        entity_ids=list(BO3_MATCH_IDS[: len(offsets)]),
    )


def seed_standalone(session: Session) -> None:
    """Одиночный матч (Bo1) вне серии."""
    payload = [pro_match(series_id=0, series_type=0)]
    seed_page(
        session, endpoint_kind="pro_matches", payload=payload, entity_ids=["9000000001"]
    )


# --- серии и карты -----------------------------------------------------------


def test_complete_bo3_is_normalized_with_map_numbers(db_session: Session) -> None:
    """Полная Bo3: одна серия, три карты с номерами 1..3, две команды, лига."""
    seed_bo3(db_session)
    stats = normalize_once(db_session)

    assert stats.created_series == 1
    assert stats.created_games == 3
    assert stats.created_teams == 2
    assert stats.created_tournaments == 1
    assert stats.created_game_teams == 6
    assert stats.quarantined == {}

    rows = db_session.execute(
        text("SELECT provider_match_id, map_number, status FROM game ORDER BY map_number")
    ).all()
    assert [row.provider_match_id for row in rows] == list(BO3_MATCH_IDS)
    assert [row.map_number for row in rows] == [1, 2, 3]


def test_repeated_normalization_is_idempotent(db_session: Session) -> None:
    """Повторный прогон не создаёт строк и не меняет записанное."""
    seed_bo3(db_session)
    first = normalize_once(db_session)
    second = normalize_once(db_session)

    assert first.created_games == 3
    assert second.created_games == 0
    assert second.created_series == 0
    assert second.created_teams == 0
    assert second.created_tournaments == 0
    assert second.created_game_teams == 0
    assert second.quarantined == {}

    total = db_session.execute(text("SELECT count(*) FROM game")).scalar_one()
    assert total == 3


def test_repeated_observation_does_not_break_series(db_session: Session) -> None:
    """Overlap-страницы повторно наблюдают те же матчи — серия не ломается.

    Повторное наблюдение не создаёт вторую карту и не превращает Bo3 в
    «карт больше, чем формат».
    """
    seed_bo3(db_session)
    payload = [
        pro_match_at(9000000001 + index, offset_minutes=offset)
        for index, offset in enumerate((0, 60, 120))
    ]
    seed_page(
        db_session,
        endpoint_kind="pro_matches",
        payload=payload,
        entity_ids=list(BO3_MATCH_IDS),
        observed_at=DEFAULT_OBSERVED + timedelta(hours=1),
    )
    stats = normalize_once(db_session)

    assert stats.created_games == 3
    assert stats.quarantined == {}
    assert db_session.execute(text("SELECT count(*) FROM game")).scalar_one() == 3


def test_canonical_rows_are_linked_to_raw_observation(db_session: Session) -> None:
    """AC #1: у каждой canonical-записи есть ссылка на наблюдение источника."""
    seeded = seed_page(
        db_session,
        endpoint_kind="pro_matches",
        payload=[pro_match(series_id=0, series_type=0)],
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)

    for table in ("team", "tournament", "series", "game", "game_team"):
        rows = db_session.execute(
            text(f"SELECT source_observation_id FROM {table}")  # noqa: S608 - константы
        ).all()
        assert rows, f"{table}: нет строк"
        assert all(str(row.source_observation_id) in seeded["observations"] for row in rows)


def test_canonical_row_without_provenance_is_rejected(db_session: Session) -> None:
    """Схема не даёт записать canonical-строку без ссылки на raw."""
    from sqlalchemy.exc import IntegrityError

    with pytest.raises(IntegrityError):
        db_session.execute(
            text(
                """
                INSERT INTO team (canonical_name, identity_status, observed_at, ingested_at, available_at)
                VALUES ('No Provenance', 'resolved', now(), now(), now())
                """
            )
        )


def test_team_without_name_is_unresolved(db_session: Session) -> None:
    """Имя команды неизвестно → NULL и `unresolved`, а не выдуманная подпись."""
    seed_page(
        db_session,
        endpoint_kind="pro_matches",
        payload=[pro_match(series_id=0, series_type=0, radiant_name=None)],
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)

    row = db_session.execute(
        text("SELECT canonical_name, identity_status FROM team WHERE canonical_name IS NULL")
    ).all()
    assert len(row) == 1
    assert row[0].identity_status == "unresolved"


# --- карантин неоднозначного map1 --------------------------------------------


def test_incomplete_series_goes_to_quarantine(db_session: Session) -> None:
    """AC #3: неоднозначный map1 — в карантин, а не в датасет."""
    seed_bo3(db_session, offsets=(0, 60))  # только две карты из трёх
    stats = normalize_once(db_session)

    assert stats.quarantined == {"incomplete_series": 2}
    assert stats.created_games == 2

    games = db_session.execute(text("SELECT map_number, status FROM game")).all()
    assert all(row.map_number is None for row in games)
    assert all(row.status == "map_index_unresolved" for row in games)

    open_rows = db_session.execute(
        text(
            """
            SELECT reason_code, status FROM normalization_quarantine
             WHERE job_kind = 'map_index'
            """
        )
    ).all()
    assert len(open_rows) == 2
    assert all(row.reason_code == "incomplete_series" for row in open_rows)
    assert all(row.status == "open" for row in open_rows)


def test_series_completion_resolves_quarantine(db_session: Session) -> None:
    """Когда недостающая карта приехала, номера назначаются, карантин закрыт."""
    seed_bo3(db_session, offsets=(0, 60))
    normalize_once(db_session)

    payload = [pro_match_at(9000000003, offset_minutes=120)]
    seed_page(db_session, endpoint_kind="pro_matches", payload=payload, entity_ids=["9000000003"])
    normalize_once(db_session)

    numbers = db_session.execute(
        text("SELECT map_number FROM game ORDER BY map_number")
    ).all()
    assert [row.map_number for row in numbers] == [1, 2, 3]

    resolved = db_session.execute(
        text("SELECT status FROM normalization_quarantine WHERE job_kind = 'map_index'")
    ).all()
    assert [row.status for row in resolved] == ["resolved", "resolved"]


def test_missing_team_identity_is_quarantined(db_session: Session) -> None:
    """Без идентичности команд карта не пишется вовсе: участников не определить."""
    seed_page(
        db_session,
        endpoint_kind="pro_matches",
        payload=[pro_match(series_id=0, series_type=0, radiant_team_id=None)],
        entity_ids=["9000000001"],
    )
    stats = normalize_once(db_session)

    assert stats.quarantined == {"missing_team_identity": 1}
    assert stats.created_games == 0
    assert db_session.execute(text("SELECT count(*) FROM game")).scalar_one() == 0


def test_missing_result_is_quarantined(db_session: Session) -> None:
    """Игра без исхода пригодна для хранения, но не как обучающий пример."""
    seed_page(
        db_session,
        endpoint_kind="pro_matches",
        payload=[pro_match(series_id=0, series_type=0, radiant_win=None)],
        entity_ids=["9000000001"],
    )
    stats = normalize_once(db_session)

    assert stats.quarantined == {"missing_result": 1}
    row = db_session.execute(text("SELECT winner_team_id, result_type FROM game")).one()
    assert row.winner_team_id is None
    assert row.result_type == "unknown"


def test_winner_is_bound_to_canonical_team(db_session: Session) -> None:
    """Победитель — каноническая команда (по `radiant_win`), не «Radiant»."""
    seed_page(
        db_session,
        endpoint_kind="pro_matches",
        payload=[pro_match(series_id=0, series_type=0, radiant_win=False)],
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)

    row = db_session.execute(
        text(
            """
            SELECT t.canonical_name
              FROM game g JOIN team t ON t.id = g.winner_team_id
            """
        )
    ).one()
    assert row.canonical_name == "Team Dire"


# --- патчи -------------------------------------------------------------------


def test_patch_is_assigned_by_game_start(db_session: Session) -> None:
    """Патч карты вычисляется из времени старта, а не из «текущего» патча."""
    seed_page(
        db_session,
        endpoint_kind="patch_constants",
        payload=patch_constants(),
        entity_ids=["patch"],
    )
    seed_standalone(db_session)
    stats = normalize_once(db_session)

    assert stats.created_patches == 3
    row = db_session.execute(
        text("SELECT p.version_label FROM game g JOIN patch p ON p.id = g.patch_id")
    ).one()
    assert row.version_label == "7.41"


def test_patch_intervals_do_not_overlap(db_session: Session) -> None:
    """Граница патча — начало следующего; у последнего интервал открыт."""
    seed_page(
        db_session,
        endpoint_kind="patch_constants",
        payload=patch_constants(),
        entity_ids=["patch"],
    )
    normalize_once(db_session)

    rows = db_session.execute(
        text("SELECT version_label, effective_from, effective_to FROM patch ORDER BY effective_from")
    ).all()
    assert [row.version_label for row in rows] == ["7.39", "7.40", "7.41"]
    assert rows[0].effective_to == rows[1].effective_from
    assert rows[-1].effective_to is None


# --- участники, статистика, свидетельства состава ----------------------------


def test_match_detail_writes_participants_and_roster(db_session: Session) -> None:
    """Десять участников: статистика, финальные метрики и свидетельства состава."""
    seed_standalone(db_session)
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001),
        entity_ids=["9000000001"],
    )
    stats = normalize_once(db_session)

    assert stats.created_participants == 10
    assert stats.created_performances == 10
    assert stats.created_roster_memberships == 10
    assert stats.created_players == 10

    sides = db_session.execute(
        text(
            """
            SELECT gp.slot, t.canonical_name
              FROM game_participant gp JOIN team t ON t.id = gp.team_id
             ORDER BY gp.slot
            """
        )
    ).all()
    assert len({row.canonical_name for row in sides}) == 2
    assert [row.slot for row in sides] == list(range(10))


def test_roster_rows_are_not_overwritten(db_session: Session) -> None:
    """AC #2 / «нет перезаписи ростеров»: повторный прогон не меняет свидетельства."""
    seed_standalone(db_session)
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001),
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)
    before = db_session.execute(
        text(
            """
            SELECT team_id, player_id, game_id, valid_from, valid_to
              FROM roster_membership ORDER BY team_id, player_id
            """
        )
    ).all()

    second = normalize_once(db_session)
    after = db_session.execute(
        text(
            """
            SELECT team_id, player_id, game_id, valid_from, valid_to
              FROM roster_membership ORDER BY team_id, player_id
            """
        )
    ).all()

    assert second.created_roster_memberships == 0
    assert [tuple(row) for row in before] == [tuple(row) for row in after]


def test_roster_membership_interval_covers_the_game(db_session: Session) -> None:
    """Интервал свидетельства — время карты, а не «с какого-то числа по настоящее»."""
    seed_standalone(db_session)
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001),
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)

    row = db_session.execute(
        text("SELECT valid_from, valid_to FROM roster_membership LIMIT 1")
    ).one()
    assert row.valid_to is not None
    assert (row.valid_to - row.valid_from).total_seconds() == 1800


def test_match_detail_without_series_context_is_quarantined(db_session: Session) -> None:
    """Без контекста серии номер карты неопределён → участники не пишутся."""
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001),
        entity_ids=["9000000001"],
    )
    stats = normalize_once(db_session)

    assert stats.quarantined == {"missing_series_context": 1}
    assert stats.created_participants == 0


def test_missing_player_identity_is_quarantined(db_session: Session) -> None:
    """Участник без `account_id` — игрока нельзя канонизировать."""
    seed_standalone(db_session)
    players = default_players(9000000001)
    players[0]["account_id"] = None
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001, players=players),
        entity_ids=["9000000001"],
    )
    stats = normalize_once(db_session)

    assert stats.quarantined == {"missing_player_identity": 1}
    assert stats.created_participants == 0


def test_final_stats_are_marked_and_separate(db_session: Session) -> None:
    """AC #5: финальная статистика — отдельная таблица с маркером `final`.

    Pre-match слой читает `game_participant`; у него нет колонок статистики.
    """
    seed_standalone(db_session)
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001),
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)

    classes = db_session.execute(
        text("SELECT DISTINCT data_class FROM player_performance")
    ).all()
    assert [row.data_class for row in classes] == ["final"]

    participant_columns = {
        row[0]
        for row in db_session.execute(
            text(
                """
                SELECT column_name FROM information_schema.columns
                 WHERE table_name = 'game_participant'
                """
            )
        )
    }
    for forbidden in ("kills", "deaths", "assists", "gold_per_min", "net_worth"):
        assert forbidden not in participant_columns


def test_entity_mapping_links_provider_to_canonical(db_session: Session) -> None:
    """Маппинг provider → canonical пишется для команд, игроков и лиг."""
    seed_standalone(db_session)
    seed_page(
        db_session,
        endpoint_kind="match_detail",
        payload=match_detail(9000000001),
        entity_ids=["9000000001"],
    )
    normalize_once(db_session)

    mapping = db_session.execute(
        text("SELECT entity_type, external_id FROM entity_mapping ORDER BY entity_type, external_id")
    ).all()
    kinds = {row.entity_type for row in mapping}
    assert kinds == {"player", "team", "tournament"}
    assert any(row.entity_type == "team" and row.external_id == "36" for row in mapping)
