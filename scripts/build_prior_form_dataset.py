#!/usr/bin/env python
"""FEAT-001 — сборка prior-form датасета на реальных данных и отчёт покрытия.

Read-only по БД: ничего не пишет, только строит датасет через
`PriorFormBuilder` и печатает метаданные покрытия + базовые sanity-проверки.
Реальный прогон — обязательный артефакт DoD (§3.1.5): результат приложен,
синтетики нет.

Ключевой сигнал — `player_*_avail`: до match-detail enrichment он был 0
(участников в БД не было), после — должен расти. Если он снова 0, значит
нормализация не прошла или ingestion не отработал.

Примеры::

    python scripts/build_prior_form_dataset.py                 # отчёт
    python scripts/build_prior_form_dataset.py --mode observed_mode_only_study
"""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Sequence

from d2intel.db import SessionLocal
from d2intel.features.prior_form import (
    EVALUATION_MODES,
    EVENT_ASOF,
    PriorFormBuilder,
)

# Значимые признаки (не счётчики и не флаги): покрытие NaN по ним — главный
# сигнал качества датасета. Имена — из `_put_team_features`/`_put_player_features`.
PLAYER_VALUE_COLS = (
    "player_a_wr",
    "player_a_kda",
    "player_a_gpm",
    "player_a_xpm",
    "player_b_wr",
    "player_b_kda",
    "player_b_gpm",
    "player_b_xpm",
)
TEAM_VALUE_COLS = (
    "team_a_wr_lifetime",
    "team_a_wr_last_long",
    "team_a_n_eff",
    "team_b_wr_lifetime",
    "team_b_wr_last_long",
    "team_b_n_eff",
)
LAG_COLS = ("team_a_days_since_last", "team_b_days_since_last")


def dataset_report(
    df: object, meta: object
) -> dict[str, object]:
    """Числовая сводка по датафрейму + метаданные сборки."""
    import pandas as pd

    assert isinstance(df, pd.DataFrame)
    n = len(df)
    report: dict[str, object] = {
        "meta": {
            "feature_schema_version": meta.feature_schema_version,
            "lag_policy_version": meta.lag_policy_version,
            "evaluation_mode": meta.evaluation_mode,
            "target_phase": meta.target_phase,
            "params": {
                "half_life_days": meta.params.half_life_days,
                "alpha": meta.params.alpha,
                "min_eff_games": meta.params.min_eff_games,
                "last_n_long": meta.params.last_n_long,
                "last_n_short": meta.params.last_n_short,
            },
            "n_examples": meta.n_examples,
            "n_train_eligible": meta.n_train_eligible,
            "n_excluded": meta.n_excluded,
            "team_a_avail": meta.team_a_avail,
            "team_b_avail": meta.team_b_avail,
            "player_a_avail": meta.player_a_avail,
            "player_b_avail": meta.player_b_avail,
            "target_patch_known": meta.target_patch_known,
        },
        "label_balance": {
            "y_mean": round(float(df["y"].mean()), 4) if n else None,
        },
        "coverage_pct": {},
    }

    def pct(col: str) -> float | None:
        if n == 0 or col not in df.columns:
            return None
        return round(100.0 * float(df[col].notna().mean()), 2)

    for col in TEAM_VALUE_COLS + PLAYER_VALUE_COLS:
        value = pct(col)
        if value is not None:
            report["coverage_pct"][col] = value

    # days_since_last — проверка result_lag: минимум не должен быть меньше
    # лага результата (иначе в историях было бы самоё свежее состояние цели).
    lag_mins: dict[str, float] = {}
    for col in LAG_COLS:
        if n and col in df.columns:
            lag_mins[f"{col}_min_hours"] = round(
                float(df[col].min(skipna=True)) * 24, 2
            )
    if lag_mins:
        report["sanity"] = lag_mins
    return report


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Сборка prior-form датасета на реальных данных (read-only)."
    )
    parser.add_argument(
        "--mode",
        choices=sorted(EVALUATION_MODES),
        default=EVENT_ASOF,
        help=f"Режим допустимости истории (по умолчанию {EVENT_ASOF}).",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    # Винтовая консоль может быть cp1251: отчёт и вердикт печатаются в UTF-8.
    if sys.stdout.encoding is None or sys.stdout.encoding.lower() != "utf-8":
        sys.stdout.reconfigure(encoding="utf-8")
    session = SessionLocal()
    try:
        builder = PriorFormBuilder(session, evaluation_mode=args.mode)
        df, meta = builder.build()
    finally:
        session.close()

    report = dataset_report(df, meta)
    print(json.dumps(report, ensure_ascii=False, indent=2, default=str))

    # Явный вердикт по главному сигналу: появились ли player-признаки.
    player_cov = report["coverage_pct"]
    player_signal = [
        player_cov[col]
        for col in PLAYER_VALUE_COLS
        if col in player_cov and player_cov[col] is not None
    ]
    if player_signal and all(v == 0 for v in player_signal):
        print(
            "\nVERDICT: player-признаки полностью замаскированы — "
            "game_participant/player_performance пусты. Проверить "
            "scripts/ingest_match_details_once.py и scripts/normalize_once.py.",
            flush=True,
        )
        return 3
    if player_signal and any(v > 0 for v in player_signal):
        print(
            "\nVERDICT: player-признаки доступны (покрытие "
            f"{min(player_signal):.2f}..{max(player_signal):.2f}%).",
            flush=True,
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
