#!/usr/bin/env python
"""CAL-001/CAL-002: калибровка champion'а (LR) по четырёхчастному протоколу.

Части: train (замороженный, модель не переобучается) → tuning (ранняя valid,
в этом прогоне не используется — зарезервирована) → purge (embargo-полоса) →
calibration (поздняя valid) → untouched test. Champion LR используется как
есть: он обучен только на train, поэтому для него весь valid — held-out, и
калибратор, фнтящийся на calibration-части, не видит обучающих данных модели.
Ограничение фиксируется честно: C champion'а выбирался на полном valid
(протокол ML-001/ML-002), то есть calibration-строки участвовали в выборе C;
строгая ревизия (выбор C только на tuning) — отдельный прогон.

Метод калибровки (Platt/isotonic) выбирается 2-фолдным cross-fitting внутри
calibration-части. Метрики до/после — на test (итоговое чтение; реестр чтений
test ведётся в docs/CALIBRATION.md).

Пример::

    python scripts/run_calibration.py docs/frozen_split_2026-09-26.json --dry-run
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from d2intel.db import SessionLocal
from d2intel.evaluation.calibration import (
    CalibrationSplit,
    apply_isotonic,
    apply_platt,
    calibration_report,
    carve_calibration_split,
    cross_fit_select,
    fit_isotonic,
    fit_platt,
)
from d2intel.evaluation.cohort import Game1Row, select_game1_cohort
from d2intel.evaluation.freeze import FrozenSplit, assert_frozen_matches
from d2intel.evaluation.metrics import accuracy
from d2intel.evaluation.split import assign_split
from d2intel.features.prior_form import EVENT_ASOF, PriorFormBuilder, PriorFormParams
from d2intel.models.registry import register_model_version

ALGORITHM = "logreg_prior_form_calibrated"
FEATURE_SCHEMA_VERSION = "prior-form.v1"
SEED = 17
CAL_FRAC = 0.5


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Калибровка champion LR: tuning/purge/calibration/test."
    )
    parser.add_argument("manifest", help="Заморозка (docs/frozen_split_*.json).")
    parser.add_argument("--dry-run", action="store_true", help="Без записи артефакта/версии.")
    parser.add_argument("--run-key", default=None)
    return parser.parse_args(argv)


def _git_commit() -> str | None:
    import subprocess

    try:
        out = subprocess.run(  # noqa: S603
            ["git", "rev-parse", "HEAD"],
            capture_output=True, text=True, check=True,
            cwd=Path(__file__).resolve().parents[1], timeout=10,
        )
    except (subprocess.SubprocessError, OSError):
        return None
    return out.stdout.strip() or None


def _align_and_segment(session: Any, spec: Any, rows: list[Game1Row]) -> dict[str, Any]:
    """Датасет в канонических координатах + разбиение по замороженному сплиту."""
    train_labels = [row.label for row in rows if assign_split(row.event_time, spec) == "train"]
    params = PriorFormParams.fit(train_labels=train_labels)
    frame, _meta = PriorFormBuilder(session, params, evaluation_mode=EVENT_ASOF).build()
    index = {row.series_id: row for row in rows}
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
    return {
        "train": aligned[aligned["split"] == "train"],
        "valid": aligned[aligned["split"] == "valid"],
        "test": aligned[aligned["split"] == "test"],
        "params": params,
    }


def _feature_matrix(segment: Any, columns: list[str]) -> tuple[Any, Any]:
    x = segment[columns].to_numpy(dtype=float)
    y = segment["y"].to_numpy(dtype=int)
    return x, y


def _impute(x: Any) -> Any:
    return np.nan_to_num(x, nan=0.0, posinf=0.0, neginf=0.0)


def _save_calibrator(payload: dict[str, Any], run_key: str) -> tuple[str, str]:
    cal_dir = Path("artifacts/calibration")
    cal_dir.mkdir(parents=True, exist_ok=True)
    file_name = f"calibration_{run_key[:12]}.json"
    path = cal_dir / file_name
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    return file_name, digest


def _test_rows(test: Any, rows: list[Game1Row]) -> list[Game1Row]:
    index = {row.series_id: row for row in rows}
    return [index[sid] for sid in test["series_id"] if sid in index]


def _now_iso() -> str:
    from datetime import UTC, datetime

    return datetime.now(UTC).isoformat()


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    frozen = FrozenSplit.from_dict(json.loads(manifest_path.read_text(encoding="utf-8")))
    spec = frozen.spec

    session = SessionLocal()
    try:
        rows = select_game1_cohort(session)
        assert_frozen_matches(rows, frozen)
        parts = _align_and_segment(session, spec, rows)
        params: PriorFormParams = parts["params"]

        from run_catboost_challenger import FEATURE_COLUMNS, fit_lr_baseline

        # CAL-001: границы четырёх частей. Tuning — ранняя valid (резерв),
        # purge — embargo-полоса, calibration — поздняя valid, test — нетронут.
        cal_split: CalibrationSplit = carve_calibration_split(
            spec.valid_from, spec.test_from, spec.embargo, cal_frac=CAL_FRAC
        )
        valid_parts: dict[str, list[dict[str, Any]]] = {
            "tuning": [], "purge": [], "calibration": [],
        }
        for record in parts["valid"].to_dict("records"):
            moment = record["cutoff_at"]
            if moment < cal_split.tuning_from:
                valid_parts["tuning"].append(record)
            elif moment < cal_split.cal_from:
                valid_parts["purge"].append(record)
            else:
                valid_parts["calibration"].append(record)
        cal_split.counts.update(
            {
                "train": int(len(parts["train"])),
                "tuning": len(valid_parts["tuning"]),
                "purge": len(valid_parts["purge"]),
                "calibration": len(valid_parts["calibration"]),
                "test": int(len(parts["test"])),
            }
        )

        # Champion LR с протоколом ML-001/ML-002: μ и C — на train/valid,
        # test не участвует. Для него весь valid — held-out.
        x_train, y_train = _feature_matrix(parts["train"], FEATURE_COLUMNS)
        x_valid, y_valid = _feature_matrix(parts["valid"], FEATURE_COLUMNS)
        x_test, _y_test = _feature_matrix(parts["test"], FEATURE_COLUMNS)
        champion, chosen_c = fit_lr_baseline(x_train, y_train, x_valid, y_valid)

        calibration = pd.DataFrame(valid_parts["calibration"])
        x_cal, y_cal = _feature_matrix(calibration, FEATURE_COLUMNS)
        probs_cal = champion.predict_proba(_impute(x_cal))[:, 1].tolist()
        probs_test = champion.predict_proba(_impute(x_test))[:, 1].tolist()

        # CAL-002: оба калибратора фнттся ТОЛЬКО на calibration; метод — cross-fit.
        selection = cross_fit_select(y_cal.tolist(), probs_cal, seed=SEED)
        if selection["chosen"] == "platt":
            calibrator = fit_platt(y_cal.tolist(), probs_cal, seed=SEED)
            probs_after = apply_platt(calibrator, probs_test).tolist()
        else:
            calibrator = fit_isotonic(y_cal.tolist(), probs_cal)
            probs_after = apply_isotonic(calibrator, probs_test).tolist()

        test_rows = _test_rows(parts["test"], rows)
        y_test = [row.label for row in test_rows]
        report = calibration_report(y_test, probs_test, probs_after)
        report["accuracy_before"] = accuracy(y_test, [1 if p >= 0.5 else 0 for p in probs_test])
        report["accuracy_after"] = accuracy(y_test, [1 if p >= 0.5 else 0 for p in probs_after])
        report["model_version_id"] = None

        if not args.dry_run:
            run_key = args.run_key or f"cal-{frozen.content_hash[:12]}"
            cal_payload = {
                "method": selection["chosen"],
                "fitted_on": "calibration segment (late valid)",
                "model": {
                    "base_algorithm": "logreg_prior_form (champion)",
                    "c": chosen_c,
                    "prior_mean": params.prior_mean,
                    "feature_columns": FEATURE_COLUMNS,
                    "n_train": int(len(parts["train"])),
                    "limitation": (
                        "C champion'а выбирался на полном valid (протокол ML-001/002); "
                        "calibration-строки участвовали в выборе C. Строгая ревизия — "
                        "выбор C только на tuning."
                    ),
                },
                "split": cal_split.to_dict(),
                "selection": selection,
                "frozen_at": _now_iso(),
            }
            if selection["chosen"] == "platt":
                cal_payload["platt"] = {
                    "coef": float(calibrator.coef_[0][0]),
                    "intercept": float(calibrator.intercept_[0]),
                }
            else:
                cal_payload["isotonic"] = {
                    "x_thresholds_": [float(v) for v in calibrator.X_thresholds_],
                    "y_thresholds_": [float(v) for v in calibrator.y_thresholds_],
                }
            artifact_uri, artifact_hash = _save_calibrator(cal_payload, run_key)
            model_version_id = register_model_version(
                session,
                algorithm=ALGORITHM,
                feature_schema_version=FEATURE_SCHEMA_VERSION,
                seed=SEED,
                hyperparameters={
                    "run_key": run_key,
                    "base_algorithm": "logreg_prior_form",
                    "c": chosen_c,
                    "calibration_method": selection["chosen"],
                    "calibration_artifact": artifact_uri,
                    "calibration_artifact_sha256": artifact_hash,
                    "cal_split": cal_split.to_dict(),
                    "feature_columns": FEATURE_COLUMNS,
                    "prior_mean": params.prior_mean,
                    "manifest": manifest_path.name,
                },
                artifact_uri=artifact_uri,
                artifact_hash=artifact_hash,
                code_commit=_git_commit(),
                run_key=run_key,
            )
            session.commit()
            report["model_version_id"] = str(model_version_id)
            report["calibration_artifact"] = {"uri": artifact_uri, "sha256": artifact_hash}

        report.update(
            {
                "manifest": str(manifest_path),
                "cal_split": cal_split.to_dict(),
                "selection": selection,
                "chosen_c": chosen_c,
                "dry_run": args.dry_run,
            }
        )
        print(json.dumps(report, ensure_ascii=False, indent=2, default=str))
        return 0
    finally:
        session.close()


if __name__ == "__main__":
    raise SystemExit(main())
