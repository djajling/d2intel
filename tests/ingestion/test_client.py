"""ING-001 — тесты HTTP-клиента: throttle, retry, timeout, пагинация, кэш, секреты.

Все ответы отдаёт `httpx.MockTransport`; реальных запросов к OpenDota нет.
"""

from __future__ import annotations

import json
import logging
from datetime import timedelta

import httpx
import pytest

from d2intel.ingestion.contracts import (
    OPENDOTA_BASE_URL,
    EndpointKind,
    QuotaPolicy,
    RetrievalStatus,
)
from d2intel.ingestion.errors import (
    AuthError,
    MalformedResponseError,
    QuotaExhaustedError,
    RateLimitedError,
    SourceRequestError,
    SourceUnavailableError,
)
from d2intel.ingestion.opendota_client import OpenDotaClient, resume_start
from d2intel.ingestion.quota import QuotaBudget
from d2intel.ingestion.retry import RetryPolicy
from d2intel.ingestion.validation import QuarantineReason
from tests.ingestion.conftest import (
    FakeClock,
    FakeWallClock,
    RecordedRequests,
    explorer_match_row,
    json_response,
    make_client,
    patch_constant_row,
    picks_bans_row,
    pro_match_row,
    recording_handler,
    scripted_handler,
)

# --- форма batch -------------------------------------------------------------


def test_batch_contains_raw_payload_and_metadata(recorded: RecordedRequests) -> None:
    """AC #1: batch несёт provider ids, сырой payload, время наблюдения и метаданные."""
    rows = [pro_match_row(9009924057), pro_match_row(9009924056)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler)

    batch = client.fetch_pro_matches()

    assert batch.source_id == "opendota"
    assert batch.endpoint_kind is EndpointKind.PRO_MATCHES
    assert batch.retrieval_status is RetrievalStatus.OK
    assert [record.provider_entity_id for record in batch.records] == ["9009924057", "9009924056"]
    assert batch.raw_payload == rows  # сырьё как есть
    assert batch.request.http_status == 200
    assert batch.request.attempts == 1
    assert batch.request.endpoint_kind is EndpointKind.PRO_MATCHES
    assert batch.request.fingerprint
    assert batch.request.quota_headers == {}
    assert batch.completeness.is_complete is True
    assert batch.content_hash
    assert batch.observed_at.tzinfo is not None


def test_request_timeout_is_bounded(recorded: RecordedRequests) -> None:
    """AC #2: на каждый запрос выставлен конечный timeout."""
    handler = recording_handler(lambda request: json_response([pro_match_row(1)]), recorded)
    client = make_client(handler)

    client.fetch_pro_matches()

    timeouts = recorded.timeouts(0)
    assert set(timeouts) == {"connect", "read", "write", "pool"}
    for value in timeouts.values():
        assert value is not None
        assert 0 < value < 120


def test_empty_page_is_marked_as_empty_not_complete(recorded: RecordedRequests) -> None:
    """Пустой ответ — не «матчей нет» и не успех полного охвата."""
    handler = recording_handler(lambda request: json_response([]), recorded)
    client = make_client(handler)

    batch = client.fetch_pro_matches()

    assert batch.retrieval_status is RetrievalStatus.EMPTY
    assert batch.records == ()
    assert batch.completeness.empty_response is True
    assert batch.completeness.is_complete is False
    assert batch.next_cursor is None


def test_schema_drift_goes_to_quarantine(recorded: RecordedRequests) -> None:
    """AC #8: schema drift фиксируется явно, а не молча."""
    drifted = [{"match_id": 1, "start_time": 1_790_006_825, "radiant_team_id": 1, "dire_team_id": 2}]
    handler = recording_handler(lambda request: json_response(drifted), recorded)
    client = make_client(handler)

    batch = client.fetch_pro_matches()

    assert batch.records == ()
    assert batch.completeness.missing_fields
    assert "series_id" in batch.completeness.missing_fields
    assert batch.quarantined[0].reason_code == QuarantineReason.SCHEMA_DRIFT
    assert "schema_drift" in batch.completeness.notes


def test_malformed_json_body_raises(recorded: RecordedRequests) -> None:
    handler = recording_handler(
        lambda request: httpx.Response(200, text="<html>not json</html>"), recorded
    )
    client = make_client(handler)

    with pytest.raises(MalformedResponseError):
        client.fetch_pro_matches()


# --- throttle и retry --------------------------------------------------------


