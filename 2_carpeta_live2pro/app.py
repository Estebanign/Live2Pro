"""Live2Pro - interfaz gráfica (PySide6 + libVLC)."""
import os
import sys

from core import VLC_DIR, Session, Stream, ensure_dirs, update_ytdlp

# libVLC embebido: debe configurarse ANTES de importar vlc
if VLC_DIR.exists():
    os.environ["PYTHON_VLC_LIB_PATH"] = str(VLC_DIR / "libvlc.dll")
    os.environ["PYTHON_VLC_MODULE_PATH"] = str(VLC_DIR / "plugins")
    if hasattr(os, "add_dll_directory"):
        os.add_dll_directory(str(VLC_DIR))
import vlc  # noqa: E402
from PySide6.QtCore import QMimeData, QObject, Qt, QTimer, QUrl, Signal  # noqa: E402
from PySide6.QtGui import QDrag  # noqa: E402
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QGroupBox, QHBoxLayout,  # noqa: E402
                               QLabel, QLineEdit, QMainWindow, QMessageBox, QPushButton, QSpinBox,
                               QVBoxLayout, QWidget)

QSS = """
* { font-family: 'Segoe UI'; font-size: 13px; color: #e8e8ee; }
QMainWindow, QWidget#root { background: #14151a; }
QLineEdit, QComboBox { background: #1f2129; border: 1px solid #30333d; border-radius: 6px; padding: 8px; }
QPushButton { background: #2a2d38; border: 1px solid #3a3e4b; border-radius: 6px; padding: 8px 16px; }
QPushButton:hover { background: #343848; }
QPushButton:disabled { color: #70737f; background: #1c1e25; }
QPushButton#primary { background: #3b6df0; border-color: #3b6df0; font-weight: 600; }
QPushButton#primary:hover { background: #4f7cf5; }
QPushButton#danger { background: #7a2430; border-color: #7a2430; }
QGroupBox { border: 1px solid #30333d; border-radius: 8px; margin-top: 12px; padding: 14px 10px 10px 10px; font-weight: 600; }
QGroupBox::title { subcontrol-origin: margin; left: 12px; padding: 0 6px; color: #9aa0b4; }
QFrame#video { background: #000; border-radius: 6px; }
"""

STATE_COLORS = {"En vivo": "#2ecc71", "Conectando": "#f1c40f", "Reconectando": "#f39c12",
                "Desconectado": "#7f8493", "Error": "#e74c3c"}


class Bus(QObject):
    status = Signal(str, str)
    stream = Signal(object)
    resource = Signal(str, str, object)


