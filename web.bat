@echo off
set CMD=cd /d "%~dp0web" && call venv\Scripts\activate && python -m uvicorn app:app --port 8000 --reload

:: Открываем в Windows Terminal если доступен, иначе обычный cmd
where wt >nul 2>&1
if %errorlevel% == 0 (
    start wt -p "Command Prompt" cmd /k "%CMD%"
) else (
    start "Web UI" cmd /k "%CMD%"
)

:: Даём серверу 2 секунды запуститься, затем открываем браузер
timeout /t 2 /nobreak >nul
start http://localhost:8000