def test_client_uses_shared_quota_for_all_endpoints(
    recorded: RecordedRequests, default_quota: QuotaBudget
) -> None:
    """AC #2: один бюджет источника на все endpoints."""
    handler = recording_handler(
        lambda request: json_response(
            [pro_match_row(1)] if request.url.path.endswith("proMatches") else []
        ),
        recorded,
    )
    client = make_client(handler, quota=default_quota)

    client.fetch_pro_matches()
    client.fetch_patch_constants()

    assert default_quota.snapshot().day_used == 2
    assert client.quota is default_quota


def test_quota_exhaustion_prevents_request(recorded: RecordedRequests) -> None:
    """AC #4: при исчерпанном бюджете запрос не отправляется вовсе."""
    handler = recording_handler(lambda request: json_response([]), recorded)
    exhausted = QuotaBudget(QuotaPolicy(per_minute=60, per_day=0))
    client = make_client(handler, quota=exhausted)

    with pytest.raises(QuotaExhaustedError) as excinfo:
        client.fetch_pro_matches()

    assert excinfo.value.scope == "day"
    assert recorded.count == 0


def test_transient_5xx_is_retried_then_succeeds(
    recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    """AC #3: transient 5xx повторяется с backoff, затем запрос удаётся."""
    handler = scripted_handler(
        [
            httpx.Response(500, text="boom"),
            httpx.Response(503, text="boom"),
            json_response([pro_match_row(1)]),
        ],
        recorded,
    )
    client = make_client(handler, clock=fake_clock, retry_policy=RetryPolicy(jitter_ratio=0.0))

    batch = client.fetch_pro_matches()

    assert batch.records
    assert batch.request.attempts == 3
    assert recorded.count == 3
    assert fake_clock.sleeps == pytest.approx([0.5, 1.0])


def test_transient_failures_exhaust_budget_and_mark_source_unavailable(
    recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    """AC #9: исчерпание retry на transient = source outage, а не тихий пустой ответ."""
    handler = scripted_handler([httpx.Response(500, text="boom")], recorded)
    client = make_client(
        handler,
        clock=fake_clock,
        retry_policy=RetryPolicy(max_attempts=3, jitter_ratio=0.0),
    )

    with pytest.raises(SourceUnavailableError) as excinfo:
        client.fetch_pro_matches()

    assert excinfo.value.attempts == 3
    assert excinfo.value.last_status == 500
    assert recorded.count == 3


def test_rate_limit_respects_retry_after(
    recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    """AC #3: 429 обрабатывается по Retry-After, а не «наугад»."""
    handler = scripted_handler(
        [
            httpx.Response(429, headers={"Retry-After": "7"}, text="slow down"),
            json_response([pro_match_row(1)]),
        ],
        recorded,
    )
    client = make_client(handler, clock=fake_clock, retry_policy=RetryPolicy(jitter_ratio=0.0))

    batch = client.fetch_pro_matches()

    assert batch.records
    assert fake_clock.sleeps == [pytest.approx(7.0)]


def test_rate_limit_with_too_long_retry_after_stops(
    recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    """Если провайдер просит паузу больше бюджета — остановка без ожидания."""
    handler = scripted_handler(
        [httpx.Response(429, headers={"Retry-After": "9999"}, text="slow down")], recorded
    )
    client = make_client(handler, clock=fake_clock, retry_policy=RetryPolicy(jitter_ratio=0.0))

    with pytest.raises(RateLimitedError) as excinfo:
        client.fetch_pro_matches()

    assert excinfo.value.retry_after_seconds == pytest.approx(9999.0)
    assert recorded.count == 1
    assert fake_clock.sleeps == []


def test_rate_limit_without_retry_after_uses_backoff(
    recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    handler = scripted_handler(
        [httpx.Response(429, text="slow down"), json_response([pro_match_row(1)])], recorded
    )
    client = make_client(handler, clock=fake_clock, retry_policy=RetryPolicy(jitter_ratio=0.0))

    client.fetch_pro_matches()

    assert fake_clock.sleeps == [pytest.approx(0.5)]


@pytest.mark.parametrize("status", [401, 403])
def test_auth_errors_stop_without_retry(
    status: int, recorded: RecordedRequests, fake_clock: FakeClock
) -> None:
    """AC #3: auth/permission — остановка, а не бесконечный retry."""
    handler = scripted_handler([httpx.Response(status, text="forbidden")], recorded)
    client = make_client(handler, clock=fake_clock)

    with pytest.raises(AuthError) as excinfo:
        client.fetch_pro_matches()

    assert excinfo.value.status_code == status
    assert recorded.count == 1
    assert fake_clock.sleeps == []


def test_permanent_4xx_stops_without_retry(recorded: RecordedRequests, fake_clock: FakeClock) -> None:
    handler = scripted_handler([httpx.Response(400, text="bad request")], recorded)
    client = make_client(handler, clock=fake_clock)

    with pytest.raises(SourceRequestError):
        client.fetch_pro_matches()

    assert recorded.count == 1
    assert fake_clock.sleeps == []


def test_network_error_is_transient_and_retried(recorded: RecordedRequests, fake_clock: FakeClock) -> None:
    attempts = {"count": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        recorded.requests.append(request)
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise httpx.ConnectTimeout("timeout")
        return json_response([pro_match_row(1)])

    client = make_client(handler, clock=fake_clock, retry_policy=RetryPolicy(jitter_ratio=0.0))
    batch = client.fetch_pro_matches()

    assert batch.records
    assert recorded.count == 2


# --- 404 и точечные запросы --------------------------------------------------


def test_missing_match_returns_not_found_batch(recorded: RecordedRequests, fake_clock: FakeClock) -> None:
    """404 не тарифицируется и не ретраится: это факт «записи нет»."""
    handler = scripted_handler([httpx.Response(404, json={"error": "not found"})], recorded)
    client = make_client(handler, clock=fake_clock)

    batch = client.fetch_match(123)

    assert batch.retrieval_status is RetrievalStatus.NOT_FOUND
    assert batch.records == ()
    assert batch.completeness.is_complete is False
    assert recorded.count == 1
    assert fake_clock.sleeps == []


def test_match_detail_is_fetched_pointwise(recorded: RecordedRequests) -> None:
    detail = {
        "match_id": 9009924057,
        "start_time": 1_790_006_825,
        "duration": 1809,
        "radiant_win": True,
        "game_mode": 2,
        "lobby_type": 1,
        "patch": 60,
        "version": 22,
        "cluster": 191,
        "players": [],
        "draft_timings": [{"order": 0}],
    }
    handler = recording_handler(lambda request: json_response(detail), recorded)
    client = make_client(handler)

    batch = client.fetch_match(9009924057)

    assert recorded.paths() == ["/api/matches/9009924057"]
    assert batch.records[0].provider_entity_id == "9009924057"


def test_invalid_match_id_is_rejected_before_request(recorded: RecordedRequests) -> None:
    client = make_client(recording_handler(lambda request: json_response({}), recorded))
    with pytest.raises(ValueError):
        client.fetch_match(0)
    assert recorded.count == 0


# --- пагинация и overlap -----------------------------------------------------


def test_pagination_follows_next_cursor(recorded: RecordedRequests) -> None:
    """AC #6: пагинация по курсору; next_cursor = минимальный match_id страницы.

    Конец обхода определяется пустой страницей: клиент не догадывается о
    последней странице, а получает подтверждение от источника.
    """
    pages = {
        None: [pro_match_row(100), pro_match_row(90)],
        90: [pro_match_row(80), pro_match_row(70)],
        70: [pro_match_row(60)],
        60: [],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("less_than_match_id")
        key = int(cursor) if cursor is not None else None
        return json_response(pages[key])

    client = make_client(recording_handler(handler, recorded))

    batches = list(client.iter_pro_matches(max_pages=5, overlap_pages=0))

    assert len(batches) == 4
    assert [batch.next_cursor for batch in batches] == ["90", "70", "60", None]
    assert batches[-1].retrieval_status is RetrievalStatus.EMPTY
    assert [request.url.params.get("less_than_match_id") for request in recorded.requests] == [
        None,
        "90",
        "70",
        "60",
    ]
    assert batches[-1].completeness.truncated is False


def test_pagination_stops_when_budget_exhausted(recorded: RecordedRequests) -> None:
    """Ограничение по страницам не молчит: последняя страница помечается truncated."""
    pages = {
        None: [pro_match_row(100)],
        100: [pro_match_row(90)],
        90: [pro_match_row(80)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("less_than_match_id")
        key = int(cursor) if cursor is not None else None
        return json_response(pages[key])

    client = make_client(recording_handler(handler, recorded))

    batches = list(client.iter_pro_matches(max_pages=1, overlap_pages=0))

    assert len(batches) == 1
    assert batches[0].completeness.truncated is True
    assert batches[0].completeness.is_complete is False
    assert "page_budget_exhausted" in batches[0].completeness.notes
    assert recorded.count == 1


def test_overlap_refetches_previous_page(recorded: RecordedRequests) -> None:
    """AC #6: overlap-окно повторно наблюдает последнюю страницу (поздние исправления)."""
    pages = {
        None: [pro_match_row(100), pro_match_row(90)],
        90: [pro_match_row(80), pro_match_row(70)],
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("less_than_match_id")
        key = int(cursor) if cursor is not None else None
        return json_response(pages[key])

    client = make_client(recording_handler(handler, recorded))

    first = list(client.iter_pro_matches(max_pages=2, overlap_pages=0))
    cursor_payload = first[-1].cursor_payload
    assert [page["start"] for page in cursor_payload["pages"]] == [None, 90]

    recorded.requests.clear()
    resumed = list(
        client.iter_pro_matches(max_pages=1, cursor_payload=cursor_payload, overlap_pages=1)
    )

    # Повторно наблюдается страница, начинавшаяся с курсора 90.
    assert recorded.requests[0].url.params.get("less_than_match_id") == "90"
    assert resumed[0].cursor_payload["page_start"] == 90


def test_resume_start_variants() -> None:
    pages = [{"start": None, "end": 90}, {"start": 90, "end": 70}, {"start": 70, "end": 60}]
    assert resume_start([], 1) is None
    assert resume_start(pages, 0) == 60
    assert resume_start(pages, 1) == 70
    assert resume_start(pages, 2) == 90
    assert resume_start(pages, 9) is None


def test_iter_pro_matches_rejects_zero_pages() -> None:
    client = make_client(lambda request: json_response([]))
    with pytest.raises(ValueError):
        list(client.iter_pro_matches(max_pages=0))


# --- explorer ----------------------------------------------------------------


def test_explorer_matches_builds_bounded_sql(recorded: RecordedRequests) -> None:
    """SQL строится из фиксированного allowlist колонок и валидированных чисел."""
    rows = [explorer_match_row(1)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler)

    batch = client.fetch_explorer_matches(since_start_time=1_700_000_000, limit=1000)

    sql = recorded.params(0)["sql"]
    assert sql.startswith("SELECT match_id, series_id")
    assert "FROM matches" in sql
    assert "start_time >= 1700000000" in sql
    assert "LIMIT 1000 OFFSET 0" in sql
    assert batch.records[0].provider_entity_id == "1"


def test_explorer_pagination_uses_offset(recorded: RecordedRequests) -> None:
    rows = [explorer_match_row(index) for index in range(1, 4)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler)

    batch = client.fetch_explorer_matches(since_start_time=1_700_000_000, limit=3, offset=6)

    assert batch.next_cursor == "9"


def test_explorer_rejects_unknown_columns(recorded: RecordedRequests) -> None:
    """Свободный SQL не принимается: колонки только из allowlist."""
    client = make_client(recording_handler(lambda request: json_response([]), recorded))
    with pytest.raises(ValueError):
        client.fetch_explorer_matches(
            since_start_time=1_700_000_000, columns=("match_id; DROP TABLE raw_payload",)
        )
    assert recorded.count == 0


@pytest.mark.parametrize("bad", [0, -1, "1700000000"])
def test_explorer_rejects_unvalidated_bounds(bad: object, recorded: RecordedRequests) -> None:
    client = make_client(recording_handler(lambda request: json_response([]), recorded))
    with pytest.raises(ValueError):
        client.fetch_explorer_matches(since_start_time=bad)  # type: ignore[arg-type]
    assert recorded.count == 0


def test_explorer_picks_bans_is_not_offset_paginated(recorded: RecordedRequests) -> None:
    rows = [picks_bans_row(1), picks_bans_row(1, is_pick=True, ord_=1)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler)

    batch = client.fetch_explorer_picks_bans(match_ids=[1, 2])

    assert "FROM picks_bans" in recorded.params(0)["sql"]
    assert batch.next_cursor is None


def test_explorer_picks_bans_requires_match_ids(recorded: RecordedRequests) -> None:
    client = make_client(recording_handler(lambda request: json_response([]), recorded))
    with pytest.raises(ValueError):
        client.fetch_explorer_picks_bans(match_ids=[])


# --- кэш справочника патчей --------------------------------------------------


def test_patch_constants_are_cached(recorded: RecordedRequests) -> None:
    """AC #4 (cache): повторное чтение справочника не тратит квоту."""
    rows = [patch_constant_row(60)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler)

    first = client.fetch_patch_constants()
    second = client.fetch_patch_constants()

    assert recorded.count == 1
    assert second.observed_at == first.observed_at  # время наблюдения не подменяется
    assert "served_from_cache" in second.completeness.notes


def test_patch_constants_refresh_bypasses_cache(recorded: RecordedRequests) -> None:
    rows = [patch_constant_row(60)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler)

    client.fetch_patch_constants()
    client.fetch_patch_constants(refresh=True)

    assert recorded.count == 2


def test_patch_constants_cache_expires(recorded: RecordedRequests, fake_wall_clock: FakeWallClock) -> None:
    """По истечении TTL справочник перезапрашивается (и это видно по observed_at)."""
    rows = [patch_constant_row(60)]
    handler = recording_handler(lambda request: json_response(rows), recorded)
    client = make_client(handler, now=fake_wall_clock, patch_cache_ttl_seconds=60.0)

    first = client.fetch_patch_constants()
    fake_wall_clock.advance(timedelta(seconds=3600))
    second = client.fetch_patch_constants()

    assert recorded.count == 2
    assert second.observed_at > first.observed_at
    assert "served_from_cache" not in second.completeness.notes


# --- секреты -----------------------------------------------------------------


def test_api_key_is_used_but_never_stored(
    monkeypatch: pytest.MonkeyPatch, recorded: RecordedRequests, caplog: pytest.LogCaptureFixture
) -> None:
    """AC #6: ключ уходит провайдеру, но отсутствует в raw, метаданных и логах."""
    secret = "s3cr3t-opendota-key"
    monkeypatch.setenv("OPENDOTA_API_KEY", secret)
    rows = [pro_match_row(1)]
    handler = recording_handler(lambda request: json_response(rows), recorded)

    with caplog.at_level(logging.DEBUG, logger="d2intel.ingestion"):
        client = make_client(handler)
        batch = client.fetch_pro_matches()

    assert client.api_key_used is True
    assert recorded.params(0)["api_key"] == secret  # ключ действительно передан
    assert secret not in json.dumps(batch.raw_payload)
    assert secret not in json.dumps(batch.request.params)
    assert secret not in json.dumps(batch.request.quota_headers)
    assert secret not in batch.request.fingerprint
    assert secret not in caplog.text
    assert secret not in json.dumps(client.quota.journal_payload(source_id="opendota"))


def test_secret_is_redacted_from_error_details(
    monkeypatch: pytest.MonkeyPatch, recorded: RecordedRequests
) -> None:
    """Если провайдер эхом вернёт ключ в теле ошибки — он будет вырезан."""
    secret = "echoed-key"
    monkeypatch.setenv("OPENDOTA_API_KEY", secret)
    handler = recording_handler(
        lambda request: httpx.Response(400, text=f"bad api_key={secret}"), recorded
    )
    client = make_client(handler)

    with pytest.raises(SourceRequestError) as excinfo:
        client.fetch_pro_matches()

    assert secret not in str(excinfo.value)
    assert "***" in str(excinfo.value)


def test_fingerprint_does_not_depend_on_api_key(recorded: RecordedRequests) -> None:
    rows = [pro_match_row(1)]
    handler = recording_handler(lambda request: json_response(rows), recorded)

    without_key = make_client(handler).fetch_pro_matches()
    with_key = make_client(handler, api_key="a-key").fetch_pro_matches()

    assert without_key.request.fingerprint == with_key.request.fingerprint
    assert without_key.content_hash == with_key.content_hash


def test_client_does_not_expose_key_value(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("OPENDOTA_API_KEY", "hidden")
    client = make_client(lambda request: json_response([]))
    assert not hasattr(client, "api_key")
    assert client.api_key_used is True


def test_client_does_not_close_external_http_client() -> None:
    """Внешний http-клиент принадлежит вызывающему — клиент его не закрывает."""
    transport = httpx.MockTransport(lambda request: json_response([]))
    external = httpx.Client(transport=transport, base_url=OPENDOTA_BASE_URL)
    client = OpenDotaClient(http_client=external)

    client.close()

    assert external.is_closed is False
    external.close()
