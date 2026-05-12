@echo off
set "ROOT=%~dp0"
cd /d "%ROOT%web"

:: Pre-flight: проверка что python.exe в venv работает
venv\Scripts\python.exe --version >nul 2>&1
if errorlevel 1 (
    echo.
    echo [ERROR] web\venv is broken: python.exe is missing or not executable.
    echo.
    echo This typically happens when the Python interpreter the venv was created
    echo with was removed or auto-updated ^(e.g. Microsoft Store Python^).
    echo.
    echo To recreate:
    echo     rmdir /s /q web\venv
    echo     "C:\Program Files\Python312\python.exe" -m venv web\venv
    echo     web\venv\Scripts\python.exe -m pip install -r web\requirements.txt
    echo.
    pause
    exit /b 1
)

:: Pre-flight: проверка что uvicorn установлен
venv\Scripts\python.exe -c "import uvicorn" 2>nul
if errorlevel 1 (
    echo.
    echo [ERROR] uvicorn is not installed in web\venv.
    echo.
    echo Run:
    echo     web\venv\Scripts\python.exe -m pip install -r web\requirements.txt
    echo.
    pause
    exit /b 1
)

cd /d "%ROOT%"
set "CMD=venv\Scripts\python.exe -m uvicorn app:app --port 8000 --reload"

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
