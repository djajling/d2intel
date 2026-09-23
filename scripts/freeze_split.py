#!/usr/bin/env python
"""Заморозить сплит game1 и записать манифест в репозиторий.

Pre-registration по ML-001/ADR-006: heldout фиксируется **до** какого-либо
обучения. Манифест коммитится в `docs/`, хэш — его содержание.

Скрипт намеренно "хрупкий": если манифест с таким именем уже существует, а
состав когорты изменился — он падает, а не перезаписывает. Переобучаться на
новом составе test можно только новой заморозкой с новым именем и явной
записью в run-manifest.

Примеры:

    python scripts/freeze_split.py
    python scripts/freeze_split.py --valid-frac 0.70 --test-frac 0.15 --embargo-hours 24
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from d2intel.db import SessionLocal
from d2intel.evaluation.cohort import cohort_report, select_game1_cohort
from d2intel.evaluation.freeze import EXCLUDED_KEY, SEGMENTS, FrozenSplit, freeze_split
from d2intel.evaluation.split import SplitSpec

DOCS = Path(__file__).resolve().parents[1] / "docs"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Заморозить train/valid/test сплит game1 (pre-registration)."
    )
    parser.add_argument(
        "--valid-frac", type=float, default=0.70, help="Доля времени, отводимая под train."
    )
    parser.add_argument(
        "--test-frac", type=float, default=0.15, help="Доля времени под test (с конца)."
    )
    parser.add_argument(
        "--embargo-hours", type=float, default=24.0, help="Разрыв между сегментами, часы."
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Имя манифеста (без расширения). По умолчанию frozen_split_<сегодня>.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Перезаписать существующий манифест (только если хэш не изменился).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if not 0.0 < args.test_frac < 1.0 or not 0.0 < args.valid_frac < 1.0:
        print("Доли должны быть в интервале (0, 1)", file=sys.stderr)
        return 64
    if args.valid_frac + args.test_frac >= 1.0:
        print("valid_frac + test_frac должны быть < 1", file=sys.stderr)
        return 64

    session = SessionLocal()
    try:
        rows = select_game1_cohort(session)
    finally:
        session.close()

    report = cohort_report(rows)
    if not rows:
        print(json.dumps({"cohort": report, "frozen": False}, ensure_ascii=False, indent=2))
        return 0

    times = [row.event_time for row in rows]
    span = (max(times) - min(times)).total_seconds()
    valid_from = min(times) + timedelta(seconds=span * args.valid_frac)
    test_from = max(times) - timedelta(seconds=span * args.test_frac)
    if test_from <= valid_from:
        print(
            json.dumps(
                {
                    "cohort": report,
                    "frozen": False,
                    "note": "недостаточный временной охват для train/valid/test",
                },
                ensure_ascii=False,
                indent=2,
                default=str,
            )
        )
        return 0

    spec = SplitSpec(
        valid_from=valid_from,
        test_from=test_from,
        embargo=timedelta(hours=args.embargo_hours),
    )
    frozen = freeze_split(rows, spec, frozen_at=datetime.now(UTC))

    name = args.name or f"frozen_split_{datetime.now(UTC).date().isoformat()}"
    out_path = DOCS / f"{name}.json"
    if out_path.exists():
        existing = FrozenSplit.from_dict(json.loads(out_path.read_text(encoding="utf-8")))
        if existing.content_hash != frozen.content_hash and not args.force:
            print(
                f"ОТКАЗ: манифест {out_path} уже существует, а состав когорты изменился "
                f"manifest={existing.content_hash} actual={frozen.content_hash}.\n"
                "Замороженный heldout — это pre-registration: нельзя тихо его менять. "
                "Используйте --force только если понимаете, что перезаписываете заморозку, "
                "и задокументируйте это в run-manifest.",
                file=sys.stderr,
            )
            return 73

    out_path.write_text(
        json.dumps(frozen.to_dict(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    print(
        json.dumps(
            {
                "manifest": str(out_path),
                "cohort": report,
                "spec": frozen.to_dict()["spec"],
                "counts": {name_: frozen.counts.get(name_, 0) for name_ in (*SEGMENTS, EXCLUDED_KEY)},
                "content_hash": frozen.content_hash,
                "frozen_at": frozen.frozen_at.isoformat(),
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
