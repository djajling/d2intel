#!/usr/bin/env python
"""EVAL-001: итоговая оценка исходов champion'а (LR) на frozen test.

Читает замороженный сплит, восстанавливает вероятности champion'а с
идентичным протоколом ML-001/ML-002 (C выбран на valid — в рамках этого
прогона, test не участвует в подборе) и выпускает отчёт
`docs/OUTCOME_EVAL.md` + JSON: метрики (Brier/logloss/ECE), grouped
bootstrap по сериям **и по времени**, вердикт `sufficient` /
`insufficient evidence` со ссылкой на порог PRD (G-MODEL 0.70, ADR-007).

Пример::

    python scripts/evaluate_outcomes.py docs/frozen_split_2026-09-26.json
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from d2intel.db import SessionLocal
from d2intel.evaluation.cohort import Game1Row, select_game1_cohort
from d2intel.evaluation.freeze import FrozenSplit, assert_frozen_matches
from d2intel.evaluation.outcomes import evaluate_outcomes
from d2intel.evaluation.split import assign_split
from d2intel.features.prior_form import EVENT_ASOF, PriorFormBuilder, PriorFormParams

DOCS = Path(__file__).resolve().parents[1] / "docs"

THRESHOLD_ACCURACY = 0.70
PRD_REFERENCE = "docs/PRD.md §5 G-MODEL (accuracy ≥ 0.70 per-game, frozen test); ADR-007"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Итоговая оценка исходов champion (LR) на frozen test."
    )
    parser.add_argument("manifest", help="Путь к заморозке (docs/frozen_split_*.json).")
    parser.add_argument(
        "--no-write",
        action="store_true",
        help="Не писать docs/OUTCOME_EVAL.md и JSON, только напечатать.",
    )
    return parser.parse_args(argv)


def _segment(rows: list[Game1Row], spec: Any, name: str) -> list[Game1Row]:
    return [row for row in rows if assign_split(row.event_time, spec) == name]


def _align_and_split(session: Any, spec: Any, frozen: FrozenSplit) -> tuple[Any, Any, Any]:
    """Канонические координаты когорты + сегменты (протокол ML-001/ML-002)."""
    import numpy as np
    import pandas as pd

    train_labels = [row.label for row in _segment(_rows_cache, spec, "train")]
    params = PriorFormParams.fit(train_labels=train_labels)
    builder = PriorFormBuilder(session, params, evaluation_mode=EVENT_ASOF)
    frame, _meta = builder.build()
    index = {row.series_id: row for row in _rows_cache}
    aligned_rows: list[dict[str, Any]] = []
    swap_a = [c for c in frame.columns if c.startswith("team_a_")]
    swap_b = [c for c in frame.columns if c.startswith("team_b_")]
    swap_pa = [c for c in frame.columns if c.startswith("player_a_")]
    swap_pb = [c for c in frame.columns if c.startswith("player_b_")]
    diffs = [c for c in frame.columns if c.startswith("d_")]
    for record in frame.to_dict("records"):
        cohort_row = index.get(record.get("series_id"))
        if cohort_row is None:
            continue
        if record.get("team_a_id") == cohort_row.team_a_id:
            aligned_rows.append(record)
            continue
        flipped = dict(record)
        for col_a, col_b in zip(swap_a, swap_b, strict=True):
            flipped[col_a], flipped[col_b] = record.get(col_b), record.get(col_a)
        for col_a, col_b in zip(swap_pa, swap_pb, strict=True):
            flipped[col_a], flipped[col_b] = record.get(col_b), record.get(col_a)
        for col in diffs:
            value = record.get(col)
            if isinstance(value, float) and np.isnan(value):
                flipped[col] = value
            elif isinstance(value, int | float):
                flipped[col] = -value
        flipped["y"] = 1 - int(record.get("y", 0))
        flipped["team_a_id"] = record.get("team_b_id")
        flipped["team_b_id"] = record.get("team_a_id")
        aligned_rows.append(flipped)
    aligned = pd.DataFrame.from_records(aligned_rows)
    aligned["split"] = [assign_split(cutoff, spec) for cutoff in aligned["cutoff_at"]]
    return (
        aligned[aligned["split"] == "train"],
        aligned[aligned["split"] == "valid"],
        aligned[aligned["split"] == "test"],
    )


_rows_cache: list[Game1Row] = []


def main(argv: list[str] | None = None) -> int:
    global _rows_cache
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    frozen = FrozenSplit.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    spec = frozen.spec

    session = SessionLocal()
    try:
        _rows_cache = select_game1_cohort(session)
        assert_frozen_matches(_rows_cache, frozen)
        train, valid, test = _align_and_split(session, spec, frozen)

        from run_catboost_challenger import _feature_matrix, _impute, fit_lr_baseline

        x_train, y_train = _feature_matrix(train)
        x_valid, y_valid = _feature_matrix(valid)
        x_test, _y = _feature_matrix(test)
        model, chosen_c = fit_lr_baseline(x_train, y_train, x_valid, y_valid)
        probs = model.predict_proba(_impute(x_test))[:, 1].tolist()

        # Строки когорты в ПОРЯДКЕ test-фрейма (как в run_lr_baseline._test_rows):
        # вероятности идут в порядке датасета, сопоставление по series_id.
        index = {row.series_id: row for row in _rows_cache}
        test_rows: list[Game1Row] = []
        for series_id in test["series_id"]:
            row = index.get(series_id)
            if row is not None:
                test_rows.append(row)
        if len(test_rows) != len(probs):
            print(
                json.dumps(
                    {
                        "error": "порядок test-сегмента не совпал с когортой",
                        "n_test_frame": len(probs),
                        "n_test_cohort": len(test_rows),
                    },
                    indent=2,
                )
            )
            return 1
        report = evaluate_outcomes(
            labels=[row.label for row in test_rows],
            probs=probs,
            series_groups=[row.series_id for row in test_rows],
            event_times=[row.event_time for row in test_rows],
            threshold_accuracy=THRESHOLD_ACCURACY,
            prd_reference=PRD_REFERENCE,
        )
        report["model"] = {
            "algorithm": "logreg_prior_form (champion)",
            "chosen_c": chosen_c,
            "protocol": "идентичен ML-001/ML-002: μ на train, C по min valid log_loss",
            "split_manifest": str(manifest_path),
        }
        payload = json.dumps(report, ensure_ascii=False, indent=2, default=str)
        print(payload)
        if args.no_write:
            return 0

        (DOCS / "OUTCOME_EVAL.json").write_text(payload + "\n", encoding="utf-8")
        verdict = report["verdict"]
        metrics = report["metrics"]
        md = f"""# OUTCOME_EVAL — итоговая оценка исходов champion (EVAL-001)

