#!/usr/bin/env bash
# d2intel: 30-минутный цикл итогов на телефоне (Termux, NOTIF-002).
#   ingest --head -> normalize -> backfill drafts -> collect_drafts --all
#   -> close_finished_series -> prospective_reconcile --all -> auto-notify
# Лёгкий 5-минутный цикл (live_cycle.sh) не трогаем: normalize идёт ~8 мин.
# Запуск фоном: nohup scripts/termux/result_cycle.sh > artifacts/cache/result_cycle.out.log 2>&1 &
set -u
REPO_DIR="${REPO_DIR:-$HOME/d2intel}"
LOG="$REPO_DIR/artifacts/cache/result_cycle.log"
LOCK="$REPO_DIR/artifacts/cache/result_cycle.lock"
mkdir -p "$REPO_DIR/artifacts/cache"
cd "$REPO_DIR"

# shellcheck disable=SC1091
. .venv/bin/activate

while true; do
  if [ -f "$LOCK" ]; then
    echo "$(date) SKIP: previous tick still running" >> "$LOG"
    sleep 1800
    continue
  fi
  date > "$LOCK"

  python "$REPO_DIR/scripts/ingest_opendota_once.py" --head >> "$LOG" 2>&1 \
    || echo "$(date) ingest-head FAILED" >> "$LOG"

  python "$REPO_DIR/scripts/normalize_once.py" >> "$LOG" 2>&1 \
    || echo "$(date) normalize FAILED" >> "$LOG"

  python "$REPO_DIR/scripts/backfill_drafts.py" --limit 30 --sleep 2.0 >> "$LOG" 2>&1 \
    || echo "$(date) backfill-drafts FAILED" >> "$LOG"

  python "$REPO_DIR/scripts/collect_drafts.py" --all >> "$LOG" 2>&1 \
    || echo "$(date) collect-drafts FAILED" >> "$LOG"

  python "$REPO_DIR/scripts/close_finished_series.py" >> "$LOG" 2>&1 \
    || echo "$(date) close-series FAILED" >> "$LOG"
  python "$REPO_DIR/scripts/prospective_reconcile.py" --all >> "$LOG" 2>&1 \
    || echo "$(date) reconcile FAILED" >> "$LOG"

  if ! curl -s -m 5 http://127.0.0.1:8000/health >/dev/null 2>&1; then
    echo "$(date) SKIP notify: server down, итоги уйдут следующим 5-мин тиком" >> "$LOG"
    rm -f "$LOCK"
    sleep 1800
    continue
  fi
  curl -s -m 120 -X POST http://127.0.0.1:8000/api/schedule/auto-notify >> "$LOG" 2>&1 \
    || echo "$(date) auto-notify FAILED" >> "$LOG"

  rm -f "$LOCK"
  sleep 1800
done
