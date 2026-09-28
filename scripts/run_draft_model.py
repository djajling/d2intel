#!/usr/bin/env python
"""ML-003 (v5) — драфт-информированная модель по протоколу ADR-007.

Отвечает на один вопрос: добавляет ли драфт точности к prior-form сигналу.
Ответ — сравнение двух моделей на одном и том же frozen test:

* M0 (baseline) — форма команд + сторона;
* M1 (draft)    — то же самое + композиционный дифференциал по пикам.

Протокол зафиксирован заранее в `docs/ml/ML003_draft_manifest.json`
(манифест закоммичен ДО обучения — требование ADR-007). Скрипт ничего не
подгоняет: гиперпараметры берутся из манифеста, тест трогается один раз в
конце, расхождение когорты с манифестом — отказ (код 2), а не «пересобрать
под данные».

Железное правило проекта: пары «драфт → исход» — обучающие данные.
Ретроспективная метрика здесь НЕ является оценкой живого прогноза.

Пример:

    python scripts/run_draft_model.py

Коды возврата: 0 отчёт записан, 2 когорта не совпала с манифестом,
3 манифест не найден/некорректен, 4 данных для сплита мало, 64 bad args.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from sklearn.linear_model import LogisticRegression
from sklearn.metrics import accuracy_score, log_loss
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.db import SessionLocal

DEFAULT_MANIFEST = Path("docs/ml/ML003_draft_manifest.json")

NEUTRAL = 0.5
MIN_TEAM_GAMES = 3
SAME_PATCH_MIN_OBS = 3

BASELINE_COLUMNS = ("d_team_wr_asof", "d_side")
DRAFT_COLUMNS = ("d_team_wr_asof", "d_side", "d_comp_wr")

COHORT_SQL = """
    SELECT g.id AS game_id,
           g.event_time AS event_time,
           g.patch_id AS patch_id,
           g.series_id AS series_id,
           g.winner_team_id AS winner_team_id,
           ga.team_id AS slot0_team_id,
           gb.team_id AS slot1_team_id,
           ga.side AS slot0_side,
           gb.side AS slot1_side
    FROM game AS g
    JOIN game_team AS ga ON ga.game_id = g.id AND ga.slot = 0
    JOIN game_team AS gb ON gb.game_id = g.id AND gb.slot = 1
    WHERE g.winner_team_id IS NOT NULL
      AND g.event_time IS NOT NULL
      AND g.series_id IS NOT NULL
      AND g.id IN (SELECT DISTINCT game_id FROM picks_bans)
    ORDER BY g.event_time
"""

DRAFT_SQL = """
    SELECT pb.game_id, pb.hero_id, pb.is_pick, pb.team, pb.ord
    FROM picks_bans AS pb
    ORDER BY pb.game_id, pb.ord
"""

#: История героев для as-of winrate. Отбор по event_time < cohort_start,
#: потому что внутри когорты каждый пример фильтрует по своему cutoff.
HERO_HISTORY_SQL = """
    SELECT g.event_time AS event_time,
           g.patch_id AS patch_id,
           gp.hero_id AS hero_id,
           (g.winner_team_id = gp.team_id) AS won
    FROM game AS g
    JOIN game_participant AS gp ON gp.game_id = g.id
    WHERE gp.hero_id IS NOT NULL
      AND g.winner_team_id IS NOT NULL
      AND g.event_time IS NOT NULL
      AND g.event_time < :cohort_start
"""

TEAM_HISTORY_SQL = """
    SELECT g.event_time AS event_time,
           gt.team_id AS team_id,
           (g.winner_team_id = gt.team_id) AS won
    FROM game AS g
    JOIN game_team AS gt ON gt.game_id = g.id
    WHERE g.winner_team_id IS NOT NULL
      AND g.event_time IS NOT NULL
      AND g.event_time < :cohort_start
