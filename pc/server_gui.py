import contextlib
import json
import multiprocessing as mp
import os
import queue
import shutil
import socket
import subprocess
import sys
import threading
import tkinter as tk
from tkinter import messagebox, ttk

import server

CONFIG_PATH = os.path.join(os.path.dirname(__file__), "server_gui_config.json")
DEFAULT_CONFIG = {
    "host": "0.0.0.0",
    "port": "5000",
    "backend": "soundcard",
    "device": "",
    "samplerate": "48000",
    "channels": "2",
    "block_frames": "960",
}

APP_DIR = os.path.dirname(os.path.abspath(__file__))
if getattr(sys, "frozen", False) and hasattr(sys, "_MEIPASS"):
    APP_DIR = getattr(sys, "_MEIPASS")
ICON_PATH = os.path.join(APP_DIR, "assets", "server_icon.ico")
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
LOCAL_PROPERTIES_PATH = os.path.join(PROJECT_ROOT, "android", "local.properties")
_ADB_EXECUTABLE: str | None = None
if getattr(sys, "frozen", False):
    RUNTIME_DIR = os.path.dirname(os.path.abspath(sys.executable))
else:
    RUNTIME_DIR = os.path.dirname(os.path.abspath(__file__))
BUNDLED_PLATFORM_TOOLS = os.path.join(APP_DIR, "assets", "platform-tools")


class _QueueWriter:
    def __init__(self, log_queue: "mp.Queue[str]") -> None:
        self._queue = log_queue

    def write(self, text: str) -> None:
        if not text:
            return
        cleaned = text.rstrip()
        if cleaned:
            self._queue.put(cleaned)

    def flush(self) -> None:
        return


def _build_argv(config: dict[str, str]) -> list[str]:
    argv = [
        "server.py",
        "--host",
        config["host"],
        "--port",
        config["port"],
        "--backend",
        config["backend"],
        "--samplerate",
        config["samplerate"],
        "--channels",
        config["channels"],
        "--block-frames",
        config["block_frames"],
    ]
    device = config.get("device", "").strip()
    if device:
        argv.extend(["--device", device])
    return argv


def _run_server_worker(config: dict[str, str], log_queue: "mp.Queue[str]") -> None:
    writer = _QueueWriter(log_queue)
    argv = _build_argv(config)
    old_argv = list(sys.argv)
    sys.argv = argv
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            rc = server.main()
        log_queue.put(f"[worker] finalizado con codigo {rc}")
    except Exception as exc:  # pragma: no cover - subprocess safety
        log_queue.put(f"[worker] error: {exc}")
    finally:
        sys.argv = old_argv


def _run_list_worker(backend: str, log_queue: "mp.Queue[str]") -> None:
    writer = _QueueWriter(log_queue)
    old_argv = list(sys.argv)
    sys.argv = ["server.py", "--backend", backend, "--list"]
    try:
        with contextlib.redirect_stdout(writer), contextlib.redirect_stderr(writer):
            server.main()
    except Exception as exc:  # pragma: no cover - subprocess safety
        log_queue.put(f"[list] error: {exc}")
    finally:
        sys.argv = old_argv


def _detect_local_ips() -> list[str]:
    ips: set[str] = set()

    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, family=socket.AF_INET):
            ip = info[4][0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    # Fallback: detect outbound interface without sending real traffic.
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("8.8.8.8", 80))
            ip = probe.getsockname()[0]
            if ip and not ip.startswith("127."):
                ips.add(ip)
    except OSError:
        pass

    def key(ip: str) -> tuple[int, ...]:
        try:
            return tuple(int(part) for part in ip.split("."))
        except ValueError:
            return (999, 999, 999, 999)

    return sorted(ips, key=key)


