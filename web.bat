@echo off
start "Web UI" cmd /k "cd /d "%~dp0web" && call venv\Scripts\activate && python -m uvicorn app:app --port 8000 --reload"
