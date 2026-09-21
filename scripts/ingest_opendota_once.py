#!/usr/bin/env python
"""ING-001 — разовый (sync-once) прогон ingestion OpenDota.

Тонкий entrypoint: вся логика в `d2intel.ingestion`. Запуск ограничен по
умолчанию одной страницей, чтобы не расходовать квоту (60/мин, 3 000/день).

Примеры:

    # проверить форму ответа без записи в БД
    python scripts/ingest_opendota_once.py --dry-run

    # записать одну страницу /api/proMatches в raw
    python scripts/ingest_opendota_once.py --pages 1

Коды возврата: 0 completed, 2 partial, 3 stale, 4 failed, 5 quota_exhausted.
Секреты не выводятся: API-ключ (если задан в окружении) нигде не печатается.
"""

from __future__ import annotations

import argparse
import json
import sys

from d2intel.db import SessionLocal
from d2intel.ingestion.opendota_client import OpenDotaClient
from d2intel.ingestion.raw_capture import (
    RUN_COMPLETED,
    RUN_FAILED,
    RUN_PARTIAL,
    RUN_QUOTA_EXHAUSTED,
    RUN_STALE,
)
from d2intel.ingestion.sync_once import dry_run_page, run_sync_once

EXIT_CODES = {
    RUN_COMPLETED: 0,
    RUN_PARTIAL: 2,
    RUN_STALE: 3,
    RUN_FAILED: 4,
    RUN_QUOTA_EXHAUSTED: 5,
}


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Ограниченный sync-once ingestion OpenDota (ING-001).")
    parser.add_argument(
        "--pages",
        type=int,
        default=1,
        help="Сколько страниц /api/proMatches запросить за прогон (по умолчанию 1).",
    )
    parser.add_argument(
        "--overlap-pages",
        type=int,
        default=1,
        help="Сколько последних страниц повторно наблюдать (поздние исправления).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Запросить одну страницу и показать форму ответа, ничего не записывая.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.pages < 1:
        print("--pages должен быть >= 1", file=sys.stderr)
        return 64

    with OpenDotaClient() as client:
        if args.dry_run:
            print(json.dumps(dry_run_page(client), ensure_ascii=False, indent=2))
            return 0
        session = SessionLocal()
        try:
            report = run_sync_once(
                session=session,
                client=client,
                max_pages=args.pages,
                overlap_pages=args.overlap_pages,
            )
        finally:
            session.close()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return EXIT_CODES.get(report.status, 1)


if __name__ == "__main__":
    raise SystemExit(main())