def _read_android_sdk_from_local_properties() -> str | None:
    if not os.path.exists(LOCAL_PROPERTIES_PATH):
        return None

    try:
        with open(LOCAL_PROPERTIES_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                cleaned = line.strip()
                if not cleaned.startswith("sdk.dir="):
                    continue
                raw = cleaned.split("=", 1)[1].strip()
                raw = raw.replace("\\:", ":").replace("\\\\", "\\")
                if raw:
                    return raw
    except OSError:
        return None
    return None


def _candidate_adb_paths() -> list[str]:
    candidates: list[str] = []

    # Prefer bundled platform-tools first.
    candidates.append(os.path.join(BUNDLED_PLATFORM_TOOLS, "adb.exe"))
    candidates.append(os.path.join(BUNDLED_PLATFORM_TOOLS, "adb"))
    candidates.append(os.path.join(RUNTIME_DIR, "assets", "platform-tools", "adb.exe"))
    candidates.append(os.path.join(RUNTIME_DIR, "assets", "platform-tools", "adb"))
    candidates.append(os.path.join(RUNTIME_DIR, "platform-tools", "adb.exe"))
    candidates.append(os.path.join(RUNTIME_DIR, "platform-tools", "adb"))

    for env_name in ("ADB_PATH", "SONARLINK_ADB"):
        env_value = os.environ.get(env_name, "").strip().strip('"')
        if env_value:
            candidates.append(env_value)

    from_path = shutil.which("adb")
    if from_path:
        candidates.append(from_path)

    sdk_roots: list[str] = []
    for env_name in ("ANDROID_SDK_ROOT", "ANDROID_HOME"):
        value = os.environ.get(env_name, "").strip().strip('"')
        if value:
            sdk_roots.append(value)

    local_sdk = _read_android_sdk_from_local_properties()
    if local_sdk:
        sdk_roots.append(local_sdk)

    local_app_data = os.environ.get("LOCALAPPDATA", "").strip().strip('"')
    if local_app_data:
        sdk_roots.append(os.path.join(local_app_data, "Android", "Sdk"))

    user_profile = os.environ.get("USERPROFILE", "").strip().strip('"')
    if user_profile:
        sdk_roots.append(os.path.join(user_profile, "AppData", "Local", "Android", "Sdk"))

    for sdk_root in sdk_roots:
        candidates.append(os.path.join(sdk_root, "platform-tools", "adb.exe"))
        candidates.append(os.path.join(sdk_root, "platform-tools", "adb"))

    # Preserve order, remove duplicates.
    dedup: list[str] = []
    seen: set[str] = set()
    for candidate in candidates:
        normalized = os.path.normpath(os.path.expandvars(os.path.expanduser(candidate)))
        key = normalized.lower()
        if key in seen:
            continue
        seen.add(key)
        dedup.append(normalized)
    return dedup


def _resolve_adb_executable() -> str:
    global _ADB_EXECUTABLE

    if _ADB_EXECUTABLE:
        if _ADB_EXECUTABLE.lower() == "adb":
            return _ADB_EXECUTABLE
        if os.path.exists(_ADB_EXECUTABLE):
            return _ADB_EXECUTABLE

    for candidate in _candidate_adb_paths():
        if os.path.isfile(candidate):
            _ADB_EXECUTABLE = candidate
            return candidate

    # Final PATH check.
    if shutil.which("adb"):
        _ADB_EXECUTABLE = "adb"
        return "adb"

    raise RuntimeError(
        "No se encontro adb. Usa assets\\platform-tools\\adb.exe, instala Platform-Tools o define ADB_PATH."
    )


def _run_adb(args: list[str]) -> tuple[subprocess.CompletedProcess[str], str]:
    adb_exe = _resolve_adb_executable()
    try:
        proc = subprocess.run(
            [adb_exe, *args],
            capture_output=True,
            text=True,
            timeout=12,
            check=False,
        )
    except OSError as exc:
        raise RuntimeError(f"No se pudo ejecutar adb ({adb_exe}): {exc}") from exc
    return proc, adb_exe


def _list_adb_devices() -> tuple[list[str], str, str]:
    try:
        proc, adb_exe = _run_adb(["devices"])
    except RuntimeError as exc:
        raise RuntimeError(str(exc)) from exc

    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        raise RuntimeError(output or "adb devices fallo.")

    serials: list[str] = []
    lines = proc.stdout.splitlines()
    for line in lines[1:]:
        cleaned = line.strip()
        if not cleaned:
            continue
        if cleaned.endswith("\tdevice"):
            serials.append(cleaned.split("\t")[0])

    return serials, proc.stdout.strip(), adb_exe


def _adb_reverse(serial: str, port: int, remove: bool) -> None:
    remote = f"tcp:{port}"
    args = ["-s", serial, "reverse"]
    if remove:
        # adb reverse --remove expects only one endpoint argument.
        args.extend(["--remove", remote])
    else:
        args.extend([remote, remote])

    try:
        proc, _adb_exe = _run_adb(args)
    except RuntimeError as exc:
        raise RuntimeError(f"Fallo ejecutando adb reverse en {serial}: {exc}") from exc

    if proc.returncode != 0:
        output = (proc.stderr or proc.stdout or "").strip()
        if remove and "not found" in output.lower():
            # Ya no habia regla activa para ese dispositivo; no es error real.
            return
        raise RuntimeError(output or f"adb reverse fallo para {serial}.")


class ServerGuiApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        self.root.title("SonarLink Server")
        if os.path.exists(ICON_PATH):
            with contextlib.suppress(Exception):
                self.root.iconbitmap(ICON_PATH)
        self.root.geometry("780x560")
        self.root.minsize(700, 480)

        self.config_vars = {
            "host": tk.StringVar(value=DEFAULT_CONFIG["host"]),
            "port": tk.StringVar(value=DEFAULT_CONFIG["port"]),
            "backend": tk.StringVar(value=DEFAULT_CONFIG["backend"]),
            "device": tk.StringVar(value=DEFAULT_CONFIG["device"]),
            "samplerate": tk.StringVar(value=DEFAULT_CONFIG["samplerate"]),
            "channels": tk.StringVar(value=DEFAULT_CONFIG["channels"]),
            "block_frames": tk.StringVar(value=DEFAULT_CONFIG["block_frames"]),
        }

        self.server_process: mp.Process | None = None
        self.log_queue: "mp.Queue[str]" = mp.Queue()
        self.local_ips_var = tk.StringVar(value="Detectando...")
        self.usb_status_var = tk.StringVar(value="USB: inactivo")

        self._build_ui()
        self._load_config()
        self._refresh_local_ips()

        self.root.protocol("WM_DELETE_WINDOW", self._on_close)
        self.root.after(120, self._poll_logs)
        self.root.after(500, self._poll_process)

    def _build_ui(self) -> None:
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(1, weight=1)

        top = ttk.Frame(self.root, padding=12)
        top.grid(row=0, column=0, sticky="ew")
        for col in range(6):
            top.columnconfigure(col, weight=1)

        self._add_field(top, "Host", "host", 0, 0)
        self._add_field(top, "Puerto", "port", 0, 1)

        ttk.Label(top, text="Backend").grid(row=0, column=2, sticky="w", padx=6)
        backend_box = ttk.Combobox(
            top,
            textvariable=self.config_vars["backend"],
            values=["soundcard", "sounddevice", "auto"],
            state="readonly",
        )
        backend_box.grid(row=1, column=2, sticky="ew", padx=6)

        self._add_field(top, "Device (opcional)", "device", 0, 3)
        self._add_field(top, "Sample rate", "samplerate", 0, 4)
        self._add_field(top, "Block frames", "block_frames", 0, 5)

        ttk.Label(top, text="Canales").grid(row=2, column=0, sticky="w", padx=6, pady=(10, 0))
        channels_box = ttk.Combobox(
            top,
            textvariable=self.config_vars["channels"],
            values=["1", "2"],
            state="readonly",
        )
        channels_box.grid(row=3, column=0, sticky="ew", padx=6)

        btns = ttk.Frame(top)
        btns.grid(row=3, column=1, columnspan=5, sticky="ew", padx=6)
        btns.columnconfigure(0, weight=1)
        btns.columnconfigure(1, weight=1)
        btns.columnconfigure(2, weight=1)
        btns.columnconfigure(3, weight=1)

        self.start_button = ttk.Button(btns, text="Iniciar servidor", command=self._start_server)
        self.start_button.grid(row=0, column=0, sticky="ew", padx=(0, 8))

        self.stop_button = ttk.Button(btns, text="Detener", command=self._stop_server, state="disabled")
        self.stop_button.grid(row=0, column=1, sticky="ew", padx=8)

        ttk.Button(btns, text="Listar dispositivos", command=self._list_devices).grid(
            row=0,
            column=2,
            sticky="ew",
            padx=8,
        )

        ttk.Button(btns, text="Guardar config", command=self._save_config).grid(
            row=0,
            column=3,
            sticky="ew",
            padx=(8, 0),
        )

        net_frame = ttk.LabelFrame(top, text="Datos para el telefono", padding=10)
        net_frame.grid(row=4, column=0, columnspan=6, sticky="ew", padx=6, pady=(12, 0))
        net_frame.columnconfigure(0, weight=1)
        net_frame.columnconfigure(1, weight=0)
        net_frame.columnconfigure(2, weight=0)

        ttk.Entry(
            net_frame,
            textvariable=self.local_ips_var,
            state="readonly",
        ).grid(row=0, column=0, sticky="ew", padx=(0, 8))
        ttk.Button(net_frame, text="Actualizar IP", command=self._refresh_local_ips).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(0, 8),
        )
        ttk.Button(net_frame, text="Copiar IP", command=self._copy_primary_ip).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        usb_frame = ttk.LabelFrame(top, text="USB (sin red) - ADB reverse", padding=10)
        usb_frame.grid(row=5, column=0, columnspan=6, sticky="ew", padx=6, pady=(10, 0))
        usb_frame.columnconfigure(0, weight=1)
        usb_frame.columnconfigure(1, weight=0)
        usb_frame.columnconfigure(2, weight=0)

        ttk.Label(usb_frame, textvariable=self.usb_status_var).grid(
            row=0,
            column=0,
            sticky="w",
        )
        ttk.Button(usb_frame, text="Activar USB", command=self._enable_usb_reverse).grid(
            row=0,
            column=1,
            sticky="ew",
            padx=(8, 8),
        )
        ttk.Button(usb_frame, text="Desactivar USB", command=self._disable_usb_reverse).grid(
            row=0,
            column=2,
            sticky="ew",
        )

        log_frame = ttk.LabelFrame(self.root, text="Logs", padding=10)
        log_frame.grid(row=1, column=0, sticky="nsew", padx=12, pady=(0, 12))
        log_frame.columnconfigure(0, weight=1)
        log_frame.rowconfigure(0, weight=1)

        self.log_text = tk.Text(log_frame, wrap="word", state="disabled", font=("Consolas", 10))
        self.log_text.grid(row=0, column=0, sticky="nsew")

        scrollbar = ttk.Scrollbar(log_frame, orient="vertical", command=self.log_text.yview)
        scrollbar.grid(row=0, column=1, sticky="ns")
        self.log_text.configure(yscrollcommand=scrollbar.set)

        self._append_log("GUI lista. Configura parametros y pulsa 'Iniciar servidor'.")
        self._append_log("Wi-Fi: usa una IP mostrada arriba y el puerto configurado.")
        self._append_log("USB: activa 'ADB reverse' y en Android usa host 127.0.0.1.")

    def _add_field(self, parent: ttk.Frame, label: str, key: str, row: int, col: int) -> None:
        ttk.Label(parent, text=label).grid(row=row, column=col, sticky="w", padx=6)
        ttk.Entry(parent, textvariable=self.config_vars[key]).grid(row=row + 1, column=col, sticky="ew", padx=6)

    def _validate_config(self) -> dict[str, str] | None:
        cfg = {k: v.get().strip() for k, v in self.config_vars.items()}
        if not cfg["host"]:
            messagebox.showerror("Config", "Host es obligatorio")
            return None

        try:
            port = int(cfg["port"])
            if port <= 0 or port > 65535:
                raise ValueError
        except ValueError:
            messagebox.showerror("Config", "Puerto invalido")
            return None

        for key in ("samplerate", "channels", "block_frames"):
            try:
                value = int(cfg[key])
                if value <= 0:
                    raise ValueError
            except ValueError:
                messagebox.showerror("Config", f"{key} debe ser entero positivo")
                return None

        if cfg["device"]:
            try:
                int(cfg["device"])
            except ValueError:
                messagebox.showerror("Config", "Device debe ser numero entero")
                return None

        return cfg

    def _start_server(self) -> None:
        if self.server_process is not None and self.server_process.is_alive():
            return

        cfg = self._validate_config()
        if cfg is None:
            return

        self._save_config(show_message=False)
        self.server_process = mp.Process(target=_run_server_worker, args=(cfg, self.log_queue), daemon=True)
        self.server_process.start()

        self._append_log("Iniciando servidor...")
        self.start_button.configure(state="disabled")
        self.stop_button.configure(state="normal")

    def _stop_server(self) -> None:
        proc = self.server_process
        if proc is None:
            return
        if proc.is_alive():
            proc.terminate()
            proc.join(timeout=2)
            if proc.is_alive():
                proc.kill()
                proc.join(timeout=1)
        self.server_process = None
        self._append_log("Servidor detenido")
        self.start_button.configure(state="normal")
        self.stop_button.configure(state="disabled")

    def _list_devices(self) -> None:
        backend = self.config_vars["backend"].get().strip() or "auto"
        self._append_log(f"Listando dispositivos ({backend})...")

        def task() -> None:
            _run_list_worker(backend, self.log_queue)

        threading.Thread(target=task, daemon=True).start()

    def _refresh_local_ips(self) -> None:
        ips = _detect_local_ips()
        if ips:
            self.local_ips_var.set(" | ".join(ips))
            self._append_log(f"IPs detectadas: {', '.join(ips)}")
        else:
            self.local_ips_var.set("Sin IP LAN detectada")
            self._append_log("No se detectaron IPs LAN. Puedes usar modo USB con ADB.")

    def _copy_primary_ip(self) -> None:
        ips = _detect_local_ips()
        if not ips:
            messagebox.showwarning("IP", "No hay IP de red local para copiar.")
            return
        ip = ips[0]
        self.root.clipboard_clear()
        self.root.clipboard_append(ip)
        self.root.update()
        self._append_log(f"IP copiada: {ip}")

    def _parse_port(self) -> int | None:
        value = self.config_vars["port"].get().strip()
        try:
            port = int(value)
        except ValueError:
            return None
        if port <= 0 or port > 65535:
            return None
        return port

    def _enable_usb_reverse(self) -> None:
        port = self._parse_port()
        if port is None:
            messagebox.showerror("USB", "Puerto invalido para ADB reverse.")
            return
        try:
            serials, raw, adb_exe = _list_adb_devices()
            if not serials:
                self.usb_status_var.set("USB: sin dispositivos conectados")
                self._append_log("ADB devices sin telefonos en estado 'device'.")
                self._append_log(raw)
                return
            for serial in serials:
                _adb_reverse(serial, port, remove=False)
            self.usb_status_var.set(f"USB activo: 127.0.0.1:{port}")
            self._append_log(f"ADB detectado: {adb_exe}")
            self._append_log(
                f"ADB reverse activo en {len(serials)} dispositivo(s). En Android usa 127.0.0.1:{port}."
            )
        except RuntimeError as exc:
            self.usb_status_var.set("USB: error")
            messagebox.showerror("USB", str(exc))
            self._append_log(f"Error USB: {exc}")

    def _disable_usb_reverse(self) -> None:
        port = self._parse_port()
        if port is None:
            messagebox.showerror("USB", "Puerto invalido para ADB reverse.")
            return
        try:
            serials, raw, adb_exe = _list_adb_devices()
            if not serials:
                self.usb_status_var.set("USB: sin dispositivos conectados")
                self._append_log("ADB devices sin telefonos en estado 'device'.")
                self._append_log(raw)
                return
            for serial in serials:
                _adb_reverse(serial, port, remove=True)
            self.usb_status_var.set("USB: inactivo")
            self._append_log(f"ADB detectado: {adb_exe}")
            self._append_log(f"ADB reverse removido en {len(serials)} dispositivo(s).")
        except RuntimeError as exc:
            self.usb_status_var.set("USB: error")
            messagebox.showerror("USB", str(exc))
            self._append_log(f"Error USB: {exc}")

    def _append_log(self, message: str) -> None:
        self.log_text.configure(state="normal")
        self.log_text.insert("end", message + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _poll_logs(self) -> None:
        try:
            while True:
                msg = self.log_queue.get_nowait()
                self._append_log(msg)
        except queue.Empty:
            pass
        self.root.after(120, self._poll_logs)

    def _poll_process(self) -> None:
        proc = self.server_process
        if proc is not None and not proc.is_alive():
            code = proc.exitcode
            self.server_process = None
            self.start_button.configure(state="normal")
            self.stop_button.configure(state="disabled")
            self._append_log(f"Servidor finalizado (exit={code})")
        self.root.after(500, self._poll_process)

    def _save_config(self, show_message: bool = True) -> None:
        cfg = {k: v.get().strip() for k, v in self.config_vars.items()}
        try:
            with open(CONFIG_PATH, "w", encoding="utf-8") as fh:
                json.dump(cfg, fh, indent=2)
            if show_message:
                messagebox.showinfo("Config", "Configuracion guardada")
        except OSError as exc:
            messagebox.showerror("Config", f"No se pudo guardar: {exc}")

    def _load_config(self) -> None:
        if not os.path.exists(CONFIG_PATH):
            return
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as fh:
                cfg = json.load(fh)
        except (OSError, json.JSONDecodeError):
            return

        for key, var in self.config_vars.items():
            if key in cfg:
                var.set(str(cfg[key]))

    def _on_close(self) -> None:
        self._save_config(show_message=False)
        self._stop_server()
        self.root.destroy()


def launch_gui() -> None:
    root = tk.Tk()
    ServerGuiApp(root)
    root.mainloop()


if __name__ == "__main__":
    mp.freeze_support()
    launch_gui()
