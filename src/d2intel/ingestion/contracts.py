"""ING-001 — объявление контракта источника и типы batch (ARCHITECTURE.md §3).

Модуль отвечает ровно на один вопрос: **что адаптер обещает потребителю**.
Здесь нет сети, нет записи в БД и нет нормализации.

Обязательные элементы контракта (§3): `source_id`, `schema_version`,
`capabilities`, `auth_mode`, `terms_reference`, `allowed_purposes`,
`quota_policy`, cursor semantics, timezone.

Секреты в контракте не хранятся: объявляется только **имя** переменной
окружения, из которой ключ может быть прочитан (и никогда — его значение).
"""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from enum import StrEnum
from typing import Any

import httpx

# --- идентичность источника -------------------------------------------------

OPENDOTA_SOURCE_ID = "opendota"
OPENDOTA_BASE_URL = "https://api.opendota.com"
OPENDOTA_SCHEMA_VERSION = "opendota.api.v31.1.0+ing001"
OPENDOTA_ADAPTER_VERSION = "ing-001.1"

#: Ссылка на условия/правовой контекст. Публичных ToS-страниц OpenDota в рамках
#: обзора не найдено (SOURCES.md §3.1), поэтому ссылка внутренняя — на разбор
#: источника, а не на выдуманный URL. Цепочка прав Valve → OpenDota остаётся
#: открытым вопросом U8 и не считается закрытой этим контрактом.
OPENDOTA_TERMS_REFERENCE = "SOURCES.md §3.1 (OpenDota); открытый вопрос U8"
OPENDOTA_TERMS_CHECKED_AT = date(2026, 9, 21)


class EndpointKind(StrEnum):
    """Вид запроса. Значения пишутся в `raw_payload.endpoint_kind`."""

    PRO_MATCHES = "pro_matches"
    EXPLORER = "explorer"
    MATCH_DETAIL = "match_detail"
    PATCH_CONSTANTS = "patch_constants"


class RetrievalStatus(StrEnum):
    """Результат retrieval. Пустой ответ — не успех и не «матч отменён».

    Отсутствие данных у провайдера (`NOT_FOUND`) — это результат доставки, а не
    ошибка. Отказы доставки (stale/quota/auth) не выражаются этим статусом:
    клиент в таких случаях останавливается и помечает **прогон**
    (`ingestion_run.status`), а не выдаёт batch.
    """

    OK = "ok"
    EMPTY = "empty"
    NOT_FOUND = "not_found"


@dataclass(frozen=True)
class Capabilities:
    """Что источник умеет. `supports_upcoming=False` — вердикт SRC-001.

    `live_endpoint_available` отражает факт наличия `/api/live` в источнике, а не
    намерение его использовать: upcoming через live не получить, поэтому в scope
    `ING-001` live не входит.
    """

    endpoints: tuple[str, ...]
    supports_pagination: bool
    supports_bulk_export: bool
    supports_upcoming: bool
    live_endpoint_available: bool
    auth_required: bool

    def as_dict(self) -> dict[str, Any]:
        """JSONB-представление для `data_source.capabilities`."""
        return {
            "endpoints": list(self.endpoints),
            "supports_pagination": self.supports_pagination,
            "supports_bulk_export": self.supports_bulk_export,
            "supports_upcoming": self.supports_upcoming,
            "live_endpoint_available": self.live_endpoint_available,
            "auth_required": self.auth_required,
        }


@dataclass(frozen=True)
class QuotaPolicy:
    """Заявленные лимиты free-tier (OPENDOTA_API_MAP.md §1)."""

    per_minute: int = 60
    per_day: int = 3_000
    #: Статусы, которые провайдер не тарифицирует.
    untariffed_statuses: tuple[int, ...] = (404, 429, 500)
    #: Имена заголовков остатка квоты (читаются как есть, значения — журнал).
    minute_remaining_header: str = "x-rate-limit-remaining-minute"
    day_remaining_header: str = "x-rate-limit-remaining-day"

    @property
    def min_interval_seconds(self) -> float:
        """Минимальный средний интервал, соответствующий минутному лимиту."""
        return 60.0 / float(self.per_minute)


