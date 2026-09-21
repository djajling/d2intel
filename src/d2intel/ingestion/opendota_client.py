"""ING-001 — HTTP-клиент OpenDota (ARCHITECTURE.md §3).

Клиент делает ровно четыре вещи: bounded-запрос, throttle/retry, разбор формы
ответа (без нормализации) и возврат batch с сырым payload и метаданными.

Что гарантируется:

* **bounded timeout** на каждую фазу запроса (`TimeoutPolicy`), значение не `None`;
* **throttle**: общий `QuotaBudget` источника (60/мин, 3 000/день) для всех endpoints;
* **retry**: exponential backoff + jitter для transient, уважение `Retry-After`,
  немедленная остановка на 401/403 без повторов;
* **секреты**: API-ключ читается только из окружения, не попадает ни в raw, ни в
  log, ни в request metadata; отпечаток запроса от ключа не зависит;
* **pagination + overlap**: курсор по `match_id` и повторное наблюдение
  последних N страниц для поздних исправлений;
* **cache**: справочник патчей кэшируется с сохранением исходного `observed_at`.

Чего клиент не делает: не нормализует сущности, не вычисляет map index и patch
матча, не выставляет `available_at` — это `DATA-001` и ядро временной семантики.
"""

from __future__ import annotations

import json
import logging
import os
import random
import time
from collections.abc import Callable, Iterator, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

import httpx

from d2intel.ingestion.contracts import (
    OPENDOTA_CONTRACT,
    CompletenessFlags,
    EndpointKind,
    FetchBatch,
    RequestMetadata,
    RetrievalStatus,
    SourceContract,
    compute_content_hash,
    compute_request_fingerprint,
    redact_params,
    utc_now,
)
from d2intel.ingestion.errors import (
    AuthError,
    MalformedResponseError,
    RateLimitedError,
    SourceRequestError,
    SourceUnavailableError,
)
from d2intel.ingestion.quota import QuotaBudget
from d2intel.ingestion.retry import (
    ErrorClass,
    RetryPolicy,
    classify_exception,
    classify_status,
    next_delay,
    parse_retry_after,
    retry_after_exceeds_budget,
    should_retry,
)
from d2intel.ingestion.validation import (
    MATCHES_TABLE_COLUMNS,
    PICKS_BANS_COLUMNS,
    validate_explorer_matches,
    validate_explorer_picks_bans,
    validate_match_detail,
    validate_patch_constants,
    validate_pro_matches,
)

LOGGER = logging.getLogger("d2intel.ingestion.opendota")

#: Сколько последних страниц помнить для overlap-окна.
MAX_TRACKED_PAGES = 10
#: Предел длины текста ошибки провайдера в detail (без секретов).
MAX_DETAIL_CHARS = 200


@dataclass(frozen=True)
class _HttpResult:
    """Успешный (или допустимо-404) ответ + метаданные + время наблюдения."""

    response: httpx.Response
    metadata: RequestMetadata
    observed_at: datetime


def resume_start(pages: Sequence[Mapping[str, Any]], overlap_pages: int) -> int | None:
    """С какой точки возобновлять пагинацию с учётом overlap-окна.

    `overlap_pages <= 0` — строго после watermark (без повторного наблюдения).
    `overlap_pages = N` — повторно наблюдать последние N страниц (поздние
    исправления в уже увиденных записях).
    """
    if not pages:
        return None
    if overlap_pages <= 0:
        end = pages[-1].get("end")
        return int(end) if end is not None else None
    index = max(0, len(pages) - overlap_pages)
    start = pages[index].get("start")
    return int(start) if start is not None else None


def _merge_pages(
    pages: Sequence[Mapping[str, Any]],
    *,
    page_start: int | None,
    page_end: int | None,
    fetched_at: datetime,
) -> list[dict[str, Any]]:
    merged = [dict(page) for page in pages]
    if page_end is not None:
        merged.append(
            {"start": page_start, "end": page_end, "fetched_at": fetched_at.isoformat()}
        )
    return merged[-MAX_TRACKED_PAGES:]


