"""DATA-001 — карантин стадии нормализации.

Отдельная таблица, а не `ingestion_quarantine`: ключи и смысл другие.
Ingestion отвечает за «строка источника непригодна», нормализация — за
«структура неоднозначна» (недоказуемый map1, неполная серия, отсутствующая
идентичность).

Свойства:

* **идемпотентность** — `UNIQUE (job_kind, source_id, provider_entity_id,
  reason_code)`, повторный прогон не дублирует строки;
* **сырьё не теряется** — ссылка на `source_observation` и копия спорного
  фрагмента в `offending_payload`, разбор не требует повторного запроса;
* **разрешение** — когда игра всё-таки получает номер карты (приехали
  недостающие игры серии), открытые строки по ней помечаются `resolved`,
  сама запись не удаляется.
"""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any, cast

from sqlalchemy import CursorResult, text
from sqlalchemy.orm import Session

from d2intel.normalize.temporal import Envelope


@dataclass(frozen=True)
class QuarantineItem:
    """Строка карантина нормализации."""

    job_kind: str
    provider_entity_id: str | None
    reason_code: str
    observation_id: str | None
    envelope: Envelope
    reason_detail: str | None = None
    offending_payload: Mapping[str, Any] | None = None


def record_quarantine(
    session: Session,
    item: QuarantineItem,
    *,
    source_id: str,
) -> bool:
    """Записать строку карантина. `True` — строка новая, `False` — уже была."""
    payload_json = json.dumps(item.offending_payload) if item.offending_payload is not None else None
    created = session.execute(
        text(
            """
            INSERT INTO normalization_quarantine (
                job_kind, source_id, source_observation_id, provider_entity_id,
                reason_code, reason_detail, offending_payload, status,
                event_time, source_published_at, observed_at, ingested_at, available_at
            ) VALUES (
                :job_kind, :source_id, :source_observation_id, :provider_entity_id,
                :reason_code, :reason_detail, CAST(:offending_payload AS jsonb), 'open',
                :event_time, :source_published_at, :observed_at, :ingested_at, :available_at
            )
            ON CONFLICT (job_kind, source_id, provider_entity_id, reason_code) DO NOTHING
            RETURNING id
            """
        ),
        {
            "job_kind": item.job_kind,
            "source_id": source_id,
            "source_observation_id": item.observation_id,
            "provider_entity_id": item.provider_entity_id,
            "reason_code": item.reason_code,
            "reason_detail": item.reason_detail,
            "offending_payload": payload_json,
            **item.envelope.as_dict(),
        },
    ).scalar()
    return created is not None


def resolve_quarantine(
    session: Session, *, job_kind: str, provider_entity_id: str, source_id: str
) -> int:
    """Закрыть открытые строки карантина по записи. Возвращает число закрытых."""
    result = cast(
        "CursorResult[Any]",
        session.execute(
            text(
                """
            UPDATE normalization_quarantine
               SET status = 'resolved'
             WHERE job_kind = :job_kind
               AND source_id = :source_id
               AND provider_entity_id = :provider_entity_id
                   AND status = 'open'
                """
            ),
            {
                "job_kind": job_kind,
                "source_id": source_id,
                "provider_entity_id": provider_entity_id,
            },
        ),
    )
    return int(result.rowcount or 0)


def open_reasons(session: Session, *, job_kind: str | None = None) -> dict[str, int]:
    """Сводка открытых строк карантина по причинам (для отчёта прогона)."""
    statement = text(
        """
        SELECT reason_code, count(*) AS total
          FROM normalization_quarantine
         WHERE status = 'open'
           AND (:job_kind IS NULL OR job_kind = :job_kind)
         GROUP BY reason_code
         ORDER BY reason_code
        """
    )
    rows = session.execute(statement, {"job_kind": job_kind}).all()
    return {str(row.reason_code): int(row.total) for row in rows}
