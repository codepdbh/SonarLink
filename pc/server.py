import argparse
import contextlib
import queue
import socket
import struct
import sys
import threading
import time
import wave

import sounddevice as sd

try:
    import soundcard as sc
except Exception:  # pragma: no cover - optional dependency
    sc = None

MAGIC = b"PCM1"
MIC_MAGIC = b"MIC1"
DEFAULT_SAMPLE_RATE = 48000
DEFAULT_CHANNELS = 2
DEFAULT_BLOCK_FRAMES = 960  # 20 ms @ 48 kHz
DEFAULT_MIC_PORT = 5001
LOOPBACK_KEYWORDS = (
    "mezcla estereo",
    "stereo mix",
    "what u hear",
    "loopback",
)
VB_CABLE_HINTS = (
    "cable input",
    "vb-audio",
    "virtual cable",
)
PREFERRED_MIC_OUTPUT_HINTS = (
    "cable input",
    "vb-audio virtual c",
    "vb-audio virtual cable",
)


def _normalize_name(name: str) -> str:
    return " ".join("".join(ch.lower() if ch.isalnum() else " " for ch in name).split())


def _is_virtual_cable_name(name: str) -> bool:
    lowered = name.lower()
    return any(hint in lowered for hint in VB_CABLE_HINTS)


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


def list_output_devices() -> None:
    devices = sd.query_devices()
    for idx, dev in enumerate(devices):
        if dev["max_output_channels"] <= 0:
            continue
        hostapi = sd.query_hostapis(dev["hostapi"])["name"]
        print(f"{idx}: {dev['name']} [{hostapi}] (out)")


def clear_queue(q: "queue.Queue[bytes]") -> None:
    try:
        while True:
            q.get_nowait()
    except queue.Empty:
        return


def configure_tcp_keepalive(sock: socket.socket) -> None:
    with contextlib.suppress(OSError):
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    # Windows-specific keepalive tuning (on, idle_ms, interval_ms).
    if hasattr(socket, "SIO_KEEPALIVE_VALS"):
        with contextlib.suppress(OSError):
            sock.ioctl(socket.SIO_KEEPALIVE_VALS, (1, 15000, 5000))


def read_exact(conn: socket.socket, size: int) -> bytes | None:
    chunks: list[bytes] = []
    remaining = size
    while remaining > 0:
        data = conn.recv(remaining)
        if not data:
            return None
        chunks.append(data)
        remaining -= len(data)
    return b"".join(chunks)


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
        if not loopbacks:
            mic = microphones[0]
        else:
            mic = None
            # Prefer loopback that matches current Windows default output.
            try:
                default_output = sd.default.device[1]
                if default_output is not None:
                    default_name = _normalize_name(sd.query_devices(default_output)["name"])
                    for candidate in loopbacks:
                        candidate_name = _normalize_name(candidate.name)
                        if default_name and (default_name in candidate_name or candidate_name in default_name):
                            mic = candidate
                            break
            except Exception:
                mic = None

            # Avoid selecting virtual cable automatically for PC audio bridge.
            if mic is None:
                non_virtual = [m for m in loopbacks if not _is_virtual_cable_name(m.name)]
                mic = non_virtual[0] if non_virtual else loopbacks[0]
    else:
        if device_arg < 0 or device_arg >= len(microphones):
            raise RuntimeError("Indice de microfono fuera de rango.")
        mic = microphones[device_arg]
    return mic


def resolve_mic_output_device(device_arg: int | None) -> int:
    devices = sd.query_devices()

    if device_arg is not None:
        dev = sd.query_devices(device_arg)
        if dev["max_output_channels"] <= 0:
            raise RuntimeError("El dispositivo de salida para microfono no tiene canales de salida.")
        return device_arg

    output_candidates = []
    for dev in devices:
        if dev["max_output_channels"] <= 0:
            continue
        hostapi_name = sd.query_hostapis(dev["hostapi"])["name"].lower()
        name = dev["name"].lower()
        score = 0

        # Strong preference requested: "CABLE Input (VB-Audio Virtual C [MME] (out)".
        if all(hint in name for hint in PREFERRED_MIC_OUTPUT_HINTS):
            score += 250
        if "cable input" in name:
            score += 180
        if "vb-audio" in name or "virtual cable" in name:
            score += 100
        if "mme" in hostapi_name:
            score += 40

        # Avoid picking the wrong endpoint when both CABLE Input/Output exist.
        if "cable output" in name:
            score -= 160
        if "16ch" in name:
            score -= 20

        output_candidates.append((score, dev["index"]))

    if output_candidates:
        output_candidates.sort(reverse=True)
        best_score, best_index = output_candidates[0]
        if best_score > 0:
            return best_index

    default_out = sd.default.device[1]
    if default_out is not None:
        default_dev = sd.query_devices(default_out)
        if default_dev["max_output_channels"] > 0:
            return default_out

    for dev in devices:
        if dev["max_output_channels"] > 0:
            return dev["index"]

    raise RuntimeError("No se encontro dispositivo de salida para puente de microfono.")