@dataclass(frozen=True)
class TimeoutPolicy:
    """Bounded timeout: конечные значения на каждую фазу запроса."""

    connect_seconds: float = 5.0
    read_seconds: float = 20.0
    write_seconds: float = 10.0
    pool_seconds: float = 5.0

    def to_httpx(self) -> httpx.Timeout:
        """Преобразование в httpx.Timeout (все фазы ограничены)."""
        return httpx.Timeout(
            connect=self.connect_seconds,
            read=self.read_seconds,
            write=self.write_seconds,
            pool=self.pool_seconds,
        )


@dataclass(frozen=True)
class SourceContract:
    """Полное объявление контракта источника (ARCHITECTURE.md §3)."""

    source_id: str
    schema_version: str
    adapter_version: str
    capabilities: Capabilities
    auth_mode: str
    api_key_env_var: str | None
    terms_reference: str
    terms_checked_at: date
    allowed_purposes: tuple[str, ...]
    quota_policy: QuotaPolicy
    cursor_semantics: str
    cursor_param: str | None
    timezone: str
    retention_policy: str
    base_url: str
    timeout: TimeoutPolicy


@dataclass(frozen=True)
class RequestMetadata:
    """Метаданные запроса. Секреты здесь отсутствуют по построению.

    `params` — уже очищенные параметры (ключ доступа вырезан), `api_key_used` —
    только булев признак факта использования ключа, не его значение.
    """

    fingerprint: str
    endpoint_kind: EndpointKind
    method: str
    path: str
    params: Mapping[str, str]
    http_status: int | None
    attempts: int
    elapsed_ms: int
    api_key_used: bool
    quota_headers: Mapping[str, str] = field(default_factory=dict)


@dataclass(frozen=True)
class ProviderRecord:
    """Одна запись источника: provider id + сырой payload + время наблюдения.

    `payload` — сырой объект источника без нормализации и без потерь.
    """

    provider_entity_id: str
    provider_entity_type: str
    payload: Mapping[str, Any]
    observed_at: datetime
    event_time: datetime | None = None
    source_published_at: datetime | None = None


@dataclass(frozen=True)
class CompletenessFlags:
    """Полнота охвата. Пустой ответ не равен успеху полного охвата (§3).

    Семантика полей (не пересекаются):

    * `page_complete` — страница получена целиком (HTTP 200 + успешный разбор);
    * `is_complete` — в этом batch нет известных пропусков (нет карантина и нет
      обрезания по бюджету страниц). **Не** означает полный охват истории;
    * `truncated` — обход остановлен по лимиту страниц, `next_cursor` не пуст;
    * `empty_response` — страница пуста. Это факт о выдаче, а не утверждение
      «матчей не существует» и не «матч отменён»;
    * `missing_fields` — ожидаемые поля, отсутствующие во всех строках (schema drift).
    """

    is_complete: bool
    page_complete: bool
    truncated: bool = False
    empty_response: bool = False
    missing_fields: tuple[str, ...] = ()
    notes: tuple[str, ...] = ()

    @classmethod
    def full(cls, *, notes: tuple[str, ...] = ()) -> CompletenessFlags:
        return cls(is_complete=True, page_complete=True, notes=notes)

    @classmethod
    def empty(cls, *, notes: tuple[str, ...] = ()) -> CompletenessFlags:
        return cls(
            is_complete=False,
            page_complete=True,
            empty_response=True,
            notes=notes or ("empty_response_is_not_full_coverage",),
        )

    @classmethod
    def partial(
        cls,
        *,
        truncated: bool = False,
        missing_fields: tuple[str, ...] = (),
        notes: tuple[str, ...] = (),
    ) -> CompletenessFlags:
        return cls(
            is_complete=False,
            page_complete=not truncated,
            truncated=truncated,
            missing_fields=missing_fields,
            notes=notes,
        )


@dataclass(frozen=True)
class QuarantineRecord:
    """Строка, непригодная для downstream, с отдельной data-quality причиной."""

    reason_code: str
    reason_detail: str
    provider_entity_id: str | None
    provider_entity_type: str
    offending_payload: Mapping[str, Any]
    observed_at: datetime
    event_time: datetime | None = None
    source_published_at: datetime | None = None


