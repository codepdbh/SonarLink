# SonarLink

## ES - Descripcion breve
SonarLink nace de una necesidad practica: usar audifonos Bluetooth desde una PC que no tiene Bluetooth ni salida por cable util para audifonos.  
La solucion convierte el celular Android en puente de audio:

PC (Windows) -> Wi-Fi -> Android -> audifonos Bluetooth.

## EN - Short description
SonarLink was created to solve a practical issue: using Bluetooth headphones from a PC without built-in Bluetooth (or no usable wired headphone output).  
The app turns an Android phone into an audio bridge:

Windows PC -> Wi-Fi -> Android -> Bluetooth headphones.

## ES - Para que sirve
- Escuchar musica y videos del PC en audifonos Bluetooth conectados al telefono.
- Evitar comprar hardware extra para un caso de uso simple.
- Mantener una latencia razonable para multimedia.

## EN - What it is for
- Listen to PC music/videos on Bluetooth headphones connected to the phone.
- Avoid extra hardware for a simple use case.
- Keep practical latency for multimedia playback.

## ES - Arquitectura
1. `pc/server.py` captura audio del sistema (loopback) en Windows.
2. El servidor envia PCM por TCP a la app Android.
3. La app Android reproduce audio y Android lo enruta a Bluetooth.

## EN - Architecture
1. `pc/server.py` captures system audio (loopback) on Windows.
2. The server streams PCM over TCP to Android.
3. The Android app plays audio and Android routes it to Bluetooth.

## ES - Requisitos
- Windows 10/11 en el PC.
- Python 3.10+ en el PC.
- Android en la misma red Wi-Fi.
- Flutter SDK (para compilar APK).
- Opcional: `adb` para instalacion manual del APK.

## EN - Requirements
- Windows 10/11 on the PC.
- Python 3.10+ on the PC.
- Android phone on the same Wi-Fi network.
- Flutter SDK (to build APK).
- Optional: `adb` for manual APK install.

## ES - Configurar y ejecutar servidor Python
```powershell
cd pc
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Opcional: listar dispositivos disponibles.
```powershell
python server.py --list
python server.py --backend soundcard --list
```

Ejecutar servidor (recomendado en muchos equipos):
```powershell
python server.py --backend soundcard --host 0.0.0.0 --port 5000
```

Alternativa:
```powershell
python server.py --backend sounddevice --host 0.0.0.0 --port 5000
```

Prueba de captura antes de conectar el celular:
```powershell
python server.py --backend soundcard --test-record 5 --outfile capture_test.wav
```

## EN - Setup and run Python server
```powershell
cd pc
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
```

Optional: list available devices.
```powershell
python server.py --list
python server.py --backend soundcard --list
```

Run server (recommended on many systems):
```powershell
python server.py --backend soundcard --host 0.0.0.0 --port 5000
```

Alternative:
```powershell
python server.py --backend sounddevice --host 0.0.0.0 --port 5000
```

Capture test before connecting the phone:
```powershell
python server.py --backend soundcard --test-record 5 --outfile capture_test.wav
```

## ES - Ejecutar app en modo desarrollo
Desde la raiz del proyecto:
```powershell
flutter pub get
flutter run
```

En la app:
1. Ingresa la IP local del PC y puerto `5000`.
2. Pulsa `Conectar`.
3. Si aparece alerta de bateria, desactiva optimizacion para evitar cortes.

## EN - Run app in development mode
From project root:
```powershell
flutter pub get
flutter run
```

In the app:
1. Enter your PC local IP and port `5000`.
2. Tap `Conectar`.
3. If battery warning appears, disable optimization to avoid disconnects.

## ES - Compilar APK
Desde la raiz del proyecto:
```powershell
flutter clean
flutter pub get
flutter build apk --release
```

APK generado en:
`build/app/outputs/flutter-apk/app-release.apk`

APK de prueba (debug):
```powershell
flutter build apk --debug
```

## EN - Build APK
From project root:
```powershell
flutter clean
flutter pub get
flutter build apk --release
```

Generated APK path:
`build/app/outputs/flutter-apk/app-release.apk`

Debug APK:
```powershell
flutter build apk --debug
```

## ES - Problemas comunes
- No hay audio:
  - Prueba `--backend soundcard`.
  - Verifica que el WAV de prueba tenga audio.
- Error con `numpy` 2.x:
  - Ejecuta `pip install "numpy<2.0"`.
- El celular no conecta:
  - PC y telefono deben estar en la misma red Wi-Fi.
  - Permite el servidor en firewall de Windows para red privada.
- Se desconecta al bloquear pantalla:
  - Desactiva optimizacion de bateria para SonarLink.

## EN - Common issues
- No audio:
  - Try `--backend soundcard`.
  - Verify test WAV contains audio.
- `numpy` 2.x error:
  - Run `pip install "numpy<2.0"`.
- Phone cannot connect:
  - PC and phone must be on the same Wi-Fi.
  - Allow server through Windows Firewall (private network).
- Disconnects when screen is locked:
  - Disable battery optimization for SonarLink.

## ES/EN - Estructura rapida
- `lib/main.dart`: interfaz Flutter y flujo de conexion.
- `android/app/src/main/kotlin/.../MainActivity.kt`: audio nativo y estado Android.
- `pc/server.py`: captura y streaming de audio TCP.
- `pc/requirements.txt`: dependencias Python.
