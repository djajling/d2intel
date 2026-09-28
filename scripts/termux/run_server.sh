#!/usr/bin/env bash
# d2intel: uvicorn на телефоне (Termux). Читает .env, поднимает сервер.
# Запуск: scripts/termux/run_server.sh   (фоновый — nohup ... &)
set -a
REPO_DIR="${REPO_DIR:-$HOME/d2intel}"
cd "$REPO_DIR"
[ -f .env ] && . ./.env
# shellcheck disable=SC1091
. .venv/bin/activate
exec python -m uvicorn d2intel.app:app --host 127.0.0.1 --port 8000 --app-dir "$REPO_DIR/src"
