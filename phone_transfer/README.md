# Transfer-ветка: данные с ПК на телефон (2026-09-28, ночь)

В `main` этого нет и не будет — ветка одноразовая, после takeover удалить.

## Состав

- `phone_transfer/d2intel_full.dump.part01..05` — полный `pg_dump -Fc` базы
  `d2intel` с ПК (PostgreSQL 17), нарезан по 80 МБ (лимит GitHub 100 МБ/файл).
  Целиком ~365 МБ. Внутри: история, канон, `scheduled_match` (10 фикстур BLAST),
  `notify_state`,凍結 данные reconcile. Целостность проверена sha256 при нарезке.
- `phone_transfer/prospective/*.json` — 3 immutable freeze-артефакта
  (включая reconciled `8987f801`, y=1). Положить в `~/d2intel/artifacts/prospective/`.

## Hermes, команды на телефоне (каталог — копия ветки)

```bash
cat phone_transfer/d2intel_full.dump.part* > /tmp/d2intel_full.dump
pg_restore -h localhost -U d2intel -d d2intel --clean --if-exists /tmp/d2intel_full.dump
mkdir -p ~/d2intel/artifacts/prospective
cp phone_transfer/prospective/*.json ~/d2intel/artifacts/prospective/
psql -h localhost -U d2intel -d d2intel -c "SELECT count(*) FROM scheduled_match;"
psql -h localhost -U d2intel -d d2intel -c "SELECT count(*) FROM game;"
```

`pg_restore` 18-й версии читает `-Fc` из 17-й — поддерживается.
Если restore ругается на версии — сообщить владельцу, сделаем текстовый дамп.

## Скачивание без git (пофайлово через curl)

База URL сырых файлов (та же ветка):

```bash
BASE=https://raw.githubusercontent.com/djajling/d2intel/transfer/phone-2026-09-28/phone_transfer
for i in 01 02 03 04 05; do curl -sL -o d2intel_full.dump.part$i $BASE/d2intel_full.dump.part$i; done
```

Если репозиторий приватный — raw потребует токен владельца; тогда только
`git fetch origin transfer/phone-2026-09-28` с его доступом.
