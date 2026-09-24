#!/usr/bin/env python
"""ML-001 (LR-часть): Logistic Regression на prior-form признаках.

Это первый кандидат, который несёт информацию сверх константы. Делает ровно
то же, что `run_prior_baseline.py`, но на признаках FEAT-001:

1. читает замороженный манифест и **падает**, если состав когорты изменился
   (тот же `assert_frozen_matches`, что у prior-базлайна);
2. строит prior-form датасет (`PriorFormBuilder`, режим `event_asof`) и
   совмещает его с когортой по `series_id` — целевая система координат
   остаётся **когортной** (Team A = меньший canonical team_id), поэтому
   если slot-0 источник disagrees с канонической стороной, пример
   разворачивается (фичи A/B и метка меняются местами);
3. трансформации (`PriorFormParams.fit` для prior_mean μ) — **только на
   train**, как требует AC #4;
4. обучает LR на train, подбирает гиперпараметры (C) **только на valid**,
   считает accuracy / log_loss / Brier на test относительно мажоритарного
   floor и p=0.5;
5. регистрирует версию модели (идемпотентно по run_key) и пишет
   неизменяемые снимки предсказаний на test-сегмент.

Никакого подбора под test: единственный прогон, порог ADR-006 —
предзарегистрированный, недостижение фиксируется честно.

Пример::

    python scripts/run_lr_baseline.py docs/frozen_split_2026-09-22.json
    python scripts/run_lr_baseline.py docs/frozen_split_2026-09-22.json --dry-run
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from sklearn.linear_model import LogisticRegression

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
from d2intel.evaluation.split import assign_split
from d2intel.features.prior_form import (
    EVENT_ASOF,
    PriorFormBuilder,
    PriorFormParams,
)
from d2intel.models.registry import register_model_version
from d2intel.models.repository import (
    append_prediction_snapshot,
    record_evaluation,
    upsert_prediction,
)

ALGORITHM = "logreg_prior_form"
FEATURE_SCHEMA_VERSION = "prior-form.v1"
ACCEPTANCE_THRESHOLD = 0.70  # ADR-006: предзарегистрированный порог, а не обещание.

# Признаки для модели: только дифференциалы (A−B) — инвариантны к стороне.
# Абсолютные значения сторон не используются: они несут информацию о раскладе
# только в отношении к оппоненту, а «сильная команда» без контекста — шум.
FEATURE_COLUMNS = [
    "d_team_wr_lifetime",
    "d_team_wr_last_long",
    "d_team_wr_last_short",
    "d_team_n_eff",
    "d_team_days_since_last",
    "d_player_wr",
    "d_player_kda",
    "d_player_gpm",
    "d_player_xpm",
]

C_GRID = (0.01, 0.1, 1.0, 10.0)
SEED = 17


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Logistic Regression на prior-form признаках, замороженный сплит."
    )
    parser.add_argument(
        "manifest", help="Путь к манифесту заморозки (docs/frozen_split_*.json)."
    )
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


def _segment(rows: list[Game1Row], spec: Any, name: str) -> list[Game1Row]:
    return [row for row in rows if assign_split(row.event_time, spec) == name]


def _build_matrix(session: Any, params: PriorFormParams) -> pd.DataFrame:
    """Датасет prior-form в системе slot-0 (как его выпускает билдер).

    `params` (μ) уже фитятся на train снаружи и прокидываются в билдер —
    именно так требует AC #4: обучение только на train. Выравнивание в
    каноническую систему координат когорты выполняет `_align_to_cohort`.
    """
    builder = PriorFormBuilder(session, params, evaluation_mode=EVENT_ASOF)
    frame, _meta = builder.build()
    return frame


def _cohort_index(rows: list[Game1Row]) -> dict[UUID, Game1Row]:
    """Индекс когорты по серии — канонический Team A живёт именно там."""
    return {row.series_id: row for row in rows}


def _align_to_cohort(
    frame: pd.DataFrame, rows: list[Game1Row]
) -> pd.DataFrame:
    """Выровнять датасет в каноническую систему координат когорты.

    Для каждой серии: если slot-0 Team A датасета не равен каноническому
    team_a_id когорты — переставить стороны (фичи A↔B, дифференциалы
    умножаются на −1, метка инвертируется). Примеры без серии в когорте
    отбрасываются: они не принадлежат замороженному сплиту.
    """
    index = _cohort_index(rows)
    aligned: list[dict[str, Any]] = []
    swap_columns_a = [c for c in frame.columns if c.startswith("team_a_")]
    swap_columns_b = [c for c in frame.columns if c.startswith("team_b_")]
    swap_player_a = [c for c in frame.columns if c.startswith("player_a_")]
    swap_player_b = [c for c in frame.columns if c.startswith("player_b_")]
    diff_columns = [c for c in frame.columns if c.startswith("d_")]

    for record in frame.to_dict("records"):
        series_id = record.get("series_id")
        cohort_row = index.get(series_id)
        if cohort_row is None:
            continue
        needs_flip = record.get("team_a_id") != cohort_row.team_a_id
        if not needs_flip:
            aligned.append(record)
            continue
        flipped = dict(record)
        for col_a, col_b in zip(swap_columns_a, swap_columns_b, strict=True):
            flipped[col_a], flipped[col_b] = record.get(col_b), record.get(col_a)
        for col_a, col_b in zip(swap_player_a, swap_player_b, strict=True):
            flipped[col_a], flipped[col_b] = record.get(col_b), record.get(col_a)
        for col in diff_columns:
            value = record.get(col)
            if isinstance(value, float) and np.isnan(value):
                flipped[col] = value
            elif isinstance(value, int | float):
                flipped[col] = -value
        flipped["y"] = 1 - int(record.get("y", 0))
        flipped["team_a_id"] = record.get("team_b_id")
        flipped["team_b_id"] = record.get("team_a_id")
        aligned.append(flipped)
    return pd.DataFrame.from_records(aligned)


def _feature_matrix(segment: pd.DataFrame) -> tuple[np.ndarray, np.ndarray]:
    x = segment[FEATURE_COLUMNS].to_numpy(dtype=float)
    y = segment["y"].to_numpy(dtype=int)
    return x, y


def _impute(x: np.ndarray, fill_value: float = 0.0) -> np.ndarray:
    """NaN → 0 для входа в LR.

    Unknown ≠ 0 в признаке (`FEATURES.md` §1), но LR не принимает NaN.
    Обнуление — это именно «нет сигнала», что для дифференциала означает
    «стороны равны». Маски доступности остаются в датасете для отчёта.
    """
    return np.nan_to_num(x, nan=fill_value, posinf=fill_value, neginf=fill_value)


def _fit_predict(
    train: pd.DataFrame,
    valid: pd.DataFrame,
    test: pd.DataFrame,
    params: PriorFormParams,
) -> tuple[dict[str, Any], LogisticRegression | None]:
    """Обучение на train, выбор C на valid, возврат модели и отчёта.

    `params` (μ) уже фитятся на train в `main` и прокидываются сюда только
    для отчёта — само обучение LR на них не завязано.
    """
    x_train, y_train = _feature_matrix(train)
    x_valid, y_valid = _feature_matrix(valid)
    x_test, y_test = _feature_matrix(test)

    choices: list[dict[str, Any]] = []
    y_valid_list = y_valid.tolist()
    for c_value in C_GRID:
        model = LogisticRegression(
            C=c_value,
            solver="lbfgs",
            max_iter=1000,
            random_state=SEED,
        )
        model.fit(_impute(x_train), y_train)
        proba_valid = model.predict_proba(_impute(x_valid))[:, 1].tolist()
        hard_valid = [1 if p >= 0.5 else 0 for p in proba_valid]
        choices.append(
            {
                "c": c_value,
                "model": model,
                "valid_log_loss": log_loss(y_valid_list, proba_valid),
                "valid_accuracy": accuracy(y_valid_list, hard_valid),
            }
        )
    if not choices:
        return {"c_grid": [], "chosen_c": None}, None
    best = min(choices, key=lambda item: item["valid_log_loss"])
    chosen_model = best["model"]
    proba_test = chosen_model.predict_proba(_impute(x_test))[:, 1].tolist()
    proba_train = chosen_model.predict_proba(_impute(x_train))[:, 1].tolist()

    report = {
        "params_fit_on_train": {
            "prior_mean": params.prior_mean,
            "note": "PriorFormParams.fit — на train-метках до сборки датасета (AC #4)",
        },
        "c_grid": [
            {key: value for key, value in item.items() if key != "model"}
            for item in choices
        ],
        "chosen_c": best["c"],
        "chosen_by": "min valid log_loss",
        "proba_test_min": float(min(proba_test)),
        "proba_test_max": float(max(proba_test)),
        "proba_train_min": float(min(proba_train)),
        "proba_train_max": float(max(proba_train)),
    }
    return report, chosen_model


def _segment_metrics(
    rows: list[Game1Row], probs: list[float], hard: list[int]
) -> dict[str, Any]:
    labels = [row.label for row in rows]
    boot = grouped_bootstrap_interval(
        labels, probs, groups=[row.group for row in rows], statistic=log_loss
    )
    return {
        "n": len(rows),
        "accuracy": accuracy(labels, hard),
        "log_loss": log_loss(labels, probs),
        "brier": brier_score(labels, probs),
        "log_loss_uniform": uniform_log_loss(len(labels)),
        "majority_floor": majority_class_accuracy(labels),
        "bootstrap_log_loss": boot.as_dict(),
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    with manifest_path.open(encoding="utf-8") as handle:
        manifest = json.load(handle)
    frozen = FrozenSplit.from_dict(manifest)
    spec = frozen.spec

    session = SessionLocal()
    try:
        cohort = select_game1_cohort(session)
        assert_frozen_matches(cohort, frozen)

        # μ (prior_mean) фитится строго на train-метках когорты — до сборки
        # датасета, т.к. билдер использует его для shrinkage (AC #4).
        train_labels = [row.label for row in _segment(cohort, spec, "train")]
        params = PriorFormParams.fit(train_labels=train_labels)

        # Датасет prior-form в координатах когорты.
        frame = _build_matrix(session, params)
        if frame.empty:
            print(json.dumps({"error": "prior-form dataset is empty"}, indent=2))
            return 1
        aligned = _align_to_cohort(frame, cohort)
        if aligned.empty:
            print(json.dumps({"error": "no series aligned to frozen cohort"}, indent=2))
            return 1

        aligned["split"] = [
            assign_split(cutoff, spec) for cutoff in aligned["cutoff_at"]
        ]
        train = aligned[aligned["split"] == "train"]
        valid = aligned[aligned["split"] == "valid"]
        test = aligned[aligned["split"] == "test"]

        if train.empty or valid.empty or test.empty:
            print(
                json.dumps(
                    {
                        "error": "empty segment after freeze alignment",
                        "n_train": int(len(train)),
                        "n_valid": int(len(valid)),
                        "n_test": int(len(test)),
                    },
                    indent=2,
                )
            )
            return 1

        fit_report, model = _fit_predict(train, valid, test, params)
        if model is None:
            print(json.dumps({"error": "model could not be fit", **fit_report}, indent=2))
            return 1

        x_test, _y_test = _feature_matrix(test)
        proba_test = model.predict_proba(_impute(x_test))[:, 1].tolist()
        hard_test = [1 if p >= 0.5 else 0 for p in proba_test]

        test_rows = _test_rows(test, cohort)
        test_metrics = _segment_metrics(test_rows, proba_test, hard_test)

        # Снимки в БД — только не dry-run.
        snapshots: dict[str, Any] = {}
        model_version_id = None
        if not args.dry_run:
            run_key = args.run_key or frozen.content_hash
            model_version_id = register_model_version(
                session,
                algorithm=ALGORITHM,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                seed=SEED,
                hyperparameters={
                    "c": fit_report["chosen_c"],
                    "solver": "lbfgs",
                    "feature_columns": FEATURE_COLUMNS,
                    "n_train": int(len(train)),
                },
                code_commit=_git_commit(),
                run_key=run_key,
            )
            snapshots = _write_snapshots(
                session,
                model_version_id=model_version_id,
                test_rows=test_rows,
                probs=proba_test,
            )
            session.commit()

        acc = test_metrics["accuracy"]
        threshold = ACCEPTANCE_THRESHOLD
        report = {
            "manifest": str(manifest_path),
            "model": {
                "algorithm": ALGORITHM,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "n_train": int(len(train)),
                "n_valid": int(len(valid)),
                "n_test": int(len(test)),
                "model_version_id": str(model_version_id) if model_version_id else None,
            },
            "fit": fit_report,
            "test": {**test_metrics, **snapshots},
            "acceptance": {
                "threshold_accuracy": threshold,
                "measured_accuracy": acc,
                "threshold_met": acc >= threshold,
                "note": (
                    "threshold — предзарегистрированный порог ADR-006, не обещание. "
                    "LR — первый кандидат с признаками; недостижение порога "
                    "фиксируется честно, подбор под test запрещён."
                ),
            },
            "sample_verdict": sample_size_verdict(len(test_rows)),
            "dry_run": args.dry_run,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        session.close()


def _test_rows(test: pd.DataFrame, cohort: list[Game1Row]) -> list[Game1Row]:
    """Строки когорты для test-сегмента в порядке датасета."""
    index = _cohort_index(cohort)
    result: list[Game1Row] = []
    for series_id in test["series_id"]:
        row = index.get(series_id)
        if row is not None:
            result.append(row)
    return result


def _write_snapshots(
    session: Any,
    *,
    model_version_id: UUID,
    test_rows: list[Game1Row],
    probs: list[float],
) -> dict[str, Any]:
    """Неизменяемые снимки на test-сегмент + сверка с фактом.

    API `models/repository`: prediction — это запись цели (game+teams), снимок
    — фактическое предсказание с p_a и cutoff, evaluation — сверка снимка с
    исходом. Идемпотентность на всех трёх уровнях: повторный прогон того же
    эксперимента не плодит дубли.
    """
    predictions = 0
    snapshots = 0
    evaluations = 0
    for row, prob in zip(test_rows, probs, strict=True):
        prediction_id = upsert_prediction(
            session,
            game_id=row.game_id,
            team_a_id=row.team_a_id,
            team_b_id=row.team_b_id,
        )
        predictions += 1
        snapshot_id = append_prediction_snapshot(
            session,
            prediction_id=prediction_id,
            game_id=row.game_id,
            model_version_id=model_version_id,
            cutoff_at=row.event_time,
            event_time=row.event_time,
            p_a=float(prob),
        )
        snapshots += 1
        record_evaluation(
            session,
            snapshot_id=snapshot_id,
            y=bool(row.label),
            log_loss=log_loss([row.label], [float(prob)]),
            brier=brier_score([row.label], [float(prob)]),
        )
        evaluations += 1
    return {
        "predictions_written": predictions,
        "snapshots_written": snapshots,
        "evaluations_written": evaluations,
    }


if __name__ == "__main__":
    raise SystemExit(main())
