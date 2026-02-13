import contextlib
import json
import multiprocessing as mp
import os
import queue
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

        self._build_ui()
        self._load_config()

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
