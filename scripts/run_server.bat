@echo off
setlocal
rem Запуск uvicorn для d2intel как фонового сервиса (без консольного окна).
rem config.py не читает .env — секреты (STRATZ/TELEGRAM) пробрасываем в окружение.
set ROOT=C:\Users\SystemX\ZCodeProject\d2intel
set SRC=%ROOT%\src
cd /d "%SRC%"

for /f "usebackq eol=# tokens=1,* delims==" %%A in ("%ROOT%\.env") do (
  if not "%%~A"=="" if not "%%~B"=="" set "%%~A=%%~B"
)

rem pythonw -> процесс без консоли: не ворует фокус из Dota 2 и не мигает окном.
"%ROOT%\.venv\Scripts\pythonw.exe" -m uvicorn d2intel.app:app --host 127.0.0.1 --port 8000 --app-dir "%SRC%" >> "%ROOT%\artifacts\cache\uvicorn.out.log" 2>&1
endlocal
