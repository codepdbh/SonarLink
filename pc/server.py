import argparse
import queue
import socket
import struct
import sys
import wave

import sounddevice as sd

try:
    import soundcard as sc
except Exception:  # pragma: no cover - optional dependency
    sc = None

MAGIC = b"PCM1"
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2
DEFAULT_BLOCK_FRAMES = 960  # 20 ms @ 48 kHz
LOOPBACK_KEYWORDS = (
    "mezcla estereo",
    "stereo mix",
    "what u hear",
    "loopback",
)


def list_sounddevice_devices() -> None:
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        hostapi = sd.query_hostapis(dev["hostapi"])["name"]
        directions = []
        if dev["max_input_channels"] > 0:
            directions.append("in")
        if dev["max_output_channels"] > 0:
            directions.append("out")
        direction = "/".join(directions) if directions else "n/a"
        print(f"{idx}: {dev['name']} [{hostapi}] ({direction})")


def list_soundcard_devices() -> None:
    if sc is None:
        print("soundcard no esta instalado.")
        return
    microphones = sc.all_microphones(include_loopback=True)
    if not microphones:
        print("No se encontraron microfonos con soundcard.")
        return
    for idx, mic in enumerate(microphones):
        loopback = getattr(mic, "isloopback", False)
        tag = "loopback" if loopback else "mic"
        print(f"{idx}: {mic.name} ({tag})")


def clear_queue(q: "queue.Queue[bytes]") -> None:
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        return


def wasapi_loopback_supported() -> bool:
    try:
        sd.WasapiSettings(loopback=True)
    except TypeError:
        return False
    except Exception:
        return True
    return True


def find_loopback_device() -> int | None:
    devices = sd.query_devices()
    for dev in devices:
        if dev["max_input_channels"] <= 0:
            continue
        name = dev["name"].lower()
        if any(keyword in name for keyword in LOOPBACK_KEYWORDS):
            return dev["index"]
    return None


def resolve_backend(choice: str) -> str:
    if choice == "auto":
        return "soundcard" if sc is not None else "sounddevice"
    return choice


def describe_sounddevice(device: int) -> None:
    dev = sd.query_devices(device)
    hostapi = sd.query_hostapis(dev["hostapi"])["name"]
    print(f"Usando dispositivo: {device} - {dev['name']} [{hostapi}]")


def resolve_sounddevice_device(device_arg: int | None) -> tuple[int, object | None]:
    loopback_ok = wasapi_loopback_supported()
    extra = None
    if loopback_ok:
        extra = sd.WasapiSettings(loopback=True)
        if device_arg is None:
            default_output = sd.default.device[1]
            if default_output is None:
                raise RuntimeError("No se encontro dispositivo de salida por defecto.")
            device = default_output
        else:
            device = device_arg
    else:
        if device_arg is None:
            device = find_loopback_device()
            if device is None:
                raise RuntimeError(
                    "No se encontro un dispositivo de loopback. "
                    "Actualiza sounddevice o habilita 'Mezcla estereo' y usa --device <id>."
                )
        else:
            device = device_arg
    return device, extra


def resolve_soundcard_mic(device_arg: int | None):
    if sc is None:
        raise RuntimeError("soundcard no esta instalado.")
    microphones = sc.all_microphones(include_loopback=True)
    if not microphones:
        raise RuntimeError("No se encontraron microfonos con soundcard.")
    if device_arg is None:
        loopbacks = [m for m in microphones if getattr(m, "isloopback", False)]
        mic = loopbacks[0] if loopbacks else microphones[0]
    else:
        if device_arg < 0 or device_arg >= len(microphones):
            raise RuntimeError("Indice de microfono fuera de rango.")
        mic = microphones[device_arg]
    return mic


def write_wav(path: str, samplerate: int, channels: int, data: bytes) -> None:
    with wave.open(path, "wb") as wav:
        wav.setnchannels(channels)
        wav.setsampwidth(2)
        wav.setframerate(samplerate)
        wav.writeframes(data)


def float_to_pcm16(data) -> bytes:
    import numpy as np

    arr = np.asarray(data, dtype=np.float32)
    arr = np.clip(arr, -1.0, 1.0)
    pcm = (arr * 32767.0).astype("<i2")
    return pcm.tobytes()


def soundcard_numpy_guard() -> None:
    import numpy as np

    major = int(np.__version__.split(".")[0])
    if major >= 2:
        raise RuntimeError(
            "soundcard no es compatible con numpy 2.x. "
            "Instala numpy < 2.0 (ej. pip install 'numpy<2.0')."
        )


def record_test_sounddevice(args, device: int, extra, outfile: str) -> None:
    frames = int(args.samplerate * args.test_record)
    data = sd.rec(
        frames=frames,
        samplerate=args.samplerate,
        channels=args.channels,
        dtype="int16",
        device=device,
        blocking=True,
        extra_settings=extra,
    )
    write_wav(outfile, args.samplerate, args.channels, data.tobytes())


