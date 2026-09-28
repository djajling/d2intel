#!/usr/bin/env bash
# d2intel Termux bootstrap (runtime only, БЕЗ catboost — он нужен лишь для обучения).
# Запуск из Termux. Требует: pkg install git python postgresql.
set -euo pipefail

PREFIX_DIR="${PREFIX:-/data/data/com.termux/files/usr}"
HOME_DIR="${HOME:-/data/data/com.termux/files/home}"
REPO_DIR="${REPO_DIR:-$HOME_DIR/d2intel}"
PGDATA="${PGDATA:-$HOME_DIR/d2intel_pgdata}"
DATABASE_URL="${DATABASE_URL:-postgresql+psycopg://d2intel:d2intel_dev@localhost:5432/d2intel}"

echo "== 1. Пакеты Termux =="
pkg update -y
pkg install -y git python postgresql

echo "== 2. Клон репо =="
if [ ! -d "$REPO_DIR" ]; then
  git clone https://github.com/djajling/d2intel.git "$REPO_DIR"
fi
cd "$REPO_DIR"

echo "== 3. venv + runtime-зависимости (без catboost) =="
python -m venv .venv
# shellcheck disable=SC1091
. .venv/bin/activate
pip install --upgrade pip
pip install fastapi==0.115.6 uvicorn==0.34.0 jinja2==3.1.6 \
  sqlalchemy==2.0.36 alembic==1.14.1 "psycopg[binary]==3.2.3" \
  pandas==2.2.3 scikit-learn==1.6.1 numpy==2.4.6 joblib==1.6.0 \
  httpx==0.28.1 pydantic==2.10.5
pip install -e .

echo "== 4. PostgreSQL initdb + тюнинг + старт =="
if [ ! -d "$PGDATA" ]; then
  initdb -D "$PGDATA" -U postgres --auth=trust
  {
    echo "shared_buffers = 128MB"
    echo "effective_cache_size = 256MB"
    echo "max_connections = 50"
    echo "listen_addresses = 'localhost'"
  } >> "$PGDATA/postgresql.conf"
fi
pg_ctl -D "$PGDATA" -l "$HOME_DIR/d2intel_pg.log" start || true
for _ in $(seq 1 30); do pg_isready -h localhost >/dev/null 2>&1 && break; sleep 1; done

echo "== 5. Роль/БД под d2intel =="
psql -U postgres -h localhost -tc "SELECT 1 FROM pg_roles WHERE rolname='d2intel'" | grep -q 1 \
  || psql -U postgres -h localhost -c "CREATE ROLE d2intel LOGIN PASSWORD 'd2intel_dev';"
psql -U postgres -h localhost -tc "SELECT 1 FROM pg_database WHERE datname='d2intel'" | grep -q 1 \
  || psql -U postgres -h localhost -c "CREATE DATABASE d2intel OWNER d2intel;"

echo "== 6. Миграции =="
# shellcheck disable=SC1091
. .venv/bin/activate
cd "$REPO_DIR"
alembic upgrade head

echo "ГОТОВО (схема пуста). Перенос данных — docs/DEPLOY_TERMUX.md, раздел 7."
echo "Запуск: scripts/termux/run_server.sh  и  scripts/termux/live_cycle.sh"
echo "Автозапуск: скопируй scripts/termux/boot.sh в ~/.termux/boot/ и дай +x."
