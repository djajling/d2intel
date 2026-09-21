"""Общие помощники тестов ING-001: мок-транспорт, часы, синтетические ответы.

Здесь нет ни одного реального сетевого вызова: `httpx.MockTransport` полностью
подменяет транспорт, а часы и sleeper инжектируются, чтобы throttle и backoff
проверялись без ожидания.
"""

from __future__ import annotations

import random
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx
import pytest

from d2intel.ingestion.contracts import OPENDOTA_BASE_URL, QuotaPolicy
from d2intel.ingestion.opendota_client import OpenDotaClient
from d2intel.ingestion.quota import QuotaBudget

Handler = Callable[[httpx.Request], httpx.Response]


class FakeClock:
    """Монотонные часы + sleeper, продвигающий их (без реального ожидания)."""

    def __init__(self, start: float = 0.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def monotonic(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeWallClock:
    """UTC-часы для суточной границы квоты (управляемые вручную)."""

    def __init__(self, start: datetime | None = None) -> None:
        self.now = start or datetime(2026, 9, 21, 12, 0, tzinfo=UTC)

    def __call__(self) -> datetime:
        return self.now

    def advance(self, delta: timedelta) -> None:
        self.now += delta


@dataclass
class RecordedRequests:
    """Записанные запросы: путь, параметры, timeout-расширение."""

    requests: list[httpx.Request] = field(default_factory=list)

    @property
    def count(self) -> int:
        return len(self.requests)

    def params(self, index: int) -> dict[str, str]:
        return dict(self.requests[index].url.params)

    def timeouts(self, index: int) -> dict[str, float]:
        return dict(self.requests[index].extensions.get("timeout", {}))

    def paths(self) -> list[str]:
        return [request.url.path for request in self.requests]


def recording_handler(
    inner: Handler, recorded: RecordedRequests
) -> Handler:
    """Оборачивает handler, записывая каждый запрос."""

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.requests.append(request)
        return inner(request)

    return handler


def scripted_handler(
    responses: list[httpx.Response], recorded: RecordedRequests | None = None
) -> Handler:
    """Отдаёт ответы по порядку; после исчерпания — последний."""
    queue = list(responses)

    def handler(request: httpx.Request) -> httpx.Response:
        if recorded is not None:
            recorded.requests.append(request)
        if len(queue) > 1:
            return queue.pop(0)
        return queue[0]

    return handler


def make_client(
    handler: Handler,
    *,
    clock: FakeClock | None = None,
    now: Callable[[], datetime] | None = None,
    quota: QuotaBudget | None = None,
    rng: random.Random | None = None,
    api_key: str | None = None,
    **kwargs: Any,
) -> OpenDotaClient:
    """Клиент OpenDota на мок-транспорте (сеть не используется).

    `clock` — монотонные часы + sleeper (throttle/backoff без ожидания).
    `now` — UTC-часы клиента (`observed_at`, TTL кэша); по умолчанию реальные.
    """
    transport = httpx.MockTransport(handler)
    http_client = httpx.Client(transport=transport, base_url=OPENDOTA_BASE_URL)
    fake_clock = clock or FakeClock()
    client_kwargs: dict[str, Any] = dict(kwargs)
    if now is not None:
        client_kwargs["clock"] = now
    return OpenDotaClient(
        http_client=http_client,
        quota=quota,
        sleeper=fake_clock.sleep,
        rng=rng or random.Random(1234),
        api_key=api_key,
        **client_kwargs,
    )


# --- синтетические ответы OpenDota -------------------------------------------


def pro_match_row(
    match_id: int,
    *,
    start_time: int = 1_790_006_825,
    radiant_team_id: int | None = 9823272,
    dire_team_id: int | None = 36,
    **overrides: Any,
) -> dict[str, Any]:
    """Запись `/api/proMatches` (форма из OPENDOTA_API_MAP.md §2.1)."""
    row: dict[str, Any] = {
        "match_id": match_id,
        "duration": 1809,
        "start_time": start_time,
        "radiant_team_id": radiant_team_id,
        "radiant_name": "Team Yandex",
        "dire_team_id": dire_team_id,
        "dire_name": "Natus Vincere",
        "leagueid": 20279,
        "league_name": "PGL Wallachia 2026 Season 9",
        "series_id": 1145136,
        "series_type": 1,
        "radiant_score": 42,
        "dire_score": 15,
        "radiant_win": True,
        "version": 22,
    }
    row.update(overrides)
    return row


def explorer_match_row(match_id: int, **overrides: Any) -> dict[str, Any]:
    """Строка таблицы `matches` (форма из OPENDOTA_API_MAP.md §2.3)."""
    row: dict[str, Any] = {
        "match_id": match_id,
        "series_id": 1145136,
        "series_type": 1,
        "leagueid": 20279,
        "start_time": 1_790_006_825,
        "radiant_win": True,
        "duration": 1809,
        "game_mode": 2,
        "lobby_type": 1,
        "cluster": 191,
        "radiant_team_id": 9823272,
        "dire_team_id": 36,
    }
    row.update(overrides)
    return row


def picks_bans_row(match_id: int, *, is_pick: bool = False, ord_: int = 0) -> dict[str, Any]:
    """Строка таблицы `picks_bans` (форма из OPENDOTA_API_MAP.md §2.3)."""
    return {"match_id": match_id, "is_pick": is_pick, "hero_id": 145, "team": 0, "ord": ord_}


def patch_constant_row(patch_id: int, name: str = "7.41", date: str = "2026-03-24") -> dict[str, Any]:
    return {"id": patch_id, "name": name, "date": date}


def json_response(payload: Any, *, status_code: int = 200, headers: dict[str, str] | None = None) -> httpx.Response:
    return httpx.Response(status_code, json=payload, headers=headers or {})


# --- фикстуры ----------------------------------------------------------------


@pytest.fixture
def fake_clock() -> FakeClock:
    return FakeClock()


@pytest.fixture
def fake_wall_clock() -> FakeWallClock:
    return FakeWallClock()


@pytest.fixture
def recorded() -> RecordedRequests:
    return RecordedRequests()


@pytest.fixture
def small_quota(fake_clock: FakeClock, fake_wall_clock: FakeWallClock) -> QuotaBudget:
    """Бюджет с маленькими лимитами: тесты не ждут реальное окно."""
    return QuotaBudget(
        QuotaPolicy(per_minute=3, per_day=10),
        clock=fake_clock.monotonic,
        wall_clock=fake_wall_clock,
        sleeper=fake_clock.sleep,
    )


@pytest.fixture
def default_quota(fake_clock: FakeClock, fake_wall_clock: FakeWallClock) -> QuotaBudget:
    """Бюджет с реальными лимитами free-tier (60/мин, 3 000/день)."""
    return QuotaBudget(
        QuotaPolicy(),
        clock=fake_clock.monotonic,
        wall_clock=fake_wall_clock,
        sleeper=fake_clock.sleep,
    )
