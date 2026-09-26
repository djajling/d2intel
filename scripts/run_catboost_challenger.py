#!/usr/bin/env python
"""ML-002: CatBoost challenger (CPU) в сравнении с LR на замороженном сплите.

Протокол зафиксирован в manifest ДО обучения (`docs/ml/ML002_manifest.json`,
ADR-007): параметры выбираются **только на valid**, untouched test читается
один раз как итоговый гейт, сравнение с LR — парным grouped bootstrap по
сериям в рамках одного прогона. Победа над LR не требуется; повышение до
champion — отдельное решение владельца (реестр пишет `candidate`).

CatBoost обучается на NaN нативно (без импутации) — это зафиксированное
отличие от LR, который импутирует дифференциалы нулём. Обе политики указаны
в manifest, поэтому сравнение честное: каждая модель использует свою
задокументированную обработку неизвестных.

Отклонение от карточки (зафиксировано в manifest): PATCH-002/TEAM-002 не
входят — challenger обучается на тех же 9 prior-form признаках, что LR.

Пример::

    python scripts/run_catboost_challenger.py docs/ml/ML002_manifest.json --dry-run
    python scripts/run_catboost_challenger.py docs/ml/ML002_manifest.json
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
from pathlib import Path
from typing import Any
from uuid import UUID

import numpy as np
import pandas as pd
from catboost import CatBoostClassifier
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
from d2intel.features.prior_form import EVENT_ASOF, PriorFormBuilder, PriorFormParams
from d2intel.models.registry import register_model_version
from d2intel.models.repository import (
    append_prediction_snapshot,
    record_evaluation,
    upsert_prediction,
)

ALGORITHM = "catboost_prior_form"
BASELINE_ALGORITHM = "logreg_prior_form"
FEATURE_SCHEMA_VERSION = "prior-form.v1"
ACCEPTANCE_THRESHOLD = 0.70  # ADR-007: цель приёмки прогонов после вердикта.
SEED = 17
BOOTSTRAP_N = 2000

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

C_GRID = (0.01, 0.1, 1.0, 10.0)  # идентичен ML-001 — для честного парного сравнения.


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="CatBoost challenger на prior-form признаках, замороженный сплит."
    )
    parser.add_argument("manifest", help="Путь к manifest ML-002 (docs/ml/ML002_manifest.json).")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Обучить и напечатать отчёт, не регистрируя версию и не пиша снимки.",
    )
    parser.add_argument("--run-key", default=None, help="Ключ идемпотентности версии модели.")
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


# --------------------------------------------------------------------------- #
# Чистые функции (тестируются без БД)
# --------------------------------------------------------------------------- #


def select_best(grid_results: list[dict[str, Any]]) -> dict[str, Any]:
    """Выбрать параметры по min valid log_loss. Test в функцию не входит."""
    if not grid_results:
        raise ValueError("пустая сетка параметров")
    return min(grid_results, key=lambda item: item["valid_log_loss"])


def train_catboost(
    x_train: np.ndarray,
    y_train: np.ndarray,
    params: dict[str, Any],
    seed: int = SEED,
) -> CatBoostClassifier:
    """Обучить CatBoost на train с фиксированными гиперпараметрами (CPU)."""
    model = CatBoostClassifier(**params, random_seed=seed)
    model.fit(x_train, y_train)
    return model


def fit_lr_baseline(
    x_train: np.ndarray,
    y_train: np.ndarray,
    x_valid: np.ndarray,
    y_valid: np.ndarray,
) -> tuple[LogisticRegression, float]:
    """LR с протоколом ML-001: импутация NaN→0, выбор C по min valid log_loss."""
    best: dict[str, Any] | None = None
    for c_value in C_GRID:
        model = LogisticRegression(
            C=c_value, solver="lbfgs", max_iter=1000, random_state=SEED
        )
        model.fit(_impute(x_train), y_train)
        proba = model.predict_proba(_impute(x_valid))[:, 1].tolist()
        item = {"c": c_value, "model": model, "valid_log_loss": log_loss(y_valid.tolist(), proba)}
        if best is None or item["valid_log_loss"] < best["valid_log_loss"]:
            best = item
    assert best is not None
    return best["model"], float(best["c"])


def paired_log_loss_diff_bootstrap(
    y_true: list[int],
    probs_challenger: list[float],
    probs_baseline: list[float],
    groups: list[Any],
    *,
    n_boot: int = BOOTSTRAP_N,
    seed: int = SEED,
) -> dict[str, float | int]:
    """Парная разница log_loss (challenger − baseline) с bootstrap по группам.

    Группы (серии) пересэмплируются целиком — одинаковые индексы для обеих
    моделей, поэтому разница парная и дисперсия ниже, чем у двух независимых
    интервалов. Отрицательная разница = challenger лучше baseline.
    """
    if not (len(y_true) == len(probs_challenger) == len(probs_baseline) == len(groups)):
        raise ValueError("длины выборок не совпадают")
    by_group: dict[Any, list[int]] = {}
    for index, group in enumerate(groups):
        by_group.setdefault(group, []).append(index)
    group_keys = sorted(by_group, key=str)
    rng = np.random.default_rng(seed)
    diffs: list[float] = []
    for _ in range(n_boot):
        sampled = rng.choice(len(group_keys), size=len(group_keys), replace=True)
        indices = [index for pick in sampled for index in by_group[group_keys[pick]]]
        y = [y_true[index] for index in indices]
        diff = log_loss(y, [probs_challenger[index] for index in indices]) - log_loss(
            y, [probs_baseline[index] for index in indices]
        )
        diffs.append(diff)
    lower, upper = float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))
    return {
        "n_boot": n_boot,
        "mean_diff": float(np.mean(diffs)),
        "ci95_lower": lower,
        "ci95_upper": upper,
        "note": "отрицательное = challenger лучше baseline по log_loss",
    }


def _impute(x: np.ndarray, fill_value: float = 0.0) -> np.ndarray:
    """NaN → 0: политика LR (для сравнения); CatBoost эту функцию не использует."""
    return np.nan_to_num(x, nan=fill_value, posinf=fill_value, neginf=fill_value)


def _feature_matrix(segment: pd.DataFrame, columns: list[str]) -> tuple[np.ndarray, np.ndarray]:
    x = segment[columns].to_numpy(dtype=float)
    y = segment["y"].to_numpy(dtype=int)
    return x, y


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


def _coverage_stats(segment: pd.DataFrame) -> dict[str, Any]:
    """Фактическое покрытие признаков в сегменте — фиксируется в отчёте."""
    return {
        "team_a_avail": int(segment.get("team_a_avail", pd.Series(dtype=bool)).sum())
        if "team_a_avail" in segment
        else None,
        "player_a_avail": int(segment.get("player_a_avail", pd.Series(dtype=bool)).sum())
        if "player_a_avail" in segment
        else None,
        "n": int(len(segment)),
    }


# --------------------------------------------------------------------------- #
# Основной прогон
# --------------------------------------------------------------------------- #


def _segment(rows: list[Game1Row], spec: Any, name: str) -> list[Game1Row]:
    return [row for row in rows if assign_split(row.event_time, spec) == name]


def _build_matrix(session: Any, params: PriorFormParams) -> pd.DataFrame:
    builder = PriorFormBuilder(session, params, evaluation_mode=EVENT_ASOF)
    frame, _meta = builder.build()
    return frame


def _cohort_index(rows: list[Game1Row]) -> dict[UUID, Game1Row]:
    return {row.series_id: row for row in rows}


def _align_to_cohort(frame: pd.DataFrame, rows: list[Game1Row]) -> pd.DataFrame:
    """Канонические координаты когорты (копия протокола ML-001, см. его докстринг)."""
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
        if record.get("team_a_id") == cohort_row.team_a_id:
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


def _test_rows(test: pd.DataFrame, cohort: list[Game1Row]) -> list[Game1Row]:
    index = _cohort_index(cohort)
    result: list[Game1Row] = []
    for series_id in test["series_id"]:
        row = index.get(series_id)
        if row is not None:
            result.append(row)
    return result


def _save_artifact(model: CatBoostClassifier, run_key: str) -> tuple[str, str]:
    artifacts_dir = Path("artifacts/models")
    artifacts_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"{ALGORITHM}_{run_key[:12]}.cbm"
    path = artifacts_dir / file_name
    model.save_model(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return file_name, digest


def _write_snapshots(
    session: Any,
    *,
    model_version_id: UUID,
    test_rows: list[Game1Row],
    probs: list[float],
) -> dict[str, Any]:
    """Неизменяемые снимки test-сегмента + сверка (как в ML-001)."""
    predictions = snapshots = evaluations = 0
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


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    with manifest_path.open(encoding="utf-8") as handle:
        ml_manifest = json.load(handle)
    if ml_manifest.get("manifest_version") != "ml002-manifest.v1":
        print(json.dumps({"error": "неизвестная версия manifest"}, indent=2))
        return 1
    grid_spec = ml_manifest["param_grid"]
    columns = ml_manifest["features"].get("columns", FEATURE_COLUMNS)
    patch_spec = ml_manifest["features"].get("patch_weighting") or {}
    decay_grid = patch_spec.get("decay_grid")
    split_manifest_path = Path(ml_manifest["data"]["split_manifest"])
    with split_manifest_path.open(encoding="utf-8") as handle:
        frozen = FrozenSplit.from_dict(json.load(handle))
    spec = frozen.spec

    session = SessionLocal()
    try:
        cohort = select_game1_cohort(session)
        assert_frozen_matches(cohort, frozen)

        train_labels = [row.label for row in _segment(cohort, spec, "train")]
        params = PriorFormParams.fit(train_labels=train_labels)

        # --- PATCH-002: выбор patch_decay на valid (LR, test не читается) ----
        from sklearn.linear_model import LogisticRegression

        from d2intel.evaluation.metrics import log_loss as ll

        chosen_decay: float | None = None
        decay_report: list[dict[str, Any]] = []
        if decay_grid:
            for decay in decay_grid:
                d_params = PriorFormParams(
                    prior_mean=params.prior_mean, patch_decay=float(decay)
                )
                d_frame = _build_matrix(session, d_params)
                d_aligned = _align_to_cohort(d_frame, cohort)
                d_aligned["split"] = [
                    assign_split(cutoff, spec) for cutoff in d_aligned["cutoff_at"]
                ]
                d_train = d_aligned[d_aligned["split"] == "train"]
                d_valid = d_aligned[d_aligned["split"] == "valid"]
                xt, yt = _feature_matrix(d_train, columns)
                xv, yv = _feature_matrix(d_valid, columns)
                best_ll = None
                for c_value in C_GRID:
                    lr = LogisticRegression(
                        C=c_value, solver="lbfgs", max_iter=1000, random_state=SEED
                    )
                    lr.fit(_impute(xt), yt)
                    cur = ll(yv.tolist(), lr.predict_proba(_impute(xv))[:, 1].tolist())
                    if best_ll is None or cur < best_ll:
                        best_ll = cur
                decay_report.append(
                    {"patch_decay": float(decay), "valid_log_loss_lr_best": best_ll}
                )
            chosen_decay = min(
                decay_report, key=lambda item: item["valid_log_loss_lr_best"]
            )["patch_decay"]
            params = PriorFormParams(prior_mean=params.prior_mean, patch_decay=chosen_decay)

        frame = _build_matrix(session, params)
        if frame.empty:
            print(json.dumps({"error": "prior-form dataset is empty"}, indent=2))
            return 1
        aligned = _align_to_cohort(frame, cohort)
        aligned["split"] = [assign_split(cutoff, spec) for cutoff in aligned["cutoff_at"]]
        train = aligned[aligned["split"] == "train"]
        valid = aligned[aligned["split"] == "valid"]
        test = aligned[aligned["split"] == "test"]
        if train.empty or valid.empty or test.empty:
            print(json.dumps({"error": "empty segment after freeze alignment"}, indent=2))
            return 1

        # --- выбор параметров ТОЛЬКО на valid (test не читается) -------------
        x_train, y_train = _feature_matrix(train, columns)
        x_valid, y_valid = _feature_matrix(valid, columns)
        grid_results: list[dict[str, Any]] = []
        for depth in grid_spec["depth"]:
            for learning_rate in grid_spec["learning_rate"]:
                model = train_catboost(
                    x_train,
                    y_train,
                    {
                        "iterations": grid_spec["iterations"][0],
                        "depth": depth,
                        "learning_rate": learning_rate,
                        "l2_leaf_reg": grid_spec["l2_leaf_reg"][0],
                        "loss_function": grid_spec["loss_function"],
                        "task_type": "CPU",
                        "allow_writing_files": False,
                        "verbose": False,
                    },
                )
                proba_valid = model.predict_proba(x_valid)[:, 1].tolist()
                grid_results.append(
                    {
                        "depth": depth,
                        "learning_rate": learning_rate,
                        "valid_log_loss": log_loss(y_valid.tolist(), proba_valid),
                    }
                )
        chosen = select_best(grid_results)

        # --- финальное обучение на train с выбранными параметрами -----------
        challenger = train_catboost(
            x_train,
            y_train,
            {
                "iterations": grid_spec["iterations"][0],
                "depth": chosen["depth"],
                "learning_rate": chosen["learning_rate"],
                "l2_leaf_reg": grid_spec["l2_leaf_reg"][0],
                "loss_function": grid_spec["loss_function"],
                "task_type": "CPU",
                "allow_writing_files": False,
                "verbose": False,
            },
        )
        # --- baseline LR с идентичным протоколом (для парного сравнения) ----
        baseline, chosen_c = fit_lr_baseline(x_train, y_train, x_valid, y_valid)

        # --- untouched test: единственное чтение, итоговый гейт -------------
        x_test, _y_test = _feature_matrix(test, columns)
        proba_challenger = challenger.predict_proba(x_test)[:, 1].tolist()
        proba_baseline = baseline.predict_proba(_impute(x_test))[:, 1].tolist()
        hard_test = [1 if p >= 0.5 else 0 for p in proba_challenger]
        test_rows = _test_rows(test, cohort)
        challenger_metrics = _segment_metrics(test_rows, proba_challenger, hard_test)
        baseline_metrics = _segment_metrics(
            test_rows, proba_baseline, [1 if p >= 0.5 else 0 for p in proba_baseline]
        )
        paired = paired_log_loss_diff_bootstrap(
            [row.label for row in test_rows],
            proba_challenger,
            proba_baseline,
            groups=[row.group for row in test_rows],
        )

        model_version_id = None
        snapshots: dict[str, Any] = {}
        if not args.dry_run:
            run_key = args.run_key or f"ml002-{frozen.content_hash[:12]}"
            artifact_uri, artifact_hash = _save_artifact(challenger, run_key)
            model_version_id = register_model_version(
                session,
                algorithm=ALGORITHM,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                seed=SEED,
                hyperparameters={
                    **chosen,
                    "iterations": grid_spec["iterations"][0],
                    "l2_leaf_reg": grid_spec["l2_leaf_reg"][0],
                    "loss_function": grid_spec["loss_function"],
                    "task_type": "CPU",
                    "feature_columns": columns,
                    "nan_policy": "native",
                    "prior_mean": params.prior_mean,
                    "patch_decay": chosen_decay,
                    "patch_weight_version": patch_spec.get("version"),
                    "n_train": int(len(train)),
                    "manifest": manifest_path.name,
                    "manifest_sha256": hashlib.sha256(
                        manifest_path.read_bytes()
                    ).hexdigest(),
                },
                artifact_uri=artifact_uri,
                artifact_hash=artifact_hash,
                code_commit=_git_commit(),
                run_key=run_key,
            )
            snapshots = _write_snapshots(
                session,
                model_version_id=model_version_id,
                test_rows=test_rows,
                probs=proba_challenger,
            )
            session.commit()

        acc = challenger_metrics["accuracy"]
        report = {
            "manifest": str(manifest_path),
            "model": {
                "algorithm": ALGORITHM,
                "feature_schema_version": FEATURE_SCHEMA_VERSION,
                "n_train": int(len(train)),
                "n_valid": int(len(valid)),
                "n_test": int(len(test)),
                "model_version_id": str(model_version_id) if model_version_id else None,
                "coverage_train": _coverage_stats(train),
                "coverage_test": _coverage_stats(test),
            },
            "selection": {
                "rule": ml_manifest["selection"]["rule"],
                "grid_results": grid_results,
                "chosen": dict(chosen),
                "untouched_test_role": ml_manifest["selection"]["untouched_test_role"],
            },
            "patch_weighting": {
                "version": patch_spec.get("version"),
                "chosen_decay": chosen_decay,
                "decay_selection_report": decay_report,
                "weight_by_distance": {
                    f"d={d}": (chosen_decay ** d if chosen_decay is not None else None)
                    for d in range(5)
                }
                if chosen_decay is not None
                else {"legacy": "same/other"},
                "unknown_patch_weight": params.patch_other_weight,
            },
            "baseline_lr": {
                "algorithm": BASELINE_ALGORITHM,
                "chosen_c": chosen_c,
                "test": baseline_metrics,
            },
            "test_challenger": {**challenger_metrics, **snapshots},
            "paired_diff_log_loss": paired,
            "acceptance": {
                "threshold_accuracy": ACCEPTANCE_THRESHOLD,
                "measured_accuracy": acc,
                "threshold_met": acc >= ACCEPTANCE_THRESHOLD,
                "note": (
                    "Порог — цель приёмки ADR-007 для прогонов после вердикта; "
                    "недостижение фиксируется честно, подбор под test запрещён. "
                    "Повышение до champion — решение владельца; по умолчанию LR остаётся."
                ),
            },
            "sample_verdict": sample_size_verdict(len(test_rows)),
            "dry_run": args.dry_run,
        }
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
