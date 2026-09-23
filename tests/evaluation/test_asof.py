"""As-of: ничего из будущего не попадает в признак."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from d2intel.evaluation.asof import AvailabilityClock, assert_as_of, is_as_of

CUTOFF = datetime(2026, 9, 1, 12, 0, tzinfo=UTC)


def test_observation_at_cutoff_is_allowed() -> None:
    """Граница включена: доступно ровно в cutoff — доступно."""
    assert_as_of(available_at=CUTOFF, cutoff=CUTOFF, what="game")


def test_observation_before_cutoff_is_allowed() -> None:
    assert_as_of(available_at=CUTOFF - timedelta(hours=1), cutoff=CUTOFF)


def test_future_observation_is_rejected() -> None:
    with pytest.raises(Exception, match="позже cutoff"):
        assert_as_of(available_at=CUTOFF + timedelta(seconds=1), cutoff=CUTOFF)


def test_unknown_availability_is_rejected() -> None:
    """Неизвестное время доступности — не «разрешено», а отклонено."""
    with pytest.raises(Exception, match="неизвестен"):
        assert_as_of(available_at=None, cutoff=CUTOFF)


def test_is_as_of_does_not_raise() -> None:
    assert is_as_of(available_at=CUTOFF - timedelta(days=1), cutoff=CUTOFF) is True
    assert is_as_of(available_at=CUTOFF + timedelta(days=1), cutoff=CUTOFF) is False
    assert is_as_of(available_at=None, cutoff=CUTOFF) is False


def test_two_availability_clocks_exist() -> None:
    """Обе шкалы объявлены: event_time для ретроспективы, available_at для pre-match."""
    assert AvailabilityClock.EVENT_TIME.value == "event_time"
    assert AvailabilityClock.AVAILABLE_AT.value == "available_at"
