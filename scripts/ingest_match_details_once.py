#!/usr/bin/env python
"""ING — разовый (sync-once) прогон match-detail ingestion.

Точечный обход канонических игр в порядке убывания `match_id`: для каждой
загружается тяжёлый ответ `/api/matches/{id}` и пишется raw + observation.
Участники, финальная статистика и свидетельства состава появляются после
`scripts/normalize_once.py` (стадия `_normalize_match_details`).

Ограничения:

* `--limit` — жёсткий предел попыток за прогон (по умолчанию 2500, меньше
  дневного бюджета free-tier);
* квота free-tier: 60/мин и 3 000/день — клиент throttle'ит сам; при
  исчерпании **суточного** бюджета прогон останавливается (код возврата 5).
  Исчерпание минутного окна — временное: прогон ждёт смены окна и
  перецепляет клиента на свежий бюджет, после чего продолжает;
* единичные 5xx-ответы источника перебираются retry-политикой клиента;
  постоянный отказ источника останавливает прогон (код возврата 4).

Идемпотентность: уже наблюдённый `match_detail` пропускается; watermark
(`ingestion_cursor`, `endpoint_kind = 'match_detail'`) хранит наименьший
обработанный `match_id`, и следующий прогон продолжает ниже него. Ответы 404
тоже двигают watermark — повторных запросов к несуществующим матчам нет.

Примеры::

    python scripts/ingest_match_details_once.py --limit 50    # smoke-проверка
    python scripts/ingest_match_details_once.py               # дневной батч
    python scripts/ingest_match_details_once.py --limit 3000  # полный дневной бюджет

Коды возврата: 0 completed, 2 partial (достигнут limit), 5 quota_exhausted,
4 failed. Секреты не выводятся: API-ключ (если задан в окружении) нигде не
печатается.
"""

from __future__ import annotations

import argparse
import dataclasses
import json
import sys
import time
from collections.abc import Sequence

from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.db import SessionLocal
from d2intel.ingestion.contracts import EndpointKind, RetrievalStatus
from d2intel.ingestion.errors import (
    AuthError,
    IngestionError,
    QuotaExhaustedError,
    SourceRequestError,
    SourceUnavailableError,
)
from d2intel.ingestion.opendota_client import OpenDotaClient
from d2intel.ingestion.raw_capture import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_QUOTA_EXHAUSTED,
    RawCapture,
)

DEFAULT_LIMIT = 2500
MATCH_DETAIL = str(EndpointKind.MATCH_DETAIL)

STATUS_COMPLETED = "completed"
STATUS_PARTIAL = "partial"
STATUS_QUOTA_EXHAUSTED = "quota_exhausted"
STATUS_FAILED = "failed"

EXIT_CODES = {
    STATUS_COMPLETED: 0,
    STATUS_PARTIAL: 2,
    STATUS_QUOTA_EXHAUSTED: 5,
    STATUS_FAILED: 4,
}

WATERMARK_KEY = "watermark_match_id"

# Minute-окно провайдер исчерпывается часто при плотном обходе 60/мин. Это
# временное состояние, а суточный лимит — единственный реальный стоп, поэтому
# прогон ждёт и перецепляет клиента на свежий бюджет вместо полного останова.
MINUTE_WAIT_MARGIN_SECONDS = 5.0
MAX_MINUTE_WAITS = 40


def select_candidates(
    session: Session, *, watermark: int | None, limit: int
) -> list[int]:
    """Канонические игры, у которых ещё нет наблюдения match_detail.

    Порядок — убывание `match_id`: самые свежие карты первыми, чтобы
    prior-history для более старых целей накапливалась раньше. Watermark
    отсекает уже пройденный при предыдущих прогонах диапазон.
    """
    rows = session.execute(
        text(
            """
            SELECT DISTINCT provider_match_id::bigint AS match_id
              FROM game
             WHERE (CAST(:watermark AS bigint) IS NULL
                    OR provider_match_id::bigint < CAST(:watermark AS bigint))
               AND NOT EXISTS (
                     SELECT 1
                       FROM source_observation AS so
                       JOIN raw_payload AS rp ON rp.id = so.raw_payload_id
                      WHERE rp.endpoint_kind = :endpoint_kind
                        AND so.provider_entity_id = game.provider_match_id::text
               )
             ORDER BY match_id DESC
             LIMIT :limit
            """
        ),
        {
            "watermark": watermark,
            "endpoint_kind": MATCH_DETAIL,
            "limit": limit,
        },
    ).fetchall()
    return [int(row[0]) for row in rows]


def load_watermark(session: Session, source_id: str) -> int | None:
    """Наименьший обработанный match_id из предыдущего прогона."""
    row = session.execute(
        text(
            """
            SELECT cursor_payload
              FROM ingestion_cursor
             WHERE source_id = :source_id AND endpoint_kind = :endpoint_kind
            """
        ),
        {"source_id": source_id, "endpoint_kind": MATCH_DETAIL},
    ).one_or_none()
    if row is None:
        return None
    payload = row.cursor_payload or {}
    value = payload.get(WATERMARK_KEY)
    return int(value) if value is not None else None