Дата: {datetime.now().date().isoformat()} · Сплит: `{manifest_path.name}` ·
Модель: LR (champion), C = {chosen_c}, протокол идентичен ML-001/ML-002
(C выбран на valid, untouched test использован только для этой итоговой оценки).

## Метрики (n={report['n']})

| Метрика | Значение |
|---|---|
| accuracy | {metrics['accuracy']:.4f} |
| log_loss | {metrics['log_loss']:.4f} (uniform {metrics['log_loss_uniform']:.4f}) |
| Brier | {metrics['brier']:.4f} |
| ECE (10 бинов) | {metrics['expected_calibration_error']:.4f} |
| majority floor | {metrics['majority_floor']:.4f} |

## Неопределённость (bootstrap по группам, 2000 репликаций)

| Статистика | По сериям ({report['n_series']} серий) | По времени ({report['n_time_buckets']} недель) |
|---|---|---|
| log_loss, 95% CI | {report['bootstrap_log_loss_by_series']['low']:.4f} – {report['bootstrap_log_loss_by_series']['high']:.4f} | {report['bootstrap_log_loss_by_time']['low']:.4f} – {report['bootstrap_log_loss_by_time']['high']:.4f} |
| Brier, 95% CI | {report['bootstrap_brier_by_series']['low']:.4f} – {report['bootstrap_brier_by_series']['high']:.4f} | — |

## Вердикт

**{verdict['outcome']}**: accuracy {metrics['accuracy']:.4f} при пороге
{verdict['threshold_accuracy']:.2f} ({verdict['prd_reference']});
threshold_met = {verdict['threshold_met']}, объём n={report['n']} ≥ 30 =
{verdict['volume_ok']}.

{verdict['no_significance_claim']}

Порог не достигнут — это ожидаемо зафиксировано (ADR-007): модели не
подгонялись под порог, gейт G-MODEL оформляется как решение владельца.
Калибровка — отдельный этап (CAL-002/003), ECE здесь диагностическая метрика.
"""
        (DOCS / "OUTCOME_EVAL.md").write_text(md, encoding="utf-8")
        print(f"WROTE {DOCS / 'OUTCOME_EVAL.md'} и OUTCOME_EVAL.json")
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
