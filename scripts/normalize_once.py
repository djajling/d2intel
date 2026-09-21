#!/usr/bin/env python
"""DATA-001 — разовый прогон нормализации поверх уже записанного raw.

Скрипт не ходит в сеть: он читает `raw_payload`/`source_observation`,
записанные `ING-001`, и пишет canonical-слой. Повторный запуск идемпотентен.

Пример:

    python scripts/normalize_once.py

Вывод — JSON-отчёт со счётчиками созданных строк и карантином по причинам.
"""

from __future__ import annotations

import argparse
import json

from d2intel.db import SessionLocal
from d2intel.normalize.pipeline import normalize_once


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Нормализация исторического ядра из raw (DATA-001)."
    )
    parser.add_argument(
        "--source",
        default="opendota",
        help="Имя источника в data_source (по умолчанию opendota).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    session = SessionLocal()
    try:
        report = normalize_once(session, source_id=args.source)
    finally:
        session.close()
    print(json.dumps(report.as_dict(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