@dataclass(frozen=True)
class FetchBatch:
    """Результат одного retrieval: сырой payload + метаданные + курсор."""

    source_id: str
    schema_version: str
    endpoint_kind: EndpointKind
    observed_at: datetime
    retrieval_status: RetrievalStatus
    records: tuple[ProviderRecord, ...]
    quarantined: tuple[QuarantineRecord, ...]
    raw_payload: Any
    content_hash: str
    request: RequestMetadata
    next_cursor: str | None
    completeness: CompletenessFlags
    cursor_payload: Mapping[str, Any] = field(default_factory=dict)

    @property
    def is_usable(self) -> bool:
        """True, если batch содержит пригодные записи (не stale/empty/ошибка)."""
        return self.retrieval_status in {RetrievalStatus.OK, RetrievalStatus.EMPTY} and bool(
            self.records
        )


def compute_content_hash(endpoint_kind: EndpointKind | str, raw_bytes: bytes) -> str:
    """SHA-256 сырого тела ответа с префиксом вида запроса.

    Префикс не даёт совпасть хэшам одинаковых тел на разных endpoints: в БД
    уникальность объявлена как `(source_id, content_hash)`.
    """
    kind = str(endpoint_kind)
    return hashlib.sha256(kind.encode("utf-8") + b"\x00" + raw_bytes).hexdigest()


def compute_request_fingerprint(
    *,
    endpoint_kind: EndpointKind | str,
    method: str,
    path: str,
    params: Mapping[str, str],
) -> str:
    """Стабильный отпечаток запроса. Не зависит от наличия API-ключа.

    Параметры должны приходить уже очищенными (см. `redact_params`).
    """
    parts = [str(endpoint_kind), method.upper(), path]
    parts.extend(f"{key}={params[key]}" for key in sorted(params))
    return hashlib.sha256("\n".join(parts).encode("utf-8")).hexdigest()


#: Параметры/заголовки, значения которых никогда не попадают в raw/log.
SECRET_PARAM_NAMES = frozenset({"api_key", "key", "token", "access_token", "authorization"})


def redact_params(params: Mapping[str, Any]) -> dict[str, str]:
    """Удаляет секретные параметры и приводит значения к строкам."""
    redacted: dict[str, str] = {}
    for key, value in params.items():
        if key.lower() in SECRET_PARAM_NAMES:
            continue
        redacted[str(key)] = str(value)
    return redacted


def utc_now() -> datetime:
    """Текущее время UTC — используется только как `observed_at`/`ingested_at`."""
    return datetime.now(UTC)


# --- контракт OpenDota ------------------------------------------------------

OPENDOTA_CONTRACT = SourceContract(
    source_id=OPENDOTA_SOURCE_ID,
    schema_version=OPENDOTA_SCHEMA_VERSION,
    adapter_version=OPENDOTA_ADAPTER_VERSION,
    capabilities=Capabilities(
        endpoints=(
            EndpointKind.PRO_MATCHES,
            EndpointKind.EXPLORER,
            EndpointKind.MATCH_DETAIL,
            EndpointKind.PATCH_CONSTANTS,
        ),
        supports_pagination=True,
        supports_bulk_export=True,
        # upcoming-расписания в источнике нет (SRC-001, OPENDOTA_API_MAP.md §2.5).
        supports_upcoming=False,
        # /api/live в источнике есть, но не используется: upcoming через него не
        # получить, а будущие матчи — вне scope ING-001.
        live_endpoint_available=True,
        auth_required=False,
    ),
    auth_mode="optional_api_key",
    api_key_env_var="OPENDOTA_API_KEY",
    terms_reference=OPENDOTA_TERMS_REFERENCE,
    terms_checked_at=OPENDOTA_TERMS_CHECKED_AT,
    allowed_purposes=(
        "research",
        "retrospective_forecast_evaluation",
        "personal_non_commercial",
    ),
    quota_policy=QuotaPolicy(),
    # Семантика курсора: обратный обход по match_id. Параметр пагинации
    # `less_than_match_id` заявлен документацией OpenDota, но НЕ проверен живым
    # запросом (OPENDOTA_API_MAP.md §6) — требует подтверждения на первом прогоне.
    cursor_semantics="descending match_id; opaque next_cursor = min(match_id) страницы",
    cursor_param="less_than_match_id",
    timezone="UTC",
    retention_policy=(
        "raw хранится локально; удаление по требованию источника с сохранением "
        "tombstone (ARCHITECTURE.md §6)"
    ),
    base_url=OPENDOTA_BASE_URL,
    timeout=TimeoutPolicy(),
)
