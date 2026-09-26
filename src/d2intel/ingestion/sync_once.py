"""ING-001 — ограниченный sync-once прогон.

Оркестрация «взять ограниченную выборку и записать raw». Это **не** планировщик
и не backfill: окно задаётся явно (`max_pages`), прогон заканчивается и
возвращает отчёт. Автоматического периодического ingestion здесь нет — это
`ING-002` / `ING-008`.

Исходы прогона (без тихого fallback):

* `completed` — обход дошёл до естественного конца пагинации в пределах бюджета;
* `partial` — обход остановлен лимитом страниц, `next_cursor` ещё не пуст. Это
  **не ошибка**, а явное указание на неполный охват: клиент не выдаёт
  ограниченную выборку за полную;
* `stale` — источник недоступен: прогон помечен stale, данные не подменяются
  другим набором (ARCHITECTURE.md §3, п. 7);
* `quota_exhausted` — локальный бюджет исчерпан, запрос не отправлен;
* `failed` — auth/постоянная ошибка запроса/нечитаемый ответ.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from dataclasses import dataclass
from typing import Any

from sqlalchemy.orm import Session

from d2intel.ingestion.contracts import EndpointKind
from d2intel.ingestion.errors import (
    AuthError,
    IngestionError,
    MalformedResponseError,
    QuotaExhaustedError,
    RateLimitedError,
    SourceRequestError,
    SourceUnavailableError,
)
from d2intel.ingestion.opendota_client import OpenDotaClient
from d2intel.ingestion.raw_capture import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_QUOTA_EXHAUSTED,
    RUN_STALE,
    RawCapture,
    quarantine_summary,
)

LOGGER = logging.getLogger("d2intel.ingestion.sync_once")


def run_head_sync(
    *,
    session: Session,
    client: OpenDotaClient,
    max_pages: int = 1,
    endpoint_kind: EndpointKind = EndpointKind.PRO_MATCHES,
) -> RunReport:
    """Синхронизация **свежих** матчей от верха выдачи proMatches.

    В отличие от `run_sync_once`, который возобновляет пагинацию от
    сохранённого watermark (и потому догоняет только пропуски в прошлом),
    head-обход начинает с самой свежей страницы и спускается вниз до тех
    пор, пока не встретит уже известный watermark. Это режим «догнать
    настоящее», а не «доархивировать прошлое».

    Идемпотентен: пересечение с уже наблюдёнными страницами не дублирует raw.
    """
    if endpoint_kind is not EndpointKind.PRO_MATCHES:
        raise ValueError("head-sync поддерживает только proMatches")

    capture = RawCapture(session, client.contract)
    cursor = capture.load_cursor(str(endpoint_kind))
    watermark = int(cursor.cursor_value) if cursor and cursor.cursor_value else None
    run_id = capture.start_run(cursor_before=cursor.cursor_value if cursor else None)

    pages = 0
    records = 0
    quarantined = 0
    reasons: dict[str, int] = {}
    raw_inserted = 0
    raw_deduplicated = 0
    observations = 0
    cursor_after = cursor.cursor_value if cursor else None
    status = RUN_COMPLETED
    error: str | None = None

    try:
        for batch in client.iter_pro_matches(max_pages=max_pages, cursor_payload={}):
            newest = _page_newest_id(batch)
            if watermark is not None and newest is not None and newest <= watermark:
                # Спустились до известного watermark — дальше только старое.
                LOGGER.info("head-sync reached watermark %s, stopping", watermark)
                break
            result = capture.ingest_batch(batch, run_id)
            pages += 1
            records += len(batch.records)
            quarantined += len(batch.quarantined)
            reasons = _merge_counts(
                reasons, quarantine_summary([_reason_row(r) for r in batch.quarantined])
            )
            raw_inserted += 1 if result.raw_inserted else 0
            raw_deduplicated += 0 if result.raw_inserted else 1
            observations += result.observations_inserted
            if result.cursor_value is not None:
                cursor_after = result.cursor_value
            if batch.next_cursor is None:
                break
    except QuotaExhaustedError as exc:
        status = RUN_QUOTA_EXHAUSTED
        error = _safe_error(exc)
    except SourceUnavailableError as exc:
        status = RUN_STALE
        error = _safe_error(exc)
    except (AuthError, SourceRequestError, MalformedResponseError, RateLimitedError) as exc:
        status = RUN_FAILED
        error = _safe_error(exc)
    except IngestionError as exc:  # pragma: no cover - защитная ветка
        status = RUN_FAILED
        error = _safe_error(exc)

    cursor_state = capture.load_cursor(str(endpoint_kind))
    capture.finish_run(
        run_id,
        status=status,
        error_summary=error,
        quota_headers=client.quota.journal_payload(source_id=client.contract.source_id),
        cursor_after=cursor_state.cursor_value if cursor_state else cursor_after,
    )
    report = RunReport(
        run_id=run_id,
        status=status,
        pages=pages,
        records=records,
        quarantined=quarantined,
        quarantined_by_reason=reasons,
        raw_inserted=raw_inserted,
        raw_deduplicated=raw_deduplicated,
        observations=observations,
        cursor_before=cursor.cursor_value if cursor else None,
        cursor_after=cursor_state.cursor_value if cursor_state else cursor_after,
        error=error,
    )
    LOGGER.info("head-sync finished %s", report.as_dict())
    return report


def _page_newest_id(batch: Any) -> int | None:
    """Самый большой provider_entity_id на странице (верх выдачи)."""
    ids = [
        int(record.provider_entity_id)
        for record in batch.records
        if str(record.provider_entity_id or "").isdigit()
    ]
    return max(ids) if ids else None


@dataclass(frozen=True)
class RunReport:
    """Отчёт прогона. Секретов не содержит по построению."""

    run_id: str | None
    status: str
    pages: int
    records: int
    quarantined: int
    quarantined_by_reason: Mapping[str, int]
    raw_inserted: int
    raw_deduplicated: int
    observations: int
    cursor_before: str | None
    cursor_after: str | None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "pages": self.pages,
            "records": self.records,
            "quarantined": self.quarantined,
            "quarantined_by_reason": dict(self.quarantined_by_reason),
            "raw_inserted": self.raw_inserted,
            "raw_deduplicated": self.raw_deduplicated,
            "observations": self.observations,
            "cursor_before": self.cursor_before,
            "cursor_after": self.cursor_after,
            "error": self.error,
        }


def run_sync_once(
    *,
    session: Session,
    client: OpenDotaClient,
    max_pages: int = 1,
    overlap_pages: int = 1,
    endpoint_kind: EndpointKind = EndpointKind.PRO_MATCHES,
) -> RunReport:
    """Ограниченный прогон `/api/proMatches` с записью raw.

    Идемпотентен по построению: повторный прогон с теми же параметрами создаёт
    новые наблюдения, но не дублирует raw.
    """
    if endpoint_kind is not EndpointKind.PRO_MATCHES:
        raise ValueError("sync-once поддерживает только proMatches")

    capture = RawCapture(session, client.contract)
    cursor = capture.load_cursor(str(endpoint_kind))
    cursor_before = cursor.cursor_value if cursor else None
    cursor_payload = dict(cursor.cursor_payload) if cursor else {}
    run_id = capture.start_run(cursor_before=cursor_before)

    pages = 0
    records = 0
    quarantined = 0
    reasons: dict[str, int] = {}
    raw_inserted = 0
    raw_deduplicated = 0
    observations = 0
    cursor_after = cursor_before
    truncated = False
    status = RUN_COMPLETED
    error: str | None = None

    try:
        for batch in client.iter_pro_matches(
            max_pages=max_pages,
            cursor_payload=cursor_payload,
            overlap_pages=overlap_pages,
        ):
            result = capture.ingest_batch(batch, run_id)
            pages += 1
            records += len(batch.records)
            quarantined += len(batch.quarantined)
            reasons = _merge_counts(
                reasons, quarantine_summary([_reason_row(record) for record in batch.quarantined])
            )
            raw_inserted += 1 if result.raw_inserted else 0
            raw_deduplicated += 0 if result.raw_inserted else 1
            observations += result.observations_inserted
            truncated = truncated or batch.completeness.truncated
            if result.cursor_value is not None:
                cursor_after = result.cursor_value
        status = RUN_PARTIAL if truncated else RUN_COMPLETED
    except QuotaExhaustedError as exc:
        status = RUN_QUOTA_EXHAUSTED
        error = _safe_error(exc)
    except SourceUnavailableError as exc:
        # Source outage: помечаем stale, не подставляем другой набор данных.
        status = RUN_STALE
        error = _safe_error(exc)
    except (AuthError, SourceRequestError, MalformedResponseError, RateLimitedError) as exc:
        status = RUN_FAILED
        error = _safe_error(exc)
    except IngestionError as exc:  # pragma: no cover - защитная ветка
        status = RUN_FAILED
        error = _safe_error(exc)

    cursor_state = capture.load_cursor(str(endpoint_kind))
    capture.finish_run(
        run_id,
        status=status,
        error_summary=error,
        quota_headers=client.quota.journal_payload(source_id=client.contract.source_id),
        cursor_after=cursor_state.cursor_value if cursor_state else cursor_after,
    )
    report = RunReport(
        run_id=run_id,
        status=status,
        pages=pages,
        records=records,
        quarantined=quarantined,
        quarantined_by_reason=reasons,
        raw_inserted=raw_inserted,
        raw_deduplicated=raw_deduplicated,
        observations=observations,
        cursor_before=cursor_before,
        cursor_after=cursor_state.cursor_value if cursor_state else cursor_after,
        error=error,
    )
    LOGGER.info("sync-once finished %s", report.as_dict())
    return report


def dry_run_page(client: OpenDotaClient) -> dict[str, Any]:
    """Одна страница без записи в БД: проверка формы ответа и квоты."""
    batch = client.fetch_pro_matches()
    return {
        "retrieval_status": str(batch.retrieval_status),
        "records": len(batch.records),
        "quarantined": len(batch.quarantined),
        "next_cursor": batch.next_cursor,
        "is_complete": batch.completeness.is_complete,
        "missing_fields": list(batch.completeness.missing_fields),
        "notes": list(batch.completeness.notes),
        "observed_at": batch.observed_at.isoformat(),
    }


def _reason_row(record: Any) -> dict[str, Any]:
    return {"reason_code": str(record.reason_code)}


def _merge_counts(target: dict[str, int], extra: Mapping[str, int]) -> dict[str, int]:
    merged = dict(target)
    for key, value in extra.items():
        merged[key] = merged.get(key, 0) + value
    return merged


def _safe_error(exc: Exception) -> str:
    """Текст ошибки для `error_summary`: тип + сообщение (уже без секретов)."""
    return f"{type(exc).__name__}: {exc}"


__all__ = ["RunReport", "run_sync_once", "dry_run_page"]
