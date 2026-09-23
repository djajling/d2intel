#!/usr/bin/env python
"""Сборка когорты game1 и разбиение на train/valid/test по времени.

Это **не** обучение и не метрика модели: скрипт показывает, на каких данных
мы вообще имеем право учиться и проверяться, и какой у когорты нижний ориентир
(точность константного прогноза).

Примеры:

    python scripts/build_game1_cohort.py
    python scripts/build_game1_cohort.py --embargo-hours 24 --test-frac 0.15
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta

from d2intel.db import SessionLocal
from d2intel.evaluation.cohort import cohort_report, select_game1_cohort
from d2intel.evaluation.metrics import sample_size_verdict
from d2intel.evaluation.split import SplitSpec, assert_groups_do_not_straddle, assign_split


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Когорта game1: состав, временные сегменты, нижний ориентир точности."
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
        print(json.dumps({"cohort": report, "splits": {}}, ensure_ascii=False, indent=2))
        return 0

    times = [row.event_time for row in rows]
    span = (max(times) - min(times)).total_seconds()
    valid_from = min(times) + timedelta(seconds=span * args.valid_frac)
    test_from = max(times) - timedelta(seconds=span * args.test_frac)
    if test_from <= valid_from:
        # Выборка слишком короткая для трёх сегментов — честно говорим об этом.
        print(
            json.dumps(
                {
                    "cohort": report,
                    "splits": {},
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
    splits = [assign_split(row.event_time, spec) for row in rows]
    assert_groups_do_not_straddle(
        groups=[row.group for row in rows], splits=splits
    )

    counts: dict[str, int] = {"train": 0, "valid": 0, "test": 0, "excluded": 0}
    for split in splits:
        counts[split if split else "excluded"] += 1

    print(
        json.dumps(
            {
                "cohort": report,
                "spec": {
                    "valid_from": spec.valid_from.isoformat(),
                    "test_from": spec.test_from.isoformat(),
                    "embargo_hours": args.embargo_hours,
                },
                "splits": counts,
                "test_sample_verdict": sample_size_verdict(counts["test"]),
                "majority_class_accuracy": report["majority_class_accuracy"],
                "note": "это ориентир когорты, а не метрика модели: модель ещё не обучена",
            },
            ensure_ascii=False,
            indent=2,
            default=str,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
