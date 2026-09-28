@echo off
setlocal
rem 5-минутный цикл живого турнира (NOTIF-001 + авто-фриз):
rem   1) Портал Liquipedia -> импорт матча -> заморозка за 10 мин -> пуш в Telegram
rem   2) Сбор драфтов доигранных карт (Gate-2), идемпотентен
rem   3) Уведомления: старт турнира / старт матча / готовый драфт
rem Запускается тихо через scripts/live_cycle_silent.py (pythonw, CREATE_NO_WINDOW).
set ROOT=C:\Users\SystemX\ZCodeProject\d2intel
set LOG=%ROOT%\artifacts\cache\scheduled_run.log
cd /d "%ROOT%"

rem Здоровье сервера: если лёг — пропускаем тик, не спамим лог ошибками.
curl -s -m 5 http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 (
  echo %date% %time% SKIP: server down >> "%LOG%"
  exit /b 0
)

rem 1) Авто-заморозка (импорт из портала + freeze за 10 мин + пуш).
curl -s -m 120 -X POST http://127.0.0.1:8000/api/schedule/auto-freeze > "%ROOT%\artifacts\cache\auto_freeze_last.json" 2>&1
if errorlevel 1 echo %date% %time% auto-freeze FAILED >> "%LOG%"

rem 2) Сбор драфтов доигранных карт (Gate-2). Уже собранное пропускает.
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\collect_drafts.py" --all >> "%LOG%" 2>&1

rem 3) Уведомления (NOTIF-001): турнир / старт матча / готовый драфт.
curl -s -m 120 -X POST http://127.0.0.1:8000/api/schedule/auto-notify >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% auto-notify FAILED >> "%LOG%"

exit /b 0