def record_test_soundcard(args, mic, outfile: str) -> None:
    soundcard_numpy_guard()
    total_frames = int(args.samplerate * args.test_record)
    remaining = total_frames
    blocks: list[bytes] = []
    with mic.recorder(
        samplerate=args.samplerate,
        channels=args.channels,
        blocksize=args.block_frames,
    ) as rec:
        while remaining > 0:
            count = min(args.block_frames, remaining)
            data = rec.record(count)
            blocks.append(float_to_pcm16(data))
            remaining -= count
    write_wav(outfile, args.samplerate, args.channels, b"".join(blocks))


def stream_sounddevice(args, device: int, extra) -> None:
    q: "queue.Queue[bytes]" = queue.Queue(maxsize=64)

    def callback(indata, _frames, _time, status) -> None:
        if status:
            print(status, file=sys.stderr)
        data = bytes(indata)
        try:
            q.put_nowait(data)
        except queue.Full:
            try:
                q.get_nowait()
            except queue.Empty:
                pass
            try:
                q.put_nowait(data)
            except queue.Full:
                pass

    stream = sd.RawInputStream(
        samplerate=args.samplerate,
        blocksize=args.block_frames,
        dtype="int16",
        channels=args.channels,
        device=device,
        callback=callback,
        extra_settings=extra,
    )

    header = struct.pack(
        "<4sIHHI",
        MAGIC,
        args.samplerate,
        args.channels,
        16,
        args.block_frames,
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(1)
        print(f"Escuchando en {args.host}:{args.port}")

        with stream:
            while True:
                conn, addr = server.accept()
                print(f"Cliente conectado: {addr[0]}:{addr[1]}")
                clear_queue(q)
                try:
                    conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                    conn.sendall(header)
                    while True:
                        data = q.get()
                        if not data:
                            continue
                        conn.sendall(data)
                except (BrokenPipeError, ConnectionResetError, OSError):
                    print("Cliente desconectado")
                finally:
                    try:
                        conn.close()
                    except OSError:
                        pass


def stream_soundcard(args, mic) -> None:
    soundcard_numpy_guard()
    header = struct.pack(
        "<4sIHHI",
        MAGIC,
        args.samplerate,
        args.channels,
        16,
        args.block_frames,
    )

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.port))
        server.listen(1)
        print(f"Escuchando en {args.host}:{args.port}")

        while True:
            conn, addr = server.accept()
            print(f"Cliente conectado: {addr[0]}:{addr[1]}")
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                conn.sendall(header)
                with mic.recorder(
                    samplerate=args.samplerate,
                    channels=args.channels,
                    blocksize=args.block_frames,
                ) as rec:
                    while True:
                        data = rec.record(args.block_frames)
                        if data is None:
                            continue
                        conn.sendall(float_to_pcm16(data))
            except (BrokenPipeError, ConnectionResetError, OSError):
                print("Cliente desconectado")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass


def main() -> int:
    parser = argparse.ArgumentParser(description="Streaming de audio PC -> Android por TCP.")
    parser.add_argument("--host", default="0.0.0.0", help="IP de escucha (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Puerto TCP (default 5000)")
    parser.add_argument("--samplerate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS)
    parser.add_argument("--block-frames", type=int, default=DEFAULT_BLOCK_FRAMES)
    parser.add_argument(
        "--device",
        type=int,
        help="Indice de dispositivo (sounddevice) o speaker (soundcard). Ver --list.",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "sounddevice", "soundcard"],
        default="auto",
        help="Backend de captura (default: auto).",
    )
    parser.add_argument("--list", action="store_true", help="Lista dispositivos y sale")
    parser.add_argument(
        "--test-record",
        type=int,
        default=0,
        help="Graba N segundos a WAV y sale (ej. --test-record 5).",
    )
    parser.add_argument(
        "--outfile",
        default="capture_test.wav",
        help="Ruta del WAV de prueba (default: capture_test.wav).",
    )
    args = parser.parse_args()

    backend = resolve_backend(args.backend)

    if args.list:
        if backend == "soundcard":
            list_soundcard_devices()
        else:
            list_sounddevice_devices()
        return 0

    if backend == "soundcard":
        mic = resolve_soundcard_mic(args.device)
        loopback = getattr(mic, "isloopback", False)
        label = "loopback" if loopback else "mic"
        print(f"Backend: soundcard | Mic: {mic.name} ({label})")
        if args.test_record > 0:
            record_test_soundcard(args, mic, args.outfile)
            print(f"Archivo creado: {args.outfile}")
            return 0
        stream_soundcard(args, mic)
        return 0

    device, extra = resolve_sounddevice_device(args.device)
    describe_sounddevice(device)
    if args.test_record > 0:
        record_test_sounddevice(args, device, extra, args.outfile)
        print(f"Archivo creado: {args.outfile}")
        return 0
    stream_sounddevice(args, device, extra)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
