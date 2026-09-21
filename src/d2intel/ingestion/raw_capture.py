"""ING-001 — идемпотентная запись raw, наблюдений, карантина и watermark.

Слой реализует пункты 3–7 контракта source adapter (`ARCHITECTURE.md` §3):

* **raw hash + request metadata** — `content_hash` считается по сырому телу ответа;
* **идемпотентность** — `raw_payload` дедуплицируется по `(source_id, content_hash)`
  транзакционным upsert; повторный прогон не создаёт дублей;
* **at-least-once** — доставка может повториться, поэтому обработка идемпотентна;
* **повторные наблюдения** — одинаковый payload на разных retrievals даёт **новую**
  строку `source_observation` с собственным временем: одинаковое содержимое ≠
  одинаковое событие получения;
* **watermark только после commit** — курсор двигается отдельной транзакцией
  строго после успешного commit данных;
* **карантин** — непригодные строки получают отдельную data-quality причину и
  ссылку на прогон/отпечаток запроса; сырой payload при этом не теряется.

Границы: слой не нормализует сущности, не вычисляет map index и не выставляет
`available_at` «по смыслу». Raw доступен ровно в момент записи, поэтому
`available_at = ingested_at` (см. комментарий в `_temporal_envelope`).
"""

from __future__ import annotations

import hashlib
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.ingestion.contracts import FetchBatch, SourceContract, utc_now
from d2intel.ingestion.opendota_client import dumps_payload

#: Статусы прогона ingestion (значения `ingestion_run.status`).
RUN_RUNNING = "running"
RUN_COMPLETED = "completed"
RUN_PARTIAL = "partial"
RUN_STALE = "stale"
RUN_FAILED = "failed"
RUN_QUOTA_EXHAUSTED = "quota_exhausted"


@dataclass(frozen=True)
class CursorState:
    """Прочитанный watermark пагинации."""

    endpoint_kind: str
    cursor_value: str | None
    cursor_payload: Mapping[str, Any]
    last_run_id: str | None


@dataclass(frozen=True)
class IngestResult:
    """Результат записи одного batch."""

    raw_payload_id: str
    raw_inserted: bool
    observations_inserted: int
    quarantined_inserted: int
    cursor_advanced: bool
    cursor_value: str | None


