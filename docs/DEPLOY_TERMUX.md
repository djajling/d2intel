# Деплой d2intel на Android (Termux / «Гермес»)

Полный хост: PostgreSQL + приложение целиком на телефоне, работает без ПК.
Решение владельца от 2026-09-28.

## Что нужно знать заранее

- **catboost на телефон НЕ ставим.** Runtime-цепочка (сервер, 5-мин цикл,
  `auto-freeze` / `auto-notify` / `collect_drafts` / `prospective_reconcile`,
  Telegram) использует только модель `logreg_prior_form` (joblib +
  scikit-learn). `catboost` — challenger, нужен лишь для обучения, на телефоне
  не требуется. Это снимает главный риск (сборка под aarch64).
- Runtime-зависимости (все есть aarch64-wheel'ы): `fastapi`, `uvicorn`,
  `jinja2`, `sqlalchemy`, `alembic`, `psycopg[binary]` (v3), `pandas`,
  `scikit-learn`, `numpy`, `joblib`, `httpx`, `pydantic`.
- **Тайминг BLAST:** турнир стартует 29.09 13:00 MSK. Полная миграция БД
  (~365 МБ) + тест на телефоне до утра рискованны. Рекомендую: на BLAST
  поднять **ПК-сервис** (`scripts/install_tasks.bat`, уже готов) как
  гарантированный живой путь, а телефон довести как постоянный хост
  параллельно/после. Ниже — полный гайд для телефона.

## 0. Окружение (что такое «Гермес»)

Гайд рассчитан на **Termux-native** (`pkg`/`apt`, нативный aarch64 Linux).
Если «Гермес» — это proot-дистрибутив (Ubuntu/Debian через `proot`/`start.sh`),
зайди в него и вместо `pkg install` используй `apt install` (пакеты те же:
`git`, `python3`, `python3-pip`, `postgresql`, `postgresql-contrib`). Все
скрипты ниже — для Termux-native; для proot меняй только менеджер пакетов.

Определи окружение (в Termux):

```
echo "$PREFIX"
# /data/data/com.termux/files/usr  -> Termux-native (так и пишем дальше)
# пусто                          -> ты внутри proot-дистрибутива (apt вместо pkg)
```

Доп. пакеты из F-Droid: **Termux**, **Termux:Boot** (автозапуск при загрузке
телефона), **Termux:API** (опционально). Ставь Termux только из F-Droid, не из
Play Store (там устаревший).

## 1. Пакеты и репозиторий

```
pkg update -y
pkg install -y git python postgresql
git clone https://github.com/djajling/d2intel.git ~/d2intel
cd ~/d2intel
```

## 2. venv + runtime-зависимости (без catboost)

```
python -m venv .venv
. .venv/bin/activate
pip install --upgrade pip
pip install fastapi==0.115.6 uvicorn==0.34.0 jinja2==3.1.6 \
  sqlalchemy==2.0.36 alembic==1.14.1 "psycopg[binary]==3.2.3" \
  pandas==2.2.3 scikit-learn==1.6.1 numpy==2.4.6 joblib==1.6.0 \
  httpx==0.28.1 pydantic==2.10.5
pip install -e .
```

Или одним вызовом `scripts/termux/bootstrap.sh` (он делает шаги 1–6, кроме
переноса данных).

## 3. PostgreSQL: initdb, тюнинг под телефон, старт

initdb по умолчанию ставит `shared_buffers` великоват для телефона — уменьшаем.

```
export PGDATA="$HOME/d2intel_pgdata"
initdb -D "$PGATA" -U postgres --auth=trust
# тюнинг под телефон:
echo "shared_buffers = 128MB"        >> "$PGDATA/postgresql.conf"
echo "effective_cache_size = 256MB"  >> "$PGDATA/postgresql.conf"
echo "max_connections = 50"          >> "$PGDATA/postgresql.conf"
echo "listen_addresses = 'localhost'" >> "$PGDATA/postgresql.conf"
pg_ctl -D "$PGDATA" -l "$HOME/d2intel_pg.log" start
```

## 4. Роль и база под d2intel

`DATABASE_URL` по умолчанию:
`postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel`.

```
psql -U postgres -h localhost -c "CREATE ROLE d2intel LOGIN PASSWORD 'd2intel_dev';"
psql -U postgres -h localhost -c "CREATE DATABASE d2intel OWNER d2intel;"
```

## 5. Миграции схемы

```
. .venv/bin/activate
cd ~/d2intel
alembic upgrade head
```

После этого схема готова (таблицы пусты — данные переносим отдельно, см. §7).

## 6. .env и запуск

Скопируй свой `.env` (с `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`, при
необходимости `DATABASE_URL`) в `~/d2intel/.env`. **В git не коммить.**

Запуск сервера (фон):

```
scripts/termux/run_server.sh
```

Цикл живого турнира (каждые 5 мин) — отдельным процессом:

```
scripts/termux/live_cycle.sh
```

Цикл итогов NOTIF-002 (каждые 30 мин: свежие игры → normalize → драфты →
закрытие серий → reconcile → итог в TG) — отдельным процессом:

```
scripts/termux/result_cycle.sh
```

Проверка:

```
curl -s http://127.0.0.1:8000/health
curl -s -X POST "http://127.0.0.1:8000/api/schedule/auto-notify?dry_run=true"
```

## 7. Перенос БД с ПК (отдельно, после гайда)

База на ПК: история матчей, ~365 МБ. Дамп → перенос файла → restore.

На ПК (из venv или с `pg_dump` от PostgreSQL 17):

```
pg_dump -h localhost -U d2intel -d d2intel -F c -f d2intel_dump.dump
```

Переноси `d2intel_dump.dump` на телефон (adb push / USB / облако) в `~/.termux`
или `~`. Затем на телефоне (postgres поднят, роль/БД из §4 созданы):

```
pg_restore -h localhost -U d2intel -d d2intel --clean --if-exists d2intel_dump.dump
```

Если версии PostgreSQL на ПК и телефоне сильно различаются и `pg_restore`
ругается — вместо `-F c` делай на ПК текстовый дамп
(`pg_dump -F p ... > d2intel.sql`) и заливай `psql -U d2intel -d d2intel -f d2intel.sql`.

После restore миграции трогать не нужно (схема уже на head). Проверь цикл
реальным прогоном `auto-notify` (без `dry_run`).

## 8. Автозапуск при загрузке телефона (Termux:Boot)

Положи `scripts/termux/boot.sh` в `~/.termux/boot/` и дай права
`chmod +x ~/.termux/boot/d2intel-boot.sh` (имя файла — любое, главное
исполняемый и в этом каталоге). `boot.sh` поднимает postgres + сервер +
5-мин цикл + 30-мин цикл итогов и
держит `termux-wake-lock`, чтобы телефон не засыпал важным процессам.

В proot-варианте Termux:Boot не сработает напрямую — нужен `./start.sh`
дистрибутива из `~/.termux/boot/` с вызовом скриптов внутри chroot.

## 9. Грабли

- `initdb` отказывается от root — в Termux ты не root, всё ок.
- Если `pg_ctl start` падает с «could not create lock file» — проверь, что
  `$PGDATA` на внутреннем хранилище Termux (`$HOME`), а не на sdcard (там нет
  прав exec/lock).
- `psycopg[binary]` тащит свою libpq — `pkg install libpq` не обязателен.
- Если `pip install -e .` не собирает пакет — проверь `pkg install clang make`
  (реже нужно для чисто-python пакета d2intel).
- STRATZ free-tier: ~2 запроса / 15 мин; на телефоне счётчик квоты живёт в
  `artifacts/cache/stratz_quota.json` (переживает перезапуск).
