# SonarLink

Windows PC audio to Android over local network, then Android routes to Bluetooth headphones.

PC (Windows) -> Wi-Fi -> Android -> Bluetooth

## ES - Que es y para que sirve

SonarLink nace para resolver un problema simple: escuchar audio de una PC sin Bluetooth usando el telefono Android como puente.

Sirve para:
- Musica, videos y audio del sistema de Windows.
- Uso local en la misma red Wi-Fi.
- Evitar hardware extra en escenarios basicos.

## EN - What it is and why it exists

SonarLink solves a practical issue: listening to PC audio when the computer has no Bluetooth audio output. Android works as the bridge.

Use cases:
- Music, videos, and Windows system audio.
- Local streaming inside the same Wi-Fi network.
- Avoid extra hardware for a simple setup.

## Features

- Real-time PCM streaming over TCP (`pc/server.py` -> Android app).
- IP history on Android for faster reconnect.
- Connection status and start/stop controls.
- Battery optimization warning to reduce background disconnects.
- PC server in CLI and GUI modes.
- Windows EXE build for the server.

## Requirements

- Windows 10/11 (PC side).
- Python 3.10+ (PC side).
- Android device on the same local network.
- Flutter SDK (for app build).
- Optional: `adb` for APK install.

## Quick Start (recommended)

### 1) Start PC server (GUI)

```powershell
cd pc
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python server_gui.py
```

Alternative shortcut:

```powershell
cd pc
run_gui.bat
```

### 2) Connect from Android app

1. Open SonarLink on Android.
2. Enter PC local IP and port `5000`.
3. Tap `Conectar`.
4. If asked, disable battery optimization for SonarLink.

### 3) Optional: USB mode (no Wi-Fi)

1. Connect Android to PC via USB.
2. Enable USB debugging on Android.
3. In `SonarLink Server` GUI, click `Activar USB`.
4. In Android app, select `USB` mode and connect.

In USB mode, Android uses `127.0.0.1:<puerto>` through `adb reverse`.
The PC GUI first looks for `pc/assets/platform-tools/adb.exe`.

## PC Server (CLI)

List capture devices:

```powershell
cd pc
.\.venv\Scripts\activate
python server.py --backend soundcard --list
python server.py --backend sounddevice --list
```

Run server (usually best on many Realtek setups):

```powershell
python server.py --backend soundcard --host 0.0.0.0 --port 5000
```

Alternative backend:

```powershell
python server.py --backend sounddevice --host 0.0.0.0 --port 5000
```

Capture test to WAV (verify loopback before using phone):

```powershell
python server.py --backend soundcard --test-record 5 --outfile capture_test.wav
```

## Build Android APK

From project root:

```powershell
flutter clean
flutter pub get
flutter build apk --release
```

Output:

`build/app/outputs/flutter-apk/app-release.apk`

Debug APK:

```powershell
flutter build apk --debug
```

Current Android package id:

`com.codepdbh.sonarlink`

## Build PC Server as EXE

```powershell
cd pc
build_exe.bat
```

Output:

`pc/dist/SonarLink-Server.exe`

## Google Play Resources

- Privacy policy HTML: `docs/privacy-policy.html`
- Suggested Pages URL:
  `https://codepdbh.github.io/SonarLink/privacy-policy.html`

## Common Issues

- No audio:
  - Try `--backend soundcard`.
  - Check if `capture_test.wav` has sound.
- `numpy` 2.x error with `soundcard`:
  - Run `pip install "numpy<2.0"`.
- Android cannot connect:
  - PC and phone must be on the same Wi-Fi/LAN.
  - Allow Python/server in Windows Firewall (private network).
- Works once then stops after idle:
  - Keep app excluded from battery optimization.

## Project Structure

- `lib/main.dart` - Flutter UI and connection flow.
- `android/app/src/main/kotlin/com/codepdbh/sonarlink/MainActivity.kt` - native Android audio path.
- `pc/server.py` - TCP audio capture/streaming server.
- `pc/server_gui.py` - desktop GUI wrapper for server.
- `pc/README.md` - focused guide for PC module.
- `docs/privacy-policy.html` - bilingual privacy policy page.
