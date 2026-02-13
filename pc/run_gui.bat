@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No existe .venv. Ejecuta:
  echo         python -m venv .venv
  echo         .venv\Scripts\python -m pip install -r requirements.txt
  exit /b 1
)

call ".venv\Scripts\activate"
python server_gui.py
endlocal
