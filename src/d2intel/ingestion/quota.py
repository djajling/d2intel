"""ING-001 — общий бюджет квоты источника (ARCHITECTURE.md §3, п. 2).

Один экземпляр `QuotaBudget` на источник обслуживает **все** endpoints клиента.
Логика:

* скользящее минутное окно (60 запросов / 60 с) — строже, чем граница минуты у
  провайдера, поэтому 429 не провоцируется намеренно;
* суточный счётчик (3 000) с границей по UTC-дате;
* заголовки провайдера (`X-Rate-Limit-Remaining-Minute` / `-Day`) читаются и
  **ужесточают** локальный лимит, если провайдер сообщил меньший остаток;
* журнал наблюдённых заголовков сохраняется (пишется в `ingestion_run.quota_headers`).

Время берётся из инжектируемых `clock` (монотонный, для окна) и `wall_clock`
(UTC, для суточной границы) — так throttle тестируется без реальных ожиданий.
"""

from __future__ import annotations

import threading
import time
from collections import deque
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from d2intel.ingestion.contracts import QuotaPolicy
from d2intel.ingestion.errors import QuotaExhaustedError

#: Сколько записей журнала хранить в памяти (журнал — диагностика, не архив).
MAX_JOURNAL_ENTRIES = 500


@dataclass(frozen=True)
class QuotaSnapshot:
    """Текущее состояние бюджета (без секретов)."""

    per_minute: int
    per_day: int
    minute_used: int
    day_used: int
    minute_remaining: int
    day_remaining: int
    provider_minute_remaining: int | None
    provider_day_remaining: int | None


@dataclass
class _JournalEntry:
    at: datetime
    event: str
    endpoint_kind: str | None
    http_status: int | None
    remaining_minute: int | None
    remaining_day: int | None

    def as_dict(self) -> dict[str, Any]:
        return {
            "at": self.at.isoformat(),
            "event": self.event,
            "endpoint_kind": self.endpoint_kind,
            "http_status": self.http_status,
            "remaining_minute": self.remaining_minute,
            "remaining_day": self.remaining_day,
        }


def _parse_int_header(value: str | None) -> int | None:
    if value is None:
        return None
    try:
        return int(value.strip())
    except (TypeError, ValueError):
        return None


