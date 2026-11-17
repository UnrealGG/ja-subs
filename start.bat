@echo off
chcp 65001 >nul
cd /d "%~dp0"
set PYTHONIOENCODING=utf-8

echo ==========================================
echo   Japanese live subtitle
echo   Wait for "ready", then play any video.
echo   Close from the right-click menu or top-right X.
echo   Ctrl+C in this console stops the launcher.
echo ==========================================
echo.

".venv\Scripts\python.exe" -u live_ja.py %*

if errorlevel 1 (
  echo.
  echo [FAILED] copy the error above and paste it back.
  pause
)
