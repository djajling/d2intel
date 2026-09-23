#!/usr/bin/env python
"""Загрузка справочника патчей `/api/constants/patch` в raw-слой.

Справочник меняется редко, поэтому за один прогон делается **ровно один запрос**
(квота OpenDota: 60/мин, 3000/день). Полученный batch пишется обычным путём
`ING-001`: `raw_payload` + `source_observation` с видом `patch_constants`.
После этого `scripts/normalize_once.py` создаёт строки `patch`.

Примеры:

    python scripts/ingest_patch_constants.py            # один запрос, с кэшем клиента
    python scripts/ingest_patch_constants.py --refresh   # игнорировать кэш клиента

Прогон идемпотентен: повторный вызов записывает то же наблюдение повторно,
не продвигая watermark вперёд (курсор для справочника не используется).
"""

from __future__ import annotations

import argparse
import json

from d2intel.db import SessionLocal
from d2intel.ingestion.opendota_client import OpenDotaClient
from d2intel.ingestion.raw_capture import RUN_COMPLETED, RUN_FAILED, RawCapture


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Однозапросная загрузка справочника патчей OpenDota в raw (ING-001)."
    )
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Игнорировать кэш клиента и выполнить живой запрос.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session = SessionLocal()
    try:
        with OpenDotaClient() as client:
            batch = client.fetch_patch_constants(refresh=args.refresh)
            capture = RawCapture(session, client.contract)
            run_id = capture.start_run()
            try:
                result = capture.ingest_batch(batch, run_id)
                capture.finish_run(
                    run_id,
                    status=RUN_COMPLETED,
                    quota_headers=client.quota.journal_payload(
                        source_id=client.contract.source_id
                    ),
                )
            except Exception as exc:  # pragma: no cover - аварийный путь
                capture.finish_run(run_id, status=RUN_FAILED, error_summary=str(exc)[:500])
                raise
        print(
            json.dumps(
                {
                    "run_id": run_id,
                    "status": RUN_COMPLETED,
                    "endpoint_kind": batch.endpoint_kind,
                    "records": len(batch.records),
                    "quarantined": len(batch.quarantined),
                    "retrieval_status": batch.retrieval_status,
                    "observed_at": batch.observed_at.isoformat(),
                    "raw_inserted": result.raw_inserted,
                    "observations_inserted": result.observations_inserted,
                    "cursor_advanced": result.cursor_advanced,
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
