"""Baseline «prior»: константная вероятность P(Team A выигрывает map1).

Это самая слабая содержательная модель: она не использует ни составы, ни
форму, ни драфт — только долю побед Team A в обучающей выборке. Два
назначения:

1. **Обязательный нижний ориентир** (ADR-006): любая реальная модель
   сравнивается с prior, а точность — с точностью мажоритарного класса.
2. **Проверка цепочки записи**: prior не требует признаков, поэтому он
   первым прокачивает всю схему предсказаний от фит-до-снимка, не дожидаясь
   FEAT-001.

Честность:
- `fit` смотрит **только на train**. Доли valid/test в оценку prior не идут.
- На пустом train модель **воздерживается**, а не выдаёт 0.5 «как настоящий»
  прогноз: совпадение чисел не должно маскировать отсутствие данных.
- Метрики prior сообщает вместе с `fitted_n` — доверять доле из 3 наблюдений
  нельзя.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass


class PriorAbstentionError(ValueError):
    """Модель воздерживается: обучающей выборки нет."""


@dataclass(frozen=True)
class PriorBaseline:
    """Константный прогноз P(Team A) = доля побед Team A на train."""

    p_a: float
    fitted_n: int
    abstention_reason: str | None = None

    @property
    def is_abstaining(self) -> bool:
        return self.abstention_reason is not None

    @property
    def hard_label(self) -> int:
        """Класс, который предсказывает мажоритарное правило prior (1 — Team A)."""
        return 1 if self.p_a >= 0.5 else 0

    @classmethod
    def fit(cls, labels: Sequence[int]) -> PriorBaseline:
        """Оценить p_a по меткам train. Пустой train → воздержание."""
        materialized = list(labels)
        if not materialized:
            return cls(
                p_a=0.5,
                fitted_n=0,
                abstention_reason="обучающая выборка пуста",
            )
        return cls(p_a=sum(materialized) / len(materialized), fitted_n=len(materialized))

    def predict_proba_a(self) -> float:
        """P(Team A) для любого матча. Одинаково, потому что модель константная."""
        if self.is_abstaining:
            raise PriorAbstentionError(self.abstention_reason or "воздержание")
        return self.p_a

    def predict(self, n: int) -> list[float]:
        """`n` одинаковых прогнозов — для удобства пакетной оценки."""
        return [self.predict_proba_a() for _ in range(n)]
