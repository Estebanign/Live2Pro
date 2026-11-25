"""Live2Pro - núcleo (sin interfaz gráfica).

Resuelve una URL de YouTube Live con yt-dlp y la entrega a ProPresenter por:
  * NDI  (ffmpeg -> numpy -> ndi-python)      -> ProPresenter 21 (Ajustes > Entradas)
  * HLS local (ffmpeg -c copy + http local)   -> ProPresenter 22+ (Video Stream)
"""
from __future__ import annotations

import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from dataclasses import dataclass
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

FROZEN = getattr(sys, "frozen", False)
APP_DIR = Path(sys.executable).parent if FROZEN else Path(__file__).resolve().parent.parent
BIN_DIR = APP_DIR / "bin"          # ffmpeg.exe, yt-dlp.exe, deno.exe
VLC_DIR = APP_DIR / "vlc"          # libvlc.dll, libvlccore.dll, plugins\
USER_DIR = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / "Live2Pro"
USER_BIN = USER_DIR / "bin"        # copia escribible de yt-dlp (para poder actualizarlo)
OUT_DIR = Path.home() / "Documents" / "Live2Pro"
NOWIN = getattr(subprocess, "CREATE_NO_WINDOW", 0)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"
HLS_PORT = 38765


def ensure_dirs() -> None:
    for d in (USER_BIN, OUT_DIR):
        d.mkdir(parents=True, exist_ok=True)
    for n in ("yt-dlp.exe", "deno.exe"):
        src, dst = BIN_DIR / n, USER_BIN / n
        if src.exists() and not dst.exists():
            shutil.copy2(src, dst)


def tool(name: str) -> str:
    p = USER_BIN / name
    return str(p if p.exists() else BIN_DIR / name)


def tool_env() -> dict:
    env = os.environ.copy()
    env["PATH"] = os.pathsep.join([str(USER_BIN), str(BIN_DIR), env.get("PATH", "")])
    return env


# --------------------------------------------------------------------------- yt-dlp
class ResolveError(Exception):
    def __init__(self, msg: str, fatal: bool = True):
        super().__init__(msg)
        self.fatal = fatal  # fatal = no tiene sentido reintentar solo


@dataclass
class Stream:
    title: str
    url: str            # manifiesto HLS (.m3u8) directo de YouTube
    width: int
    height: int
    fps: float
    is_live: bool
    video_id: str


_YT = re.compile(r"^https?://((www|m|music)\.)?(youtube\.com|youtu\.be)/", re.I)

_ERRORS = [  # (fragmento en stderr de yt-dlp, mensaje, fatal)
    ("private video", "La transmisión es privada. Live2Pro solo funciona con vivos públicos o no listados.", True),
    ("members-only", "La transmisión es solo para miembros del canal.", True),
    ("sign in to confirm", "YouTube pide verificación (posible bloqueo temporal por IP). Probá de nuevo en unos minutos.", False),
    ("will begin in", "El vivo todavía no empezó. Live2Pro reintentará cuando comience.", False),
    ("premieres in", "El estreno todavía no empezó. Reintentando…", False),
    ("video unavailable", "El video no está disponible o fue eliminado.", True),
    ("not a valid url", "El enlace no es válido.", True),
    ("unable to download", "No se pudo contactar a YouTube. Revisá tu conexión a Internet.", False),
    ("http error", "YouTube rechazó la solicitud. Probá actualizar yt-dlp.", False),
]


def resolve(url: str) -> Stream:
    url = url.strip()
    if not _YT.match(url):
        raise ResolveError("El enlace no parece ser de YouTube (youtube.com o youtu.be).")
    cmd = [tool("yt-dlp.exe"), "-J", "--no-playlist", "--no-warnings",
           "-f", "best[protocol^=m3u8]/best", url]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=90,
                           creationflags=NOWIN, env=tool_env(), encoding="utf-8", errors="replace")
    except FileNotFoundError:
        raise ResolveError("Falta yt-dlp.exe en la carpeta bin de Live2Pro.")
    except subprocess.TimeoutExpired:
        raise ResolveError("yt-dlp tardó demasiado en responder.", fatal=False)
    if r.returncode != 0:
        low = r.stderr.lower()
        for frag, msg, fatal in _ERRORS:
            if frag in low:
                raise ResolveError(msg, fatal)
        last = (r.stderr.strip().splitlines() or ["error desconocido"])[-1]
        raise ResolveError(f"No se pudo obtener la transmisión: {last}", fatal=False)
    info = json.loads(r.stdout)
    media = info.get("url") or (info.get("requested_formats") or [{}])[0].get("url")
    if not media:
        raise ResolveError("yt-dlp no devolvió una URL reproducible.", fatal=False)
    return Stream(title=info.get("title", "YouTube Live"), url=media,
                  width=int(info.get("width") or 0), height=int(info.get("height") or 0),
                  fps=float(info.get("fps") or 0), is_live=bool(info.get("is_live")),
                  video_id=info.get("id", ""))