@dataclass
class QuotaBudget:
    """Общий бюджет источника: throttle + дневной лимит + журнал headers."""

    policy: QuotaPolicy
    clock: Callable[[], float] = time.monotonic
    wall_clock: Callable[[], datetime] = lambda: datetime.now(UTC)
    sleeper: Callable[[float], None] = time.sleep
    #: Сколько максимум ждать освобождения минутного окна внутри `acquire`.
    max_wait_seconds: float = 60.0
    _minute_window: deque[float] = field(default_factory=deque, init=False, repr=False)
    _day_key: str = field(default="", init=False, repr=False)
    _day_used: int = field(default=0, init=False, repr=False)
    _provider_minute_remaining: int | None = field(default=None, init=False, repr=False)
    _provider_day_remaining: int | None = field(default=None, init=False, repr=False)
    _journal: deque[_JournalEntry] = field(
        default_factory=lambda: deque(maxlen=MAX_JOURNAL_ENTRIES), init=False, repr=False
    )
    #: RLock, а не Lock: методы диагностики (`snapshot`) вызываются и внутри
    #: уже захваченной секции, чтобы ошибка несла актуальное состояние бюджета.
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)

    # --- публичный интерфейс ------------------------------------------------

    def acquire(self) -> None:
        """Занимает слот квоты. Блокирует минутное окно, суточный лимит — стоп.

        Raises:
            QuotaExhaustedError: суточный лимит исчерпан, провайдер сообщил
                нулевой остаток, или ожидание окна превышает `max_wait_seconds`.
        """
        with self._lock:
            self._roll_day()
            self._raise_if_day_exhausted()
            self._raise_if_provider_exhausted()

            waited = 0.0
            while True:
                now = self._clock_now()
                self._evict_minute(now)
                if len(self._minute_window) < self._effective_minute_limit():
                    break
                wait = self._minute_window[0] + 60.0 - now
                wait = max(wait, 0.001)
                if waited + wait > self.max_wait_seconds:
                    raise QuotaExhaustedError(
                        scope="minute",
                        retry_after_seconds=wait,
                        snapshot=self.snapshot(),
                    )
                self.sleeper(wait)
                waited += wait

            self._minute_window.append(self._clock_now())
            self._day_used += 1
            self._journal_append(event="acquire", endpoint_kind=None, status=None)

    def record_headers(
        self,
        headers: Mapping[str, str],
        *,
        endpoint_kind: str | None = None,
        http_status: int | None = None,
    ) -> None:
        """Читает остаток квоты из заголовков ответа и пишет журнал."""
        lowered = {key.lower(): value for key, value in headers.items()}
        minute_remaining = _parse_int_header(lowered.get(self.policy.minute_remaining_header))
        day_remaining = _parse_int_header(lowered.get(self.policy.day_remaining_header))
        with self._lock:
            if minute_remaining is not None:
                self._provider_minute_remaining = minute_remaining
            if day_remaining is not None:
                self._provider_day_remaining = day_remaining
            self._journal_append(
                event="response",
                endpoint_kind=endpoint_kind,
                status=http_status,
                remaining_minute=minute_remaining,
                remaining_day=day_remaining,
            )

    def snapshot(self) -> QuotaSnapshot:
        """Снимок состояния бюджета."""
        with self._lock:
            self._roll_day()
            now = self._clock_now()
            self._evict_minute(now)
            minute_used = len(self._minute_window)
            return QuotaSnapshot(
                per_minute=self.policy.per_minute,
                per_day=self.policy.per_day,
                minute_used=minute_used,
                day_used=self._day_used,
                minute_remaining=max(0, self._effective_minute_limit() - minute_used),
                day_remaining=max(0, self._effective_day_limit() - self._day_used),
                provider_minute_remaining=self._provider_minute_remaining,
                provider_day_remaining=self._provider_day_remaining,
            )

    def journal(self) -> tuple[dict[str, Any], ...]:
        """Журнал headers/событий (для `ingestion_run.quota_headers`)."""
        with self._lock:
            return tuple(entry.as_dict() for entry in self._journal)

    def journal_payload(self, *, source_id: str) -> dict[str, Any]:
        """JSONB-полезная нагрузка журнала для записи в прогон."""
        snapshot = self.snapshot()
        return {
            "source_id": source_id,
            "per_minute": snapshot.per_minute,
            "per_day": snapshot.per_day,
            "minute_used": snapshot.minute_used,
            "day_used": snapshot.day_used,
            "provider_minute_remaining": snapshot.provider_minute_remaining,
            "provider_day_remaining": snapshot.provider_day_remaining,
            "entries": list(self.journal()),
        }

    # --- внутреннее ---------------------------------------------------------

    def _clock_now(self) -> float:
        return self.clock()

    def _roll_day(self) -> None:
        key = self.wall_clock().astimezone(UTC).date().isoformat()
        if key != self._day_key:
            self._day_key = key
            self._day_used = 0
            # Провайдерский остаток относился к прошлым суткам.
            self._provider_day_remaining = None

    def _evict_minute(self, now: float) -> None:
        while self._minute_window and now - self._minute_window[0] >= 60.0:
            self._minute_window.popleft()

    def _effective_minute_limit(self) -> int:
        limit = self.policy.per_minute
        if self._provider_minute_remaining is not None:
            limit = min(limit, len(self._minute_window) + self._provider_minute_remaining)
        return max(limit, 1)

    def _effective_day_limit(self) -> int:
        limit = self.policy.per_day
        if self._provider_day_remaining is not None:
            limit = min(limit, self._day_used + self._provider_day_remaining)
        return max(limit, 0)

    def _raise_if_day_exhausted(self) -> None:
        if self._day_used >= self._effective_day_limit():
            raise QuotaExhaustedError(scope="day", retry_after_seconds=None, snapshot=self.snapshot())

    def _raise_if_provider_exhausted(self) -> None:
        if self._provider_minute_remaining is not None and self._provider_minute_remaining <= 0:
            raise QuotaExhaustedError(
                scope="minute", retry_after_seconds=60.0, snapshot=self.snapshot()
            )
        if self._provider_day_remaining is not None and self._provider_day_remaining <= 0:
            raise QuotaExhaustedError(scope="day", retry_after_seconds=None, snapshot=self.snapshot())

    def _journal_append(
        self,
        *,
        event: str,
        endpoint_kind: str | None,
        status: int | None,
        remaining_minute: int | None = None,
        remaining_day: int | None = None,
    ) -> None:
        self._journal.append(
            _JournalEntry(
                at=self.wall_clock().astimezone(UTC),
                event=event,
                endpoint_kind=endpoint_kind,
                http_status=status,
                remaining_minute=(
                    remaining_minute
                    if remaining_minute is not None
                    else self._provider_minute_remaining
                ),
                remaining_day=(
                    remaining_day if remaining_day is not None else self._provider_day_remaining
                ),
            )
        )
