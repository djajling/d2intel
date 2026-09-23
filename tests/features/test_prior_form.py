"""FEAT-001 — тесты prior-form датасета.

Покрытие по карточке `FEAT-001` (TESTS): тест на отсутствие данных после
cutoff; тест масок; тест единственности примера на серию. По `ML.md` §5 —
обязательные leakage-тесты: будущие матчи не меняют признаки, целевая карта не
видна pre-match запросу, unknown roster получает тот же fallback, что serving.

Часть тестов — pure-unit (in-memory записи, без БД). Интеграционные (сборка на
canonical-слое) требуют выделенную тестовую БД и пропускаются без неё.
"""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from d2intel.features.prior_form import (
    EVENT_ASOF,
    OBSERVED_MODE_ONLY_STUDY,
    REASON_OBSERVED_STUDY,
    PriorFormBuilder,
    PriorFormParams,
    PriorGame,
    PriorParticipant,
    TargetRow,
    n_eff,
    patch_weight,
    player_form,
    recency_weight,
    smoothed_winrate,
    team_form,
)

CUTOFF = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)
TEAM_A = uuid4()
TEAM_B = uuid4()
PATCH_X = uuid4()
PATCH_Y = uuid4()

DEFAULT_PARAMS = PriorFormParams()


# --------------------------------------------------------------------------- #
# Фабрики in-memory записей
# --------------------------------------------------------------------------- #


def game_at(
    team_id: UUID,
    days_ago: float,
    *,
    won: bool,
    patch_id: UUID | None = None,
    game_id: UUID | None = None,
) -> PriorGame:
    """Завершённая карта команды за `days_ago` до cutoff."""
    event_time = CUTOFF - timedelta(days=days_ago)
    return PriorGame(
        game_id=game_id if game_id is not None else uuid4(),
        team_id=team_id,
        event_time=event_time,
        won=won,
        patch_id=patch_id,
        observed_at=event_time + timedelta(hours=1),
    )


def participant_at(
    team_id: UUID,
    player_id: UUID,
    days_ago: float,
    *,
    won: bool,
    kills: int = 5,
    deaths: int = 5,
    assists: int = 5,
    gold_per_min: int = 500,
    xp_per_min: int = 600,
    game_id: UUID | None = None,
) -> PriorParticipant:
    """Участник карты с финальной статистикой за `days_ago` до cutoff."""
    event_time = CUTOFF - timedelta(days=days_ago)
    return PriorParticipant(
        game_id=game_id if game_id is not None else uuid4(),
        team_id=team_id,
        player_id=player_id,
        event_time=event_time,
        won=won,
        patch_id=PATCH_X,
        kills=kills,
        deaths=deaths,
        assists=assists,
        gold_per_min=gold_per_min,
        xp_per_min=xp_per_min,
        observed_at=event_time + timedelta(hours=1),
    )


def target(
    *,
    game_id: UUID | None = None,
    team_a: UUID = TEAM_A,
    team_b: UUID = TEAM_B,
    y: bool = True,
) -> TargetRow:
    """Целевая map1-запись."""
    return TargetRow(
        series_id=uuid4(),
        game_id=game_id if game_id is not None else uuid4(),
        cutoff_at=CUTOFF,
        team_a_id=team_a,
        team_b_id=team_b,
        patch_id=PATCH_X,
        target_observed_at=CUTOFF - timedelta(days=1),
        y=y,
    )


# --------------------------------------------------------------------------- #
# Формулы: weight, n_eff, shrinkage
# --------------------------------------------------------------------------- #


def pd_isnan(value: object) -> bool:
    """`math.isnan` для значений колонок pandas (включая object-dtype)."""
    return isinstance(value, float) and math.isnan(value)


def test_smoothed_winrate_shrinkage_math() -> None:
    """(Σw·y + αμ) / (Σw + α): победы при μ=0.5 и α=10 дают 0.75."""
    params = PriorFormParams(alpha=10.0, prior_mean=0.5)
    assert smoothed_winrate(w_sum=10.0, wy_sum=10.0, params=params) == pytest.approx(0.75)


def test_smoothed_winrate_returns_prior_mean_without_history() -> None:
    """Истории нет — значение равно μ, а не «0 побед»."""
    params = PriorFormParams(alpha=10.0, prior_mean=0.4)
    assert smoothed_winrate(w_sum=0.0, wy_sum=0.0, params=params) == pytest.approx(0.4)


