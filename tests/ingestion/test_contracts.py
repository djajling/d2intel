"""ING-001 — тесты контракта источника и его обязательных элементов.

AC #1: клиент объявляет контракт источника (ARCHITECTURE.md §3).
AC #6: секреты не хранятся в контракте и не попадают в метаданные запроса.
"""

from __future__ import annotations

import json

import pytest

from d2intel.ingestion.contracts import (
    OPENDOTA_CONTRACT,
    Capabilities,
    CompletenessFlags,
    EndpointKind,
    QuotaPolicy,
    TimeoutPolicy,
    compute_content_hash,
    compute_request_fingerprint,
    redact_params,
)


def test_contract_declares_all_required_elements() -> None:
    """Контракт объявляет все элементы из ARCHITECTURE.md §3."""
    contract = OPENDOTA_CONTRACT
    assert contract.source_id == "opendota"
    assert contract.schema_version
    assert isinstance(contract.capabilities, Capabilities)
    assert contract.auth_mode
    assert contract.terms_reference
    assert contract.allowed_purposes
    assert isinstance(contract.quota_policy, QuotaPolicy)
    assert contract.cursor_semantics
    assert contract.cursor_param
    assert contract.timezone == "UTC"
    assert contract.adapter_version


def test_contract_declares_no_upcoming_source() -> None:
    """Вердикт SRC-001 зафиксирован в контракте: upcoming-источника нет."""
    capabilities = OPENDOTA_CONTRACT.capabilities
    assert capabilities.supports_upcoming is False
    assert capabilities.auth_required is False
    assert EndpointKind.PRO_MATCHES in capabilities.endpoints
    assert EndpointKind.EXPLORER in capabilities.endpoints


def test_contract_holds_no_secret_value() -> None:
    """В контракте только имя переменной окружения, а не значение ключа."""
    serialized = json.dumps(
        {
            "auth_mode": OPENDOTA_CONTRACT.auth_mode,
            "api_key_env_var": OPENDOTA_CONTRACT.api_key_env_var,
            "terms_reference": OPENDOTA_CONTRACT.terms_reference,
        },
        ensure_ascii=False,
    )
    assert OPENDOTA_CONTRACT.api_key_env_var == "OPENDOTA_API_KEY"
    assert "Bearer" not in serialized
    # Ссылка на условия не выдумана: публичного ToS-URL у OpenDota не найдено.
    assert "http" not in OPENDOTA_CONTRACT.terms_reference


def test_quota_policy_matches_free_tier() -> None:
    """Заявленные лимиты free-tier: 60/мин, 3 000/день, 404/429/500 не тарифицируются."""
    policy = OPENDOTA_CONTRACT.quota_policy
    assert policy.per_minute == 60
    assert policy.per_day == 3_000
    assert policy.untariffed_statuses == (404, 429, 500)
    assert policy.min_interval_seconds == pytest.approx(1.0)


def test_timeout_policy_is_bounded() -> None:
    """Bounded timeout: все фазы запроса имеют конечные положительные значения."""
    policy = TimeoutPolicy()
    timeout = policy.to_httpx()
    for value in (timeout.connect, timeout.read, timeout.write, timeout.pool):
        assert value is not None
        assert value > 0
        assert value < 120


def test_redact_params_removes_secrets() -> None:
    """Секретные параметры вырезаются, остальные сохраняются."""
    redacted = redact_params({"sql": "SELECT 1", "api_key": "super-secret", "token": "x"})
    assert redacted == {"sql": "SELECT 1"}
    assert "super-secret" not in json.dumps(redacted)


def test_request_fingerprint_ignores_absent_secret() -> None:
    """Отпечаток запроса не зависит от ключа (ключ в параметры не передаётся)."""
    first = compute_request_fingerprint(
        endpoint_kind=EndpointKind.PRO_MATCHES,
        method="GET",
        path="/api/proMatches",
        params={},
    )
    second = compute_request_fingerprint(
        endpoint_kind=EndpointKind.PRO_MATCHES,
        method="GET",
        path="/api/proMatches",
        params=redact_params({"api_key": "another-key"}),
    )
    assert first == second
    assert first == compute_request_fingerprint(
        endpoint_kind=EndpointKind.PRO_MATCHES,
        method="GET",
        path="/api/proMatches",
        params={},
    )


def test_content_hash_depends_on_endpoint_kind() -> None:
    """Одинаковое тело на разных endpoints не считается одним raw-payload."""
    body = b'[{"match_id": 1}]'
    assert compute_content_hash(EndpointKind.PRO_MATCHES, body) != compute_content_hash(
        EndpointKind.EXPLORER, body
    )
    assert compute_content_hash(EndpointKind.PRO_MATCHES, body) == compute_content_hash(
        EndpointKind.PRO_MATCHES, body
    )


def test_empty_response_is_not_full_coverage() -> None:
    """Пустой ответ — не успех полного охвата и не «матч отменён»."""
    flags = CompletenessFlags.empty()
    assert flags.empty_response is True
    assert flags.is_complete is False
    assert flags.page_complete is True
    assert "empty_response_is_not_full_coverage" in flags.notes
