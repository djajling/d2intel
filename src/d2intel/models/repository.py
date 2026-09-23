"""Запись предсказаний в канонический слой (схема из миграции 0001).

Три таблицы:

- `prediction` — **запрос** на предсказание цели. Изменяемая (триггера нет),
  идемпотентна по `request_key`: повторный прогон не плодит дубликаты целей.
- `prediction_snapshot` — **неизменяемый** результат: триггер
  `prediction_snapshot_no_mutation` запрещает UPDATE/DELETE. Новая версия
  модели = новый `snapshot_seq`, а не перезапись старого.
- `prediction_evaluation` — сверка снимка с фактом: `y`, `log_loss`, `brier`.

`idempotency_key` на снимке делает повторный прогон того же прогона модели
no-op'ом: скрипт можно перезапускать, не боясь задвоить снимки.

Режим `retrospective_reconstructed` — это бэктест на известных результатах.
Ограничение зафиксировано в ADR-006 и `docs/EVALUATION.md`: реальное время
доступности фикстур источником не сообщается, поэтому retrospective cutoff
равен `event_time` — это **не консервативная** оценка.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

INSERT_PREDICTION = """
    INSERT INTO prediction (
        target_type, target_game_id, team_a_id, team_b_id, phase_contract, request_key
    ) VALUES (
        'game', :game_id, :team_a_id, :team_b_id, :phase_contract, :request_key
    )
    ON CONFLICT (request_key) DO UPDATE SET request_key = EXCLUDED.request_key
    RETURNING id
"""

SELECT_SNAPSHOT_BY_IDEM = """
    SELECT id FROM prediction_snapshot WHERE idempotency_key = :idempotency_key
"""

NEXT_SNAPSHOT_SEQ = """
    SELECT COALESCE(max(snapshot_seq), 0) + 1
      FROM prediction_snapshot
     WHERE prediction_id = :prediction_id
"""

INSERT_PREDICTION_SNAPSHOT = """
    INSERT INTO prediction_snapshot (
        prediction_id, snapshot_seq, computed_at, cutoff_at, model_version_id,
        p_a, p_b, abstention_reason, evaluation_mode, state_hash, idempotency_key,
        event_time, observed_at, ingested_at, available_at
    ) VALUES (
        :prediction_id, :snapshot_seq, now(), :cutoff_at, :model_version_id,
        :p_a, :p_b, :abstention_reason, 'retrospective_reconstructed',
        :state_hash, :idempotency_key,
        :event_time, now(), now(), now()
    )
    RETURNING id
"""

INSERT_PREDICTION_EVALUATION = """
    INSERT INTO prediction_evaluation (
        snapshot_id, metric_definition_version, y, log_loss, brier
    ) VALUES (
        :snapshot_id, :metric_definition_version, :y, :log_loss, :brier
    )
    RETURNING id
"""

SELECT_PREDICTION_EVALUATION = """
    SELECT id
      FROM prediction_evaluation
     WHERE snapshot_id = :snapshot_id
       AND metric_definition_version = :metric_definition_version
       AND result_revision_id IS NULL
     LIMIT 1
"""


def prediction_request_key(game_id: UUID) -> str:
    """Детерминированный ключ цели: одна карта — один запрос на предсказание."""
    return f"game1:pre_draft:{game_id}"


def snapshot_idempotency_key(game_id: UUID, model_version_id: UUID) -> str:
    """Ключ идемпотентности: один прогон модели на одной цели — один снимок."""
    return f"game1:{game_id}:model:{model_version_id}"


def snapshot_state_hash(
    *,
    prediction_id: UUID,
    model_version_id: UUID,
    cutoff_at: datetime,
    p_a: float | None,
) -> str:
    """Хэш состояния снимка — для проверки воспроизводимости."""
    payload = f"{prediction_id}|{model_version_id}|{cutoff_at.isoformat()}|{p_a}"
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def upsert_prediction(
    session: Session,
    *,
    game_id: UUID,
    team_a_id: UUID,
    team_b_id: UUID,
    phase_contract: str = "pre_draft",
) -> UUID:
    """Получить (или создать) запись цели предсказания."""
    row = session.execute(
        text(INSERT_PREDICTION),
        {
            "game_id": str(game_id),
            "team_a_id": str(team_a_id),
            "team_b_id": str(team_b_id),
            "phase_contract": phase_contract,
            "request_key": prediction_request_key(game_id),
        },
    ).scalar_one()
    return UUID(str(row))


def append_prediction_snapshot(
    session: Session,
    *,
    prediction_id: UUID,
    game_id: UUID,
    model_version_id: UUID,
    cutoff_at: datetime,
    event_time: datetime,
    p_a: float | None = None,
    abstention_reason: str | None = None,
) -> UUID:
    """Добавить неизменяемый снимок предсказания.

    Либо `p_a` (тогда `p_b = 1 - p_a`), либо `abstention_reason` — третьего не
    дано, этого требует CHECK-ограничение схемы.
    """
    if p_a is None and abstention_reason is None:
        raise ValueError("нужен либо p_a, либо abstention_reason")
    if p_a is not None and abstention_reason is not None:
        raise ValueError("p_a и abstention_reason взаимно исключают друг друга")

    idempotency_key = snapshot_idempotency_key(game_id, model_version_id)
    existing = session.execute(
        text(SELECT_SNAPSHOT_BY_IDEM), {"idempotency_key": idempotency_key}
    ).first()
    if existing is not None:
        return UUID(str(existing.id))

    snapshot_seq = session.execute(
        text(NEXT_SNAPSHOT_SEQ), {"prediction_id": str(prediction_id)}
    ).scalar_one()

    row = session.execute(
        text(INSERT_PREDICTION_SNAPSHOT),
        {
            "prediction_id": str(prediction_id),
            "snapshot_seq": snapshot_seq,
            "cutoff_at": cutoff_at,
            "model_version_id": str(model_version_id),
            "p_a": p_a,
            "p_b": None if p_a is None else 1.0 - p_a,
            "abstention_reason": abstention_reason,
            "state_hash": snapshot_state_hash(
                prediction_id=prediction_id,
                model_version_id=model_version_id,
                cutoff_at=cutoff_at,
                p_a=p_a,
            ),
            "idempotency_key": idempotency_key,
            "event_time": event_time,
        },
    ).scalar_one()
    return UUID(str(row))


def record_evaluation(
    session: Session,
    *,
    snapshot_id: UUID,
    y: bool | None,
    log_loss: float | None,
    brier: float | None,
    metric_definition_version: str = "logloss+brier.v1",
) -> UUID:
    """Свернуть снимок с фактом. `y = None` — исход на момент оценки неизвестен.

    Идемпотентно: уникальный индекс схемы не спасает (`result_revision_id`
    равен NULL, а NULL в Postgres различим), поэтому дубли отсекаются явным
    поиском — перезапуск скрипта не плодит вторые сверки на том же снимке.
    """
    existing = session.execute(
        text(SELECT_PREDICTION_EVALUATION),
        {
            "snapshot_id": str(snapshot_id),
            "metric_definition_version": metric_definition_version,
        },
    ).first()
    if existing is not None:
        return UUID(str(existing.id))

    row = session.execute(
        text(INSERT_PREDICTION_EVALUATION),
        {
            "snapshot_id": str(snapshot_id),
            "metric_definition_version": metric_definition_version,
            "y": y,
            "log_loss": log_loss,
            "brier": brier,
        },
    ).scalar_one()
    return UUID(str(row))
