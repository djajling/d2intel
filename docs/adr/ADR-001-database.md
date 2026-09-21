# ADR-001 — PostgreSQL и границы хранения

**Статус:** Accepted (утверждён владельцем 2026-09-21, решение по варианту A; реализация — `DB-001`).

**Контекст:** один разработчик, бесплатные источники, нужны provenance, temporal joins, идемпотентность и неизменяемая история.

**Предложение:** одна PostgreSQL; canonical — typed tables/PK/FK; raw и snapshots — JSONB; крупные replay/model artifacts — локальные файлы с checksum/manifest. Никаких Redis/ClickHouse/feature-store сервисов в MVP.

**Альтернативы:** SQLite проще для throwaway research, но переход к общим API/worker транзакциям потребует миграции; отдельное object storage — после измерения объёма. Не создавать распределённое хранилище заранее.

**Последствия:** нужны migrations и backup/restore test; реляционные связи не растворяются в JSON. Append-only snapshots и temporal revisions реализуются явно, не появляются автоматически из выбора БД.

**Основания:** [constraints](https://www.postgresql.org/docs/current/ddl-constraints.html), [range types](https://www.postgresql.org/docs/current/rangetypes.html).

**Условия пересмотра:** измеренный размер/latency превышают ресурсы одиночной БД, подтверждён отдельный workload. Связанные документы: DATA_MODEL.md, ARCHITECTURE.md. Принятие — PRD-001/PRD-004, реализация — DB-001.
