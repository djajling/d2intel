#!/usr/bin/env bash
# d2intel: автозапуск на телефоне (Termux:Boot).
# Положи этот файл в ~/.termux/boot/ (права +x). Termux:Boot вызовет его при
# загрузке телефона. Поднимает postgres + uvicorn + 5-мин цикл, держит wake-lock.
set -u
termux-wake-lock

REPO_DIR="${REPO_DIR:-$HOME/d2intel}"
PGDATA="${PGDATA:-$HOME/d2intel_pgdata}"
LOG_DIR="$REPO_DIR/artifacts/cache"
mkdir -p "$LOG_DIR"

# 1) PostgreSQL
pg_ctl -D "$PGDATA" -l "$HOME/d2intel_pg.log" start || true
for _ in $(seq 1 30); do pg_isready -h localhost >/dev/null 2>&1 && break; sleep 1; done

# 2) Сервер (фон)
nohup "$REPO_DIR/scripts/termux/run_server.sh" > "$LOG_DIR/uvicorn.out.log" 2>&1 &

# 3) Цикл живого турнира (фон)
nohup "$REPO_DIR/scripts/termux/live_cycle.sh" > "$LOG_DIR/cycle.out.log" 2>&1 &

# 4) Цикл итогов NOTIF-002 (фон, каждые 30 мин)
nohup "$REPO_DIR/scripts/termux/result_cycle.sh" > "$LOG_DIR/result_cycle.out.log" 2>&1 &

echo "d2intel boot: postgres + server + live-cycle + result-cycle started"
