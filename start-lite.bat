@echo off
title JA-Subs (lite: qwen2.5-3b)
cd /d "%~dp0"
echo Starting JA live subtitle (small model, less VRAM)...
echo.
.venv\Scripts\python.exe -u live_ja.py --model qwen2.5:3b %*
echo.
echo [stopped] press any key to close.
pause >nul