def describe_output_device(device: int, label: str) -> None:
    dev = sd.query_devices(device)
    hostapi = sd.query_hostapis(dev["hostapi"])["name"]
    print(f"{label}: {device} - {dev['name']} [{hostapi}]")


def mono16_to_stereo(data: bytes) -> bytes:
    if not data:
        return data
    if len(data) % 2:
        data = data[:-1]
    out = bytearray(len(data) * 2)
    j = 0
    for i in range(0, len(data), 2):
        lo = data[i]
        hi = data[i + 1]
        out[j] = lo
        out[j + 1] = hi
        out[j + 2] = lo
        out[j + 3] = hi
        j += 4
    return bytes(out)


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
                    configure_tcp_keepalive(conn)
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
                configure_tcp_keepalive(conn)
                conn.sendall(header)
                silence_block = bytes(args.block_frames * args.channels * 2)
                idle_sleep = max(args.block_frames / float(args.samplerate), 0.01)
                with mic.recorder(
                    samplerate=args.samplerate,
                    channels=args.channels,
                    blocksize=None,
                ) as rec:
                    while True:
                        # `record(None)` returns currently available frames; when
                        # idle it can be empty. Send silence to keep connection
                        # active during playback pauses and avoid app timeouts.
                        try:
                            data = rec.record(None)
                        except Exception as exc:
                            print(f"Capture warning: {exc}", file=sys.stderr)
                            conn.sendall(silence_block)
                            time.sleep(idle_sleep)
                            continue
                        if data is None or len(data) == 0:
                            conn.sendall(silence_block)
                            time.sleep(idle_sleep)
                            continue
                        conn.sendall(float_to_pcm16(data))
            except (BrokenPipeError, ConnectionResetError, OSError):
                print("Cliente desconectado")
            finally:
                try:
                    conn.close()
                except OSError:
                    pass


