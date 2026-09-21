"""DATA-001 — временной конверт canonical-записи.

Правила взяты из `docs/PRD_TEMPORAL.md` и не изобретаются заново:

* `observed_at` — когда источник фактически наблюдался (берётся из
  `source_observation`, а не «сейчас»);
* `ingested_at` — момент записи canonical-строки (часы процесса);
* `available_at` — canonical становится доступна пайплайну после записи, то есть
  не раньше `ingested_at`;
* `event_time` — время события в игровом мире (старт карты); для сущностей
  без события (команда, игрок) — `None`, а не «время загрузки».
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class Envelope:
    """Пять временных полей одной записи."""

    event_time: datetime | None
    source_published_at: datetime | None
    observed_at: datetime
    ingested_at: datetime
    available_at: datetime

    def as_dict(self) -> dict[str, datetime | None]:
        """Значения для SQL-параметров."""
        return {
            "event_time": self.event_time,
            "source_published_at": self.source_published_at,
            "observed_at": self.observed_at,
            "ingested_at": self.ingested_at,
            "available_at": self.available_at,
        }


def build_envelope(
    *,
    observed_at: datetime,
    ingested_at: datetime,
    event_time: datetime | None = None,
    source_published_at: datetime | None = None,
) -> Envelope:
    """Собрать конверт с гарантией `observed_at <= ingested_at <= available_at`.

    Расхождение часов (наблюдение «позже» записи) не исправляется молча в
    обратную сторону: `ingested_at` поднимается до `observed_at`, чтобы
    constraint не был нарушен, а сам факт остаётся видимым в данных.
    """
    if observed_at > ingested_at:
        ingested_at = observed_at
    return Envelope(
        event_time=event_time,
        source_published_at=source_published_at,
        observed_at=observed_at,
        ingested_at=ingested_at,
        # canonical доступна после завершения записи — не раньше.
        available_at=ingested_at,
    )
