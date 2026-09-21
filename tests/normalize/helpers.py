"""Общие помощники тестов нормализации (DATA-001).

Помощники создают raw-слой таким же способом, как `ING-001`: один
`raw_payload` на страницу + отдельное `source_observation` на запись. Тесты
нормализации обязаны работать с настоящим raw, иначе проверка связности
raw↔canonical ничего не проверяет.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.ingestion.contracts import OPENDOTA_SOURCE_ID

DEFAULT_START = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
DEFAULT_OBSERVED = datetime(2026, 9, 2, 9, 0, tzinfo=UTC)


def ensure_source(session: Session, name: str = OPENDOTA_SOURCE_ID) -> str:
    """`data_source` по имени. Создаёт при отсутствии (идемпотентно)."""
    existing = session.execute(
        text("SELECT id FROM data_source WHERE name = :name"), {"name": name}
    ).scalar()
    if existing is not None:
        return str(existing)
    created = session.execute(
        text(
            """
            INSERT INTO data_source (name, adapter_version, capabilities, created_at)
            VALUES (:name, 'test', CAST('{}' AS jsonb), now())
            RETURNING id
            """
        ),
        {"name": name},
    ).scalar_one()
    return str(created)


def seed_page(
    session: Session,
    *,
    endpoint_kind: str,
    payload: Any,
    entity_ids: Sequence[str],
    observed_at: datetime = DEFAULT_OBSERVED,
    source_name: str = OPENDOTA_SOURCE_ID,
) -> dict[str, Any]:
    """Записать страницу raw и наблюдения по записям.

    Возвращает `{"source", "run", "raw_payload", "observations"}`, где
    `observations` — список id в порядке `entity_ids`.
    """
    source_id = ensure_source(session, source_name)
    run_id = session.execute(
        text(
            """
            INSERT INTO ingestion_run (source_id, started_at, status)
            VALUES (:source_id, :started_at, 'completed')
            RETURNING id
            """
        ),
        {"source_id": source_id, "started_at": observed_at},
    ).scalar_one()
    content_hash = hashlib.sha256(
        json.dumps(payload, sort_keys=True, default=str).encode("utf-8")
    ).hexdigest()
    raw_id = session.execute(
        text(
            """
            INSERT INTO raw_payload (
                source_id, endpoint_kind, content_hash, schema_version, payload_json,
                event_time, observed_at, ingested_at, available_at
            ) VALUES (
                :source_id, :endpoint_kind, :content_hash, 'test.v1',
                CAST(:payload_json AS jsonb), :event_time, :observed_at, :observed_at, :observed_at
            )
            ON CONFLICT (source_id, content_hash) DO NOTHING
            RETURNING id
            """
        ),
        {
            "source_id": source_id,
            "endpoint_kind": endpoint_kind,
            "content_hash": content_hash,
            "payload_json": json.dumps(payload, default=str),
            "event_time": observed_at,
            "observed_at": observed_at,
        },
    ).scalar()
    if raw_id is None:
        raw_id = session.execute(
            text(
                "SELECT id FROM raw_payload WHERE source_id = :source_id AND content_hash = :hash"
            ),
            {"source_id": source_id, "hash": content_hash},
        ).scalar_one()

    observation_ids: list[str] = []
    for entity_id in entity_ids:
        observation_id = session.execute(
            text(
                """
                INSERT INTO source_observation (
                    run_id, raw_payload_id, provider_entity_id, provider_entity_type,
                    observed_at, ingested_at, available_at
                ) VALUES (
                    :run_id, :raw_payload_id, :provider_entity_id, :endpoint_kind,
                    :observed_at, :observed_at, :observed_at
                )
                RETURNING id
                """
            ),
            {
                "run_id": run_id,
                "raw_payload_id": raw_id,
                "provider_entity_id": entity_id,
                "endpoint_kind": endpoint_kind,
                "observed_at": observed_at,
            },
        ).scalar_one()
        observation_ids.append(str(observation_id))
    session.flush()
    return {
        "source": source_id,
        "run": str(run_id),
        "raw_payload": str(raw_id),
        "observations": observation_ids,
    }


# --- фабрики payload ---------------------------------------------------------


def pro_match(**overrides: Any) -> dict[str, Any]:
    """Запись `/api/proMatches`. Значения по умолчанию — Bo3, карта в серии."""
    base: dict[str, Any] = {
        "match_id": 9000000001,
        "duration": 1800,
        "start_time": int(DEFAULT_START.timestamp()),
        "leagueid": 20279,
        "league_name": "Test League",
        "radiant_team_id": 36,
        "radiant_name": "Team Radiant",
        "dire_team_id": 2586976,
        "dire_name": "Team Dire",
        "series_id": 1145136,
        "series_type": 1,
        "radiant_score": 30,
        "dire_score": 21,
        "radiant_win": True,
    }
    base.update(overrides)
    return base


def pro_match_at(match_id: int, offset_minutes: int, **overrides: Any) -> dict[str, Any]:
    """Запись со стартом, сдвинутым на `offset_minutes` от базового времени."""
    start = DEFAULT_START + timedelta(minutes=offset_minutes)
    overrides.setdefault("match_id", match_id)
    overrides["start_time"] = int(start.timestamp())
    return pro_match(**overrides)


def player_entry(account_id: int, *, radiant: bool = True, position: int = 0) -> dict[str, Any]:
    """Элемент `players[]` детального ответа."""
    return {
        "account_id": account_id,
        "hero_id": 10 + position,
        "player_slot": position if radiant else position + 128,
        "isRadiant": radiant,
        "kills": 5 + position,
        "deaths": 2,
        "assists": 7,
        "net_worth": 20000,
        "gold_per_min": 550,
        "xp_per_min": 600,
        "last_hits": 300,
        "denies": 10,
        "hero_damage": 25000,
    }


def match_detail(
    match_id: int,
    *,
    players: Sequence[dict[str, Any]] | None = None,
    **overrides: Any,
) -> dict[str, Any]:
    """Ответ `/api/matches/{id}`."""
    roster = list(players) if players is not None else default_players(match_id)
    base: dict[str, Any] = {
        "match_id": match_id,
        "start_time": int(DEFAULT_START.timestamp()),
        "duration": 1800,
        "radiant_win": True,
        "players": roster,
    }
    base.update(overrides)
    return base


def default_players(match_id: int) -> list[dict[str, Any]]:
    """Десять участников: пять Radiant (слотами 0..4) и пять Dire (5..9)."""
    return [
        player_entry(match_id * 10 + index, radiant=index < 5, position=index % 5)
        for index in range(10)
    ]


def patch_constants() -> list[dict[str, Any]]:
    """Справочник патчей: три записи, границы интервалов вычисляются на месте."""
    return [
        {"id": 58, "name": "7.39", "date": "2025-05-22"},
        {"id": 59, "name": "7.40", "date": "2025-12-16"},
        {"id": 60, "name": "7.41", "date": "2026-03-24"},
    ]
