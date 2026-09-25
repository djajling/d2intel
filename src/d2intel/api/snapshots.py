"""API-001 — запись immutable снимков предсказания + шаблонное evidence.

Разделение с `predict.py`: здесь только запись в БД и формирование ответа.
Доменная логика (выбор цели, сборка признаков) — в `predict.py`.

Снимок `prediction_snapshot` неизменяем (триггер
`prediction_snapshot_no_mutation`): повторный вызов эндпоинта создаёт
**новый** `snapshot_seq`, а не перезаписывает старый — это AC #1. Сама цель
(`prediction`) изменяема и идемпотентна по `request_key`.

`feature_snapshot` (AC #3: «снапшот содержит фичи») — отдельная immutable
таблица: значения признаков + маски + cutoff + версия схемы. Маски
доступности хранятся **отдельно от значений** (`API-002` AC #4), неизвестное
не подменяется нулём.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from typing import Any
from uuid import UUID

import numpy as np
from pydantic import BaseModel, Field
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.models.repository import (
    prediction_request_key,
    record_evaluation,
    snapshot_idempotency_key,
    upsert_prediction,
)

PREDICTION_TEMPLATE_EVIDENCE_VERSION = "template.v1"

# Метка ретроспективного режима — единственный доступный на ретро-контуре.
RETROSPECTIVE_MODE = "retrospective_reconstructed"

INSERT_FEATURE_SNAPSHOT = """
    INSERT INTO feature_snapshot (
        target_type, target_game_id, cutoff_at, evaluation_mode,
        values_json, coverage_json, feature_schema_version, content_hash,
        assumed_available_at, lag_policy_version, event_time,
        observed_at, ingested_at, available_at
    ) VALUES (
        'game', CAST(:game_id AS uuid), CAST(:cutoff_at AS timestamptz), :evaluation_mode,
        CAST(:values_json AS jsonb), CAST(:coverage_json AS jsonb),
        :feature_schema_version, :content_hash,
        CAST(:assumed_available_at AS timestamptz), :lag_policy_version,
        CAST(:event_time AS timestamptz),
        now(), now(), now()
    )
    RETURNING id
"""

SELECT_FEATURE_SNAPSHOT_BY_CONTENT = """
    SELECT id FROM feature_snapshot WHERE content_hash = :content_hash