def test_recency_weight_half_life() -> None:
    """Возраст = half-life → вес 0.5; будущее не весит; H ≤ 0 → все равны."""
    params = PriorFormParams(half_life_days=120.0)
    assert recency_weight(0.0, params) == pytest.approx(1.0)
    assert recency_weight(120.0, params) == pytest.approx(0.5)
    assert recency_weight(-10.0, params) == 0.0
    flat = PriorFormParams(half_life_days=0.0)
    assert recency_weight(365.0, flat) == 1.0


def test_n_eff_uniform_weights() -> None:
    """Равные веса → n_eff = n."""
    assert n_eff(w_sum=4.0, w2_sum=4.0) == pytest.approx(4.0)
    assert n_eff(w_sum=0.0, w2_sum=0.0) == 0.0


def test_patch_weight_policy() -> None:
    """Тот же патч — полный вес; другой/неизвестный — отдельная политика."""
    params = PriorFormParams(patch_same_weight=1.0, patch_other_weight=0.6)
    assert patch_weight(PATCH_X, PATCH_X, params) == pytest.approx(1.0)
    assert patch_weight(PATCH_Y, PATCH_X, params) == pytest.approx(0.6)
    # неизвестный патч не считается автоматически «старым»
    assert patch_weight(None, PATCH_X, params) == pytest.approx(0.6)
    assert patch_weight(PATCH_X, None, params) == pytest.approx(0.6)


# --------------------------------------------------------------------------- #
# Cutoff и утечки (карточка TESTS #1; ML.md §5.1, §5.2)
# --------------------------------------------------------------------------- #


def test_team_form_excludes_future_games() -> None:
    """Игры после cutoff (или в окне задержки) не меняют признаки.

    `ML.md` §5.1: добавление будущих матчей не меняет ранее построенный
    snapshot — здесь та же инвариантность для признаков.
    """
    history = [game_at(TEAM_A, 30.0, won=True), game_at(TEAM_A, 5.0, won=False)]
    base = team_form(
        history, team_id=TEAM_A, cutoff=CUTOFF, target_patch=PATCH_X, params=DEFAULT_PARAMS
    )
    with_future = team_form(
        history
        + [
            # будущее событие — строго после cutoff
            game_at(TEAM_A, -1.0, won=True),
            # началась за час до cutoff: результат не мог быть известен
            # (result_lag по умолчанию 4 часа)
            game_at(TEAM_A, 1 / 24, won=True),
        ],
        team_id=TEAM_A,
        cutoff=CUTOFF,
        target_patch=PATCH_X,
        params=DEFAULT_PARAMS,
    )
    assert base.n_games == 2
    assert with_future.n_games == base.n_games
    assert with_future.wr_lifetime == base.wr_lifetime


def test_team_form_result_lag_policy_versioned() -> None:
    """Карта в окне задержки исключена; result_lag = 0 — включена.

    Политика задержки — единственное, что отличает «событие было» от
    «результат был известен» в режиме реконструкции.
    """
    recent = [game_at(TEAM_A, 1 / 24, won=True)]  # за час до cutoff
    assert not team_form(
        recent, team_id=TEAM_A, cutoff=CUTOFF, target_patch=None, params=DEFAULT_PARAMS
    ).avail
    zero_lag = PriorFormParams(result_lag=timedelta(0))
    assert team_form(
        recent, team_id=TEAM_A, cutoff=CUTOFF, target_patch=None, params=zero_lag
    ).avail


def test_team_form_target_game_excluded() -> None:
    """Собственный исход целевой карты не попадает в pre-match признаки.

    `ML.md` §5.2: target outcome не доступен pre-match feature query.
    Отсечение по `exclude_game_id` — страховка поверх cutoff-фильтра.
    """
    target_game_id = uuid4()
    only_target = game_at(TEAM_A, 0.5, won=True, game_id=target_game_id)
    excluded = team_form(
        [only_target],
        team_id=TEAM_A,
        cutoff=CUTOFF,
        target_patch=None,
        params=DEFAULT_PARAMS,
        exclude_game_id=target_game_id,
    )
    assert excluded.n_games == 0
    assert not excluded.avail
    # без явного исключения карта была бы учтена — значит, фильтр не избыточен
    included = team_form(
        [only_target], team_id=TEAM_A, cutoff=CUTOFF, target_patch=None, params=DEFAULT_PARAMS
    )
    assert included.n_games == 1


