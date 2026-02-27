# SonarLink

PC (Windows) -> Android -> Bluetooth  
Audio streaming bridge for computers without Bluetooth audio output.

## ES - Que es y para que sirve

SonarLink nace para resolver un problema practico: escuchar el audio de una PC sin Bluetooth usando un telefono Android como puente.

Uso principal:
- Musica, videos y audio del sistema de Windows.
- Modo Wi-Fi/LAN y modo USB (`adb reverse`).
- Microfono del telefono hacia la PC (mic bridge) de forma opcional.

## EN - What it is and why it exists

SonarLink solves a practical issue: play PC audio on Bluetooth headphones when the computer has no Bluetooth audio output. Android acts as the bridge.

Main use:
- Music, videos, and Windows system audio.
- Wi-Fi/LAN mode and USB mode (`adb reverse`).
- Optional phone microphone to PC (mic bridge).

## Current Features

- Real-time PCM audio bridge from `pc/server.py` to Android.
- Optional mic bridge (Android mic -> PC output device).
- Separate toggles for `Audio bridge` and `Mic bridge`.
- Auto-detected local IPs in server GUI.
- USB helper using bundled `assets/platform-tools/adb.exe`.
- Driver check on startup in server GUI (VB-CABLE prompt/install when bundled).
- Android IP history and reconnect workflow.
- CLI server and GUI server.
- Windows EXE packaging.

## Requirements

- Windows 10/11.
- Python 3.10+.
- Android phone.
- Same LAN/Wi-Fi for network mode.
- USB cable + USB debugging for USB mode.
- Flutter SDK only if you want to build the Android app.

## Quick Start

### 1) Run server GUI

```powershell
cd pc
python -m venv .venv
.\.venv\Scripts\activate
pip install -r requirements.txt
python server_gui.py
```

Alternative:

```powershell
cd pc
run_gui.bat
```

### 2) Connect Android app (Wi-Fi)

1. Open SonarLink app.
2. Use one IP shown in the server GUI.
3. Use `5000` for audio and `5001` for mic bridge (optional).
4. Tap `Conectar`.

### 3) Optional USB mode

1. Connect phone by USB and enable USB debugging.
2. In server GUI, click `Activar USB`.
3. In Android app, select USB mode (`host 127.0.0.1`).

## CLI Usage

List input/loopback devices:

```powershell
cd pc
.\.venv\Scripts\activate
python server.py --backend soundcard --list
python server.py --backend sounddevice --list
```

List output devices (useful for mic bridge output):

```powershell
python server.py --list-outputs
```

Run with both bridges enabled:

```powershell
python server.py --backend soundcard --host 0.0.0.0 --port 5000 --mic-port 5001 --audio-bridge on --mic-bridge on
```

Run only audio:

```powershell
python server.py --backend soundcard --host 0.0.0.0 --port 5000 --audio-bridge on --mic-bridge off
```

Run only microphone:

```powershell
python server.py --backend soundcard --host 0.0.0.0 --port 5000 --mic-port 5001 --audio-bridge off --mic-bridge on
```

## Build Android APK / AAB

```powershell
flutter clean
flutter pub get
flutter build apk --release
flutter build appbundle --release
```

Outputs:
- `build/app/outputs/flutter-apk/app-release.apk`
- `build/app/outputs/bundle/release/app-release.aab`

Package id:
- `com.codepdbh.sonarlink`

## Build Windows EXE (Server GUI)

```powershell
cd pc
build_exe.bat
```

Output:
- `pc/dist/SonarLink-Server.exe`

`build_exe.bat` includes:
- `assets/platform-tools/*` for ADB.
- `assets/driver/*` for VB-CABLE installer resources.

## Privacy Policy

- File: `docs/privacy-policy.html`
- URL: `https://codepdbh.github.io/SonarLink/privacy-policy.html`

## Common Issues

- No PC audio: try backend `soundcard`.
- No PC audio: verify capture with test WAV:

```powershell
python server.py --backend soundcard --test-record 5 --outfile capture_test.wav
```

- `numpy` 2.x error with `soundcard`:

```powershell
pip install "numpy<2.0"
```

- Android reconnect loops or random disconnects: exclude SonarLink from battery optimization.
- Android reconnect loops or random disconnects: keep phone and PC on a stable local network.
- Mic bridge output: by default it prefers `CABLE Input (VB-Audio Virtual C ... [MME])`.
- Mic bridge output: override with `Mic out dev (opc.)` in GUI or `--mic-output-device <id>` in CLI.

## Project Structure

- `lib/main.dart` - Flutter UI and connection flow.
- `android/app/src/main/kotlin/com/codepdbh/sonarlink/MainActivity.kt` - Android audio/mic native bridge.
- `pc/server.py` - audio + mic bridge server.
- `pc/server_gui.py` - desktop GUI, USB helper, and startup checks.
- `pc/README.md` - PC module quick guide.
- `docs/privacy-policy.html` - privacy policy (ES/EN).