class OpenDotaClient:
    """Клиент OpenDota: sync-once retrieval с throttle, retry и пагинацией."""

    def __init__(
        self,
        *,
        contract: SourceContract = OPENDOTA_CONTRACT,
        http_client: httpx.Client | None = None,
        quota: QuotaBudget | None = None,
        retry_policy: RetryPolicy | None = None,
        sleeper: Callable[[float], None] = time.sleep,
        clock: Callable[[], datetime] = utc_now,
        rng: random.Random | None = None,
        api_key: str | None = None,
        patch_cache_ttl_seconds: float = 86_400.0,
        logger: logging.Logger | None = None,
    ) -> None:
        self._contract = contract
        self._retry_policy = retry_policy or RetryPolicy()
        self._sleeper = sleeper
        self._clock = clock
        self._rng = rng or random.Random()
        self._logger = logger or LOGGER
        self._quota = quota or QuotaBudget(contract.quota_policy, sleeper=sleeper)
        self._patch_cache_ttl_seconds = patch_cache_ttl_seconds
        self._patch_cache: FetchBatch | None = None
        self._owns_http_client = http_client is None
        self._http = http_client or httpx.Client(
            base_url=contract.base_url,
            timeout=contract.timeout.to_httpx(),
            headers={"User-Agent": f"d2intel/{contract.adapter_version} (personal research)"},
        )
        # Ключ не обязателен: free-tier работает без него. Значение живёт только
        # в памяти процесса и никогда не пишется в raw/log/метаданные.
        self._api_key = api_key if api_key is not None else self._read_api_key()

    # --- жизненный цикл -----------------------------------------------------

    def close(self) -> None:
        if self._owns_http_client:
            self._http.close()

    def __enter__(self) -> OpenDotaClient:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.close()

    # --- свойства -----------------------------------------------------------

    @property
    def contract(self) -> SourceContract:
        return self._contract

    @property
    def quota(self) -> QuotaBudget:
        return self._quota

    @property
    def api_key_used(self) -> bool:
        """Только признак факта наличия ключа — не значение."""
        return bool(self._api_key)

    # --- endpoints ----------------------------------------------------------

    def fetch_pro_matches(
        self,
        *,
        less_than_match_id: int | None = None,
        tracked_pages: Sequence[Mapping[str, Any]] = (),
    ) -> FetchBatch:
        """Одна страница `/api/proMatches` (обнаружение про-матчей)."""
        params: dict[str, Any] = {}
        if less_than_match_id is not None:
            params[self._contract.cursor_param or "less_than_match_id"] = less_than_match_id
        result = self._request(EndpointKind.PRO_MATCHES, "/api/proMatches", params)
        payload = self._decode_json(result.response, endpoint_kind=EndpointKind.PRO_MATCHES)
        validation = validate_pro_matches(payload, observed_at=result.observed_at)

        page_ids = _match_ids(payload)
        page_end = min(page_ids) if page_ids else None
        next_cursor = str(page_end) if page_end is not None else None
        pages = _merge_pages(
            tracked_pages,
            page_start=less_than_match_id,
            page_end=page_end,
            fetched_at=result.observed_at,
        )
        notes: list[str] = []
        if validation.quarantined:
            notes.append("page_has_quarantine")
        if validation.missing_fields:
            notes.append("schema_drift")
        completeness = _page_completeness(
            validation.records,
            validation.quarantined,
            notes,
            validation.missing_fields,
        )
        return FetchBatch(
            source_id=self._contract.source_id,
            schema_version=self._contract.schema_version,
            endpoint_kind=EndpointKind.PRO_MATCHES,
            observed_at=result.observed_at,
            retrieval_status=_status_for(validation.records, payload),
            records=validation.records,
            quarantined=validation.quarantined,
            raw_payload=payload,
            content_hash=compute_content_hash(EndpointKind.PRO_MATCHES, result.response.content),
            request=result.metadata,
            next_cursor=next_cursor,
            completeness=completeness,
            cursor_payload={
                "endpoint_kind": str(EndpointKind.PRO_MATCHES),
                "page_start": less_than_match_id,
                "page_end": page_end,
                "pages": pages,
            },
        )

    def iter_pro_matches(
        self,
        *,
        max_pages: int = 1,
        cursor_payload: Mapping[str, Any] | None = None,
        overlap_pages: int = 1,
    ) -> Iterator[FetchBatch]:
        """Ограниченный обход страниц `/api/proMatches` с overlap-окном.

        `max_pages` — жёсткий предел: сколько страниц разрешено запросить за прогон.
        Последняя страница при исчерпании бюджета помечается `truncated`.
        """
        if max_pages < 1:
            raise ValueError("max_pages должен быть >= 1")
        pages: list[Mapping[str, Any]] = list((cursor_payload or {}).get("pages", []))
        start = resume_start(pages, overlap_pages)
        for index in range(max_pages):
            batch = self.fetch_pro_matches(less_than_match_id=start, tracked_pages=pages)
            if index == max_pages - 1 and batch.next_cursor is not None:
                batch = replace(
                    batch,
                    completeness=replace(
                        batch.completeness,
                        is_complete=False,
                        truncated=True,
                        notes=(*batch.completeness.notes, "page_budget_exhausted"),
                    ),
                )
            yield batch
            pages = list(batch.cursor_payload.get("pages", []))
            if batch.next_cursor is None:
                return
            start = int(batch.next_cursor)

    def fetch_explorer_matches(
        self,
        *,
        since_start_time: int,
        until_start_time: int | None = None,
        columns: Sequence[str] = MATCHES_TABLE_COLUMNS,
        limit: int = 1_000,
        offset: int = 0,
    ) -> FetchBatch:
        """Bulk-выгрузка выборочных колонок таблицы `matches` через `/api/explorer`."""
        sql = _build_matches_sql(
            since_start_time=since_start_time,
            until_start_time=until_start_time,
            columns=columns,
            limit=limit,
            offset=offset,
        )
        return self._fetch_explorer(
            sql=sql,
            columns=tuple(columns),
            limit=limit,
            offset=offset,
            validator=validate_explorer_matches,
            endpoint_kind=EndpointKind.EXPLORER,
        )

    def fetch_explorer_picks_bans(
        self,
        *,
        match_ids: Sequence[int],
        columns: Sequence[str] = PICKS_BANS_COLUMNS,
    ) -> FetchBatch:
        """Bulk-выгрузка `picks_bans` для явно перечисленных матчей."""
        sql = _build_picks_bans_sql(match_ids=match_ids, columns=columns)
        return self._fetch_explorer(
            sql=sql,
            columns=tuple(columns),
            limit=len(match_ids),
            offset=0,
            validator=validate_explorer_picks_bans,
            endpoint_kind=EndpointKind.EXPLORER,
            # У одного матча много строк picks_bans — offset-пагинация неприменима.
            paginated=False,
        )

    def fetch_match(self, match_id: int) -> FetchBatch:
        """Точечный `/api/matches/{id}`. Ответ тяжёлый — использовать адресно."""
        if not isinstance(match_id, int) or isinstance(match_id, bool) or match_id <= 0:
            raise ValueError("match_id должен быть положительным целым")
        result = self._request(
            EndpointKind.MATCH_DETAIL, f"/api/matches/{match_id}", {}, allow_not_found=True
        )
        if result.response.status_code == 404:
            return FetchBatch(
                source_id=self._contract.source_id,
                schema_version=self._contract.schema_version,
                endpoint_kind=EndpointKind.MATCH_DETAIL,
                observed_at=result.observed_at,
                retrieval_status=RetrievalStatus.NOT_FOUND,
                records=(),
                quarantined=(),
                raw_payload=_safe_body(result.response),
                content_hash=compute_content_hash(EndpointKind.MATCH_DETAIL, result.response.content),
                request=result.metadata,
                next_cursor=None,
                completeness=CompletenessFlags.empty(notes=("match_not_found",)),
            )
        payload = self._decode_json(result.response, endpoint_kind=EndpointKind.MATCH_DETAIL)
        validation = validate_match_detail(payload, observed_at=result.observed_at)
        return FetchBatch(
            source_id=self._contract.source_id,
            schema_version=self._contract.schema_version,
            endpoint_kind=EndpointKind.MATCH_DETAIL,
            observed_at=result.observed_at,
            retrieval_status=_status_for(validation.records, payload),
            records=validation.records,
            quarantined=validation.quarantined,
            raw_payload=payload,
            content_hash=compute_content_hash(EndpointKind.MATCH_DETAIL, result.response.content),
            request=result.metadata,
            next_cursor=None,
            completeness=_page_completeness(
                validation.records,
                validation.quarantined,
                list(validation.notes),
                validation.missing_fields,
            ),
        )

    def fetch_patch_constants(self, *, refresh: bool = False) -> FetchBatch:
        """`/api/constants/patch` с кэшем: справочник меняется редко.

        Кэшированный batch сохраняет **исходный** `observed_at`: время наблюдения
        данных не подменяется временем чтения из кэша.
        """
        cached = self._patch_cache
        if cached is not None and not refresh:
            age = (self._clock() - cached.observed_at).total_seconds()
            if age <= self._patch_cache_ttl_seconds:
                self._logger.debug("patch_constants cache hit age_seconds=%s", int(age))
                return replace(
                    cached,
                    completeness=replace(
                        cached.completeness,
                        notes=(*cached.completeness.notes, "served_from_cache"),
                    ),
                )
        result = self._request(EndpointKind.PATCH_CONSTANTS, "/api/constants/patch", {})
        payload = self._decode_json(result.response, endpoint_kind=EndpointKind.PATCH_CONSTANTS)
        validation = validate_patch_constants(payload, observed_at=result.observed_at)
        batch = FetchBatch(
            source_id=self._contract.source_id,
            schema_version=self._contract.schema_version,
            endpoint_kind=EndpointKind.PATCH_CONSTANTS,
            observed_at=result.observed_at,
            retrieval_status=_status_for(validation.records, payload),
            records=validation.records,
            quarantined=validation.quarantined,
            raw_payload=payload,
            content_hash=compute_content_hash(EndpointKind.PATCH_CONSTANTS, result.response.content),
            request=result.metadata,
            next_cursor=None,
            completeness=_page_completeness(
                validation.records,
                validation.quarantined,
                list(validation.notes),
                validation.missing_fields,
            ),
        )
        self._patch_cache = batch
        return batch

    # --- транспорт ----------------------------------------------------------

    def _fetch_explorer(
        self,
        *,
        sql: str,
        columns: tuple[str, ...],
        limit: int,
        offset: int,
        validator: Callable[..., Any],
        endpoint_kind: EndpointKind,
        paginated: bool = True,
    ) -> FetchBatch:
        result = self._request(endpoint_kind, "/api/explorer", {"sql": sql})
        payload = self._decode_json(result.response, endpoint_kind=endpoint_kind)
        rows = payload if isinstance(payload, list) else []
        validation = validator(
            rows, requested_columns=columns, observed_at=result.observed_at
        )
        next_cursor = str(offset + len(rows)) if paginated and len(rows) >= limit else None
        notes = list(validation.notes)
        if validation.quarantined:
            notes.append("page_has_quarantine")
        return FetchBatch(
            source_id=self._contract.source_id,
            schema_version=self._contract.schema_version,
            endpoint_kind=endpoint_kind,
            observed_at=result.observed_at,
            retrieval_status=_status_for(validation.records, payload),
            records=validation.records,
            quarantined=validation.quarantined,
            raw_payload=payload,
            content_hash=compute_content_hash(endpoint_kind, result.response.content),
            request=result.metadata,
            next_cursor=next_cursor,
            completeness=_page_completeness(validation.records, validation.quarantined, notes),
            cursor_payload={
                "endpoint_kind": str(endpoint_kind),
                "offset": offset,
                "limit": limit,
                "rows": len(rows),
            },
        )

    def _request(
        self,
        endpoint_kind: EndpointKind,
        path: str,
        params: Mapping[str, Any],
        *,
        allow_not_found: bool = False,
    ) -> _HttpResult:
        """Один логический запрос с throttle и ограниченным retry."""
        cleaned = redact_params(params)
        fingerprint = compute_request_fingerprint(
            endpoint_kind=endpoint_kind, method="GET", path=path, params=cleaned
        )
        query: dict[str, Any] = dict(cleaned)
        if self._api_key:
            # Ключ уходит провайдеру, но не попадает ни в метаданные, ни в лог.
            query["api_key"] = self._api_key
        started = time.monotonic()
        attempts = 0

        while True:
            attempts += 1
            self._quota.acquire()
            try:
                # Timeout задаётся на каждый запрос из контракта: bounded-границы
                # не зависят от того, какой http-клиент передан извне.
                response = self._http.get(
                    path, params=query, timeout=self._contract.timeout.to_httpx()
                )
            except httpx.HTTPError as exc:
                error_class = classify_exception(exc)
                self._log_failure(endpoint_kind, path, None, attempts, exc)
                if should_retry(error_class) and attempts < self._retry_policy.max_attempts:
                    self._sleep_before_retry(attempts, None)
                    continue
                raise SourceUnavailableError(
                    attempts=attempts,
                    last_status=None,
                    detail=self._redact(f"{type(exc).__name__}: {exc}"),
                ) from exc

            status = response.status_code
            self._quota.record_headers(
                response.headers, endpoint_kind=str(endpoint_kind), http_status=status
            )
            if status < 400 or (allow_not_found and status == 404):
                metadata = self._metadata(
                    fingerprint=fingerprint,
                    endpoint_kind=endpoint_kind,
                    path=path,
                    params=cleaned,
                    response=response,
                    attempts=attempts,
                    elapsed_ms=int((time.monotonic() - started) * 1000),
                )
                self._logger.debug(
                    "opendota fetch ok endpoint=%s status=%s attempts=%s elapsed_ms=%s",
                    endpoint_kind,
                    status,
                    attempts,
                    metadata.elapsed_ms,
                )
                return _HttpResult(
                    response=response,
                    metadata=metadata,
                    # observed_at — момент фактического получения ответа.
                    observed_at=self._clock(),
                )

            error_class = classify_status(status)
            detail = self._redact(_safe_body(response))
            self._log_failure(endpoint_kind, path, status, attempts, detail)
            if error_class is ErrorClass.AUTH:
                raise AuthError(status_code=status, detail=detail)
            if error_class is ErrorClass.PERMANENT:
                raise SourceRequestError(status_code=status, detail=detail)
            if error_class is ErrorClass.NOT_FOUND:
                raise SourceRequestError(status_code=status, detail=detail)

            retry_after = (
                parse_retry_after(response.headers.get("retry-after"), now=self._clock())
                if error_class is ErrorClass.RATE_LIMIT
                else None
            )
            if retry_after_exceeds_budget(retry_after, self._retry_policy):
                raise RateLimitedError(
                    retry_after_seconds=retry_after,
                    detail=f"HTTP {status}: Retry-After превышает retry-бюджет",
                )
            if attempts >= self._retry_policy.max_attempts:
                if error_class is ErrorClass.RATE_LIMIT:
                    raise RateLimitedError(
                        retry_after_seconds=retry_after,
                        detail=f"HTTP {status} после {attempts} попыток",
                    )
                raise SourceUnavailableError(
                    attempts=attempts, last_status=status, detail=f"HTTP {status}"
                )
            self._sleep_before_retry(attempts, retry_after)

    def _sleep_before_retry(self, failures: int, retry_after_seconds: float | None) -> None:
        delay = next_delay(
            attempt=failures,
            policy=self._retry_policy,
            rng=self._rng,
            retry_after_seconds=retry_after_seconds,
        )
        self._logger.debug("retry backoff seconds=%.3f after_failures=%s", delay, failures)
        self._sleeper(delay)

    def _metadata(
        self,
        *,
        fingerprint: str,
        endpoint_kind: EndpointKind,
        path: str,
        params: Mapping[str, str],
        response: httpx.Response,
        attempts: int,
        elapsed_ms: int,
    ) -> RequestMetadata:
        policy = self._contract.quota_policy
        headers = {key.lower(): value for key, value in response.headers.items()}
        quota_headers = {
            name: headers[name]
            for name in (policy.minute_remaining_header, policy.day_remaining_header, "retry-after")
            if name in headers
        }
        return RequestMetadata(
            fingerprint=fingerprint,
            endpoint_kind=endpoint_kind,
            method="GET",
            path=path,
            params=params,
            http_status=response.status_code,
            attempts=attempts,
            elapsed_ms=elapsed_ms,
            api_key_used=self.api_key_used,
            quota_headers=quota_headers,
        )

    def _decode_json(self, response: httpx.Response, *, endpoint_kind: EndpointKind) -> Any:
        try:
            return response.json()
        except ValueError as exc:
            raise MalformedResponseError(
                detail=f"{endpoint_kind}: ответ не является JSON ({type(exc).__name__})"
            ) from exc

    def _log_failure(
        self,
        endpoint_kind: EndpointKind,
        path: str,
        status: int | None,
        attempts: int,
        exc: object,
    ) -> None:
        self._logger.warning(
            "opendota fetch failed endpoint=%s path=%s status=%s attempts=%s detail=%s",
            endpoint_kind,
            path,
            status,
            attempts,
            self._redact(str(exc))[:MAX_DETAIL_CHARS],
        )

    def _redact(self, text: str) -> str:
        """Страховка: значение ключа не должно попасть в лог/детали ошибки."""
        if not self._api_key:
            return text[:MAX_DETAIL_CHARS]
        return text.replace(self._api_key, "***")[:MAX_DETAIL_CHARS]

    def _read_api_key(self) -> str | None:
        env_var = self._contract.api_key_env_var
        if not env_var:
            return None
        value = os.getenv(env_var)
        if value is None or not value.strip():
            return None
        return value.strip()


