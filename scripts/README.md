# scripts/ — одноразовые entrypoints

Будущие разовые скрипты (ingestion backfill, evaluation, manifest-сборка и т.д.)
размещаются здесь. Это не сервисы и не доменные модули — только тонкие
entrypoints, вызывающие код из `src/d2intel`.

Текущие скрипты:

- `db_healthcheck.py` — проверка живости БД (SELECT 1), возвращает 0/1.
- `ingest_patch_constants.py` — загрузка справочника `/api/constants/patch` в raw
  **одним запросом** (квота: 60/мин, 3000/день); `--refresh` игнорирует кэш клиента.
  После прогона `normalize_once.py` создаёт строки `patch`. Идемпотентен.
- `normalize_once.py` — нормализация исторического ядра из записанного raw (DATA-001).
- `backfill_game_patch.py` — дозаполнение `game.patch_id` для карт, записанных до
  появления справочника патчей. `patch_id` — производный атрибут, не наблюдение;
  трогает только `patch_id IS NULL`, снимки не затрагивает. `--dry-run` — только счёт.
- `ingest_opendota_once.py` — разовый (sync-once) прогон ingestion OpenDota:
  ограниченный `--pages`, throttle/retry внутри клиента, запись raw. Реальных
  запросов в тестах нет; запуск вручную. Коды возврата: 0 completed, 2 partial
  (неполный охват, не ошибка), 3 stale, 4 failed, 5 quota_exhausted.