"""


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="ML-003: драфт против baseline по ADR-007.")
    parser.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    parser.add_argument("--bootstrap", type=int, default=2000, help="Реплик grouped bootstrap.")
    return parser.parse_args(argv)


# --- чистые функции (тестируются без БД) ---------------------------------


def hero_winrate(
    same_patch: list[bool],
    any_patch: list[bool],
    *,
    patch_min_obs: int = SAME_PATCH_MIN_OBS,
) -> float:
    """As-of winrate героя: сначала тот же патч, иначе вся история до T.

    Списки — результаты игр (True = победа), уже отфильтрованные по
    `event_time < T`. Нет данных вообще → нейтральный 0.5, а не ноль:
    отсутствие истории не равнозначно проигрышу.
    """
    if len(same_patch) >= patch_min_obs and same_patch:
        return sum(same_patch) / len(same_patch)
    if any_patch:
        return sum(any_patch) / len(any_patch)
    return NEUTRAL


def team_winrate(games: list[bool], *, min_games: int = MIN_TEAM_GAMES) -> float:
    """WR команды; меньше min_games игр → 0.5 (нет информации)."""
    if len(games) < min_games or not games:
        return NEUTRAL
    return sum(games) / len(games)


def mean_or_neutral(values: list[float]) -> float:
    """Среднее по имеющимся значениям; пусто → 0.5."""
    if not values:
        return NEUTRAL
    return sum(values) / len(values)


def split_by_time(
    rows: list[dict[str, Any]], test_size: int
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Последние по event_time test_size игр — frozen test, остальное — train."""
    ordered = sorted(rows, key=lambda row: row["event_time"])
    if len(ordered) <= test_size:
        raise ValueError(
            f"когорта ({len(ordered)}) не больше test_size ({test_size}) — сплит невозможен"
        )
    return ordered[:-test_size], ordered[-test_size:]


def majority_accuracy(labels: list[int]) -> float:
    """Точность константного прогноза — обязательный ориентир ADR-007 п.2."""
    if not labels:
        return 0.0
    ones = sum(labels)
    return max(ones, len(labels) - ones) / len(labels)


def verdict(*, accuracy: float, threshold: float, ci: tuple[float, float]) -> str:
    """Вердикт строго по правилу ADR-007 п.4 — без подгонки порога."""
    if accuracy >= threshold:
        return f"порог достигнут: accuracy {accuracy:.3f} >= {threshold:.2f}"
    return (
        f"порог не достигнут: accuracy {accuracy:.3f} "
        f"[{ci[0]:.3f}, {ci[1]:.3f}] при пороге {threshold:.2f}"
    )


def grouped_bootstrap_ci(
    pairs: list[tuple[str, int, int]],
    *,
    replicates: int,
    seed: int,
) -> tuple[float, float]:
    """95% CI точности grouped bootstrap по сериям.

    `pairs` — (series_id, y_true, y_pred). Берём серии, а не отдельные карты:
    карты одной серии не независимы. Это грубая неопределённость, а не тест
    (ADR-007 п.5).
    """
    by_series: dict[str, list[tuple[int, int]]] = defaultdict(list)
    for series_id, y_true, y_pred in pairs:
        by_series[series_id].append((y_true, y_pred))
    series_ids = sorted(by_series)
    if not series_ids:
        return (0.0, 0.0)
    rng = random.Random(seed)
    values: list[float] = []
    for _ in range(max(replicates, 1)):
        picked = [rng.choice(series_ids) for _ in series_ids]
        total = correct = 0
        for series_id in picked:
            for y_true, y_pred in by_series[series_id]:
                total += 1
                correct += int(y_true == y_pred)
        values.append(correct / total if total else 0.0)
    values.sort()
    low = values[int(0.025 * (len(values) - 1))]
    high = values[int(0.975 * (len(values) - 1))]
    return (low, high)


# --- сбор датасета --------------------------------------------------------


def _hero_index(db: Session, cohort_start: datetime) -> dict[int, list[tuple[datetime, Any, bool]]]:
    index: dict[int, list[tuple[datetime, Any, bool]]] = defaultdict(list)
    for row in db.execute(text(HERO_HISTORY_SQL), {"cohort_start": cohort_start}).all():
        index[int(row.hero_id)].append(
            (row.event_time, row.patch_id, bool(row.won))
        )
    for rows in index.values():
        rows.sort(key=lambda item: item[0])
    return index


def _team_index(db: Session, cohort_start: datetime) -> dict[str, list[tuple[datetime, bool]]]:
    index: dict[str, list[tuple[datetime, bool]]] = defaultdict(list)
    for row in db.execute(text(TEAM_HISTORY_SQL), {"cohort_start": cohort_start}).all():
        index[str(row.team_id)].append((row.event_time, bool(row.won)))
    for rows in index.values():
        rows.sort(key=lambda item: item[0])
    return index


def _hero_wr(
    rows: list[tuple[datetime, Any, bool]], cutoff: datetime, patch_id: Any
) -> float:
    """Сначала тот же патч (наблюдений >= 3), иначе вся история до T."""
    same = [won for (t, p, won) in rows if t < cutoff and p == patch_id]
    if len(same) >= SAME_PATCH_MIN_OBS:
        return hero_winrate(same, same)
    any_patch = [won for (t, _, won) in rows if t < cutoff]
    return hero_winrate([], any_patch)


def _team_wr(rows: list[tuple[datetime, bool]], cutoff: datetime) -> float:
    return team_winrate([won for (t, won) in rows if t < cutoff])


