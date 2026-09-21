"""ING-001 — исключения ingestion-слоя.

Явная классификация нужна, чтобы retry-политика различала: transient (повтор
осмыслен), rate limit (повтор после `Retry-After`), auth/permission (немедленная
остановка, повторов нет) и постоянные ошибки запроса.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:  # pragma: no cover - только для типов
    from d2intel.ingestion.quota import QuotaSnapshot


class IngestionError(Exception):
    """Базовая ошибка ingestion-слоя."""


class SourceUnavailableError(IngestionError):
    """Источник недоступен: transient-ошибки исчерпали retry-бюджет.

    Сигнал «source outage». Вызывающий обязан пометить прогон как stale/abstain,
    а не подставлять тихо другой набор данных (ARCHITECTURE.md §3, п. 7).
    """

    def __init__(self, *, attempts: int, last_status: int | None, detail: str) -> None:
        super().__init__(f"source unavailable after {attempts} attempt(s): {detail}")
        self.attempts = attempts
        self.last_status = last_status
        self.detail = detail


class AuthError(IngestionError):
    """401/403: ошибка доступа. Остановка, повторов нет."""

    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(f"authentication/permission failure (HTTP {status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class RateLimitedError(IngestionError):
    """429, который нельзя безопасно переждать (Retry-After больше бюджета)."""

    def __init__(self, *, retry_after_seconds: float | None, detail: str) -> None:
        super().__init__(f"rate limited: {detail}")
        self.retry_after_seconds = retry_after_seconds
        self.detail = detail


class SourceRequestError(IngestionError):
    """Постоянная ошибка запроса (4xx, кроме 401/403/404/429). Повтор бесполезен."""

    def __init__(self, *, status_code: int, detail: str) -> None:
        super().__init__(f"source rejected request (HTTP {status_code}): {detail}")
        self.status_code = status_code
        self.detail = detail


class MalformedResponseError(IngestionError):
    """Ответ получен, но его тело не разбирается (не JSON).

    Не retry-класс: повтор того же запроса с высокой вероятностью даст тот же
    результат, поэтому это явная остановка с фиксацией факта.
    """

    def __init__(self, *, detail: str) -> None:
        super().__init__(f"malformed source response: {detail}")
        self.detail = detail


class QuotaExhaustedError(IngestionError):
    """Локальный бюджет квоты исчерпан: запрос не отправляется.

    `scope` — 'minute' (окно 60/мин) или 'day' (суточный лимит 3 000).
    """

    def __init__(
        self,
        *,
        scope: str,
        retry_after_seconds: float | None,
        snapshot: QuotaSnapshot | None = None,
    ) -> None:
        detail = (
            f"quota scope={scope} exhausted"
            if retry_after_seconds is None
            else f"quota scope={scope} exhausted, retry in {retry_after_seconds:.3f}s"
        )
        super().__init__(detail)
        self.scope = scope
        self.retry_after_seconds = retry_after_seconds
        self.snapshot = snapshot