# --- вспомогательное ---------------------------------------------------------


def _status_for(records: Sequence[Any], payload: Any) -> RetrievalStatus:
    if records:
        return RetrievalStatus.OK
    if isinstance(payload, list) and not payload:
        return RetrievalStatus.EMPTY
    return RetrievalStatus.EMPTY


def _page_completeness(
    records: Sequence[Any],
    quarantined: Sequence[Any],
    notes: Sequence[str],
    missing_fields: Sequence[str] = (),
) -> CompletenessFlags:
    if not records and not quarantined:
        return CompletenessFlags.empty(notes=tuple(notes) or ())
    if quarantined or missing_fields:
        return CompletenessFlags.partial(
            missing_fields=tuple(missing_fields), notes=tuple(notes)
        )
    return CompletenessFlags.full(notes=tuple(notes))


def _match_ids(payload: Any) -> list[int]:
    if not isinstance(payload, list):
        return []
    ids: list[int] = []
    for row in payload:
        if not isinstance(row, Mapping):
            continue
        match_id = row.get("match_id")
        if isinstance(match_id, int) and not isinstance(match_id, bool) and match_id > 0:
            ids.append(match_id)
    return ids


def _safe_body(response: httpx.Response) -> str:
    try:
        return response.text
    except Exception:  # pragma: no cover - защита от экзотических ошибок декодирования
        return "<unreadable body>"


