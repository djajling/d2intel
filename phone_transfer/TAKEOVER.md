# TAKEOVER d2intel: телефон — основной хост (2026-09-28, ночь)

ПК уходит в офлайн. Завтра 29.09 матчи BLAST Slam VIII 13:00/16:00/19:00 МСК.
Дайджест владельцу уже ушёл с ПК. Цель: к 29.09 12:00 МСК живой контур.
Файл — в transfer-ветке рядом с данными, чтобы читался прямо из клона.

## 0. Диагностика (ответом владельцу в TG)

```bash
git -C ~/hermes-sandbox/d2intel log --oneline -1
pg_isready -h localhost
psql -U d2intel -h localhost -d d2intel -c "SELECT count(*) FROM scheduled_match;"
psql -U d2intel -h localhost -d d2intel -c "SELECT count(*) FROM game;"
psql -U d2intel -h localhost -d d2intel -c "SELECT count(*) FROM scheduled_match_notify_state;"
ls ~/hermes-sandbox/d2intel/artifacts/prospective/
```

Плюс: какие ключи есть в `.env` (**только имена**), `alembic current` в репо.

## 1. Код

```bash
git clone https://github.com/djajling/d2intel.git ~/hermes-sandbox/d2intel
cd ~/hermes-sandbox/d2intel && git checkout main && git pull
# жди коммит a784a0a (NOTIF-002 + termux/result_cycle.sh + ночной чек-лист)
python -m venv .venv && . .venv/bin/activate
pip install --upgrade pip
pip install fastapi==0.115.6 uvicorn==0.34.0 jinja2==3.1.6 sqlalchemy==2.0.36 \
  alembic==1.14.1 "psycopg[binary]==3.2.3" pandas==2.2.3 scikit-learn==1.6.1 \
  numpy==2.4.6 joblib==1.6.0 httpx==0.28.1 pydantic==2.10.5
pip install -e .
```

Без catboost (runtime его не требует). Полный гайд: `docs/DEPLOY_TERMUX.md`.

## 2. Данные (эта ветка)

```bash
git fetch origin transfer/phone-2026-09-28 && git checkout transfer/phone-2026-09-28
cat phone_transfer/d2intel_full.dump.part* > /tmp/d2intel_full.dump
pg_restore -h localhost -U d2intel -d d2intel --clean --if-exists /tmp/d2intel_full.dump
mkdir -p ~/hermes-sandbox/d2intel/artifacts/prospective
cp phone_transfer/prospective/*.json ~/hermes-sandbox/d2intel/artifacts/prospective/
git checkout main
```

Проверка: `scheduled_match` = 10 (8 BLAST + 2 Wallachia), `game` > 16000.
`pg_restore` 18-й версии читает `-Fc` из 17-й. Если ругается на версии —
сообщить владельцу (нужен текстовый дамп с ПК).

## 3. Конфиг и схема

`.env` в корне репо: `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` (значения не светить).
Затем:

```bash
.venv/bin/activate && alembic upgrade head   # жди 0008
```

## 4. Запуск (каждый — фоном через nohup, логи в artifacts/cache/)

```bash
nohup scripts/termux/run_server.sh > artifacts/cache/uvicorn.out.log 2>&1 &
nohup scripts/termux/live_cycle.sh > artifacts/cache/cycle.out.log 2>&1 &
nohup scripts/termux/result_cycle.sh > artifacts/cache/result_cycle.out.log 2>&1 &
curl -s 127.0.0.1:8000/health
curl -s -X POST "127.0.0.1:8000/api/schedule/auto-notify?dry_run=true"
```

Обновить `~/.termux/boot/d2intel-boot.sh` из репо (там 4 процесса) + `termux-wake-lock`.
Владельцу руками: снять battery-optimization с Termux, иначе Doze убьёт циклы.

## 5. Завтра

Следить за `artifacts/cache/result_cycle.log`. После каждой карты: драфт в
`draft_observed`, freeze → reconcile, итог в TG. Сбои и статусы — владельцу в TG.
Цикл насоса: freeze за 10 мин до старта → `match_start`; после карт `draft_ready`;
после reconcile `match_result` (попали/нет + log_loss/brier).
