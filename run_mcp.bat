@echo off
cd /d "%~dp0"
set PYTHONPATH=%~dp0
.venv\Scripts\python.exe -m src.a2a.mcp_server