def test_team_form_recency_ordering() -> None:
    """Свежая победа весит больше давней.

    При единственном выигрыше недавняя карта отодвигает winrate от μ сильнее,
    чем выигрыш больше года назад — recency-вес работает в правильную сторону.
    """
    params = PriorFormParams(half_life_days=120.0, alpha=10.0, prior_mean=0.5)
    recent_win = [game_at(TEAM_A, 5.0, won=True)]
    old_win = [game_at(TEAM_B, 400.0, won=True)]
    recent_wr = team_form(
        recent_win, team_id=TEAM_A, cutoff=CUTOFF, target_patch=None, params=params
    ).wr_lifetime
    old_wr = team_form(
        old_win, team_id=TEAM_B, cutoff=CUTOFF, target_patch=None, params=params
    ).wr_lifetime
    assert recent_wr is not None and old_wr is not None
    assert recent_wr > old_wr > params.prior_mean


def test_team_form_last_n_windows() -> None:
    """Окна last-N считаются по самым свежим картам, lifetime — по всем."""
    long_history = [game_at(TEAM_A, 1.0 + 0.1 * index, won=index % 2 == 0) for index in range(30)]
    form = team_form(
        long_history, team_id=TEAM_A, cutoff=CUTOFF, target_patch=None, params=DEFAULT_PARAMS
    )
    assert form.n_games == 30
    assert form.n_last_long == DEFAULT_PARAMS.last_n_long
    assert form.n_last_short == DEFAULT_PARAMS.last_n_short


# --------------------------------------------------------------------------- #
# Маски доступности (карточка TESTS #2; FEATURES.md §1 «неизвестное ≠ 0»)
# --------------------------------------------------------------------------- #


def test_team_form_no_history_masks_not_zeros() -> None:
    """Нет истории — признаки отсутствуют, маска ложна; нолей нет."""
    form = team_form(
        [], team_id=TEAM_A, cutoff=CUTOFF, target_patch=PATCH_X, params=DEFAULT_PARAMS
    )
    assert form.n_games == 0
    assert not form.avail
    assert form.wr_lifetime is None
    assert form.days_since_last is None
    assert not form.low_coverage


def test_player_form_no_known_roster_masks() -> None:
    """Нет prior-known roster — availability-aware fallback: маска, не нули.

    `ML.md` §5.3: неизвестный состав получает тот же fallback/mask, что
    serving.
    """
    form = player_form(
        [], team_id=TEAM_A, cutoff=CUTOFF, params=DEFAULT_PARAMS
    )
    assert form.n_known_players == 0
    assert not form.avail
    assert form.wr is None
    assert form.kda is None
    assert form.gpm is None
    assert form.xpm is None


def test_player_form_aggregates_known_players() -> None:
    """Минимальный player prior-form:_wr, KDA, GPM, XPM по prior-known roster."""
    p1, p2 = uuid4(), uuid4()
    other_team = uuid4()
    participants = [
        participant_at(TEAM_A, p1, 2.0, won=True, kills=5, deaths=5, assists=10, gold_per_min=600, xp_per_min=700),
        participant_at(TEAM_A, p2, 3.0, won=False, kills=2, deaths=8, assists=4, gold_per_min=400, xp_per_min=500),
        # p1 играл и за другую команду — индивидуальная история учитывает все карты
        participant_at(other_team, p1, 4.0, won=True, kills=10, deaths=2, assists=5, gold_per_min=800, xp_per_min=900),
        # игрок из «будущего» — не prior-known
        participant_at(TEAM_A, uuid4(), -1.0, won=True),
    ]
    form = player_form(participants, team_id=TEAM_A, cutoff=CUTOFF, params=DEFAULT_PARAMS)
    assert form.avail
    assert form.n_known_players == 2
    assert 0.0 < form.wr < 1.0
    # p1: (5+10)/5 = 3.0 и (10+5)/2 = 7.5 → среднее 5.25; p2: (2+4)/8 = 0.75
    assert form.kda == pytest.approx((5.25 + 0.75) / 2)
    # p1: (600 + 800)/2 = 700; p2: 400
    assert form.gpm == pytest.approx((700.0 + 400.0) / 2)
    # p1: (700 + 900)/2 = 800; p2: 500
    assert form.xpm == pytest.approx((800.0 + 500.0) / 2)


