# Servidor SonarLink (PC)

Este modulo permite transmitir el audio del PC a la app Android por Wi-Fi.

## Modos disponibles
- `server.py`: modo consola (CLI).
- `server_gui.py`: interfaz grafica (iniciar, detener, logs, listar dispositivos).

## Requisitos
- Windows 10/11
- Python 3.10+

## Instalacion
```powershell
cd pc
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Usar interfaz grafica
```powershell
cd pc
.\.venv\Scripts\activate
python server_gui.py
```

O directo:
```powershell
cd pc
run_gui.bat
```

## Usar modo consola
```powershell
cd pc
.\.venv\Scripts\activate
python server.py --backend soundcard --host 0.0.0.0 --port 5000
```

## Listar dispositivos
```powershell
python server.py --backend soundcard --list
python server.py --backend sounddevice --list
```

## Probar captura de audio (WAV)
```powershell
python server.py --backend soundcard --test-record 5 --outfile capture_test.wav
```

## Empaquetar en .exe
```powershell
cd pc
build_exe.bat
```

Salida esperada:
- `pc\dist\SonarLink-Server.exe`

## Notas
- Si aparece error con `numpy 2.x`, ejecutar:
```powershell
pip install "numpy<2.0"
```
- Permite el servidor en firewall de Windows para redes privadas.