def stream_mic_bridge(args, stop_event: threading.Event) -> None:
    try:
        output_device = resolve_mic_output_device(args.mic_output_device)
    except RuntimeError as exc:
        print(f"Mic bridge deshabilitado: {exc}", file=sys.stderr)
        return

    describe_output_device(output_device, "Mic bridge output")

    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        server.bind((args.host, args.mic_port))
        server.listen(1)
        server.settimeout(1.0)
        print(f"Mic bridge escuchando en {args.host}:{args.mic_port}")

        while not stop_event.is_set():
            try:
                conn, addr = server.accept()
            except TimeoutError:
                continue
            print(f"Mic cliente conectado: {addr[0]}:{addr[1]}")
            try:
                conn.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
                configure_tcp_keepalive(conn)
                conn.settimeout(1.0)

                header = read_exact(conn, 16)
                if header is None:
                    raise RuntimeError("Mic bridge sin encabezado")
                magic, samplerate, channels, bits, block_frames = struct.unpack("<4sIHHI", header)
                if magic != MIC_MAGIC:
                    raise RuntimeError("Mic bridge encabezado invalido")
                if bits != 16:
                    raise RuntimeError("Mic bridge solo soporta PCM 16-bit")
                if channels <= 0:
                    raise RuntimeError("Mic bridge canales invalidos")

                input_channels = channels
                frame_size = input_channels * (bits // 8)
                stream_block = block_frames if block_frames > 0 else 0
                output_channels = input_channels
                out_dev = sd.query_devices(output_device)
                max_out = int(out_dev["max_output_channels"])
                if input_channels == 1 and max_out >= 2:
                    # Some virtual devices are more stable with stereo frames.
                    output_channels = 2
                if output_channels > max_out:
                    raise RuntimeError(
                        f"Salida no soporta canales requeridos ({output_channels} > {max_out})"
                    )

                with sd.RawOutputStream(
                    samplerate=samplerate,
                    blocksize=stream_block,
                    dtype="int16",
                    channels=output_channels,
                    device=output_device,
                ) as out_stream:
                    carry = b""
                    while not stop_event.is_set():
                        try:
                            data = conn.recv(8192)
                        except TimeoutError:
                            continue
                        if not data:
                            break
                        payload = carry + data
                        aligned = len(payload) - (len(payload) % frame_size)
                        if aligned > 0:
                            chunk = payload[:aligned]
                            if input_channels == 1 and output_channels == 2:
                                chunk = mono16_to_stereo(chunk)
                            out_stream.write(chunk)
                        carry = payload[aligned:]
            except (BrokenPipeError, ConnectionResetError, OSError) as exc:
                print(f"Mic cliente desconectado: {exc}")
            except Exception as exc:
                print(f"Mic bridge error: {exc}", file=sys.stderr)
            finally:
                try:
                    conn.close()
                except OSError:
                    pass
                print("Mic cliente cerrado")
        print("Mic bridge detenido")


def main() -> int:
    parser = argparse.ArgumentParser(description="Streaming de audio PC -> Android por TCP.")
    parser.add_argument("--host", default="0.0.0.0", help="IP de escucha (default 0.0.0.0)")
    parser.add_argument("--port", type=int, default=5000, help="Puerto TCP (default 5000)")
    parser.add_argument("--samplerate", type=int, default=DEFAULT_SAMPLE_RATE)
    parser.add_argument("--channels", type=int, default=DEFAULT_CHANNELS)
    parser.add_argument("--block-frames", type=int, default=DEFAULT_BLOCK_FRAMES)
    parser.add_argument("--mic-port", type=int, default=DEFAULT_MIC_PORT, help="Puerto TCP para mic bridge")
    parser.add_argument(
        "--device",
        type=int,
        help="Indice de dispositivo (sounddevice) o speaker (soundcard). Ver --list.",
    )
    parser.add_argument(
        "--mic-output-device",
        type=int,
        help="Indice de salida para microfono remoto (ideal: CABLE Input).",
    )
    parser.add_argument(
        "--backend",
        choices=["auto", "sounddevice", "soundcard"],
        default="auto",
        help="Backend de captura (default: auto).",
    )
    parser.add_argument("--list", action="store_true", help="Lista dispositivos y sale")
    parser.add_argument("--list-outputs", action="store_true", help="Lista dispositivos de salida y sale")
    parser.add_argument(
        "--audio-bridge",
        choices=["on", "off"],
        default="on",
        help="Habilita servidor de audio PC->Android (default: on).",
    )
    parser.add_argument(
        "--mic-bridge",
        choices=["on", "off"],
        default="on",
        help="Habilita puente de microfono del celular al PC (default: on).",
    )
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
    audio_enabled = args.audio_bridge == "on"
    mic_enabled = args.mic_bridge == "on"

    if args.list:
        if backend == "soundcard":
            list_soundcard_devices()
        else:
            list_sounddevice_devices()
        return 0
    if args.list_outputs:
        list_output_devices()
        return 0
    if not audio_enabled and not mic_enabled:
        print("Nada que iniciar: audio_bridge=off y mic_bridge=off", file=sys.stderr)
        return 1

    mic_thread: threading.Thread | None = None
    mic_stop_event = threading.Event()

    def ensure_mic_bridge_started() -> None:
        nonlocal mic_thread
        if args.mic_bridge != "on":
            return
        if mic_thread is None or not mic_thread.is_alive():
            mic_thread = threading.Thread(
                target=stream_mic_bridge,
                args=(args, mic_stop_event),
                daemon=False,
            )
            mic_thread.start()

    def hold_until_mic_stops() -> int:
        print("Audio deshabilitado. Mic bridge activo.")
        try:
            while True:
                if mic_thread is not None and not mic_thread.is_alive():
                    print("Mic bridge finalizado")
                    return 0
                time.sleep(0.5)
        except KeyboardInterrupt:
            print("Detenido por usuario")
            return 0

    if mic_enabled:
        ensure_mic_bridge_started()

    try:
        if not audio_enabled:
            return hold_until_mic_stops()

        if backend == "soundcard":
            try:
                mic = resolve_soundcard_mic(args.device)
            except RuntimeError as exc:
                if mic_enabled:
                    print(f"Audio bridge error: {exc}", file=sys.stderr)
                    return hold_until_mic_stops()
                raise
            loopback = getattr(mic, "isloopback", False)
            label = "loopback" if loopback else "mic"
            print(f"Backend: soundcard | Mic: {mic.name} ({label})")
            if args.test_record > 0:
                record_test_soundcard(args, mic, args.outfile)
                print(f"Archivo creado: {args.outfile}")
                return 0
            stream_soundcard(args, mic)
            return 0

        try:
            device, extra = resolve_sounddevice_device(args.device)
        except RuntimeError as exc:
            if mic_enabled:
                print(f"Audio bridge error: {exc}", file=sys.stderr)
                return hold_until_mic_stops()
            raise
        describe_sounddevice(device)
        if args.test_record > 0:
            record_test_sounddevice(args, device, extra, args.outfile)
            print(f"Archivo creado: {args.outfile}")
            return 0
        stream_sounddevice(args, device, extra)
        return 0
    except KeyboardInterrupt:
        print("Detenido por usuario")
        return 0
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    finally:
        if mic_thread is not None:
            mic_stop_event.set()
            mic_thread.join(timeout=2.5)


if __name__ == "__main__":
    raise SystemExit(main())
