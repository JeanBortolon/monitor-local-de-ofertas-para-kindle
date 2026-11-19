@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd /d "%~dp0"
python "%~dp0kindle.py" >> "%~dp0execucoes.log" 2>&1