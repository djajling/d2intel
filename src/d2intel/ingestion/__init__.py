"""ING-001 — ingestion: OpenDota-клиент и raw capture.

Пакет реализует контракт source adapter из `ARCHITECTURE.md` §3:
`fetch → validate → store`. Нормализации, вычисления feature и map index
здесь нет — это `DATA-001` / `FEAT-001`.

Границы пакета:

* `contracts` — объявление контракта источника и типы batch/метаданных;
* `quota` — общий бюджет источника (60/мин, 3 000/день) + журнал headers;
* `retry` — классификация ошибок, backoff с jitter, `Retry-After`;
* `validation` — проверка формы сырых строк и причины карантина (без нормализации);
* `opendota_client` — HTTP-клиент OpenDota (timeout, throttle, retry, пагинация);
* `raw_capture` — идемпотентная запись raw + наблюдений + карантина + watermark;
* `sync_once` — ограниченный sync-once прогон (оркестрация, не планировщик).
"""

from __future__ import annotations

__all__ = ["contracts", "quota", "retry", "validation", "opendota_client", "raw_capture", "sync_once"]
