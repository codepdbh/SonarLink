@echo off
setlocal

cd /d "%~dp0"

echo Creando entorno virtual...
python -m venv .venv || goto :error

call ".venv\Scripts\activate" || goto :error

echo Iniciando servidor...
python server.py --host 0.0.0.0 --port 5000
goto :eof

:error
echo.
echo Ocurrio un error. Revisa los mensajes anteriores.
exit /b 1
