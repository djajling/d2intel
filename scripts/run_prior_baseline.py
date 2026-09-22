#!/usr/bin/env python
"""Первый baseline на реальных данных: константный prior на замороженном сплите.

Это **не** попытка выбить 0.70 (ADR-006). Prior — это обязательный нижний
ориентир: он сообщает ровно ту информацию, которая есть в частоте побед Team A
на train, и ничего больше. Без признаков (FEAT-001) лучше него быть нельзя.

Что делает скрипт:

1. читает замороженный манифест и **падает**, если состав когорты изменился;
2. фитит prior **только на train**;
3. считает accuracy / log_loss / Brier на valid и test относительно
   мажоритарного floor и «ничего не знаю» (p = 0.5);
4. регистрирует версию модели и пишет неизменяемые снимки предсказаний на
   test-сегмент (это и есть первые реальные предсказания в БД).

Пример:

    python scripts/run_prior_baseline.py docs/frozen_split_2026-09-22.json
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path
from typing import Any
from uuid import UUID

from d2intel.db import SessionLocal
from d2intel.evaluation.cohort import Game1Row, select_game1_cohort
from d2intel.evaluation.freeze import FrozenSplit, assert_frozen_matches
from d2intel.evaluation.metrics import (
    accuracy,
    brier_score,
    grouped_bootstrap_interval,
    log_loss,
    majority_class_accuracy,
    sample_size_verdict,
    uniform_log_loss,
)
from d2intel.evaluation.split import SplitName, assign_split
from d2intel.models.prior import PriorBaseline
from d2intel.models.registry import register_model_version
from d2intel.models.repository import (
    append_prediction_snapshot,
    record_evaluation,
    upsert_prediction,
)

ALGORITHM = "prior_const"
FEATURE_SCHEMA_VERSION = "none.v1"
ACCEPTANCE_THRESHOLD = 0.70  # ADR-006: предзарегистрированный порог, а не обещание.


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Baseline prior на замороженном сплите game1."
    )
    parser.add_argument("manifest", help="Путь к манифесту заморозки (docs/frozen_split_*.json).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Считать метрики и напечатать отчёт, не записывая снимки в БД.",
    )
    parser.add_argument(
        "--run-key",
        default=None,
        help="Ключ идемпотентности версии модели. По умолчанию — хэш манифеста.",
    )
    return parser.parse_args(argv)


def _git_commit() -> str | None:
    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
            cwd=Path(__file__).resolve().parents[1],
            timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def _segment(rows: list[Game1Row], spec, name: SplitName) -> list[Game1Row]:
    return [row for row in rows if assign_split(row.event_time, spec) == name]


def _segment_metrics(rows: list[Game1Row], prior: PriorBaseline) -> dict[str, Any]:
    """Метрики константного prior на одном сегменте."""
    labels = [row.label for row in rows]
    probs = prior.predict(len(labels))
    hard = [prior.hard_label] * len(labels)
    boot = grouped_bootstrap_interval(
        labels, probs, groups=[row.group for row in rows], statistic=log_loss
    )
    return {
        "n": len(rows),
        "accuracy_prior": accuracy(labels, hard),
        "log_loss_prior": log_loss(labels, probs),
        "brier_prior": brier_score(labels, probs),
        "majority_class_accuracy_floor": majority_class_accuracy(labels),
        "log_loss_uniform_reference": uniform_log_loss(len(labels)),
        "log_loss_bootstrap": boot.as_dict(),
    }


def _write_test_snapshots(
    session, *, test_rows: list[Game1Row], prior: PriorBaseline, model_version_id: UUID
) -> dict[str, int]:
    """Неизменяемые снимки предсказаний на test + сверка с фактом."""
    written = 0
    evaluated = 0
    for row in test_rows:
        prediction_id = upsert_prediction(
            session,
            game_id=row.game_id,
            team_a_id=row.team_a_id,
            team_b_id=row.team_b_id,
        )
        snapshot_id = append_prediction_snapshot(
            session,
            prediction_id=prediction_id,
            game_id=row.game_id,
            model_version_id=model_version_id,
            cutoff_at=row.event_time,
            event_time=row.event_time,
            p_a=prior.predict_proba_a(),
        )
        written += 1
        record_evaluation(
            session,
            snapshot_id=snapshot_id,
            y=bool(row.label),
            log_loss=log_loss([row.label], [prior.predict_proba_a()]),
            brier=brier_score([row.label], [prior.predict_proba_a()]),
        )
        evaluated += 1
    return {"snapshots_written": written, "evaluations_written": evaluated}


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    if not manifest_path.is_file():
        print(f"манифест не найден: {manifest_path}", file=sys.stderr)
        return 64
    frozen = FrozenSplit.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))

    session = SessionLocal()
    try:
        rows = select_game1_cohort(session)
        try:
            assert_frozen_matches(rows, frozen)
        except Exception as exc:  # noqa: BLE001
            print(f"ОТКАЗ: {exc}", file=sys.stderr)
            return 73

        train_rows = _segment(rows, frozen.spec, "train")
        valid_rows = _segment(rows, frozen.spec, "valid")
        test_rows = _segment(rows, frozen.spec, "test")

        prior = PriorBaseline.fit([row.label for row in train_rows])
        if prior.is_abstaining:
            print(
                json.dumps(
                    {
                        "model": {"algorithm": ALGORITHM, "abstention": prior.abstention_reason},
                        "train_n": len(train_rows),
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            return 0

        test_metrics = _segment_metrics(test_rows, prior)
        valid_metrics = _segment_metrics(valid_rows, prior)
        test_n = len(test_rows)

        snapshots: dict[str, int] = {}
        model_version_id: UUID | None = None
        if not args.dry_run:
            run_key = args.run_key or f"manifest:{frozen.content_hash[:16]}"
            model_version_id = register_model_version(
                session,
                algorithm=ALGORITHM,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                hyperparameters={"p_a": prior.p_a, "fitted_n": prior.fitted_n},
                code_commit=_git_commit(),
                training_cutoff=frozen.spec.valid_from - frozen.spec.embargo,
                run_key=run_key,
            )
            snapshots = _write_test_snapshots(
                session, test_rows=test_rows, prior=prior, model_version_id=model_version_id
            )
            session.commit()

        threshold = ACCEPTANCE_THRESHOLD
        acc = float(test_metrics["accuracy_prior"])
        report = {
            "manifest": str(manifest_path),
            "content_hash": frozen.content_hash,
            "model": {
                "algorithm": ALGORITHM,
                "model_version_id": None if model_version_id is None else str(model_version_id),
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "p_a": prior.p_a,
                "fitted_n": prior.fitted_n,
                "hard_label": prior.hard_label,
                "training_cutoff": (frozen.spec.valid_from - frozen.spec.embargo).isoformat(),
            },
            "train": {"n": len(train_rows)},
            "valid": valid_metrics,
            "test": {**test_metrics, **snapshots},
            "acceptance": {
                "threshold_accuracy": threshold,
                "measured_accuracy": acc,
                "threshold_met": acc >= threshold,
                "note": (
                    "threshold — предзарегистрированный порог ADR-006, не обещание. "
                    "Prior по построению не является кандидатом на порог: он не несёт "
                    "информации сверх частоты побед Team A на train."
                ),
            },
            "sample_verdict": sample_size_verdict(test_n),
            "dry_run": args.dry_run,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