def build_dataset(db: Session) -> list[dict[str, Any]]:
    """Одна строка на игру когорты: признаки считаются только из данных до T."""
    cohort = [dict(row._mapping) for row in db.execute(text(COHORT_SQL)).all()]
    if not cohort:
        return []
    cohort_start = cohort[0]["event_time"]

    drafts: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in db.execute(text(DRAFT_SQL)).all():
        item = dict(row._mapping)
        drafts[str(item["game_id"])].append(item)

    hero_index = _hero_index(db, cohort_start)
    team_index = _team_index(db, cohort_start)

    dataset: list[dict[str, Any]] = []
    for game in cohort:
        game_id = str(game["game_id"])
        team0, team1 = str(game["slot0_team_id"]), str(game["slot1_team_id"])
        # Канонические координаты когорты — как в ML-002.
        team_a, team_b = sorted((team0, team1))
        side_a = game["slot0_side"] if team_a == team0 else game["slot1_side"]

        cutoff = game["event_time"]
        patch_id = game["patch_id"]

        d_team_wr = differential(
            _team_wr(team_index.get(team_a, []), cutoff),
            _team_wr(team_index.get(team_b, []), cutoff),
        )
        d_side = 1.0 if side_a == "radiant" else -1.0

        # Пики: picks_bans.team в координатах radiant(0)/dire(1) —
        # привязываем к команде через game_team.side, а не к слоту.
        a_is_radiant = side_a == "radiant"
        picks_a: list[float] = []
        picks_b: list[float] = []
        for row in drafts.get(game_id, []):
            if not row["is_pick"]:
                continue
            belongs_to_a = (row["team"] == 0) == a_is_radiant
            wr = _hero_wr(hero_index.get(int(row["hero_id"]), []), cutoff, patch_id)
            (picks_a if belongs_to_a else picks_b).append(wr)

        d_comp = differential(mean_or_neutral(picks_a), mean_or_neutral(picks_b))

        dataset.append(
            {
                "game_id": game_id,
                "series_id": str(game["series_id"]),
                "event_time": cutoff,
                "y": 1 if str(game["winner_team_id"]) == team_a else 0,
                "n_moves": len(drafts.get(game_id, [])),
                "n_picks_a": len(picks_a),
                "n_picks_b": len(picks_b),
                "d_team_wr_asof": d_team_wr,
                "d_side": d_side,
                "d_comp_wr": d_comp,
            }
        )
    return dataset


def differential(a: float, b: float) -> float:
    return a - b


# --- обучение и отчёт -----------------------------------------------------


def _fit_predict(
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    columns: tuple[str, ...],
    params: dict[str, Any],
) -> tuple[list[int], list[float]]:
    x_train = [[row[c] for c in columns] for row in train]
    x_test = [[row[c] for c in columns] for row in test]
    y_train = [row["y"] for row in train]
    model = Pipeline(
        [
            ("scaler", StandardScaler()),
            (
                "lr",
                LogisticRegression(
                    C=float(params.get("C", 1.0)),
                    penalty=str(params.get("penalty", "l2")),
                    class_weight=params.get("class_weight"),
                    max_iter=int(params.get("max_iter", 1000)),
                    random_state=int(params.get("random_state", 17)),
                ),
            ),
        ]
    )
    model.fit(x_train, y_train)
    proba = model.predict_proba(x_test)[:, 1]
    pred = [1 if p >= 0.5 else 0 for p in proba]
    return pred, proba


