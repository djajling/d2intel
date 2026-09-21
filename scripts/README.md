# scripts/ — одноразовые entrypoints

Будущие разовые скрипты (ingestion backfill, evaluation, manifest-сборка и т.д.)
размещаются здесь. Это не сервисы и не доменные модули — только тонкие
entrypoints, вызывающие код из `src/d2intel`.

Текущие скрипты:

- `db_healthcheck.py` — проверка живости БД (SELECT 1), возвращает 0/1.
- `ingest_opendota_once.py` — разовый (sync-once) прогон ingestion OpenDota:
  ограниченный `--pages`, throttle/retry внутри клиента, запись raw. Реальных
  запросов в тестах нет; запуск вручную. Коды возврата: 0 completed, 2 partial
  (неполный охват, не ошибка), 3 stale, 4 failed, 5 quota_exhausted.
