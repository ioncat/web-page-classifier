@echo off
set "ROOT=%~dp0"
set "CMD=call venv\Scripts\activate && python -m uvicorn app:app --port 8000 --reload"

:: Открываем в Windows Terminal если доступен, иначе обычный cmd
where wt >nul 2>&1
if %errorlevel% == 0 (
    wt -d "%ROOT%web" cmd /k "%CMD%"
) else (
    start "Web UI" /d "%ROOT%web" cmd /k "%CMD%"
)

:: Даём серверу 2 секунды запуститься, затем открываем браузер
timeout /t 2 /nobreak >nul
start http://localhost:8000