"""


class EvidenceItem(BaseModel):
    """Один пункт шаблонного объяснения (не LLM, AC #5).

    `field` — путь к полю снимка, на которое ссылается утверждение;
    `template` — идентификатор шаблона (для верификации, что текст не
    сгенерирован свободно).
    """

    field: str
    template: str
    text: str
    uncertain: bool = Field(
        default=False,
        description="Утверждение основано на неизвестных/низко-покрытых данных",
    )


class PredictionResponse(BaseModel):
    """Ответ эндпоинта предсказания. Все поля обязательны (AC #3)."""

    prediction_id: str
    snapshot_id: str
    model_version_id: str
    algorithm: str
    feature_schema_version: str
    cutoff_at: str
    evaluation_mode: str
    target_phase: str
    lag_policy_version: str
    p_a: float
    p_b: float
    evidence: list[EvidenceItem]
    evidence_version: str
    abstention_reason: str | None = None


def _json_default(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, float) and np.isnan(value):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    raise TypeError(f"unsupported type: {type(value)!r}")


def _to_json(value: Any) -> str:
    """Сериализация в JSON, пригодный для CAST AS jsonb.

    PostgreSQL jsonb не принимает NaN/Infinity (`allow_nan` по умолчанию в
    Python-кодере их пропускает), а неизвестные признаки у нас — именно NaN.
    Поэтому NaN кодируется как `null`: маска `known: false` рядом говорит,
    что это неизвестность, а не «нулевое значение».
    """
    return json.dumps(
        _normalize_nan(value),
        ensure_ascii=False,
        default=_json_default,
        allow_nan=False,
    )


def _normalize_nan(value: Any) -> Any:
    """Рекурсивно заменить NaN/Infinity на None — jsonb их не хранит."""
    if isinstance(value, dict):
        return {key: _normalize_nan(item) for key, item in value.items()}
    if isinstance(value, list | tuple):
        return [_normalize_nan(item) for item in value]
    if isinstance(value, float):
        return None if (np.isnan(value) or np.isinf(value)) else value
    return value


def _content_hash(values: dict[str, Any], coverage: dict[str, Any]) -> str:
    payload = _to_json({"values": values, "coverage": coverage})
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _is_unknown(value: Any) -> bool:
    """Значение неизвестно: None или NaN. Не подменяется нулём."""
    if value is None:
        return True
    if isinstance(value, float):
        return bool(np.isnan(value))
    return False


def _coverage_masks(
    feature_row: dict[str, Any], feature_columns: list[str]
) -> dict[str, Any]:
    """Маски доступности: для каждого значения — было ли оно известно.

    Правило: признак считается uncertain, если его значение None/NaN или
    соответствующая маска avail говорит False. Маски хранятся отдельно от
    значений (AC #4 `API-002`), поэтому здесь только явные булевы флаги.
    """
    masks: dict[str, Any] = {}
    for column in feature_columns:
        value = feature_row.get(column)
        masks[column] = {
            "known": value is not None and not (
                isinstance(value, float) and np.isnan(value)
            ),
        }
    # Явные маски билдера, если они есть в строке.
    for key, mask_key in (
        ("team_a_avail", "team_a_avail"),
        ("team_b_avail", "team_b_avail"),
        ("player_a_avail", "player_a_avail"),
        ("player_b_avail", "player_b_avail"),
    ):
        if key in feature_row:
            masks[mask_key] = bool(feature_row[key])
    return masks


def write_feature_snapshot(
    session: Session,
    *,
    game_id: UUID,
    cutoff_at: datetime,
    feature_row: dict[str, Any],
    feature_columns: list[str],
    feature_schema_version: str,
    lag_policy_version: str,
    assumed_available_at: datetime,
) -> UUID:
    """Записать immutable feature_snapshot и вернуть его id.

    Идемпотентно по `content_hash`: повторный вызов с теми же значениями
    переиспользует существующую запись, а не создаёт дубликат.
    """
    values = {column: feature_row.get(column) for column in feature_columns}
    coverage = _coverage_masks(feature_row, feature_columns)
    content_hash = _content_hash(values, coverage)

    existing = session.execute(
        text(SELECT_FEATURE_SNAPSHOT_BY_CONTENT), {"content_hash": content_hash}
    ).first()
    if existing is not None:
        return UUID(str(existing.id))

    row = session.execute(
        text(INSERT_FEATURE_SNAPSHOT),
        {
            "game_id": str(game_id),
            "cutoff_at": cutoff_at,
            "evaluation_mode": RETROSPECTIVE_MODE,
            "values_json": _to_json(values),
            "coverage_json": _to_json(coverage),
            "feature_schema_version": feature_schema_version,
            "content_hash": content_hash,
            "assumed_available_at": assumed_available_at,
            "lag_policy_version": lag_policy_version,
            "event_time": cutoff_at,
        },
    ).scalar_one()
    return UUID(str(row))


def write_prediction_snapshot(
    session: Session,
    *,
    game_id: UUID,
    team_a_id: UUID,
    team_b_id: UUID,
    model_version: dict[str, Any],
    cutoff_at: datetime,
    p_a: float,
    evaluation_mode: str,
    feature_row: dict[str, Any],
    feature_columns: list[str],
) -> dict[str, Any]:
    """Полный immutable снимок: цель + feature_snapshot + prediction_snapshot.

    Возвращает id prediction и snapshot для ответа. **На каждый вызов
    сервиса — новый снимок** (AC #1): идемпотентность `repository` нужна
    скриптам обучения (перезапуск не дублирует), а сервис предсказывает по
    запросу, и каждый запрос — отдельное вычисление со своим `snapshot_seq`.
    Поэтому идемпотентный путь здесь не используется.
    """
    feature_snapshot_id = write_feature_snapshot(
        session,
        game_id=game_id,
        cutoff_at=cutoff_at,
        feature_row=feature_row,
        feature_columns=feature_columns,
        feature_schema_version=model_version["feature_schema_version"],
        lag_policy_version=model_version.get("lag_policy_version", "lag-policy.v1"),
        assumed_available_at=cutoff_at,
    )

    prediction_id = upsert_prediction(
        session,
        game_id=game_id,
        team_a_id=team_a_id,
        team_b_id=team_b_id,
    )
    snapshot_id = _append_service_snapshot(
        session,
        prediction_id=prediction_id,
        game_id=game_id,
        model_version_id=model_version["id"],
        cutoff_at=cutoff_at,
        feature_snapshot_id=feature_snapshot_id,
        p_a=p_a,
    )
    return {
        "prediction_id": str(prediction_id),
        "snapshot_id": str(snapshot_id),
        "feature_snapshot_id": str(feature_snapshot_id),
    }


INSERT_SERVICE_SNAPSHOT = """
    INSERT INTO prediction_snapshot (
        prediction_id, snapshot_seq, computed_at, cutoff_at, model_version_id,
        feature_snapshot_id, p_a, p_b, abstention_reason, evaluation_mode,
        state_hash, idempotency_key, event_time, observed_at, ingested_at, available_at
    ) VALUES (
        CAST(:prediction_id AS uuid), :snapshot_seq, now(), CAST(:cutoff_at AS timestamptz),
        CAST(:model_version_id AS uuid), CAST(:feature_snapshot_id AS uuid),
        :p_a, 1.0 - :p_a, NULL, :evaluation_mode,
        :state_hash, :idempotency_key, CAST(:event_time AS timestamptz),
        now(), now(), now()
    )
    RETURNING id
"""


def _append_service_snapshot(
    session: Session,
    *,
    prediction_id: UUID,
    game_id: UUID,
    model_version_id: UUID,
    cutoff_at: datetime,
    feature_snapshot_id: UUID,
    p_a: float,
) -> UUID:
    """Новый снимок на каждый вызов сервиса — отдельный `snapshot_seq`.

    В отличие от `repository.append_prediction_snapshot`, здесь **нет**
    идемпотентности по `(game, model_version)`: каждый HTTP-вызов — это
    отдельное вычисление, и его надо сохранить (AC #1). Сама строка
    всё равно immutable — триггер
    `prediction_snapshot_no_mutation` защищает её от перезаписи.
    """
    snapshot_seq = session.execute(
        text(
            "SELECT COALESCE(max(snapshot_seq), 0) + 1 "
            "FROM prediction_snapshot WHERE prediction_id = CAST(:id AS uuid)"
        ),
        {"id": prediction_id},
    ).scalar_one()

    state_hash = _snapshot_state_hash(
        prediction_id=prediction_id,
        model_version_id=model_version_id,
        cutoff_at=cutoff_at,
        p_a=p_a,
        feature_snapshot_id=feature_snapshot_id,
    )
    row = session.execute(
        text(INSERT_SERVICE_SNAPSHOT),
        {
            "prediction_id": prediction_id,
            "snapshot_seq": snapshot_seq,
            "cutoff_at": cutoff_at,
            "model_version_id": model_version_id,
            "feature_snapshot_id": feature_snapshot_id,
            "p_a": p_a,
            "evaluation_mode": RETROSPECTIVE_MODE,
            "state_hash": state_hash,
            "idempotency_key": (
                f"service:{game_id}:model:{model_version_id}:seq:{snapshot_seq}"
            ),
            "event_time": cutoff_at,
        },
    ).scalar_one()
    return UUID(str(row))


def _snapshot_state_hash(
    *,
    prediction_id: UUID,
    model_version_id: UUID,
    cutoff_at: datetime,
    p_a: float,
    feature_snapshot_id: UUID,
) -> str:
    """Хэш состояния снимка для проверки воспроизводимости."""
    payload = (
        f"{prediction_id}|{model_version_id}|{cutoff_at.isoformat()}|"
        f"{p_a}|{feature_snapshot_id}"
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def build_template_evidence(
    *,
    p_a: float,
    feature_row: dict[str, Any],
    feature_columns: list[str],
    model_version: dict[str, Any],
    cutoff_at: str,
) -> list[EvidenceItem]:
    """Шаблонные объяснения без LLM (AC #5).

    Каждый пункт ссылается на поле снимка и помечен `template`-идентификатором.
    Утверждения о причинности и прибыльности не допускаются (`API-003` AC #3):
    формулировки только о вероятности и о том, какие признаки известны.
    """
    items: list[EvidenceItem] = []

    items.append(
        EvidenceItem(
            field="p_a",
            template="probability",
            text=(
                f"Оценка P(Team A выигрывает карту 1) = {p_a:.4f} "
                f"при cutoff {cutoff_at}."
            ),
        )
    )
    items.append(
        EvidenceItem(
            field="model_version_id",
            template="model_source",
            text=(
                f"Модель: {model_version['algorithm']}, "
                f"версия {model_version['id']}."
            ),
        )
    )

    for side in ("a", "b"):
        avail_key = f"team_{side}_avail"
        known = bool(feature_row.get(avail_key, False))
        n_games = feature_row.get(f"team_{side}_n_games")
        text_line = (
            f"Team {side.upper()}: известно матчей в истории — {n_games}."
            if known
            else f"Team {side.upper()}: история неизвестна (no coverage)."
        )
        items.append(
            EvidenceItem(
                field=avail_key,
                template="team_coverage",
                text=text_line,
                uncertain=not known,
            )
        )

    player_known = bool(feature_row.get("player_a_avail", False)) and bool(
        feature_row.get("player_b_avail", False)
    )
    items.append(
        EvidenceItem(
            field="player_a_avail",
            template="player_coverage",
            text=(
                "Признаки игроков доступны."
                if player_known
                else "Признаки игроков недоступны (roster неизвестен)."
            ),
            uncertain=not player_known,
        )
    )

    unknown_features = sorted(
        column
        for column in feature_columns
        if _is_unknown(feature_row.get(column))
    )
    if unknown_features:
        items.append(
            EvidenceItem(
                field="coverage_json",
                template="unknown_features",
                text=(
                    "Неизвестные признаки: "
                    + ", ".join(unknown_features)
                    + ". Их значения не используются как нули."
                ),
                uncertain=True,
            )
        )
    return items


__all__ = [
    "EvidenceItem",
    "PREDICTION_TEMPLATE_EVIDENCE_VERSION",
    "PredictionResponse",
    "RETROSPECTIVE_MODE",
    "build_template_evidence",
    "prediction_request_key",
    "record_evaluation",
    "snapshot_idempotency_key",
    "write_feature_snapshot",
    "write_prediction_snapshot",
]