def update_ytdlp() -> str:
    r = subprocess.run([tool("yt-dlp.exe"), "-U"], capture_output=True, text=True, timeout=180,
                       creationflags=NOWIN, env=tool_env(), encoding="utf-8", errors="replace")
    return (r.stdout + r.stderr).strip() or "Sin respuesta de yt-dlp."


# --------------------------------------------------------------------------- salidas
class OutputError(Exception):
    pass


def _read_exact(f, n: int) -> bytes:
    buf = bytearray()
    while len(buf) < n:
        chunk = f.read(n - len(buf))
        if not chunk:
            return b""
        buf += chunk
    return bytes(buf)


class NdiEngine:
    """ffmpeg decodifica a UYVY (video) + f32le (audio por TCP local) y se envía por NDI."""

    def __init__(self, source_name: str, width: int = 1280, height: int = 720, fps: int = 30):
        self.name, self.w, self.h, self.fps = source_name, width, height, fps
        self.proc = None
        self.running = False
        self._threads: list[threading.Thread] = []
        self._ndi = None
        self._send = None

    def start(self, stream: Stream) -> None:
        try:
            import numpy as np  # noqa: F401
            import NDIlib as ndi
        except ImportError:
            raise OutputError("Falta el módulo NDI (ndi-python) o el runtime de NDI. Instalá 'NDI Tools'.")
        if not ndi.initialize():
            raise OutputError("No se pudo inicializar NDI (¿CPU/runtime no compatible?).")
        self._ndi = ndi
        cfg = ndi.SendCreate()
        cfg.ndi_name = self.name
        cfg.clock_video = False
        cfg.clock_audio = False
        self._send = ndi.send_create(cfg)
        if self._send is None:
            raise OutputError("No se pudo crear la fuente NDI.")

        srv = socket.socket()
        srv.bind(("127.0.0.1", 0))
        srv.listen(1)
        port = srv.getsockname()[1]
        vf = (f"scale={self.w}:{self.h}:force_original_aspect_ratio=decrease,"
              f"pad={self.w}:{self.h}:(ow-iw)/2:(oh-ih)/2,fps={self.fps},format=uyvy422")
        cmd = [tool("ffmpeg.exe"), "-hide_banner", "-loglevel", "warning", "-user_agent", UA,
               "-i", stream.url,
               "-map", "0:v:0", "-vf", vf, "-f", "rawvideo", "pipe:1",
               "-map", "0:a:0?", "-ac", "2", "-ar", "48000", "-f", "f32le", f"tcp://127.0.0.1:{port}"]
        log = open(USER_DIR / "ffmpeg.log", "wb")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=log,
                                     creationflags=NOWIN, env=tool_env(), bufsize=0)
        conn, t0 = None, time.time()
        srv.settimeout(0.5)
        while conn is None:
            if self.proc.poll() is not None:
                srv.close()
                raise OutputError("ffmpeg no pudo abrir la transmisión (ver ffmpeg.log).")
            if time.time() - t0 > 30:
                self.stop()
                raise OutputError("Tiempo agotado esperando el audio/video de ffmpeg.")
            try:
                conn, _ = srv.accept()
            except socket.timeout:
                pass
        srv.close()
        self.running = True
        for fn, arg in ((self._video_loop, None), (self._audio_loop, conn)):
            t = threading.Thread(target=fn, args=(arg,) if arg else (), daemon=True)
            t.start()
            self._threads.append(t)

    def _video_loop(self) -> None:
        import numpy as np
        ndi = self._ndi
        frame = ndi.VideoFrameV2()
        frame.FourCC = ndi.FOURCC_VIDEO_TYPE_UYVY
        frame.frame_rate_N, frame.frame_rate_D = self.fps * 1000, 1000
        size = self.w * self.h * 2
        while self.running:
            raw = _read_exact(self.proc.stdout, size)
            if not raw:
                break
            frame.data = np.frombuffer(raw, np.uint8).reshape(self.h, self.w, 2)
            ndi.send_send_video_v2(self._send, frame)
        self.running = False

    def _audio_loop(self, conn: socket.socket) -> None:
        import numpy as np
        ndi = self._ndi
        n = 1024
        size = n * 2 * 4
        f = conn.makefile("rb", buffering=0)
        while self.running:
            raw = _read_exact(f, size)
            if not raw:
                break
            planar = np.ascontiguousarray(np.frombuffer(raw, np.float32).reshape(n, 2).T)
            af = ndi.AudioFrameV2()
            af.sample_rate, af.no_channels, af.no_samples = 48000, 2, n
            af.channel_stride_in_bytes = n * 4
            af.data = planar
            ndi.send_send_audio_v2(self._send, af)
        self.running = False

    def alive(self) -> bool:
        return self.running and self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        self.running = False
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        for t in self._threads:
            t.join(timeout=2)
        if self._ndi and self._send:
            self._ndi.send_destroy(self._send)
            self._send = None


class _Quiet(SimpleHTTPRequestHandler):
    def log_message(self, *a):  # sin ruido ni consola
        pass

    def end_headers(self):
        self.send_header("Cache-Control", "no-store")
        self.send_header("Access-Control-Allow-Origin", "*")
        super().end_headers()


