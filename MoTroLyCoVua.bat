@echo off
setlocal

cd /d "%~dp0"

if not exist ".venv\Scripts\pythonw.exe" (
  echo Khong tim thay moi truong Python cua ChessAssistant.
  echo Vui long kiem tra thu muc .venv.
  pause
  exit /b 1
)

start "" ".venv\Scripts\pythonw.exe" "%~dp0TroLyCoVua.pyw"