def test_player_form_excludes_target_game() -> None:
    """Участники целевой карты не учитываются как prior-known roster."""
    target_game_id = uuid4()
    p1 = uuid4()
    participants = [
        participant_at(TEAM_A, p1, 0.5, won=True, game_id=target_game_id),
    ]
    form = player_form(
        participants,
        team_id=TEAM_A,
        cutoff=CUTOFF,
        params=DEFAULT_PARAMS,
        exclude_game_id=target_game_id,
    )
    assert not form.avail
    assert form.n_known_players == 0


# --------------------------------------------------------------------------- #
# Параметры: fit только на train (AC #5)
# --------------------------------------------------------------------------- #


def test_params_fit_uses_train_labels_only() -> None:
    """μ вычисляется только по train-меткам, прочее — documented defaults."""
    fitted = PriorFormParams.fit([1.0, 1.0, 0.0])
    assert fitted.prior_mean == pytest.approx(2.0 / 3.0)
    assert fitted.half_life_days == DEFAULT_PARAMS.half_life_days
    assert PriorFormParams.fit([]).prior_mean == 0.5
    overrides = PriorFormParams.fit([0.0, 0.0], half_life_days=60.0)
    assert overrides.prior_mean == 0.0
    assert overrides.half_life_days == 60.0


def test_params_fit_does_not_touch_other_data() -> None:
    """Сборка с fit-параметрами не выводит μ из всего датасета.

    Косвенная проверка: признаки одной команды не зависят от наличия других
    примеров — построитель работает строго по своей истории до cutoff.
    """
    params = PriorFormParams.fit([1.0, 1.0])  # μ = 1.0
    form = team_form(
        [game_at(TEAM_A, 1.0, won=False)],
        team_id=TEAM_A,
        cutoff=CUTOFF,
        target_patch=None,
        params=params,
    )
    # единственный проигрыш не может дать wr = 0 из-за shrinkage к μ = 1.0
    assert form.wr_lifetime is not None
    assert form.wr_lifetime > 0.0


# --------------------------------------------------------------------------- #
# Режимы и сборка (AC #3)
# --------------------------------------------------------------------------- #


def test_builder_rejects_unknown_mode() -> None:
    """Неизвестный режим — ошибка, а не тихое значение по умолчанию."""
    with pytest.raises(ValueError):  # noqa: B017 — сообщение не проверяем
        PriorFormBuilder(session=None, evaluation_mode="not_a_mode")  # type: ignore[arg-type]


def test_builder_eligibility_observed_mode_never_trains() -> None:
    """observed_mode_only_study не попадает в обучение/оценку MVP (AC #3)."""
    observed = PriorFormBuilder(session=None, evaluation_mode=OBSERVED_MODE_ONLY_STUDY)  # type: ignore[arg-type]
    eligible, reason = observed._eligibility(target())
    assert not eligible
    assert reason == REASON_OBSERVED_STUDY
    event_mode = PriorFormBuilder(session=None, evaluation_mode=EVENT_ASOF)  # type: ignore[arg-type]
    assert event_mode._eligibility(target()) == (True, None)


# --------------------------------------------------------------------------- #
# Интеграция на canonical-слое (нужна выделенная тестовая БД со схемой 0003)
# --------------------------------------------------------------------------- #


def _seed_observation(session: Session) -> str:
    source = session.execute(
        text(
            """
            INSERT INTO data_source (name, adapter_version, capabilities, created_at)
            VALUES (:name, 'feat-test', CAST('{}' AS jsonb), now())
            RETURNING id
            """
        ),
        {"name": f"feat-source-{uuid4().hex[:8]}"},
    ).scalar_one()
    run = session.execute(
        text(
            "INSERT INTO ingestion_run (source_id, started_at, status) "
            "VALUES (:source_id, now(), 'completed') RETURNING id"
        ),
        {"source_id": source},
    ).scalar_one()
    raw = session.execute(
        text(
            """
            INSERT INTO raw_payload (
                source_id, endpoint_kind, content_hash, schema_version, payload_json,
                observed_at, ingested_at, available_at
            ) VALUES (
                :source_id, 'fixture', :content_hash, 'feat.v1', CAST('{}' AS jsonb),
                now(), now(), now()
            )
            RETURNING id
            """
        ),
        {"source_id": source, "content_hash": f"feat-{uuid4().hex}"},
    ).scalar_one()
    observation = session.execute(
        text(
            """
            INSERT INTO source_observation (
                run_id, raw_payload_id, provider_entity_id, provider_entity_type,
                observed_at, ingested_at, available_at
            ) VALUES (
                :run_id, :raw_payload_id, 'feat-entity', 'fixture',
                now(), now(), now()
            )
            RETURNING id
            """
        ),
        {"run_id": run, "raw_payload_id": raw},
    ).scalar_one()
    session.flush()
    return str(observation)


