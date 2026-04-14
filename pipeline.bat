@echo off
cd /d "%~dp0pipeline"
call venv\Scripts\activate
python main.py %*
