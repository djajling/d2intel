"""FEAT-001 — минимальный prior-form датасет as-of для map1.

Для каждой серии с доказанным `map_number = 1` строится **один** обучающий
пример с признаками «форма/приоры», доступными строго до cutoff, явными
масками доступности и режимом `event_asof` / `observed_mode_only_study`.

Границы задачи (карточка `FEAT-001` в `BACKLOG.md`):

* target — исход **первой карты серии**, а не серии; Team A/B — canonical
  identity (слот 0 / слот 1 в `game_team`);
* каждый признак считается на истории **строго до cutoff**; финальная
  статистика и фактический состав **целевой** карты не читаются — только
  `game_participant` и `player_performance` **прошлых** карт;
* маски доступности явные: неизвестное — это `NaN` + `avail = False`, а не `0`;
* режим `observed_mode_only_study` не попадает в обучение/оценку MVP
  (`train_eligible = False`, `exclusion_reason` заполнен);
* трансформации, которые чему-то учатся (пока только `prior_mean` — базовый
  winrate μ), фитятся **только на train** через `PriorFormParams.fit` — сам
  построитель ничего не вычисляет по всему датасету (`ML.md` §4).

Временная семантика — `docs/PRD_TEMPORAL.md`:

* `event_asof` (соответствует `retrospective_reconstructed`): допустимость
  истории определяется по времени события с учётом версии политики задержки —
  `assumed_available_at = event_time + result_lag` (`LAG_POLICY_VERSION`).
  Это реконструкция: реальные `observed_at` — «сейчас», поэтому пример честно
  маркируется режимом `event_asof`, а не выдаётся за point-in-time replay;
* `observed_mode_only_study` (соответствует `prospective_observed`):
  допустимость определяется фактическим `observed_at <= cutoff`. В
  реконструированном датасете таких примеров нет — режим существует, чтобы их
  не смешивать с обучающей когортой (`PRD_TEMPORAL.md` §6).

Формулы — `FEATURES.md` §1–2: вес `w_i = exp(−ln2 · age_i / H) · ρ(patch_i)`,
сглаженный winrate `(Σw_i y_i + αμ) / (Σw_i + α)`, эффективный объём
`n_eff = (Σw_i)² / Σw_i²`.
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

#: Версия схемы признаков. Меняется при любом изменении состава/формул.
FEATURE_SCHEMA_VERSION = "prior-form.v1"

#: Версия политики задержки реконструкции (`PRD_TEMPORAL.md` §3.2).
LAG_POLICY_VERSION = "lag-policy.v1"

#: Режимы допустимости истории (карточка FEAT-001, OUTPUT).
EVENT_ASOF = "event_asof"
OBSERVED_MODE_ONLY_STUDY = "observed_mode_only_study"
EVALUATION_MODES: tuple[str, ...] = (EVENT_ASOF, OBSERVED_MODE_ONLY_STUDY)

#: Фаза прогноза: первая карта серии, до драфта (`ML.md` §1).
TARGET_PHASE = "map1_pre_draft"

#: Причина исключения примера из обучающей/оценочной когорты.
REASON_OBSERVED_STUDY = "observed_mode_only_study"

_SECONDS_PER_DAY = 86400.0


# --------------------------------------------------------------------------- #
# Параметры (fit только на train)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PriorFormParams:
    """Параметры признаков. Всё, чему можно обучиться, фитится на train.

    `FEATURES.md` §1: H (half-life), α (shrinkage), μ (prior), ρ (patch policy)
    фиксируются на training/tuning данных. Здесь обучаемое — только `prior_mean`
    (базовый winrate), остальное — задокументированные значения по умолчанию,
    которые tuning (`ML-001`) сможет переопределить через `dataclasses.replace`.
    """

    #: Half-life recency-веса в днях (H).
    half_life_days: float = 120.0
    #: Сила shrinkage к `prior_mean` (α).
    alpha: float = 12.0
    #: Базовый winrate μ — **fit на train** (см. `fit`).
    prior_mean: float = 0.5
    #: ρ для prior-игр того же патча, что и target.
    patch_same_weight: float = 1.0
    #: ρ для prior-игр другого/неизвестного патча.
    patch_other_weight: float = 0.6
    #: Порог n_eff, ниже которого команда помечается `low_coverage`.
    min_eff_games: float = 5.0
    #: Окно «последние N карт» (длинное).
    last_n_long: int = 20
    #: Окно «последние N карт» (короткое).
    last_n_short: int = 10
    #: Реконструированная задержка доступности результата карты от её старта.
    result_lag: timedelta = field(default_factory=lambda: timedelta(hours=4))

    @classmethod
    def fit(
        cls,
        train_labels: Sequence[float],
        **overrides: float | timedelta | int,
    ) -> PriorFormParams:
        """Параметры с μ, вычисленным **только по train-меткам**.

        Остальные параметры — значения по умолчанию; их tuning — задача
        `ML-001`. Любой параметр можно перебить через `overrides`.
        """
        labels = list(train_labels)
        prior_mean = sum(labels) / len(labels) if labels else 0.5
        merged: dict[str, float | timedelta | int] = {"prior_mean": prior_mean}
        merged.update(overrides)
        return cls(**merged)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Входные записи (значения из canonical-слоя, без ссылок на ORM)
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class PriorGame:
    """Завершённая карта в прошлом с командной точки зрения."""

    game_id: UUID
    team_id: UUID
    event_time: datetime
    won: bool
    patch_id: UUID | None
    observed_at: datetime


@dataclass(frozen=True)
class PriorParticipant:
    """Участник прошлой карты с его финальной статистикой (если есть)."""

    game_id: UUID
    team_id: UUID
    player_id: UUID
    event_time: datetime
    won: bool
    patch_id: UUID | None
    kills: int | None
    deaths: int | None
    assists: int | None
    gold_per_min: int | None
    xp_per_min: int | None
    observed_at: datetime


@dataclass(frozen=True)
class TargetRow:
    """Целевой пример: доказанный map1 серии с известным исходом."""

    series_id: UUID
    game_id: UUID
    cutoff_at: datetime
    team_a_id: UUID
    team_b_id: UUID
    patch_id: UUID | None
    target_observed_at: datetime
    y: bool


# --------------------------------------------------------------------------- #
# Чистая часть: допустимость, веса, агрегаты
# --------------------------------------------------------------------------- #


def assumed_available_at(event_time: datetime, params: PriorFormParams) -> datetime:
    """Когда результат карты считается доступным по политике реконструкции.

    Применяется только в режиме `event_asof` (`LAG_POLICY_VERSION`): карта,
    начавшаяся непосредственно перед cutoff, ещё не доиграна, и её результат не
    мог быть известен. В режиме `observed_mode_only_study` используется
    фактический `observed_at`.
    """
    return event_time + params.result_lag


def _is_eligible(
    record: PriorGame | PriorParticipant,
    *,
    cutoff: datetime,
    evaluation_mode: str,
    params: PriorFormParams,
    exclude_game_id: UUID | None,
) -> bool:
    """Была ли запись известна до cutoff.

    Два независимых условия:
    1. событие произошло строго до cutoff (`event_time < cutoff`);
    2. информация о нём была доступна до cutoff — `assumed_available_at` для
       режима реконструкции либо фактическое `observed_at` для observed-режима.

    Целевую карту исключаем явно (страховка при `result_lag = 0`): её
    собственный исход не имеет права попасть в pre-match признаки.
    """
    if exclude_game_id is not None and record.game_id == exclude_game_id:
        return False
    if record.event_time >= cutoff:
        return False
    available = (
        record.observed_at
        if evaluation_mode == OBSERVED_MODE_ONLY_STUDY
        else assumed_available_at(record.event_time, params)
    )
    return available <= cutoff


def recency_weight(age_days: float, params: PriorFormParams) -> float:
    """exp(−ln2 · age / H): недавние игры весят больше."""
    if age_days < 0.0:
        return 0.0
    half_life = params.half_life_days
    if half_life <= 0.0:
        return 1.0
    return math.exp(-math.log(2.0) * age_days / half_life)


def patch_weight(prior_patch: UUID | None, target_patch: UUID | None, params: PriorFormParams) -> float:
    """ρ(patch_i, patch_target): текущий патч — полный вес, прочие — меньше.

    Неизвестный патч целевой игры не считается «старым» автоматически:
    используется `patch_other_weight`, а факт неизвестности виден в маске
    `target_patch_unknown`.
    """
    if target_patch is None or prior_patch is None:
        return params.patch_other_weight
    if prior_patch == target_patch:
        return params.patch_same_weight
    return params.patch_other_weight


@dataclass(frozen=True)
class _WeightedOutcome:
    """Суммы по взвешенной истории исходов."""

    w_sum: float = 0.0
    wy_sum: float = 0.0
    w2_sum: float = 0.0
    n: int = 0


def _accumulate(outcomes: Sequence[tuple[float, bool]]) -> _WeightedOutcome:
    """Σw, Σw·y, Σw², n по списку `(weight, won)`."""
    w_sum = wy_sum = w2_sum = 0.0
    n = 0
    for weight, won in outcomes:
        w_sum += weight
        wy_sum += weight * (1.0 if won else 0.0)
        w2_sum += weight * weight
        n += 1
    return _WeightedOutcome(w_sum=w_sum, wy_sum=wy_sum, w2_sum=w2_sum, n=n)


def n_eff(w_sum: float, w2_sum: float) -> float:
    """Эффективный объём взвешенной выборки: (Σw)² / Σw² (`FEATURES.md` §1)."""
    if w2_sum <= 0.0:
        return 0.0
    return (w_sum * w_sum) / w2_sum


def smoothed_winrate(w_sum: float, wy_sum: float, params: PriorFormParams) -> float:
    """Сглаженный winrate: (Σw·y + αμ) / (Σw + α).

    При отсутствии истории возвращает μ — это честный prior, а не «0 побед».
    Маска `avail` при этом `False`, поэтому значение нельзя прочитать как
    наблюдение.
    """
    denominator = w_sum + params.alpha
    if denominator <= 0.0:
        return params.prior_mean
    return (wy_sum + params.alpha * params.prior_mean) / denominator


@dataclass(frozen=True)
class TeamForm:
    """Team prior-form as-of cutoff. `None` — данных нет."""

    n_games: int
    n_eff: float
    wr_lifetime: float | None
    n_last_long: int
    wr_last_long: float | None
    n_last_short: int
    wr_last_short: float | None
    days_since_last: float | None
    same_patch_n: int
    avail: bool
    low_coverage: bool


def team_form(
    games: Sequence[PriorGame],
    *,
    team_id: UUID,
    cutoff: datetime,
    target_patch: UUID | None,
    params: PriorFormParams,
    evaluation_mode: str = EVENT_ASOF,
    exclude_game_id: UUID | None = None,
) -> TeamForm:
    """Team prior-form: взвешенный winrate по всем и последним N картам до cutoff.

    Используются **все** завершённые карты команды до cutoff, а не только map1
    (`ML.md` §1: «Истории всех прошлых карт разрешены для Team/Player form при
    соблюдении cutoff»).
    """
    team_games = [
        game
        for game in games
        if game.team_id == team_id
        and _is_eligible(
            game,
            cutoff=cutoff,
            evaluation_mode=evaluation_mode,
            params=params,
            exclude_game_id=exclude_game_id,
        )
    ]
    # От новых к старым — нужно для окон last-N.
    team_games.sort(key=lambda game: game.event_time, reverse=True)

    weighted = [
        (
            recency_weight((cutoff - game.event_time).total_seconds() / _SECONDS_PER_DAY, params)
            * patch_weight(game.patch_id, target_patch, params),
            game.won,
        )
        for game in team_games
    ]

    total = _accumulate(weighted)
    total_long = _accumulate(weighted[: params.last_n_long])
    total_short = _accumulate(weighted[: params.last_n_short])

    days_since_last: float | None = None
    if team_games:
        days_since_last = (cutoff - team_games[0].event_time).total_seconds() / _SECONDS_PER_DAY

    same_patch_n = 0
    if target_patch is not None:
        same_patch_n = sum(1 for game in team_games if game.patch_id == target_patch)

    games_n_eff = n_eff(total.w_sum, total.w2_sum)
    avail = total.n > 0
    return TeamForm(
        n_games=total.n,
        n_eff=games_n_eff if avail else 0.0,
        wr_lifetime=smoothed_winrate(total.w_sum, total.wy_sum, params) if avail else None,
        n_last_long=total_long.n,
        wr_last_long=smoothed_winrate(total_long.w_sum, total_long.wy_sum, params)
        if total_long.n > 0
        else None,
        n_last_short=total_short.n,
        wr_last_short=smoothed_winrate(total_short.w_sum, total_short.wy_sum, params)
        if total_short.n > 0
        else None,
        days_since_last=days_since_last,
        same_patch_n=same_patch_n,
        avail=avail,
        low_coverage=avail and games_n_eff < params.min_eff_games,
    )


@dataclass(frozen=True)
class PlayerForm:
    """Player prior-form команды as-of cutoff (минимальный набор FEAT-001).

    Агрегируется по **prior-known roster**: игрокам, которые играли за команду
    в картах до cutoff (inference из прошлых карт, а не confirmed roster —
    `PRD_TEMPORAL.md` §3.2). Индивидуальная статистика считается по всем прошлым
    картам игрока (включая другие команды), как требует `FEATURES.md` §2.
    """

    n_known_players: int
    n_games: int
    wr: float | None
    kda: float | None
    gpm: float | None
    xpm: float | None
    avail: bool


def _kda(kills: int | None, deaths: int | None, assists: int | None) -> float | None:
    """(K + A) / max(1, D). `None`, если нет хотя бы одной части.

    `FEATURES.md` §2: ratio при 0 deaths условен — знаменатель `max(1, deaths)`,
    а рядом лежат отдельные маски/n.
    """
    if kills is None or deaths is None or assists is None:
        return None
    return (kills + assists) / max(1, deaths)


def _mean(values: Sequence[float]) -> float | None:
    """Среднее по наличным значениям или `None` (не ноль)."""
    if not values:
        return None
    return sum(values) / len(values)


def player_form(
    participants: Sequence[PriorParticipant],
    *,
    team_id: UUID,
    cutoff: datetime,
    params: PriorFormParams,
    evaluation_mode: str = EVENT_ASOF,
    exclude_game_id: UUID | None = None,
) -> PlayerForm:
    """Минимальный player prior-form команды as-of cutoff.

    prior-known roster = игроки, замеченные в составе команды в прошлых картах.
    Если таких нет — все признаки `None`, `avail = False` (availability-aware
    fallback, а не нули). Фактический состав целевой карты не читается
    (`ML.md` §5.3).
    """
    eligible = [
        participant
        for participant in participants
        if _is_eligible(
            participant,
            cutoff=cutoff,
            evaluation_mode=evaluation_mode,
            params=params,
            exclude_game_id=exclude_game_id,
        )
    ]

    known_players: set[UUID] = {
        participant.player_id for participant in eligible if participant.team_id == team_id
    }
    if not known_players:
        return PlayerForm(
            n_known_players=0,
            n_games=0,
            wr=None,
            kda=None,
            gpm=None,
            xpm=None,
            avail=False,
        )

    by_player: dict[UUID, list[PriorParticipant]] = {}
    for participant in eligible:
        if participant.player_id in known_players:
            by_player.setdefault(participant.player_id, []).append(participant)

    wr_values: list[float] = []
    kda_values: list[float] = []
    gpm_values: list[float] = []
    xpm_values: list[float] = []
    n_games_total = 0

    for player_id in known_players:
        player_games = by_player[player_id]
        weighted = [
            (
                recency_weight(
                    (cutoff - participant.event_time).total_seconds() / _SECONDS_PER_DAY,
                    params,
                ),
                participant.won,
            )
            for participant in player_games
        ]
        total = _accumulate(weighted)
        n_games_total += total.n
        wr_values.append(smoothed_winrate(total.w_sum, total.wy_sum, params))

        # Описательная статистика — среднее по картам с известными значениями.
        kda_per_game = [
            value
            for value in (_kda(p.kills, p.deaths, p.assists) for p in player_games)
            if value is not None
        ]
        gpm_per_game = [p.gold_per_min for p in player_games if p.gold_per_min is not None]
        xpm_per_game = [p.xp_per_min for p in player_games if p.xp_per_min is not None]
        kda_value = _mean(kda_per_game)
        gpm_value = _mean(gpm_per_game)
        xpm_value = _mean(xpm_per_game)
        if kda_value is not None:
            kda_values.append(kda_value)
        if gpm_value is not None:
            gpm_values.append(gpm_value)
        if xpm_value is not None:
            xpm_values.append(xpm_value)

    return PlayerForm(
        n_known_players=len(known_players),
        n_games=n_games_total,
        wr=_mean(wr_values),
        kda=_mean(kda_values),
        gpm=_mean(gpm_values),
        xpm=_mean(xpm_values),
        avail=True,
    )


# --------------------------------------------------------------------------- #
# Извлечение из canonical-слоя (тонкий слой БД)
# --------------------------------------------------------------------------- #


_TARGETS_SQL = """
WITH ranked AS (
    SELECT
        g.id AS game_id,
        g.series_id AS series_id,
        g.event_time AS cutoff_at,
        g.winner_team_id AS winner_team_id,
        g.patch_id AS patch_id,
        g.observed_at AS target_observed_at,
        gta.team_id AS team_a_id,
        gtb.team_id AS team_b_id,
        ROW_NUMBER() OVER (
            PARTITION BY g.series_id
            ORDER BY g.attempt_number ASC, g.event_time ASC
        ) AS row_number
    FROM game AS g
    JOIN game_team AS gta ON gta.game_id = g.id AND gta.slot = 0
    JOIN game_team AS gtb ON gtb.game_id = g.id AND gtb.slot = 1
    WHERE g.map_number = 1
      AND g.status = 'completed'
      AND g.winner_team_id IS NOT NULL
      AND g.event_time IS NOT NULL
)
SELECT
    series_id, game_id, cutoff_at, winner_team_id, patch_id,
    target_observed_at, team_a_id, team_b_id
