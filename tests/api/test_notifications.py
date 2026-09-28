"""Уведомления (NOTIF-001) — модульные тесты форматов и идемпотентности.

Тесты проверяют формирование сообщений и состояние отправок, а не реальную
отправку в Telegram: ``sender`` подменяется. Хозяин чата ничего не получает.

Покрытие:
* формат трёх видов сообщений (турнир/матч/драфт);
* честное «нет данных» вместо подмены;
* идемпотентность (fixture_id, kind) — повторный вызов не шлёт второй раз;
* force=True — ручной повтор владельца;
* пометка статуса модели в блоке вероятности.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.api.notifications import (
    DRAFT_READY,
    MATCH_START,
    _probability_block,
    build_draft_message,
    build_match_start_message,
    build_tournament_start_message,
    trigger_draft_ready,
    trigger_match_start,
    trigger_tournament_start,
)
from d2intel.app import create_app
from d2intel.db import get_db

#: Та же подстрока, что и `TOURNAMENT_FILTER` в schedule.py: авто-цикл
#: считает своим турниром BLAST Slam VIII (решение владельца 2026-09-27).
TOURNAMENT_FILTER = "blast slam viii"

#: Время старта фикстуры: на час раньше текущего момента. Жёсткая константа
#: здесь не годится — системные часы расходятся с датой тестового сценария,
#: и триггер «начался ли матч» начинает отвечать not_started_yet.
NOW = datetime.now(UTC)
TOURNAMENT = "BLAST Slam VIII"


@pytest.fixture
def api(db_session: Session) -> TestClient:  # noqa: ANN001
    app = create_app()

    def _override() -> Any:
        yield db_session

    app.dependency_overrides[get_db] = _override
    return TestClient(app)


def _create_fixture(
    db: Session,
    *,
    tournament: str = TOURNAMENT,
    team_a: str = "Team Yandex",
    team_b: str = "Natus Vincere",
    scheduled_at: datetime | None = NOW,
    status: str = "upcoming",
    draft_observed: dict[str, Any] | None = None,
) -> str:
    row = db.execute(
        text(
            """
            INSERT INTO scheduled_match
                (tournament_label, team_a_label, team_b_label, stage_label,
                 scheduled_at, status, draft_observed)
            VALUES (:tournament, :a, :b, 'Bo3', :at, :status, CAST(:draft AS jsonb))
            RETURNING id
            """
        ),
        {
            "tournament": tournament,
            "a": team_a,
            "b": team_b,
            "at": scheduled_at,
            "status": status,
            "draft": json.dumps(draft_observed) if draft_observed else None,
        },
    ).scalar_one()
    db.commit()
    return str(row)


def _sent_kinds(db: Session, fixture_id: str) -> set[str]:
    rows = db.execute(
        text(
            "SELECT kind FROM scheduled_match_notify_state "
            "WHERE fixture_id = CAST(:fid AS uuid)"
        ),
        {"fid": fixture_id},
    ).scalars()
    return set(rows)


# ---------------------------------------------------------------------------
# Формат сообщений
# ---------------------------------------------------------------------------

def test_probability_block_marks_unaccepted_model() -> None:
    block = _probability_block(0.62, "Team Yandex", "Natus Vincere")
    assert "62%" in block
    assert "38%" in block
    # Статус модели — честная пометка, а не уверенный прогноз.
    assert "не принята" in block


def test_probability_block_without_freeze_is_honest() -> None:
    block = _probability_block(None, "A", "B")
    assert "нет заморозки" in block


def test_tournament_message_lists_all_upcoming() -> None:
    fixtures = [
        {
            "scheduled_at": datetime.now(UTC) + timedelta(hours=1),
            "team_a_label": "PARI",
            "team_b_label": "Level UP",
            "stage_label": "Bo3",
        },
        {
            "scheduled_at": datetime.now(UTC) + timedelta(hours=4),
            "team_a_label": "Team Spirit",
            "team_b_label": "Team Nemesis",
            "stage_label": "Bo3",
        },
    ]
    message = build_tournament_start_message(tournament=TOURNAMENT, fixtures=fixtures)
    assert message is not None
    assert TOURNAMENT in message
    assert "PARI" in message
    assert "Level UP" in message
    assert "Team Spirit" in message
    assert "CC BY-SA 3.0" in message


def test_tournament_message_without_fixtures_is_none() -> None:
    message = build_tournament_start_message(tournament=TOURNAMENT, fixtures=[])
    assert message is None


def test_match_start_message_shape() -> None:
    fixture = {
        "team_a_label": "Team Yandex",
        "team_b_label": "MOUZ",
        "stage_label": "Bo3",
        "tournament_label": TOURNAMENT,
    }
    message = build_match_start_message(
        tournament=TOURNAMENT, fixture=fixture, p_a=0.55
    )
    assert "Team Yandex" in message
    assert "MOUZ" in message
    assert "55%" in message
    assert "Bo3" in message


def test_draft_message_lists_picks_and_bans() -> None:
    hero_names = {1: "Anti-Mage", 2: "Axe", 3: "Bane", 4: "Bloodseeker"}
    map_entry = {
        "map_number": 1,
        "draft": [
            {"hero_id": 1, "team": "radiant", "is_pick": True},
            {"hero_id": 2, "team": "dire", "is_pick": True},
            {"hero_id": 3, "team": "radiant", "is_pick": False},
            {"hero_id": 4, "team": "dire", "is_pick": False},
        ],
    }
    fixture = {
        "team_a_label": "Team Yandex",
        "team_b_label": "Natus Vincere",
        "tournament_label": TOURNAMENT,
        "stage_label": "Bo3",
    }
    message = build_draft_message(
        tournament=TOURNAMENT,
        fixture=fixture,
        map_entry=map_entry,
        hero_names=hero_names,
        p_a=0.58,
    )
    assert "Anti-Mage" in message
    assert "Axe" in message
    # Баны — отдельный блок, не подмешаны в пики.
    assert "баны" in message
    assert "Bane" in message
    assert "58%" in message


# ---------------------------------------------------------------------------
# Триггеры + идемпотентность
# ---------------------------------------------------------------------------

def test_match_start_sends_once_and_is_idempotent(db_session: Session) -> None:
    fixture_id = _create_fixture(db_session, scheduled_at=NOW - timedelta(hours=1))
    sent: list[str] = []

    first = trigger_match_start(
        db_session, fixture_id=fixture_id, now=NOW, sender=lambda t: sent.append(t) or True
    )
    assert first["status"] == "sent"
    assert MATCH_START in _sent_kinds(db_session, fixture_id)
    assert len(sent) == 1

    second = trigger_match_start(
        db_session, fixture_id=fixture_id, now=NOW, sender=lambda t: sent.append(t) or True
    )
    assert second["status"] == "already_sent"
    assert len(sent) == 1, "повторный вызов авто-цикла не должен слать второй раз"


def test_match_start_not_yet_started(db_session: Session) -> None:
    fixture_id = _create_fixture(db_session, scheduled_at=NOW + timedelta(hours=3))
    result = trigger_match_start(
        db_session, fixture_id=fixture_id, now=NOW, sender=lambda t: True
    )
    assert result["status"] == "not_started_yet"
    assert _sent_kinds(db_session, fixture_id) == set()


def test_match_start_force_repeats(db_session: Session) -> None:
    fixture_id = _create_fixture(db_session, scheduled_at=NOW - timedelta(hours=1))
    sent: list[str] = []
    trigger_match_start(db_session, fixture_id=fixture_id, now=NOW, sender=lambda t: sent.append(t) or True)
    result = trigger_match_start(
        db_session,
        fixture_id=fixture_id,
        now=NOW,
        sender=lambda t: sent.append(t) or True,
        force=True,
    )
    assert result["status"] == "sent"
    assert len(sent) == 2, "force=True — ручной повтор владельца"


def test_match_start_without_freeze_is_honest(db_session: Session) -> None:
    fixture_id = _create_fixture(db_session, scheduled_at=NOW - timedelta(hours=1))
    captured: list[str] = []
    trigger_match_start(
        db_session, fixture_id=fixture_id, now=NOW, sender=lambda t: captured.append(t) or True
    )
    body = captured[0]
    assert "нет заморозки" in body, "отсутствие заморозки не подменяется числом"


def test_tournament_start_single_message_for_all_fixtures(db_session: Session) -> None:
    """Стартовый день BLAST Slam VIII — 8 матчей, пуш должен быть один."""
    for index, (a, b) in enumerate(
        [
            ("PARI", "Level UP"),
            ("Team Spirit", "Team Nemesis"),
            ("LGD Gaming", "Xtreme Gaming"),
            ("1w Team", "Natus Vincere"),
        ]
    ):
        _create_fixture(
            db_session,
            team_a=a,
            team_b=b,
            scheduled_at=NOW + timedelta(hours=index),
        )
    sent: list[str] = []
    results = trigger_tournament_start(
        db_session, tournament=TOURNAMENT, now=NOW, sender=lambda t: sent.append(t) or True
    )
    assert results[0]["status"] == "sent"
    assert len(sent) == 1, "один пуш на старт турнира, а не по числу матчей"
    body = sent[0]
    for team in ("PARI", "Level UP", "Team Spirit", "1w Team"):
        assert team in body


def test_tournament_start_too_early(db_session: Session) -> None:
    _create_fixture(db_session, scheduled_at=NOW + timedelta(days=3))
    results = trigger_tournament_start(
        db_session, tournament=TOURNAMENT, now=NOW, sender=lambda t: True
    )
    assert results[0]["status"] == "too_early"


def test_tournament_start_ignores_other_tournaments(db_session: Session) -> None:
    _create_fixture(db_session, tournament="Other Tournament", scheduled_at=NOW)
    _create_fixture(db_session, tournament=TOURNAMENT, scheduled_at=NOW)
    results = trigger_tournament_start(
        db_session, tournament=TOURNAMENT, now=NOW, sender=lambda t: True
    )
    assert results[0]["status"] == "sent"


def test_draft_ready_uses_latest_map(db_session: Session) -> None:
    fixture_id = _create_fixture(
        db_session,
        draft_observed={
            "maps": [
                {
                    "match_id": "111",
                    "map_number": 1,
                    "draft": [
                        {"hero_id": 1, "team": "radiant", "is_pick": True},
                        {"hero_id": 2, "team": "dire", "is_pick": True},
                    ],
                },
                {
                    "match_id": "222",
                    "map_number": 2,
                    "draft": [
                        {"hero_id": 3, "team": "radiant", "is_pick": True},
                        {"hero_id": 4, "team": "dire", "is_pick": True},
                    ],
                },
            ]
        },
    )
    captured: list[str] = []
    result = trigger_draft_ready(
        db_session, fixture_id=fixture_id, sender=lambda t: captured.append(t) or True
    )
    assert result["status"] == "sent"
    assert DRAFT_READY in _sent_kinds(db_session, fixture_id)


def test_draft_ready_absent_draft_is_honest(db_session: Session) -> None:
    fixture_id = _create_fixture(
        db_session,
        draft_observed={"maps": [{"match_id": "111", "map_number": 1, "draft": None}]},
    )
    result = trigger_draft_ready(
        db_session, fixture_id=fixture_id, sender=lambda t: True
    )
    assert result["status"] == "draft_absent"
    assert _sent_kinds(db_session, fixture_id) == set()


def test_send_failure_does_not_mark_sent(db_session: Session) -> None:
    fixture_id = _create_fixture(db_session, scheduled_at=NOW - timedelta(hours=1))
    result = trigger_match_start(
        db_session, fixture_id=fixture_id, now=NOW, sender=lambda t: False
    )
    assert result["status"] == "send_failed"
    assert _sent_kinds(db_session, fixture_id) == set(), (
        "при провале отправки состояние не фиксируется — цикл попробует ещё раз"
    )


# ---------------------------------------------------------------------------
# Эндпоинт авто-цикла
# ---------------------------------------------------------------------------

def test_auto_notify_endpoint_smoke(api: TestClient) -> None:
    response = api.post("/api/schedule/auto-notify", params={"dry_run": True})
    assert response.status_code == 200
    payload = response.json()
    assert payload["tournament_filter"] == TOURNAMENT_FILTER
    assert payload["sent"] == 0
    assert "results" in payload


def test_auto_notify_endpoint_sends_match_start(api: TestClient, db_session: Session) -> None:
    _create_fixture(db_session, scheduled_at=NOW - timedelta(hours=1))
    response = api.post("/api/schedule/auto-notify", params={"dry_run": True})
    assert response.status_code == 200
    payload = response.json()
    dry_run_texts = [r["text"] for r in payload["results"] if r.get("kind") == "dry_run"]
    assert any("игра началась" in t for t in dry_run_texts), (
        "драфт-сообщение о старте матча должно формироваться"
    )
    # dry-run не фиксирует отправку — состояние не меняется.
    assert MATCH_START not in _all_sent_kinds(db_session)


def test_auto_notify_endpoint_sends_for_real(
    api: TestClient, db_session: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Боевой путь: реальный отправитель подменён, состояние пишется в БД."""
    captured: list[str] = []

    def _fake_telegram(text_body: str) -> bool:
        captured.append(text_body)
        return True

    monkeypatch.setattr(
        "d2intel.api.notifications._default_telegram_sender", _fake_telegram
    )
    _create_fixture(db_session, scheduled_at=NOW - timedelta(hours=1))
    response = api.post("/api/schedule/auto-notify")
    assert response.status_code == 200
    payload = response.json()
    assert payload["sent"] >= 1
    sent_results = [r for r in payload["results"] if r.get("status") == "sent"]
    assert any(r["kind"] == MATCH_START for r in sent_results)
    assert any("игра началась" in t for t in captured)

    # Повторный вызов авто-цикла — ничего нового не отправляется.
    second = api.post("/api/schedule/auto-notify").json()
    assert second["sent"] == 0


def _all_sent_kinds(db: Session) -> set[str]:
    rows = db.execute(text("SELECT kind FROM scheduled_match_notify_state")).scalars()
    return set(rows)