def _seed_team(session: Session, observation_id: str, name: str) -> UUID:
    row = session.execute(
        text(
            """
            INSERT INTO team (canonical_name, identity_status, source_observation_id,
                              observed_at, ingested_at, available_at)
            VALUES (:name, 'resolved', :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"name": name, "observation_id": observation_id},
    ).scalar_one()
    return UUID(str(row))


def _seed_series(session: Session, observation_id: str, key: str) -> UUID:
    row = session.execute(
        text(
            """
            INSERT INTO series (best_of, status, series_key, source_observation_id,
                                observed_at, ingested_at, available_at)
            VALUES (3, 'completed', :key, :observation_id, now(), now(), now())
            RETURNING id
            """
        ),
        {"key": key, "observation_id": observation_id},
    ).scalar_one()
    return UUID(str(row))


def _seed_game(
    session: Session,
    observation_id: str,
    *,
    series_id: UUID,
    match_id: int,
    map_number: int | None,
    event_time: datetime,
    slot0: UUID,
    slot1: UUID,
    slot0_wins: bool,
) -> UUID:
    """Карта с независимыми стороной и исходом: slot 0 = radiant (Team A)."""
    winner = slot0 if slot0_wins else slot1
    game_row = session.execute(
        text(
            """
            INSERT INTO game (series_id, map_number, attempt_number, status,
                              provider_match_id, winner_team_id, result_type,
                              source_observation_id, event_time,
                              observed_at, ingested_at, available_at)
            VALUES (:series_id, :map_number, 1, 'completed', :match_id, :winner, 'played',
                    :observation_id, :event_time, now(), now(), now())
            RETURNING id
            """
        ),
        {
            "series_id": series_id,
            "match_id": match_id,
            "map_number": map_number,
            "winner": winner,
            "observation_id": observation_id,
            "event_time": event_time,
        },
    ).scalar_one()
    game_uuid = UUID(str(game_row))
    for slot, (team_id, side) in enumerate(((slot0, "radiant"), (slot1, "dire"))):
        session.execute(
            text(
                """
                INSERT INTO game_team (game_id, team_id, side, slot, source_observation_id,
                                       observed_at, ingested_at, available_at)
                VALUES (:game_id, :team_id, :side, :slot, :observation_id,
                        now(), now(), now())
                """
            ),
            {
                "game_id": game_uuid,
                "team_id": team_id,
                "side": side,
                "slot": slot,
                "observation_id": observation_id,
            },
        )
    session.flush()
    return game_uuid


def test_build_dataset_one_example_per_series_and_no_leakage(feature_session: Session) -> None:
    """Один пример на серию; target-карта не попадает в свои же признаки.

    Сценарий: A и B играют серию (map1 — выигрыш A), до этого A выигрывала у
    C, а B проигрывала C. Вторая серия (Bo1) — выигрыш B: для неё карты первой
    серии — уже легитимная прошлая история.
    """
    observation_id = _seed_observation(feature_session)
    team_a = _seed_team(feature_session, observation_id, "Team Alpha")
    team_b = _seed_team(feature_session, observation_id, "Team Bravo")
    team_c = _seed_team(feature_session, observation_id, "Team Charlie")

    t0 = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    # прошлая история до серии
    _seed_game(
        feature_session,
        observation_id,
        series_id=_seed_series(feature_session, observation_id, "series-past-a"),
        match_id=8000000001,
        map_number=1,
        event_time=t0 - timedelta(days=10),
        slot0=team_a,
        slot1=team_c,
        slot0_wins=True,
    )
    _seed_game(
        feature_session,
        observation_id,
        series_id=_seed_series(feature_session, observation_id, "series-past-b"),
        match_id=8000000002,
        map_number=1,
        event_time=t0 - timedelta(days=9),
        slot0=team_c,
        slot1=team_b,
        slot0_wins=True,
    )
    # целевая серия: map1 (target) и map2
    series_one = _seed_series(feature_session, observation_id, "series-one")
    target_game = _seed_game(
        feature_session,
        observation_id,
        series_id=series_one,
        match_id=8000000003,
        map_number=1,
        event_time=t0,
        slot0=team_a,
        slot1=team_b,
        slot0_wins=True,
    )
    _seed_game(
        feature_session,
        observation_id,
        series_id=series_one,
        match_id=8000000004,
        map_number=2,
        event_time=t0 + timedelta(minutes=40),
        slot0=team_a,
        slot1=team_b,
        slot0_wins=False,
    )
    # вторая серия позже: для неё карты первой серии — прошлая история
    series_two = _seed_series(feature_session, observation_id, "series-two")
    _seed_game(
        feature_session,
        observation_id,
        series_id=series_two,
        match_id=8000000005,
        map_number=1,
        event_time=t0 + timedelta(days=2),
        slot0=team_a,
        slot1=team_b,
        slot0_wins=False,
    )

    frame, meta = PriorFormBuilder(feature_session).build()

    # один пример на серию с доказанным map1: две прошлые серии + две
    # целевые — все четыре серии имеют собственный map1
    assert meta.n_examples == 4
    assert frame["series_id"].is_unique
    assert set(frame["evaluation_mode"]) == {EVENT_ASOF}
    assert meta.n_train_eligible == 4

    first = frame[frame["game_id"] == target_game].iloc[0]
    # target — map1, Team A = slot 0 (radiant) выиграла
    assert first["y"] == 1
    # в признаки A/B вошли только прошлые карты, не целевая (leakage-тест)
    assert first["team_a_n_games"] == 1
    assert first["team_b_n_games"] == 1
    assert bool(first["team_a_avail"]) is True
    # A выиграла единственную прошлую карту, B проиграла — форма A сильнее
    assert first["team_a_wr_lifetime"] > first["team_b_wr_lifetime"]
    # участников не было — player-фичи отсутствуют, маска ложна (не нули)
    assert bool(first["player_a_avail"]) is False
    assert bool(pd_isnan(first["player_a_wr"]))
    assert bool(pd_isnan(first["d_player_wr"]))

    # для второй серии карты первой серии — легитимная прошлая история
    second = frame[frame["series_id"] == series_two].iloc[0]
    assert second["y"] == 0
    assert second["team_a_n_games"] == 3  # прошлый выигрыш + map1 + map2 первой серии
    assert second["team_b_n_games"] == 3


def test_build_dataset_observed_mode_is_study_only(feature_session: Session) -> None:
    """observed_mode_only_study: примеры размечены и в обучение не идут (AC #3).

    В реконструированном датасете observed_at = «сейчас» > cutoff, поэтому
    признаков в этом режиме нет — но режим обязан быть размечен.
    """
    observation_id = _seed_observation(feature_session)
    team_a = _seed_team(feature_session, observation_id, "Team Alpha")
    team_b = _seed_team(feature_session, observation_id, "Team Bravo")
    series_id = _seed_series(feature_session, observation_id, "series-observed")
    _seed_game(
        feature_session,
        observation_id,
        series_id=series_id,
        match_id=8000000010,
        map_number=1,
        event_time=datetime(2026, 8, 1, 12, 0, tzinfo=UTC),
        slot0=team_a,
        slot1=team_b,
        slot0_wins=True,
    )

    frame, meta = PriorFormBuilder(
        feature_session, evaluation_mode=OBSERVED_MODE_ONLY_STUDY
    ).build()

    assert meta.n_examples == 1
    assert meta.n_train_eligible == 0
    assert meta.n_excluded == 1
    assert frame.iloc[0]["evaluation_mode"] == OBSERVED_MODE_ONLY_STUDY
    assert frame.iloc[0]["exclusion_reason"] == REASON_OBSERVED_STUDY
    # истории по фактическому наблюдению до cutoff нет — маски ложны
    assert bool(frame.iloc[0]["team_a_avail"]) is False
