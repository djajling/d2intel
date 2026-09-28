@echo off
setlocal
rem 30-минутный цикл итогов (NOTIF-002): свежие игры -> канон -> закрытие серий
rem   -> reconcile -> auto-notify (шаг match_result пушит итог в Telegram).
rem Лёгкий 5-минутный цикл (live_cycle.bat) не трогаем: normalize идёт ~8 мин
rem   и в 5-минутное окно не влезает. Защита от наложения — lock-файл.
rem Запускается тихо через scripts/result_cycle_silent.py (pythonw, CREATE_NO_WINDOW).
set ROOT=C:\Users\SystemX\ZCodeProject\d2intel
set LOG=%ROOT%\artifacts\cache\result_cycle.log
set LOCK=%ROOT%\artifacts\cache\result_cycle.lock
cd /d "%ROOT%"

rem Уже идёт прошлый тик (normalize не уложился в окно) — пропускаем без шума.
if exist "%LOCK%" (
  echo %date% %time% SKIP: previous tick still running >> "%LOG%"
  exit /b 0
)
echo %date% %time% > "%LOCK%"

rem 1) Свежие завершённые игры из OpenDota (дешёвый head-sync, ~100 наблюдений).
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\ingest_opendota_once.py" --head >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% ingest-head FAILED >> "%LOG%"

rem 2) Нормализация в канон (долгая, ~8 мин; lock держит окно).
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\normalize_once.py" >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% normalize FAILED >> "%LOG%"

rem 3) Драфты свежих карт (Gate-2): только недостающие, идемпотентно.
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\backfill_drafts.py" --limit 30 --sleep 2.0 >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% backfill-drafts FAILED >> "%LOG%"

rem 4) picks_bans -> draft_observed фикстур (для draft_ready в 5-мин цикле).
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\collect_drafts.py" --all >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% collect-drafts FAILED >> "%LOG%"

rem 5) Закрытие доигранных серий по Liquipedia + reconcile заморозок.
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\close_finished_series.py" >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% close-series FAILED >> "%LOG%"
"%ROOT%\.venv\Scripts\python.exe" "%ROOT%\scripts\prospective_reconcile.py" --all >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% reconcile FAILED >> "%LOG%"

rem 6) Уведомления (шаг match_result подхватит свежие reconcile; остальное
rem    идемпотентно промолчит). Сервер нужен только здесь.
curl -s -m 5 http://127.0.0.1:8000/health >nul 2>&1
if errorlevel 1 (
  echo %date% %time% SKIP notify: server down, итоги уйдут следующим 5-мин тиком >> "%LOG%"
  del "%LOCK%"
  exit /b 0
)
curl -s -m 120 -X POST http://127.0.0.1:8000/api/schedule/auto-notify >> "%LOG%" 2>&1
if errorlevel 1 echo %date% %time% auto-notify FAILED >> "%LOG%"

del "%LOCK%"
exit /b 0