FROM ranked
WHERE row_number = 1
"""

_PRIOR_GAMES_SQL = """
SELECT
    g.id AS game_id,
    gt.team_id AS team_id,
    g.event_time AS event_time,
    g.winner_team_id AS winner_team_id,
    g.patch_id AS patch_id,
    g.observed_at AS observed_at
FROM game AS g
JOIN game_team AS gt ON gt.game_id = g.id
WHERE g.winner_team_id IS NOT NULL
  AND g.event_time IS NOT NULL
"""

_PARTICIPANTS_SQL = """
SELECT
    gp.game_id AS game_id,
    gp.team_id AS team_id,
    gp.player_id AS player_id,
    g.event_time AS event_time,
    g.winner_team_id AS winner_team_id,
    g.patch_id AS patch_id,
    pp.kills AS kills,
    pp.deaths AS deaths,
    pp.assists AS assists,
    pp.gold_per_min AS gold_per_min,
    pp.xp_per_min AS xp_per_min,
    g.observed_at AS observed_at
FROM game_participant AS gp
JOIN game AS g ON g.id = gp.game_id
LEFT JOIN player_performance AS pp ON pp.game_participant_id = gp.id
WHERE g.winner_team_id IS NOT NULL
  AND g.event_time IS NOT NULL
"""


def fetch_targets(session: Session) -> list[TargetRow]:
    """Целевые примеры: по одной доказанной map1 на серию.

    Серия могла переигрываться (`attempt_number` > 1) — берём самую раннюю
    попытку, отсюда и `ROW_NUMBER`. Гарантирует «один пример на серию».
    """
    rows = session.execute(text(_TARGETS_SQL))
    targets: list[TargetRow] = []
    for row in rows:
        winner: object = row.winner_team_id
        if winner != row.team_a_id and winner != row.team_b_id:
            # Победитель вне пары — данные противоречивы, пример не строим.
            continue
        targets.append(
            TargetRow(
                series_id=row.series_id,
                game_id=row.game_id,
                cutoff_at=row.cutoff_at,
                team_a_id=row.team_a_id,
                team_b_id=row.team_b_id,
                patch_id=row.patch_id,
                target_observed_at=row.target_observed_at,
                y=winner == row.team_a_id,
            )
        )
    return targets


def fetch_prior_games(session: Session) -> list[PriorGame]:
    """Вся завершённая история с командной точки зрения (bulk-извлечение).

    Фильтр по cutoff выполняется в памяти (`team_form`): один bulk-запрос
    вместо N+1. Используются **все** завершённые карты, а не только map1 —
    командная форма учитывается на любой прошлой карте (`ML.md` §1).
    """
    rows = session.execute(text(_PRIOR_GAMES_SQL))
    return [
        PriorGame(
            game_id=row.game_id,
            team_id=row.team_id,
            event_time=row.event_time,
            won=row.winner_team_id == row.team_id,
            patch_id=row.patch_id,
            observed_at=row.observed_at,
        )
        for row in rows
    ]


def fetch_participants(session: Session) -> list[PriorParticipant]:
    """Участники прошлых карт с финальной статистикой (bulk-извлечение).

    `player_performance` читается **только для прошлых карт** — финальная
    статистика целевой карты до матча недоступна (`PRD_TEMPORAL.md` §3.3);
    отсечение по cutoff и явное исключение целевой карты — в `player_form`.
    """
    rows = session.execute(text(_PARTICIPANTS_SQL))
    return [
        PriorParticipant(
            game_id=row.game_id,
            team_id=row.team_id,
            player_id=row.player_id,
            event_time=row.event_time,
            won=row.winner_team_id == row.team_id,
            patch_id=row.patch_id,
            kills=row.kills,
            deaths=row.deaths,
            assists=row.assists,
            gold_per_min=row.gold_per_min,
            xp_per_min=row.xp_per_min,
            observed_at=row.observed_at,
        )
        for row in rows
    ]


# --------------------------------------------------------------------------- #
# Сборка датасета
# --------------------------------------------------------------------------- #


@dataclass(frozen=True)
class DatasetMeta:
    """Метаданные сборки: версии, параметры, покрытие, режим.

    Покрытие считается по примерам, а не по строкам в БД — это отчёт о
    пригодности датасета, а не о сырых данных.
    """

    feature_schema_version: str
    lag_policy_version: str
    evaluation_mode: str
    target_phase: str
    params: PriorFormParams
    n_examples: int
    n_train_eligible: int
    n_excluded: int
    team_a_avail: int
    team_b_avail: int
    player_a_avail: int
    player_b_avail: int
    target_patch_known: int


class PriorFormBuilder:
    """Сборщик prior-form датасета: один пример на серию с доказанным map1.

    Построитель не вычисляет ничего по всему датасету: каждый пример строится
    только из своей истории до cutoff и переданных параметров. Любое обучение
    (μ) — снаружи, через `PriorFormParams.fit` на train-подмножестве.
    """

    def __init__(
        self,
        session: Session,
        params: PriorFormParams | None = None,
        *,
        evaluation_mode: str = EVENT_ASOF,
    ) -> None:
        if evaluation_mode not in EVALUATION_MODES:
            raise ValueError(f"unsupported evaluation_mode: {evaluation_mode!r}")
        self._session = session
        self._params = params if params is not None else PriorFormParams()
        self._evaluation_mode = evaluation_mode

    @property
    def params(self) -> PriorFormParams:
        """Параметры сборки (могут быть fit на train)."""
        return self._params

    @property
    def evaluation_mode(self) -> str:
        """Режим допустимости истории."""
        return self._evaluation_mode

    def build(self) -> tuple[pd.DataFrame, DatasetMeta]:
        """Собрать датасет и метаданные. Столбцы — см. `_row_to_dict`."""
        targets = fetch_targets(self._session)
        prior_games = fetch_prior_games(self._session)
        participants = fetch_participants(self._session)

        records: list[dict[str, object]] = []
        n_train_eligible = 0
        n_excluded = 0
        team_a_avail = 0
        team_b_avail = 0
        player_a_avail = 0
        player_b_avail = 0
        target_patch_known = 0

        for target in targets:
            form_a = team_form(
                prior_games,
                team_id=target.team_a_id,
                cutoff=target.cutoff_at,
                target_patch=target.patch_id,
                params=self._params,
                evaluation_mode=self._evaluation_mode,
                exclude_game_id=target.game_id,
            )
            form_b = team_form(
                prior_games,
                team_id=target.team_b_id,
                cutoff=target.cutoff_at,
                target_patch=target.patch_id,
                params=self._params,
                evaluation_mode=self._evaluation_mode,
                exclude_game_id=target.game_id,
            )
            players_a = player_form(
                participants,
                team_id=target.team_a_id,
                cutoff=target.cutoff_at,
                params=self._params,
                evaluation_mode=self._evaluation_mode,
                exclude_game_id=target.game_id,
            )
            players_b = player_form(
                participants,
                team_id=target.team_b_id,
                cutoff=target.cutoff_at,
                params=self._params,
                evaluation_mode=self._evaluation_mode,
                exclude_game_id=target.game_id,
            )

            train_eligible, exclusion_reason = self._eligibility(target)
            if train_eligible:
                n_train_eligible += 1
            else:
                n_excluded += 1
            team_a_avail += int(form_a.avail)
            team_b_avail += int(form_b.avail)
            player_a_avail += int(players_a.avail)
            player_b_avail += int(players_b.avail)
            target_patch_known += int(target.patch_id is not None)

            records.append(
                _row_to_dict(
                    target=target,
                    form_a=form_a,
                    form_b=form_b,
                    players_a=players_a,
                    players_b=players_b,
                    evaluation_mode=self._evaluation_mode,
                    train_eligible=train_eligible,
                    exclusion_reason=exclusion_reason,
                )
            )

        frame = pd.DataFrame.from_records(records)
        meta = DatasetMeta(
            feature_schema_version=FEATURE_SCHEMA_VERSION,
            lag_policy_version=LAG_POLICY_VERSION,
            evaluation_mode=self._evaluation_mode,
            target_phase=TARGET_PHASE,
            params=self._params,
            n_examples=len(records),
            n_train_eligible=n_train_eligible,
            n_excluded=n_excluded,
            team_a_avail=team_a_avail,
            team_b_avail=team_b_avail,
            player_a_avail=player_a_avail,
            player_b_avail=player_b_avail,
            target_patch_known=target_patch_known,
        )
        return frame, meta

    def _eligibility(self, target: TargetRow) -> tuple[bool, str | None]:
        """Принадлежность примера обучающей/оценочной когорте.

        `observed_mode_only_study` никогда не попадает в обучение/оценку MVP
        (карточка FEAT-001, AC #3). Метка режима обязательна
        (`PRD_TEMPORAL.md` §6): пример без режима не входит в eval-когорту.
        Unlabeled-таргеты отсеиваются ещё в `fetch_targets` (`status =
        'completed'` и известный победитель), поэтому здесь unreachable-веток
        нет — но причина исключения остаётся единственным источником правды.
        """
        if self._evaluation_mode == OBSERVED_MODE_ONLY_STUDY:
            return False, REASON_OBSERVED_STUDY
        return True, None


# --------------------------------------------------------------------------- #
# Структура выходной строки
# --------------------------------------------------------------------------- #


def _row_to_dict(
    *,
    target: TargetRow,
    form_a: TeamForm,
    form_b: TeamForm,
    players_a: PlayerForm,
    players_b: PlayerForm,
    evaluation_mode: str,
    train_eligible: bool,
    exclusion_reason: str | None,
) -> dict[str, object]:
    """Схема строки датасета: идентичность, маски и значения — рядом."""
    row: dict[str, object] = {
        # --- идентификация примера ---
        "series_id": target.series_id,
        "game_id": target.game_id,
        "cutoff_at": target.cutoff_at,
        "team_a_id": target.team_a_id,
        "team_b_id": target.team_b_id,
        "target_phase": TARGET_PHASE,
        "evaluation_mode": evaluation_mode,
        "train_eligible": train_eligible,
        "exclusion_reason": exclusion_reason,
        "target_patch_unknown": target.patch_id is None,
        # --- target: исход map1 для Team A ---
        "y": int(bool(target.y)),
    }
    _put_team_features(row, form_a, side="a")
    _put_team_features(row, form_b, side="b")
    _put_player_features(row, players_a, side="a")
    _put_player_features(row, players_b, side="b")
    _put_differentials(row)
    return row


def _put_team_features(row: dict[str, object], form: TeamForm, *, side: str) -> None:
    """Team prior-form для одной стороны + явная маска доступности."""
    row[f"team_{side}_n_games"] = form.n_games
    row[f"team_{side}_n_eff"] = form.n_eff if form.avail else float("nan")
    row[f"team_{side}_wr_lifetime"] = form.wr_lifetime if form.avail else float("nan")
    row[f"team_{side}_n_last_long"] = form.n_last_long
    row[f"team_{side}_wr_last_long"] = form.wr_last_long if form.n_last_long > 0 else float("nan")
    row[f"team_{side}_n_last_short"] = form.n_last_short
    row[f"team_{side}_wr_last_short"] = (
        form.wr_last_short if form.n_last_short > 0 else float("nan")
    )
    row[f"team_{side}_days_since_last"] = (
        form.days_since_last if form.days_since_last is not None else float("nan")
    )
    row[f"team_{side}_same_patch_n"] = form.same_patch_n
    row[f"team_{side}_avail"] = form.avail
    row[f"team_{side}_low_coverage"] = form.low_coverage


def _put_player_features(row: dict[str, object], form: PlayerForm, *, side: str) -> None:
    """Минимальный player prior-form для одной стороны + маска.

    Нет prior-known roster — значения `NaN`, маска `False`: неизвестное не
    подменяется нулём (`FEATURES.md` §1).
    """
    row[f"player_{side}_n_known"] = form.n_known_players
    row[f"player_{side}_n_games"] = form.n_games
    row[f"player_{side}_wr"] = form.wr if form.avail else float("nan")
    row[f"player_{side}_kda"] = form.kda if form.avail else float("nan")
    row[f"player_{side}_gpm"] = form.gpm if form.avail else float("nan")
    row[f"player_{side}_xpm"] = form.xpm if form.avail else float("nan")
    row[f"player_{side}_avail"] = form.avail


def _put_differentials(row: dict[str, object]) -> None:
    """Side-neutral дифференциалы A−B (`ML.md` §1).

    `NaN` распространяется из любой неизвестной стороны — дифференциал не
    маскирует отсутствие данных нулём.
    """
    row["d_team_wr_lifetime"] = _diff(row, "team_a_wr_lifetime", "team_b_wr_lifetime")
    row["d_team_wr_last_long"] = _diff(row, "team_a_wr_last_long", "team_b_wr_last_long")
    row["d_team_wr_last_short"] = _diff(row, "team_a_wr_last_short", "team_b_wr_last_short")
    row["d_team_n_eff"] = _diff(row, "team_a_n_eff", "team_b_n_eff")
    row["d_team_days_since_last"] = _diff(row, "team_a_days_since_last", "team_b_days_since_last")
    row["d_player_wr"] = _diff(row, "player_a_wr", "player_b_wr")
    row["d_player_kda"] = _diff(row, "player_a_kda", "player_b_kda")
    row["d_player_gpm"] = _diff(row, "player_a_gpm", "player_b_gpm")
    row["d_player_xpm"] = _diff(row, "player_a_xpm", "player_b_xpm")


def _diff(row: dict[str, object], left: str, right: str) -> float:
    """A − B как float, `NaN` при любом отсутствии."""
    left_value = row[left]
    right_value = row[right]
    if not isinstance(left_value, float | int) or not isinstance(right_value, float | int):
        return float("nan")
    return float(left_value) - float(right_value)