def run_match_details(
    *, session: Session, client: OpenDotaClient, limit: int
) -> dict[str, object]:
    """Один ограниченный прогон match-detail ingestion."""
    capture = RawCapture(session, client.contract)
    source_id = capture.ensure_data_source()
    watermark_before = load_watermark(session, source_id)
    run_id = capture.start_run(
        cursor_before=str(watermark_before) if watermark_before is not None else None
    )

    candidates = select_candidates(session, watermark=watermark_before, limit=limit)
    fetched = 0
    usable = 0
    not_found = 0
    quarantined = 0
    raw_inserted = 0
    observations = 0
    watermark_after = watermark_before
    status = STATUS_COMPLETED
    error: str | None = None
    minute_waits = 0
    extra_clients: list[OpenDotaClient] = []

    try:
        for match_id in candidates:
            try:
                batch = client.fetch_match(match_id)
            except QuotaExhaustedError as exc:
                if exc.scope == "day" or exc.retry_after_seconds is None:
                    # Суточный бюджет — настоящий стоп: продолжать некуда.
                    status = STATUS_QUOTA_EXHAUSTED
                    break
                minute_waits += 1
                if minute_waits > MAX_MINUTE_WAITS:
                    status = STATUS_QUOTA_EXHAUSTED
                    error = (
                        f"minute window exhausted {minute_waits} times in a row; "
                        "likely provider-side throttling — rerun later"
                    )
                    break
                # Провайдер обнулил минутный остаток, и его шапка не обновится,
                # пока не придёт новый ответ, а ответ невозможен, пока acquire()
                # поднимается на устаревшем нуле. Ждём смены окна и перецепляем
                # клиента на свежий бюджет (суточный лимит проверяется по шапке
                # провайдера на первом же ответе — перерасхода не будет).
                delay = exc.retry_after_seconds + MINUTE_WAIT_MARGIN_SECONDS
                print(
                    f"quota: minute window exhausted ({minute_waits}/{MAX_MINUTE_WAITS}), "
                    f"sleeping {delay:.0f}s and re-attaching client",
                    flush=True,
                )
                time.sleep(delay)
                fresh = OpenDotaClient()
                extra_clients.append(fresh)
                client = fresh
                continue
            except (SourceUnavailableError, AuthError, SourceRequestError) as exc:
                # Транзиентные уже перебраны retry-политикой внутри клиента;
                # сюда попадают постоянные — продолжать бессмысленно.
                status = STATUS_FAILED
                error = f"{type(exc).__name__}: {exc}"
                break
            except IngestionError as exc:
                status = STATUS_FAILED
                error = f"{type(exc).__name__}: {exc}"
                break
            minute_waits = 0

            # Watermark для нисходящего обхода: текущий match_id — наименьший из
            # обработанных. `page_end` читает `_advance_cursor` — он же хранит
            # payload целиком, поэтому ключ дублируется явно.
            batch = dataclasses.replace(
                batch,
                cursor_payload={
                    "endpoint_kind": MATCH_DETAIL,
                    WATERMARK_KEY: match_id,
                    "page_end": match_id,
                },
            )
            result = capture.ingest_batch(batch, run_id)
            fetched += 1
            raw_inserted += int(result.raw_inserted)
            observations += result.observations_inserted
            quarantined += result.quarantined_inserted
            if batch.retrieval_status == RetrievalStatus.NOT_FOUND:
                not_found += 1
            else:
                usable += len(batch.records)
            watermark_after = match_id

            if fetched % 50 == 0:
                print(
                    f"progress: fetched={fetched}/{len(candidates)} "
                    f"usable={usable} not_found={not_found} watermark={watermark_after}",
                    flush=True,
                )
    finally:
        # Перецепленные клиенты закрываются при любом исходе цикла.
        for fresh in extra_clients:
            fresh.close()

    if status == STATUS_COMPLETED and fetched >= limit:
        # Достигли бюджет — охват заведомо неполный, прогон помечается partial.
        status = STATUS_PARTIAL
    if status == STATUS_COMPLETED and candidates and fetched < len(candidates):
        status = STATUS_PARTIAL

    # `ingestion_run` закрывается явным статусом: «прогон закончился» не равно
    # «охват полный», partial/quota — это не ошибки, а факты.
    run_status = {
        STATUS_COMPLETED: RUN_COMPLETED,
        STATUS_PARTIAL: RUN_PARTIAL,
        STATUS_QUOTA_EXHAUSTED: RUN_QUOTA_EXHAUSTED,
        STATUS_FAILED: RUN_FAILED,
    }[status]
    capture.finish_run(
        run_id,
        status=run_status,
        error_summary=error,
        cursor_after=str(watermark_after) if watermark_after is not None else None,
    )

    quota = client.quota.snapshot()
    return {
        "run_id": run_id,
        "status": status,
        "candidates": len(candidates),
        "fetched": fetched,
        "usable": usable,
        "not_found": not_found,
        "quarantined": quarantined,
        "raw_inserted": raw_inserted,
        "observations": observations,
        "watermark_before": watermark_before,
        "watermark_after": watermark_after,
        "minute_waits": minute_waits,
        "quota_remaining": {"minute": quota.minute_remaining, "day": quota.day_remaining},
        "error": error,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Ограниченный sync-once match-detail ingestion OpenDota."
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help=f"Сколько матчей запросить за прогон (по умолчанию {DEFAULT_LIMIT}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    if args.limit < 1:
        print("--limit должен быть >= 1", file=sys.stderr)
        return 64

    with OpenDotaClient() as client:
        session = SessionLocal()
        try:
            report = run_match_details(
                session=session, client=client, limit=args.limit
            )
        finally:
            session.close()
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
    return EXIT_CODES.get(str(report["status"]), 1)


if __name__ == "__main__":
    raise SystemExit(main())
