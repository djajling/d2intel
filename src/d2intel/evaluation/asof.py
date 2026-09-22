"""As-of семантика и проверка отсутствия утечек.

Ключевой риск проекта — подсмотреть будущее. Здесь это формализуется:
у каждого наблюдения есть **момент доступности**, и он сравнивается с cutoff.

## Две шкалы доступности

`AvailabilityClock.EVENT_TIME` (по умолчанию)
    Факт становится известен, когда событие произошло: исход карты известен
    после её окончания. Для ретроспективного среза это единственная шкала,
    на которой история вообще доступна.

`AvailabilityClock.AVAILABLE_AT`
    Когда наблюдение реально получено нами (`ingested_at`/`available_at`).
    В нашем первом срезе почти все строки имеют `available_at` = момент
    загрузки (2026-09-22), поэтому на этой шкале **вся** история оказывается
    «из будущего» и ни один признак не проходит проверку. Шкала оставлена
    сознательно: она нужна для настоящего pre-match прогона, где срез
    загружается до матча.

## Известное ограничение (не скрываем)

Истинный cutoff «до драфта, до матча» требует времени объявления фикстуры.
OpenDota его не отдаёт. Поэтому ретроспективный cutoff = `event_time`
момента матча: считается, что всё, что произошло **строго раньше**, нам
известно. Это **не** консервативная оценка — она допускает данные, ставшие
известными вплоть до старта матча, — но она зафиксирована явно, а не
подразумевается. Ограничение должно быть указано в любом отчёте о метрике.
"""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum


class AvailabilityClock(StrEnum):
    """Шкала, по которой определяется момент доступности наблюдения."""

    EVENT_TIME = "event_time"
    AVAILABLE_AT = "available_at"


class LeakageViolation(Exception):
    """Нарушение as-of: в признак попали данные, недоступные на cutoff."""


def assert_as_of(
    *,
    available_at: datetime | None,
    cutoff: datetime,
    what: str = "observation",
) -> None:
    """Проверить, что наблюдение доступно не позже cutoff.

    `available_at is None` трактуется как «неизвестно» и **отклоняется**:
    неизвестное время доступности нельзя считать безопасным.
    """
    if available_at is None:
        raise LeakageViolation(
            f"{what}: момент доступности неизвестен (None) — считать доступным нельзя"
        )
    if available_at > cutoff:
        raise LeakageViolation(
            f"{what}: available_at={available_at.isoformat()} позже cutoff={cutoff.isoformat()}"
        )


def is_as_of(*, available_at: datetime | None, cutoff: datetime) -> bool:
    """Ненарушающая версия `assert_as_of` (для фильтрации, а не для падения)."""
    if available_at is None:
        return False
    return available_at <= cutoff