class RawCapture:
    """Запись raw-слоя. Один экземпляр на сессию (транзакции контролирует он)."""

    def __init__(
        self,
        session: Session,
        contract: SourceContract,
        *,
        clock: Callable[[], datetime] = utc_now,
    ) -> None:
        self._session = session
        self._contract = contract
        self._clock = clock
        self._source_id: str | None = None

    # --- источник и прогон --------------------------------------------------

    def ensure_data_source(self) -> str:
        """Регистрирует источник из объявленного контракта (идемпотентно)."""
        if self._source_id is not None:
            return self._source_id
        existing = self._session.execute(
            text("SELECT id FROM data_source WHERE name = :name ORDER BY created_at LIMIT 1"),
            {"name": self._contract.source_id},
        ).scalar()
        if existing is not None:
            self._source_id = str(existing)
            return self._source_id

        capabilities = self._contract.capabilities.as_dict()
        terms_checked_at = self._contract.terms_checked_at
        created = self._session.execute(
            text(
                """
                INSERT INTO data_source (
                    name, adapter_version, capabilities, terms_url, terms_checked_at,
                    allowed_purposes, retention_policy
                ) VALUES (
                    :name, :adapter_version, CAST(:capabilities AS jsonb), :terms_url,
                    :terms_checked_at, :allowed_purposes, :retention_policy
                )
                RETURNING id
                """
            ),
            {
                "name": self._contract.source_id,
                "adapter_version": self._contract.adapter_version,
                "capabilities": dumps_payload(capabilities),
                # Публичного ToS-URL у OpenDota в рамках обзора не найдено —
                # выдумывать ссылку нельзя, остаётся NULL + внутренний reference.
                "terms_url": None,
                "terms_checked_at": terms_checked_at,
                "allowed_purposes": list(self._contract.allowed_purposes),
                "retention_policy": self._contract.retention_policy,
            },
        ).scalar_one()
        self._session.commit()
        self._source_id = str(created)
        return self._source_id

    def start_run(
        self, *, cursor_before: str | None = None, status: str = RUN_RUNNING
    ) -> str:
        """Открывает `ingestion_run`."""
        source_id = self.ensure_data_source()
        run_id = self._session.execute(
            text(
                """
                INSERT INTO ingestion_run (source_id, started_at, status, cursor_before)
                VALUES (:source_id, :started_at, :status, :cursor_before)
                RETURNING id
                """
            ),
            {
                "source_id": source_id,
                "started_at": self._clock(),
                "status": status,
                "cursor_before": cursor_before,
            },
        ).scalar_one()
        self._session.commit()
        return str(run_id)

    def finish_run(
        self,
        run_id: str,
        *,
        status: str,
        error_summary: str | None = None,
        quota_headers: Mapping[str, Any] | None = None,
        cursor_after: str | None = None,
    ) -> None:
        """Закрывает прогон. Секретов в `error_summary` быть не должно."""
        self._session.execute(
            text(
                """
                UPDATE ingestion_run
                   SET finished_at = :finished_at,
                       status = :status,
                       error_summary = :error_summary,
                       quota_headers = CAST(:quota_headers AS jsonb),
                       cursor_after = COALESCE(:cursor_after, cursor_after)
                 WHERE id = :run_id
                """
            ),
            {
                "run_id": run_id,
                "finished_at": self._clock(),
                "status": status,
                "error_summary": error_summary,
                "quota_headers": dumps_payload(quota_headers or {}),
                "cursor_after": cursor_after,
            },
        )
        self._session.commit()

    def mark_stale(self, run_id: str, reason: str) -> None:
        """Source outage: прогон помечается stale. Тихий fallback не выполняется."""
        self.finish_run(run_id, status=RUN_STALE, error_summary=reason)

    # --- watermark ----------------------------------------------------------

    def load_cursor(self, endpoint_kind: str) -> CursorState | None:
        """Читает watermark. None — прогонов ещё не было."""
        source_id = self.ensure_data_source()
        row = self._session.execute(
            text(
                """
                SELECT cursor_value, cursor_payload, last_run_id
                  FROM ingestion_cursor
                 WHERE source_id = :source_id AND endpoint_kind = :endpoint_kind
                """
            ),
            {"source_id": source_id, "endpoint_kind": endpoint_kind},
        ).one_or_none()
        if row is None:
            return None
        return CursorState(
            endpoint_kind=endpoint_kind,
            cursor_value=row.cursor_value,
            cursor_payload=dict(row.cursor_payload or {}),
            last_run_id=str(row.last_run_id) if row.last_run_id is not None else None,
        )

    # --- запись batch -------------------------------------------------------

    def ingest_batch(self, batch: FetchBatch, run_id: str) -> IngestResult:
        """Пишет batch: raw (идемпотентно) + наблюдения + карантин, затем watermark.

        Watermark продвигается **после** commit данных: сбой между commit и
        продвижением безопасен (повторный прогон идемпотентен и лишь повторно
        наблюдает те же строки), обратный порядок потерял бы данные.
        """
        source_id = self.ensure_data_source()
        ingested_at = self._clock()
        observed_at, available_at = self._temporal_envelope(batch.observed_at, ingested_at)

        raw_id, raw_inserted = self._upsert_raw_payload(
            batch, source_id=source_id, observed_at=observed_at, ingested_at=ingested_at,
            available_at=available_at,
        )
        observations = self._insert_observations(
            batch,
            raw_payload_id=raw_id,
            run_id=run_id,
            observed_at=observed_at,
            ingested_at=ingested_at,
            available_at=available_at,
        )
        quarantined = self._insert_quarantine(
            batch,
            source_id=source_id,
            run_id=run_id,
            observed_at=observed_at,
            ingested_at=ingested_at,
            available_at=available_at,
        )
        # Данные durable — только теперь можно двигать watermark.
        self._session.commit()
        cursor_value = self._advance_cursor(batch, run_id=run_id)
        return IngestResult(
            raw_payload_id=raw_id,
            raw_inserted=raw_inserted,
            observations_inserted=observations,
            quarantined_inserted=quarantined,
            cursor_advanced=cursor_value is not None,
            cursor_value=cursor_value,
        )

    # --- внутреннее ---------------------------------------------------------

    def _temporal_envelope(
        self, observed_at: datetime, ingested_at: datetime
    ) -> tuple[datetime, datetime]:
        """Временной конверт записи raw.

        Клиент фиксирует только фактическое время получения (`observed_at`).
        `ingested_at` — момент записи. `available_at` не выводится из `event_time`:
        raw доступен ровно тогда, когда записан, поэтому равен `ingested_at`.
        """
        if observed_at > ingested_at:
            # Наблюдение не может быть позже записи: часы/инъекция времени разошлись.
            ingested_at = observed_at
        return observed_at, ingested_at

    def _upsert_raw_payload(
        self,
        batch: FetchBatch,
        *,
        source_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        available_at: datetime,
    ) -> tuple[str, bool]:
        payload_json = dumps_payload(batch.raw_payload)
        inserted = self._session.execute(
            text(
                """
                INSERT INTO raw_payload (
                    source_id, endpoint_kind, content_hash, schema_version, payload_json,
                    event_time, source_published_at, observed_at, ingested_at, available_at
                ) VALUES (
                    :source_id, :endpoint_kind, :content_hash, :schema_version,
                    CAST(:payload_json AS jsonb),
                    :event_time, :source_published_at, :observed_at, :ingested_at, :available_at
                )
                ON CONFLICT (source_id, content_hash) DO NOTHING
                RETURNING id
                """
            ),
            {
                "source_id": source_id,
                "endpoint_kind": str(batch.endpoint_kind),
                "content_hash": batch.content_hash,
                "schema_version": batch.schema_version,
                "payload_json": payload_json,
                "event_time": _batch_event_time(batch),
                "source_published_at": None,
                "observed_at": observed_at,
                "ingested_at": ingested_at,
                "available_at": available_at,
            },
        ).scalar()
        if inserted is not None:
            return str(inserted), True
        existing = self._session.execute(
            text(
                """
                SELECT id FROM raw_payload
                 WHERE source_id = :source_id AND content_hash = :content_hash
                """
            ),
            {"source_id": source_id, "content_hash": batch.content_hash},
        ).scalar_one()
        return str(existing), False

    def _insert_observations(
        self,
        batch: FetchBatch,
        *,
        raw_payload_id: str,
        run_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        available_at: datetime,
    ) -> int:
        """Повторные retrieval не дедуплицируются: каждое получение — своё событие."""
        rows: list[dict[str, Any]] = [
            {
                "provider_entity_id": record.provider_entity_id,
                "provider_entity_type": record.provider_entity_type,
                "event_time": record.event_time,
                "source_published_at": record.source_published_at,
            }
            for record in batch.records
        ]
        if not rows:
            # Пустая/непригодная страница — тоже событие получения, и оно должно
            # быть видно: «пусто» не равно «успех полного охвата».
            rows.append(
                {
                    "provider_entity_id": None,
                    "provider_entity_type": str(batch.endpoint_kind),
                    "event_time": None,
                    "source_published_at": None,
                }
            )
        statement = text(
            """
            INSERT INTO source_observation (
                run_id, raw_payload_id, provider_entity_id, provider_entity_type,
                request_fingerprint, event_time, source_published_at,
                observed_at, ingested_at, available_at
            ) VALUES (
                :run_id, :raw_payload_id, :provider_entity_id, :provider_entity_type,
                :request_fingerprint, :event_time, :source_published_at,
                :observed_at, :ingested_at, :available_at
            )
            """
        )
        for row in rows:
            self._session.execute(
                statement,
                {
                    "run_id": run_id,
                    "raw_payload_id": raw_payload_id,
                    "provider_entity_id": row["provider_entity_id"],
                    "provider_entity_type": row["provider_entity_type"],
                    "request_fingerprint": batch.request.fingerprint,
                    "event_time": row["event_time"],
                    "source_published_at": row["source_published_at"],
                    "observed_at": observed_at,
                    "ingested_at": ingested_at,
                    "available_at": available_at,
                },
            )
        return len(rows)

    def _insert_quarantine(
        self,
        batch: FetchBatch,
        *,
        source_id: str,
        run_id: str,
        observed_at: datetime,
        ingested_at: datetime,
        available_at: datetime,
    ) -> int:
        statement = text(
            """
            INSERT INTO ingestion_quarantine (
                run_id, source_id, endpoint_kind, reason_code, reason_detail,
                provider_entity_id, provider_entity_type, request_fingerprint,
                content_hash, offending_payload, status,
                event_time, source_published_at, observed_at, ingested_at, available_at
            ) VALUES (
                :run_id, :source_id, :endpoint_kind, :reason_code, :reason_detail,
                :provider_entity_id, :provider_entity_type, :request_fingerprint,
                :content_hash, CAST(:offending_payload AS jsonb), 'open',
                :event_time, :source_published_at, :observed_at, :ingested_at, :available_at
            )
            ON CONFLICT (source_id, content_hash, reason_code) DO NOTHING
            RETURNING id
            """
        )
        inserted = 0
        for record in batch.quarantined:
            result = self._session.execute(
                statement,
                {
                    "run_id": run_id,
                    "source_id": source_id,
                    "endpoint_kind": str(batch.endpoint_kind),
                    "reason_code": str(record.reason_code),
                    "reason_detail": record.reason_detail,
                    "provider_entity_id": record.provider_entity_id,
                    "provider_entity_type": record.provider_entity_type,
                    "request_fingerprint": batch.request.fingerprint,
                    "content_hash": _quarantine_hash(batch, record.offending_payload),
                    "offending_payload": dumps_payload(record.offending_payload),
                    "event_time": record.event_time,
                    "source_published_at": record.source_published_at,
                    "observed_at": observed_at,
                    "ingested_at": ingested_at,
                    "available_at": available_at,
                },
            )
            # DO NOTHING не возвращает строку → повторный карантин не дублируется.
            inserted += len(result.fetchall())
        return inserted

    def _advance_cursor(self, batch: FetchBatch, *, run_id: str) -> str | None:
        """Продвигает watermark отдельной транзакцией (после commit данных)."""
        page_end = batch.cursor_payload.get("page_end")
        cursor_value = str(page_end) if page_end is not None else batch.next_cursor
        if cursor_value is None:
            return None
        source_id = self.ensure_data_source()
        self._session.execute(
            text(
                """
                INSERT INTO ingestion_cursor (
                    source_id, endpoint_kind, cursor_value, cursor_payload, last_run_id
                ) VALUES (
                    :source_id, :endpoint_kind, :cursor_value,
                    CAST(:cursor_payload AS jsonb), :last_run_id
                )
                ON CONFLICT (source_id, endpoint_kind) DO UPDATE
                   SET cursor_value = EXCLUDED.cursor_value,
                       cursor_payload = EXCLUDED.cursor_payload,
                       last_run_id = EXCLUDED.last_run_id,
                       updated_at = now()
                """
            ),
            {
                "source_id": source_id,
                "endpoint_kind": str(batch.endpoint_kind),
                "cursor_value": cursor_value,
                "cursor_payload": dumps_payload(batch.cursor_payload),
                "last_run_id": run_id,
            },
        )
        self._session.commit()
        return cursor_value


def _batch_event_time(batch: FetchBatch) -> datetime | None:
    """`event_time` уровня payload — минимальное известное время события записей."""
    times = [record.event_time for record in batch.records if record.event_time is not None]
    return min(times) if times else None


def _quarantine_hash(batch: FetchBatch, offending_payload: Mapping[str, Any]) -> str:
    """Хэш непригодной строки: одинаковые плохие строки не дублируют карантин."""
    digest = hashlib.sha256()
    digest.update(str(batch.endpoint_kind).encode("utf-8"))
    digest.update(b"\x00")
    digest.update(dumps_payload(offending_payload).encode("utf-8"))
    return digest.hexdigest()


def quarantine_summary(rows: Sequence[Mapping[str, Any]]) -> dict[str, int]:
    """Сводка карантина по причинам (для отчёта прогона)."""
    summary: dict[str, int] = {}
    for row in rows:
        reason = str(row.get("reason_code"))
        summary[reason] = summary.get(reason, 0) + 1
    return summary