class DragItem(QLabel):
    """Elemento arrastrable: entrega el archivo generado como URL de archivo local."""

    def __init__(self):
        super().__init__("Todavía no hay recurso generado")
        self.path = None
        self.setAlignment(Qt.AlignCenter)
        self.setMinimumHeight(56)
        self._style(False)

    def _style(self, active: bool):
        c = "#3b6df0" if active else "#30333d"
        self.setStyleSheet(f"QLabel {{ border: 2px dashed {c}; border-radius: 8px; padding: 8px; }}")

    def set_file(self, name: str, path):
        self.path = path
        self.setText(f"⠿  {name}\n(arrastrá este elemento a la Biblioteca de medios)")
        self._style(True)

    def set_plain(self, text: str):
        self.path = None
        self.setText(text)
        self._style(False)

    def mouseMoveEvent(self, e):
        if self.path and e.buttons() & Qt.LeftButton:
            mime = QMimeData()
            mime.setUrls([QUrl.fromLocalFile(str(self.path))])
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.exec(Qt.CopyAction)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Live2Pro")
        self.resize(980, 780)
        self.bus = Bus()
        self.bus.status.connect(self.on_status)
        self.bus.stream.connect(self.on_stream)
        self.bus.resource.connect(self.on_resource)
        self.session = Session(self.bus.status.emit, self.bus.stream.emit, self.bus.resource.emit)
        self.vlc = vlc.Instance("--no-audio", "--quiet", "--no-video-title-show")  # vista previa muda
        self.player = self.vlc.media_player_new()
        self.copy_text = ""

        root = QWidget(objectName="root")
        self.setCentralWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(18, 14, 18, 14)

        title = QLabel("Live2Pro")
        title.setStyleSheet("font-size: 22px; font-weight: 700;")
        lay.addWidget(title)

        row = QHBoxLayout()
        self.url = QLineEdit(placeholderText="Pegá aquí la URL del vivo de YouTube…")
        self.btn_connect = QPushButton("CONECTAR", objectName="primary")
        self.btn_stop = QPushButton("DETENER", objectName="danger")
        self.btn_stop.setEnabled(False)
        row.addWidget(self.url, 1)
        row.addWidget(self.btn_connect)
        row.addWidget(self.btn_stop)
        lay.addLayout(row)

        self.state = QLabel("●  Desconectado")
        self.info = QLabel("")
        self.info.setStyleSheet("color: #9aa0b4;")
        lay.addWidget(self.state)

        self.video = QFrame(objectName="video")
        self.video.setMinimumHeight(340)
        lay.addWidget(self.video, 1)
        lay.addWidget(self.info)

        box = QGroupBox("RECURSO PARA PROPRESENTER")
        b = QVBoxLayout(box)
        r1 = QHBoxLayout()
        self.mode = QComboBox()
        self.mode.addItem("NDI  (ProPresenter 21, con audio)", "ndi")
        self.mode.addItem("Cámara virtual  (ProPresenter 21, audio por la PC)", "vcam")
        self.mode.addItem("HLS local  (ProPresenter 22+: Video Stream)", "hls")
        self.res = QComboBox()
        self.res.addItem("720p", 720)
        self.res.addItem("1080p", 1080)
        self.audio = QComboBox()
        self.audio.addItem("Audio: salida predeterminada de la PC", None)
        try:
            import sounddevice as sd
            for i, d in enumerate(sd.query_devices()):
                if d["max_output_channels"] > 0 and sd.query_hostapis(d["hostapi"])["name"] == "MME":
                    self.audio.addItem(f"Audio: {d['name']}", i)
        except Exception:  # noqa: BLE001
            pass
        self.delay = QSpinBox()
        self.delay.setRange(0, 2000)
        self.delay.setSingleStep(50)
        self.delay.setSuffix(" ms retardo de video")
        self.btn_gen = QPushButton("GENERAR RECURSO", objectName="primary")
        self.btn_gen.setEnabled(False)
        r1.addWidget(self.mode, 1)
        r1.addWidget(self.res)
        r1.addWidget(self.btn_gen)
        b.addLayout(r1)
        r1b = QHBoxLayout()
        r1b.addWidget(self.audio, 1)
        r1b.addWidget(self.delay)
        b.addLayout(r1b)
        self.drag = DragItem()
        b.addWidget(self.drag)
        r2 = QHBoxLayout()
        self.btn_copy = QPushButton("Copiar ubicación del recurso")
        self.btn_copy.setEnabled(False)
        self.btn_upd = QPushButton("Actualizar yt-dlp")
        r2.addWidget(self.btn_copy)
        r2.addStretch(1)
        r2.addWidget(self.btn_upd)
        b.addLayout(r2)
        lay.addWidget(box)

        self.btn_connect.clicked.connect(self.connect_clicked)
        self.url.returnPressed.connect(self.connect_clicked)
        self.btn_stop.clicked.connect(self.stop_clicked)
        self.btn_gen.clicked.connect(self.generate_clicked)
        self.btn_copy.clicked.connect(lambda: QApplication.clipboard().setText(self.copy_text))
        self.btn_upd.clicked.connect(self.update_clicked)

        self.watch = QTimer(self)  # si la vista previa se cae, forzar reconexión
        self.watch.timeout.connect(self.check_player)
        self.watch.start(3000)

    # ---- acciones
    def connect_clicked(self):
        url = self.url.text().strip()
        if not url:
            QMessageBox.information(self, "Live2Pro", "Pegá primero la URL del vivo.")
            return
        self.btn_connect.setEnabled(False)
        self.btn_stop.setEnabled(True)
        self.session.start(url)

    def stop_clicked(self):
        self.player.stop()
        self.session.set_output(None)
        self.session.stop()
        self.btn_connect.setEnabled(True)
        self.btn_stop.setEnabled(False)
        self.btn_gen.setEnabled(False)
        self.btn_copy.setEnabled(False)
        self.drag.set_plain("Todavía no hay recurso generado")
        self.info.setText("")

    def generate_clicked(self):
        mode = self.mode.currentData()
        self.drag.set_plain("Generando…")
        self.session.set_output(mode, self.res.currentData(), self.audio.currentData(), self.delay.value())

    def update_clicked(self):
        self.btn_upd.setEnabled(False)
        self.btn_upd.setText("Actualizando…")
        QApplication.processEvents()
        try:
            msg = update_ytdlp()
        finally:
            self.btn_upd.setEnabled(True)
            self.btn_upd.setText("Actualizar yt-dlp")
        QMessageBox.information(self, "yt-dlp", msg)

    # ---- eventos del núcleo (llegan por señales: seguro entre hilos)
    def on_status(self, state: str, msg: str):
        key = "En vivo" if state.startswith(("En vivo", "Reproduciendo")) else state
        color = STATE_COLORS.get(key, "#7f8493")
        self.state.setText(f"<span style='color:{color}'>●</span>  {state}" + (f" — {msg}" if msg else ""))
        if state == "Error":
            self.btn_connect.setEnabled(True)
            self.btn_stop.setEnabled(False)
            if msg:
                QMessageBox.warning(self, "Live2Pro", msg)

    def on_stream(self, s: Stream):
        self.setWindowTitle(f"Live2Pro — {s.title}")
        res = f"{s.width}x{s.height}" if s.width else "resolución n/d"
        fps = f" @ {s.fps:g} fps" if s.fps else ""
        self.info.setText(f"{s.title}   |   {res}{fps}   |   {'EN VIVO' if s.is_live else 'no es en vivo'}")
        media = self.vlc.media_new(s.url)
        media.add_option(":network-caching=1500")
        self.player.set_media(media)
        if sys.platform.startswith("win"):
            self.player.set_hwnd(int(self.video.winId()))
        self.player.play()
        self.btn_gen.setEnabled(True)

    def on_resource(self, kind: str, text: str, path):
        self.copy_text = text
        self.btn_copy.setEnabled(True)
        if kind == "ndi":
            self.drag.set_plain(f"Fuente NDI activa:\n{text}\nEn ProPresenter: Ajustes > Entradas > Video Inputs > + > Dispositivo")
        elif kind == "vcam":
            self.drag.set_plain(f"Cámara virtual activa: {text}\nEn ProPresenter: Ajustes > Entradas > Video Inputs > + > Dispositivo")
        else:
            self.drag.set_file(path.name, path)

    def check_player(self):
        if self.session.stream and self.player.get_state() in (vlc.State.Ended, vlc.State.Error):
            self.session.reconnect()

    def closeEvent(self, e):
        self.player.stop()
        self.session.set_output(None)
        self.session.stop()
        e.accept()


def main():
    ensure_dirs()
    app = QApplication(sys.argv)
    app.setStyleSheet(QSS)
    w = MainWindow()
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
