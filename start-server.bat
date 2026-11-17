@echo off
title JA-Subs Local Server
cd /d "%~dp0"
echo Starting local subtitle service on ws://127.0.0.1:8765
echo Keep this window open while watching. Close it to stop.
echo.
.venv\Scripts\python.exe -u server_ws.py --loopback
echo.
echo [stopped] press any key to close.
pause >nul
