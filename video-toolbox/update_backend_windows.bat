@echo off
setlocal
cd /d "%~dp0"
if not exist ".venv\Scripts\python.exe" (
  echo Run start_windows.bat first.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" -m pip install -U --pre "yt-dlp[default]"
echo.
echo yt-dlp was updated. Restart Video Toolbox.
pause
