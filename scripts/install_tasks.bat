@echo off
rem ============================================================================
rem  Установка задач Планировщика для d2intel (запустить ОТ ИМЕНИ АДМИНИСТРАТОРА).
rem  Правый клик по файлу -> "Запуск от имени администратора".
rem
rem  Задачи:
rem    d2intel-server      - uvicorn стартует при загрузке ПК (переживает ребут)
rem    d2intel-live-cycle  - цикл каждые 5 мин (авто-фриз + драфты + уведомления)
rem
rem  Запуск под SYSTEM, чтобы работало без активного входа владельца.
rem  Если нужен запуск только при входе владельца — замените /ru SYSTEM на
rem  /ru %USERNAME% (без пароля; тогда задача сработает после логина).
rem ============================================================================
setlocal
set ROOT=C:\Users\SystemX\ZCodeProject\d2intel
set PYTHONW=%ROOT%\.venv\Scripts\pythonw.exe

rem Остановить старый сервер на :8000 (если запущен не как сервис),
rem чтобы задача d2intel-server не споткнулась об занятый порт.
for /f "tokens=5" %%a in ('netstat -ano ^| findstr /R ":8000 .*LISTENING"') do taskkill /pid %%a /f >nul 2>&1

schtasks /create /tn "d2intel-server" /tr "\"%ROOT%\scripts\run_server.bat\"" /sc onstart /ru SYSTEM /f
if errorlevel 1 goto :fail

schtasks /create /tn "d2intel-live-cycle" /tr "\"%PYTHONW%\" \"%ROOT%\scripts\live_cycle_silent.py\"" /sc minute /mo 5 /ru SYSTEM /f
if errorlevel 1 goto :fail

rem Сразу поднять сервер и сделать первый тик цикла (без ожидания ребута).
schtasks /run /tn "d2intel-server" >nul 2>&1
timeout /t 3 >nul
schtasks /run /tn "d2intel-live-cycle" >nul 2>&1

echo.
echo OK: задачи зарегистрированы и запущены.
echo   schtasks /query /tn "d2intel-server"
echo   schtasks /query /tn "d2intel-live-cycle"
echo.
echo Сервер поднят как сервис (переживёт ребут). Лог цикла: artifacts\cache\scheduled_run.log
goto :end

:fail
echo.
echo ОШИБКА регистрации задачи. Запустите этот файл от имени администратора.

:end
pause
endlocal
