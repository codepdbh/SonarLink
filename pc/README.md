# Servidor de Audio (PC)

Este servidor captura el audio del sistema en Windows (WASAPI loopback) y lo envía por TCP a la app Android.

## Requisitos
- Python 3.10+
- Windows

## Instalación
```powershell
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

## Uso
1. Opcional: listar dispositivos
```powershell
python server.py --list
```

2. Ejecutar servidor
```powershell
python server.py --host 0.0.0.0 --port 5000
```

3. En Android, ingresa la IP del PC y el puerto.

Si el firewall de Windows pregunta, permite el acceso para redes privadas.

## Problemas comunes
- **Sin audio:** prueba otro backend de captura:
```powershell
python server.py --backend soundcard
```
Luego usa `--list` para elegir microfono loopback si es necesario:
```powershell
python server.py --backend soundcard --list
python server.py --backend soundcard --device 0
```

- **Error con numpy 2.x:** soundcard falla con numpy 2.x. Solucion:
```powershell
pip install "numpy<2.0"
```

- **Verificar captura:** graba 5 segundos a WAV y revisa si hay audio:
```powershell
python server.py --test-record 5 --outfile capture_test.wav
```

- **Error con loopback:** si ves un error de `WasapiSettings` o no hay audio, actualiza:
```powershell
pip install -U sounddevice
```
Si tu equipo no soporta loopback automático, habilita **Mezcla estéreo** en Windows y usa `--device <id>` (ver `--list`).

## Parámetros útiles
- `--device 3` para elegir dispositivo (sounddevice) o speaker (soundcard).
- `--samplerate 48000` y `--channels 2` (por defecto).
