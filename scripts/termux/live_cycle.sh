#!/usr/bin/env bash
# d2intel: 5-минутный цикл живого турнира на телефоне (Termux).
#   auto-freeze -> collect_drafts --all -> auto-notify
# Запуск фоном: nohup scripts/termux/live_cycle.sh > artifacts/cache/cycle.out.log 2>&1 &
set -u
REPO_DIR="${REPO_DIR:-$HOME/d2intel}"
LOG="$REPO_DIR/artifacts/cache/scheduled_run.log"
mkdir -p "$REPO_DIR/artifacts/cache"
cd "$REPO_DIR"

while true; do
  if ! curl -s -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "$(date) SKIP: server down" >> "$LOG"
    sleep 300
    continue
  fi

  curl -s -m 120 -X POST http://127.0.0.1:8000/api/schedule/auto-freeze \
    > "$REPO_DIR/artifacts/cache/auto_freeze_last.json" 2>&1 \
    || echo "$(date) auto-freeze FAILED" >> "$LOG"

  # shellcheck disable=SC1091
  . .venv/bin/activate
  python "$REPO_DIR/scripts/collect_drafts.py" --all >> "$LOG" 2>&1

  curl -s -m 120 -X POST http://127.0.0.1:8000/api/schedule/auto-notify >> "$LOG" 2>&1 \
    || echo "$(date) auto-notify FAILED" >> "$LOG"

  sleep 300
done
