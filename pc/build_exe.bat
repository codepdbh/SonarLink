@echo off
setlocal
cd /d "%~dp0"

if not exist ".venv\Scripts\python.exe" (
  echo [ERROR] No existe .venv. Crea el entorno primero:
  echo         python -m venv .venv
  exit /b 1
)

if not exist "assets\server_icon.ico" (
  echo [ERROR] Falta assets\server_icon.ico
  exit /b 1
)

if not exist "version_info.txt" (
  echo [ERROR] Falta version_info.txt
  exit /b 1
)

call ".venv\Scripts\activate"
python -m pip install --upgrade pip
python -m pip install pyinstaller

pyinstaller ^
  --noconfirm ^
  --clean ^
  --onefile ^
  --windowed ^
  --name "SonarLink-Server" ^
  --icon "assets\server_icon.ico" ^
  --add-data "assets\server_icon.ico;assets" ^
  --version-file "version_info.txt" ^
  server_gui.py

if %errorlevel% neq 0 (
  echo [ERROR] Fallo el empaquetado.
  exit /b %errorlevel%
)

echo [OK] EXE generado en: dist\SonarLink-Server.exe
endlocal
