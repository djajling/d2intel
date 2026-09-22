"""Заморозка сплита: детерминизм, устойчивость к порядку, детект изменения."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import UUID

import pytest

from d2intel.evaluation.freeze import (
    FrozenSplitMismatch,
    assert_frozen_matches,
    content_hash_of,
    freeze_split,
)
from d2intel.evaluation.split import SplitSpec

TEAM_A = UUID("00000000-0000-0000-0000-00000000000a")
TEAM_B = UUID("00000000-0000-0000-0000-00000000000b")

SPEC = SplitSpec(
    valid_from=datetime(2026, 7, 1, tzinfo=UTC),
    test_from=datetime(2026, 8, 1, tzinfo=UTC),
    embargo=timedelta(hours=24),
)


def _row(
    *, game: int, series: int, when: datetime, winner: UUID = TEAM_A
) -> object:
    from d2intel.evaluation.cohort import Game1Row

    return Game1Row(
        game_id=UUID(int=game),
        series_id=UUID(int=series),
        event_time=when,
        team_a_id=TEAM_A,
        team_b_id=TEAM_B,
        winner_team_id=winner,
    )


def _cohort() -> list[object]:
    base = datetime(2026, 6, 1, tzinfo=UTC)
    return [
        _row(game=1, series=1, when=base),
        _row(game=2, series=2, when=base + timedelta(days=20)),
        _row(game=3, series=3, when=base + timedelta(days=50)),  # valid
        _row(game=4, series=4, when=base + timedelta(days=80)),  # test
    ]


def test_freeze_is_deterministic_for_same_data_and_spec() -> None:
    rows = _cohort()
    first = freeze_split(rows, SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC))
    second = freeze_split(rows, SPEC, frozen_at=datetime(2026, 9, 2, tzinfo=UTC))
    assert first.content_hash == second.content_hash
    assert first.counts == second.counts


def test_content_hash_does_not_depend_on_row_order() -> None:
    rows = _cohort()
    assert content_hash_of(rows, SPEC) == content_hash_of(list(reversed(rows)), SPEC)


def test_counts_respect_embargo_boundaries() -> None:
    frozen = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert frozen.counts["train"] == 2
    assert frozen.counts["valid"] == 1
    assert frozen.counts["test"] == 1
    assert frozen.counts["excluded"] == 0


def test_embargo_excludes_rows_inside_the_gap() -> None:
    """Наблюдение в разрыве между сегментами исключается, а не приписывается к edge."""
    rows = _cohort() + [
        _row(game=5, series=5, when=SPEC.valid_from + timedelta(hours=3)),
        _row(game=6, series=6, when=SPEC.test_from - timedelta(hours=3)),
    ]
    frozen = freeze_split(rows, SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC))
    assert frozen.counts["excluded"] == 2
    assert frozen.counts["valid"] == 1


def test_new_games_in_test_window_change_the_hash() -> None:
    """Дообучение приносит новые игры в test — заморозка обязана это заметить."""
    original = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    with_more_test_games = _cohort() + [
        _row(game=7, series=7, when=datetime(2026, 8, 15, tzinfo=UTC))
    ]
    assert (
        content_hash_of(with_more_test_games, SPEC) != original.content_hash
    )


def test_extra_games_in_train_also_change_the_hash() -> None:
    original = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    with_more_train_games = _cohort() + [
        _row(game=8, series=8, when=datetime(2026, 6, 10, tzinfo=UTC))
    ]
    assert content_hash_of(with_more_train_games, SPEC) != original.content_hash


def test_second_game_in_a_frozen_series_changes_the_hash() -> None:
    """Remake или вторая карта-1 в уже замороженной серии — состав изменился."""
    original = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    with_remade_series = _cohort() + [
        _row(game=9, series=4, when=datetime(2026, 8, 2, tzinfo=UTC), winner=TEAM_B)
    ]
    assert content_hash_of(with_remade_series, SPEC) != original.content_hash


def test_assert_frozen_matches_is_silent_on_unchanged_cohort() -> None:
    frozen = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    assert_frozen_matches(_cohort(), frozen)


def test_assert_frozen_matches_raises_on_changed_cohort() -> None:
    frozen = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 1, tzinfo=UTC)
    )
    changed = _cohort() + [
        _row(game=7, series=7, when=datetime(2026, 8, 15, tzinfo=UTC))
    ]
    with pytest.raises(FrozenSplitMismatch):
        assert_frozen_matches(changed, frozen)


def test_series_straddling_segments_is_rejected() -> None:
    """Серия не может оказаться одновременно в train и test."""
    straddling = _cohort() + [
        _row(game=11, series=4, when=datetime(2026, 6, 15, tzinfo=UTC))
    ]
    with pytest.raises(ValueError):
        content_hash_of(straddling, SPEC)


def test_roundtrip_through_json_keeps_the_hash() -> None:
    frozen = freeze_split(
        _cohort(), SPEC, frozen_at=datetime(2026, 9, 3, tzinfo=UTC)
    )
    restored = type(frozen).from_dict(frozen.to_dict())
    assert restored.content_hash == frozen.content_hash
    assert restored.spec == frozen.spec
    assert restored.counts == frozen.counts
    assert restored.segment_hashes == frozen.segment_hashes
