# scripts/ — одноразовые entrypoints

Будущие разовые скрипты (ingestion backfill, evaluation, manifest-сборка и т.д.)
размещаются здесь. Это не сервисы и не доменные модули — только тонкие
entrypoints, вызывающие код из `src/d2intel`.

Текущие скрипты:

- `db_healthcheck.py` — проверка живости БД (SELECT 1), возвращает 0/1.
