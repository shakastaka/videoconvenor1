@echo off
setlocal
cd /d "%~dp0"
title Video Toolbox Launcher

where ffmpeg >nul 2>nul
if errorlevel 1 (
  echo [ERROR] FFmpeg is not installed or is missing from PATH.
  echo Install it once with: winget install Gyan.FFmpeg
  echo Then close this window and run start_windows.bat again.
  pause
  exit /b 1
)

where py >nul 2>nul
if errorlevel 1 (
  where python >nul 2>nul
  if errorlevel 1 (
    echo [ERROR] Python 3.11 or newer is required.
    echo Download it from https://www.python.org/downloads/
    pause
    exit /b 1
  )
  set "PYTHON_CMD=python"
) else (
  set "PYTHON_CMD=py -3"
)

where npm.cmd >nul 2>nul
if errorlevel 1 (
  echo [ERROR] Node.js is required. Install the LTS version from https://nodejs.org/
  pause
  exit /b 1
)

if not exist ".venv\Scripts\python.exe" (
  echo [1/3] Creating Python environment...
  %PYTHON_CMD% -m venv .venv
  if errorlevel 1 goto :failed
)

".venv\Scripts\python.exe" -c "import fastapi, uvicorn, yt_dlp, faster_whisper" >nul 2>nul
if errorlevel 1 (
  echo [2/3] Installing backend dependencies...
  ".venv\Scripts\python.exe" -m pip install --upgrade pip
  ".venv\Scripts\python.exe" -m pip install -r backend\requirements.txt
  if errorlevel 1 goto :failed
)

if not exist "frontend\node_modules" (
  echo [3/3] Installing frontend dependencies...
  call npm.cmd install --prefix frontend
  if errorlevel 1 goto :failed
)

echo Starting Video Toolbox...
start "Video Toolbox API" cmd /k ".venv\Scripts\python.exe -m uvicorn backend.app:app --host 127.0.0.1 --port 8000"
start "Video Toolbox Frontend" cmd /k "npm.cmd run dev --prefix frontend"
timeout /t 4 /nobreak >nul
start "" "http://127.0.0.1:5173"
exit /b 0

:failed
echo.
echo [ERROR] Installation failed. Copy the error text and send it in the chat.
pause
exit /b 1