def _evaluate(
    name: str,
    columns: tuple[str, ...],
    train: list[dict[str, Any]],
    test: list[dict[str, Any]],
    params: dict[str, Any],
    *,
    replicates: int,
    seed: int,
) -> dict[str, Any]:
    y_true = [row["y"] for row in test]
    pred, proba = _fit_predict(train, test, columns, params)
    accuracy = accuracy_score(y_true, pred)
    loss = log_loss(y_true, proba, labels=[0, 1])
    ci = grouped_bootstrap_ci(
        [(row["series_id"], row["y"], p) for row, p in zip(test, pred, strict=True)],
        replicates=replicates,
        seed=seed,
    )
    return {
        "model": name,
        "columns": list(columns),
        "accuracy": round(float(accuracy), 4),
        "log_loss": round(float(loss), 4),
        "bootstrap_ci95": [round(ci[0], 4), round(ci[1], 4)],
        "predictions": pred,
        "probabilities": [round(float(p), 4) for p in proba],
    }


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    manifest_path = Path(args.manifest)
    if not manifest_path.exists():
        print(f"manifest not found: {manifest_path}", file=sys.stderr)
        return 3
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

    threshold = float(manifest["protocol"]["threshold"])
    split_spec = manifest["split"]
    test_size = int(str(split_spec["expected_test"]))
    params = dict(manifest["algorithm"]["params"])

    db = SessionLocal()
    try:
        dataset = build_dataset(db)
    finally:
        db.close()

    # Когорта обязана совпасть с зафиксированной в манифесте: если данные
    # пополнились после фиксации — это уже ДРУГОЙ прогон и ему нужен новый
    # манифест, а не тихая пересборка (ADR-007, запрет подгонки).
    cohort_spec = manifest["cohort"]
    expected_games = int(cohort_spec["expected_games"])
    expected_moves = int(cohort_spec["expected_picks_bans_rows"])
    total_moves = sum(row["n_moves"] for row in dataset)
    if len(dataset) != expected_games or total_moves != expected_moves:
        print(
            "когорта не совпала с манифестом — прогон остановлен:\n"
            f"  games: ожидалось {expected_games}, есть {len(dataset)}\n"
            f"  ходов picks_bans: ожидалось {expected_moves}, есть {total_moves}\n"
            "Нужен новый манифест, зафиксированный до обучения.",
            file=sys.stderr,
        )
        return 2

    try:
        train, test = split_by_time(dataset, test_size)
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 4

    if len(train) != int(split_spec["expected_train"]):
        print(
            f"train {len(train)} != зафиксированному {split_spec['expected_train']}",
            file=sys.stderr,
        )
        return 2

    seed = int(params.get("random_state", 17))
    results = [
        _evaluate(
            "M0_baseline",
            BASELINE_COLUMNS,
            train,
            test,
            params,
            replicates=args.bootstrap,
            seed=seed,
        ),
        _evaluate(
            "M1_draft",
            DRAFT_COLUMNS,
            train,
            test,
            params,
            replicates=args.bootstrap,
            seed=seed,
        ),
    ]
    y_true = [row["y"] for row in test]
    baseline_majority = majority_accuracy(y_true)
    m0, m1 = results

    report = {
        "task_id": manifest["task_id"],
        "model_version": manifest["model_version"],
        "manifest": str(manifest_path),
        "manifest_fixed_at": manifest["fixed_at"],
        "ran_at": datetime.now().astimezone().isoformat(),
        "library_versions": _versions(),
        "cohort": {
            "games": len(dataset),
            "train": len(train),
            "test": len(test),
            "series_in_test": len({row["series_id"] for row in test}),
            "label_balance_cohort": round(sum(r["y"] for r in dataset) / len(dataset), 4),
        },
        "split": split_spec,
        "majority_class_accuracy_test": round(baseline_majority, 4),
        "models": results,
        "threshold": threshold,
        "verdict": verdict(
            accuracy=m1["accuracy"], threshold=threshold, ci=tuple(m1["bootstrap_ci95"])
        ),
        "draft_delta": {
            "accuracy": round(m1["accuracy"] - m0["accuracy"], 4),
            "log_loss": round(m1["log_loss"] - m0["log_loss"], 4),
            "interpretation": (
                "драфт помог" if m1["accuracy"] > m0["accuracy"] else
                "драфт не помог" if m1["accuracy"] < m0["accuracy"] else
                "различий нет"
            ),
        },
        "honesty": [
            "Ретроспективная метрика обучающей модели, а НЕ оценка живого прогноза.",
            "Ретроспективный cutoff = event_time матча (ADR-007 п.6).",
            f"n test = {len(test)}: у границы «30», bootstrap-интервал — грубая неопределённость, не тест.",
            "Гиперпараметры и сплит зафиксированы в манифесте до обучения; тюнинга не было.",
        ],
    }
    # per-example данные в отчёт не тащим — они разрастаются и не нужны для вердикта
    for item in results:
        item.pop("predictions", None)
        item.pop("probabilities", None)

    out_path = Path(
        manifest.get("output_prefix", "docs/ml/ML003_run_")
        + datetime.now().strftime("%Y-%m-%d")
        + ".json"
    )
    out_path.parent.mkdir(parents=True, exist_ok=True)
    if out_path.exists():
        out_path = out_path.with_name(out_path.stem + "_v2.json")
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"когорта: {len(dataset)} игр (train {len(train)} / test {len(test)})")
    print(f"majority baseline на test: {baseline_majority:.4f}")
    for item in results:
        print(
            f"{item['model']}: accuracy {item['accuracy']:.4f}  "
            f"log_loss {item['log_loss']:.4f}  CI {item['bootstrap_ci95']}"
        )
    print(f"эффект драфта: {report['draft_delta']}")
    print(f"ВЕРДИКТ: {report['verdict']}")
    print(f"отчёт: {out_path}")
    return 0


def _versions() -> dict[str, str]:
    import sklearn

    return {"sklearn": sklearn.__version__}


if __name__ == "__main__":
    raise SystemExit(main())