class HlsEngine:
    """Re-publica el vivo como HLS local (sin recodificar) en http://127.0.0.1:PORT/live.m3u8"""

    def __init__(self):
        self.proc = None
        self.httpd = None
        self.dir: Path | None = None
        self.url = ""

    def start(self, stream: Stream) -> None:
        self.dir = Path(tempfile.mkdtemp(prefix="live2pro_"))
        out = self.dir / "live.m3u8"
        cmd = [tool("ffmpeg.exe"), "-hide_banner", "-loglevel", "warning", "-user_agent", UA,
               "-i", stream.url, "-c", "copy", "-f", "hls", "-hls_time", "2", "-hls_list_size", "8",
               "-hls_flags", "delete_segments+independent_segments",
               "-hls_segment_filename", str(self.dir / "seg%05d.ts"), str(out)]
        log = open(USER_DIR / "ffmpeg.log", "wb")
        self.proc = subprocess.Popen(cmd, stdout=subprocess.DEVNULL, stderr=log,
                                     creationflags=NOWIN, env=tool_env())
        handler = partial(_Quiet, directory=str(self.dir))
        try:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", HLS_PORT), handler)
        except OSError:
            self.httpd = ThreadingHTTPServer(("127.0.0.1", 0), handler)
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}/live.m3u8"
        t0 = time.time()
        while not out.exists():
            if self.proc.poll() is not None:
                raise OutputError("ffmpeg no pudo abrir la transmisión (ver ffmpeg.log).")
            if time.time() - t0 > 30:
                self.stop()
                raise OutputError("Tiempo agotado generando el HLS local.")
            time.sleep(0.3)

    def alive(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()
        if self.httpd:
            self.httpd.shutdown()
            self.httpd.server_close()
        if self.dir:
            shutil.rmtree(self.dir, ignore_errors=True)


def write_resource_file(title: str, url: str) -> Path:
    """Archivo .m3u8 que apunta al HLS local (EXPERIMENTAL: ProPresenter 21 no documenta aceptarlo)."""
    safe = re.sub(r'[\\/:*?"<>|]+', "_", title).strip()[:80] or "YouTube Live"
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    p = OUT_DIR / f"{safe}.m3u8"
    p.write_text(f"#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=5000000\n{url}\n", encoding="utf-8")
    return p


# --------------------------------------------------------------------------- sesión
class Session:
    """Mantiene conexión + salida y reconecta sola (re-resuelve la URL, que caduca)."""

    def __init__(self, on_status, on_stream, on_resource):
        self.on_status, self.on_stream, self.on_resource = on_status, on_stream, on_resource
        self.url = ""
        self.stream: Stream | None = None
        self.out_mode: str | None = None   # None | "ndi" | "hls"
        self.out_height = 720
        self._stop = threading.Event()
        self._reconnect = threading.Event()
        self._thread: threading.Thread | None = None

    def start(self, url: str) -> None:
        self.stop()
        self.url = url
        self._stop.clear()
        self._reconnect.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=10)
        self.stream = None
        self.on_status("Desconectado", "")

    def reconnect(self) -> None:
        self._reconnect.set()

    def set_output(self, mode: str | None, height: int = 720) -> None:
        self.out_mode, self.out_height = mode, height

    def _run(self) -> None:
        backoff = 3
        while not self._stop.is_set():
            self.on_status("Conectando", "")
            try:
                s = resolve(self.url)
            except ResolveError as e:
                if e.fatal:
                    self.on_status("Error", str(e))
                    return
                self.on_status("Reconectando", str(e))
                self._stop.wait(backoff)
                backoff = min(backoff * 2, 30)
                continue
            backoff = 3
            self.stream = s
            self.on_stream(s)
            self.on_status("En vivo" if s.is_live else "Reproduciendo (no es en vivo)", "")
            engine, cur, started = None, None, time.time()
            self._reconnect.clear()
            while not self._stop.is_set() and not self._reconnect.is_set():
                if time.time() - started > 4 * 3600:   # la URL de YouTube caduca (~6 h)
                    break
                if self.out_mode != cur:
                    if engine:
                        engine.stop()
                        engine = None
                    cur = self.out_mode
                    if cur:
                        try:
                            if cur == "ndi":
                                h = self.out_height
                                engine = NdiEngine(f"LIVE2PRO - {s.title[:40]}", h * 16 // 9, h, 30)
                                engine.start(s)
                                self.on_resource("ndi", engine.name, None)
                            else:
                                engine = HlsEngine()
                                engine.start(s)
                                self.on_resource("hls", engine.url, write_resource_file(s.title, engine.url))
                        except OutputError as e:
                            self.on_status("Error", str(e))
                            engine, cur, self.out_mode = None, None, None
                if engine and not engine.alive():
                    break
                self._stop.wait(0.5)
            if engine:
                engine.stop()
            if not self._stop.is_set():
                self.on_status("Reconectando", "Se perdió la señal; reintentando…")
                self._stop.wait(2)
