"""Prior baseline: константный прогноз, фит только на train, воздержание."""

from __future__ import annotations

import pytest

from d2intel.models.prior import PriorAbstentionError, PriorBaseline


def test_fit_estimates_share_of_team_a_wins() -> None:
    prior = PriorBaseline.fit([1, 0, 1, 1, 0])
    assert prior.p_a == pytest.approx(0.6)
    assert prior.fitted_n == 5
    assert not prior.is_abstaining


def test_fit_on_empty_train_abstains_instead_of_faking_05() -> None:
    """Пустой train — это воздержание, а не «настоящий» прогноз 0.5."""
    prior = PriorBaseline.fit([])
    assert prior.is_abstaining
    assert prior.abstention_reason is not None
    assert prior.p_a == 0.5  # заглушка для отчёта, а не рабочий прогноз


def test_predict_is_constant() -> None:
    prior = PriorBaseline.fit([1, 1, 0])
    assert prior.predict(3) == [prior.p_a] * 3


def test_predict_raises_when_abstaining() -> None:
    prior = PriorBaseline.fit([])
    with pytest.raises(PriorAbstentionError):
        prior.predict_proba_a()
    with pytest.raises(PriorAbstentionError):
        prior.predict(2)


def test_hard_label_follows_majority_of_train() -> None:
    assert PriorBaseline.fit([1, 1, 0]).hard_label == 1
    assert PriorBaseline.fit([1, 0, 0]).hard_label == 0
    assert PriorBaseline.fit([]).hard_label == 1  # p_a=0.5 -> граница в сторону 1


def test_fit_does_not_touch_validation_labels() -> None:
    """Признак защиты от утечки: fit принимает только train-метки."""
    train = [1, 1, 1, 0]
    prior = PriorBaseline.fit(train)
    # valid-метки в fit не передавались — на значение p_a влиять не могут.
    assert prior.p_a == pytest.approx(0.75)
