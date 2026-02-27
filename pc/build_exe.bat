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

if not exist "assets\platform-tools\adb.exe" (
  echo [ERROR] Falta assets\platform-tools\adb.exe
  exit /b 1
)

if not exist "assets\platform-tools\AdbWinApi.dll" (
  echo [ERROR] Falta assets\platform-tools\AdbWinApi.dll
  exit /b 1
)

if not exist "assets\platform-tools\AdbWinUsbApi.dll" (
  echo [ERROR] Falta assets\platform-tools\AdbWinUsbApi.dll
  exit /b 1
)

if not exist "assets\driver" (
  echo [ERROR] Falta carpeta assets\driver
  exit /b 1
)

if not exist "assets\driver\VBCABLE_Setup_x64.exe" if not exist "assets\driver\VBCABLE_Setup.exe" (
  echo [ERROR] Falta VBCABLE_Setup_x64.exe o VBCABLE_Setup.exe en assets\driver
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
  --add-data "assets\platform-tools\adb.exe;assets\platform-tools" ^
  --add-data "assets\platform-tools\AdbWinApi.dll;assets\platform-tools" ^
  --add-data "assets\platform-tools\AdbWinUsbApi.dll;assets\platform-tools" ^
  --add-data "assets\driver;assets\driver" ^
  --version-file "version_info.txt" ^
  server_gui.py

if %errorlevel% neq 0 (
  echo [ERROR] Fallo el empaquetado.
  exit /b %errorlevel%
)

echo [OK] EXE generado en: dist\SonarLink-Server.exe
endlocal