def _require_positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise ValueError(f"{label} должен быть положительным целым")
    return value


def _require_columns(columns: Sequence[str], allowed: Sequence[str]) -> tuple[str, ...]:
    """Колонки берутся только из фиксированного allowlist (без свободного SQL)."""
    resolved = tuple(columns) if columns else tuple(allowed)
    unknown = [column for column in resolved if column not in allowed]
    if unknown:
        raise ValueError(f"неизвестные колонки: {unknown}")
    return resolved


def _build_matches_sql(
    *,
    since_start_time: int,
    until_start_time: int | None,
    columns: Sequence[str],
    limit: int,
    offset: int,
) -> str:
    resolved = _require_columns(columns, MATCHES_TABLE_COLUMNS)
    since = _require_positive_int(since_start_time, "since_start_time")
    until = (
        _require_positive_int(until_start_time, "until_start_time")
        if until_start_time is not None
        else None
    )
    _require_positive_int(limit, "limit")
    if offset < 0:
        raise ValueError("offset не может быть отрицательным")
    where = f"start_time >= {since}"
    if until is not None:
        where += f" AND start_time < {until}"
    return (
        f"SELECT {', '.join(resolved)} FROM matches WHERE {where} "
        f"ORDER BY start_time LIMIT {limit} OFFSET {offset}"
    )


def _build_picks_bans_sql(*, match_ids: Sequence[int], columns: Sequence[str]) -> str:
    resolved = _require_columns(columns, PICKS_BANS_COLUMNS)
    if not match_ids:
        raise ValueError("match_ids не может быть пустым")
    ids = ", ".join(str(_require_positive_int(match_id, "match_id")) for match_id in match_ids)
    return f"SELECT {', '.join(resolved)} FROM picks_bans WHERE match_id IN ({ids})"


def dumps_payload(payload: Any) -> str:
    """Канонический JSON payload (для хэширования в тестах и диагностике)."""
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


__all__ = [
    "OpenDotaClient",
    "resume_start",
    "dumps_payload",
]
