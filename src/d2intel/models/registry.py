"""Регистрация версии модели в `model_version` (миграция 0001).

Версия — это неизменяемая запись (триггер `model_version_no_mutation` запрещает
UPDATE/DELETE): обучили — зарегистрировали — больше не трогаем. Поэтому поле
`promotion_status` здесь не выставляется в `champion`: повышение — отдельное
решение владельца по результатам итогового гейта (ADR-006, ML-002).
"""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.orm import Session

INSERT_MODEL_VERSION = """
    INSERT INTO model_version (
        algorithm, feature_schema_version, seed, hyperparameters,
        artifact_uri, artifact_hash, code_commit, training_cutoff,
        promotion_status, computed_at
    ) VALUES (
        :algorithm, :feature_schema_version, :seed, CAST(:hyperparameters AS jsonb),
        :artifact_uri, :artifact_hash, :code_commit, :training_cutoff,
        'candidate', now()
    )
    RETURNING id
"""

SELECT_MODEL_VERSION_BY_RUN_KEY = """
    SELECT id
      FROM model_version
     WHERE algorithm = :algorithm
       AND hyperparameters->>'run_key' = :run_key
     ORDER BY computed_at DESC
     LIMIT 1
"""


def register_model_version(
    session: Session,
    *,
    algorithm: str,
    feature_schema_version: str,
    seed: int | None = None,
    hyperparameters: dict[str, Any] | None = None,
    artifact_uri: str | None = None,
    artifact_hash: str | None = None,
    code_commit: str | None = None,
    training_cutoff: datetime | None = None,
    run_key: str | None = None,
) -> UUID:
    """Записать новую версию модели как `candidate`. Возвращает id версии.

    С `run_key` регистрация **идемпотентна**: повторный прогон того же
    эксперимента переиспользует уже зарегистрированную версию, а не плодит
    дубликаты. Сама `model_version` неизменяема (триггер), поэтому идемпотентность
    нужна именно на вставке.
    """
    params = {
        "algorithm": algorithm,
        "feature_schema_version": feature_schema_version,
        "seed": seed,
        "hyperparameters": json.dumps(
            {**(hyperparameters or {}), **({"run_key": run_key} if run_key else {})},
            ensure_ascii=False,
        ),
        "artifact_uri": artifact_uri,
        "artifact_hash": artifact_hash,
        "code_commit": code_commit,
        "training_cutoff": training_cutoff,
    }
    if run_key is not None:
        existing = session.execute(
            text(SELECT_MODEL_VERSION_BY_RUN_KEY),
            {"algorithm": algorithm, "run_key": run_key},
        ).first()
        if existing is not None:
            return UUID(str(existing.id))
    row = session.execute(text(INSERT_MODEL_VERSION), params).scalar_one()
    return UUID(str(row))
