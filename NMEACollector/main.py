"""NMEA Collector — thu thập và ghi log bản tin NMEA từ thiết bị thật trên tàu."""

import os
import sys

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QProgressBar,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from transmitters import list_serial_ports

from receiver import ReceiverThread
from session_logger import SessionLogger

# ── Bảng màu ────────────────────────────────────────────────────────────────
_LOG_BG    = "#1e1e1e"
_COL_GPS   = "#00e676"
_COL_RADAR = "#ffee58"
_COL_AIS   = "#40c4ff"
_COL_INFO  = "#90a4ae"
_COL_ERR   = "#ef5350"
_COL_REC   = "#ff6090"   # màu nhấp nháy khi đang ghi

_GPS_TAGS   = {'RMC','GGA','GNS','GLL','VTG','ZDA','GSA','GSV','GBS',
               'HDT','HDM','HDG','ROT','THS','RMB'}
_AIS_TAGS   = {'VDM','VDO'}
_RADAR_TAGS = {'TTM','TTD','OSD','RSD','RCD','RCL'}


def _tag_colour(tag: str) -> str:
    if tag in _AIS_TAGS:   return _COL_AIS
    if tag in _RADAR_TAGS: return _COL_RADAR
    if tag in _GPS_TAGS:   return _COL_GPS
    return "#ffffff"


def _btn(label: str, normal: str, hover: str, pressed: str, text: str = "white") -> QPushButton:
    b = QPushButton(label)
    b.setStyleSheet(
        f"QPushButton{{background:{normal};color:{text};font-weight:bold;"
        f"border:none;border-radius:4px;padding:5px 12px;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:pressed{{background:{pressed};}}"
        f"QPushButton:disabled{{background:#4a4a4a;color:#888;}}"
    )
    return b


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NMEA Collector")
        self.setMinimumSize(1100, 660)

        self._receiver:      ReceiverThread | None = None
        self._logger:        SessionLogger  | None = None
        self._last_session:  str | None           = None   # path of last stopped session
        self._stats:         dict[str, int]       = {}
        self._total_rx  = 0
        self._blink     = False

        self._build_ui()
        self._wire()

        # Timer cập nhật UI mỗi 500ms
        self._ui_timer = QTimer(self)
        self._ui_timer.setInterval(500)
        self._ui_timer.timeout.connect(self._refresh_ui)
        self._ui_timer.start()

    # ── Build UI ─────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        left  = self._build_left()
        right = self._build_right()

        spl = QSplitter(Qt.Orientation.Horizontal)
        spl.addWidget(left)
        spl.addWidget(right)
        spl.setSizes([360, 720])
        root.addWidget(spl)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Chưa kết nối")

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.addWidget(self._build_connection())
        lay.addWidget(self._build_session())
        lay.addWidget(self._build_stats())
        lay.addStretch()
        return w

    # ── Connection panel ─────────────────────────────────────────────────────

    def _build_connection(self) -> QGroupBox:
        grp = QGroupBox("Kết nối")
        lay = QVBoxLayout(grp)

        mode_row = QHBoxLayout()
        self._rb_serial = QRadioButton("Cổng Serial")
        self._rb_tcp_c  = QRadioButton("TCP Client")
        self._rb_tcp_s  = QRadioButton("TCP Server")
        self._rb_serial.setChecked(True)
        self._mode_grp  = QButtonGroup(self)
        for rb in (self._rb_serial, self._rb_tcp_c, self._rb_tcp_s):
            self._mode_grp.addButton(rb)
            mode_row.addWidget(rb)
        lay.addLayout(mode_row)

        # Serial
        self._w_serial = QWidget()
        sf = QFormLayout(self._w_serial)
        sf.setContentsMargins(0,0,0,0)
        pr = QHBoxLayout()
        self._ser_port = QComboBox()
        self._btn_refresh = QPushButton("↺")
        self._btn_refresh.setFixedWidth(32)
        pr.addWidget(self._ser_port, stretch=1)
        pr.addWidget(self._btn_refresh)
        self._ser_baud = QComboBox()
        self._ser_baud.addItems(["4800","9600","19200","38400","115200"])
        sf.addRow("Cổng:", pr)
        sf.addRow("Baud:", self._ser_baud)
        lay.addWidget(self._w_serial)

        # TCP Client
        self._w_tcp_c = QWidget()
        tf = QFormLayout(self._w_tcp_c)
        tf.setContentsMargins(0,0,0,0)
        self._tcp_host = QLineEdit("192.168.1.1")
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1,65535)
        self._tcp_port.setValue(10110)
        tf.addRow("Máy chủ:", self._tcp_host)
        tf.addRow("Cổng:", self._tcp_port)
        self._w_tcp_c.setVisible(False)
        lay.addWidget(self._w_tcp_c)

        # TCP Server
        self._w_tcp_s = QWidget()
        sf2 = QFormLayout(self._w_tcp_s)
        sf2.setContentsMargins(0,0,0,0)
        self._srv_host = QLineEdit("0.0.0.0")
        self._srv_port = QSpinBox()
        self._srv_port.setRange(1,65535)
        self._srv_port.setValue(10110)
        sf2.addRow("Địa chỉ bind:", self._srv_host)
        sf2.addRow("Cổng:", self._srv_port)
        self._w_tcp_s.setVisible(False)
        lay.addWidget(self._w_tcp_s)

        btn_row = QHBoxLayout()
        self._btn_connect    = _btn("Kết nối",    "#28a745","#218838","#1a6b2a")
        self._btn_disconnect = _btn("Ngắt kết nối", "#dc3545","#c82333","#a71d2a")
        self._btn_disconnect.setEnabled(False)
        btn_row.addWidget(self._btn_connect)
        btn_row.addWidget(self._btn_disconnect)
        lay.addLayout(btn_row)

        self._refresh_ports()
        return grp

    # ── Session panel ─────────────────────────────────────────────────────────

    def _build_session(self) -> QGroupBox:
        grp = QGroupBox("Phiên ghi / Lưu file")
        lay = QVBoxLayout(grp)

        # Output folder
        folder_row = QHBoxLayout()
        folder_row.addWidget(QLabel("Lưu vào:"))
        self._txt_folder = QLineEdit(os.path.expanduser("~/Documents/NMEA_Logs"))
        self._txt_folder.setReadOnly(True)
        self._btn_folder = QPushButton("...")
        self._btn_folder.setFixedWidth(32)
        folder_row.addWidget(self._txt_folder, stretch=1)
        folder_row.addWidget(self._btn_folder)
        lay.addLayout(folder_row)

        # Prefix
        prefix_row = QHBoxLayout()
        prefix_row.addWidget(QLabel("Tiền tố:"))
        self._txt_prefix = QLineEdit("session")
        prefix_row.addWidget(self._txt_prefix, stretch=1)
        lay.addLayout(prefix_row)

        # Session buttons
        sess_row = QHBoxLayout()
        self._btn_new_session  = _btn("▶  Phiên mới",    "#0d6efd","#0b5ed7","#0a52be")
        self._btn_resume       = _btn("↩  Ghi tiếp",     "#6f42c1","#5a32a3","#4a2888")
        self._btn_stop_session = _btn("■  Dừng",         "#fd7e14","#e06c0d","#c25c0b")
        self._btn_new_session.setToolTip("Tạo file phiên mới với timestamp")
        self._btn_resume.setToolTip("Ghi tiếp vào file phiên vừa dừng")
        self._btn_new_session.setEnabled(False)
        self._btn_resume.setEnabled(False)
        self._btn_stop_session.setEnabled(False)
        sess_row.addWidget(self._btn_new_session)
        sess_row.addWidget(self._btn_resume)
        sess_row.addWidget(self._btn_stop_session)
        lay.addLayout(sess_row)

        # Current session info
        self._lbl_session_file = QLabel("—")
        self._lbl_session_file.setStyleSheet("color:#ffc107; font-style:italic;")
        self._lbl_session_file.setWordWrap(True)
        self._lbl_session_info = QLabel("0 bản tin  |  00:00")
        self._lbl_session_info.setStyleSheet("color:#90a4ae;")

        self._rec_dot = QLabel("●")
        self._rec_dot.setStyleSheet("color:#555; font-size:14px;")
        info_row = QHBoxLayout()
        info_row.addWidget(self._rec_dot)
        info_row.addWidget(self._lbl_session_info, stretch=1)

        lay.addWidget(self._lbl_session_file)
        lay.addLayout(info_row)

        return grp

    # ── Stats panel ───────────────────────────────────────────────────────────

    def _build_stats(self) -> QGroupBox:
        grp = QGroupBox("Thống kê")
        lay = QVBoxLayout(grp)

        self._lbl_total = QLabel("Tổng nhận được: 0")
        self._lbl_total.setStyleSheet("font-weight:bold;")
        lay.addWidget(self._lbl_total)

        self._stats_widget = QWidget()
        self._stats_layout = QVBoxLayout(self._stats_widget)
        self._stats_layout.setSpacing(2)
        self._stats_layout.setContentsMargins(0,0,0,0)

        scroll = QScrollArea()
        scroll.setWidget(self._stats_widget)
        scroll.setWidgetResizable(True)
        scroll.setMaximumHeight(160)
        scroll.setStyleSheet("border:none;")
        lay.addWidget(scroll)

        self._btn_reset_stats = QPushButton("Đặt lại thống kê")
        self._btn_reset_stats.setStyleSheet("color:#90a4ae;")
        lay.addWidget(self._btn_reset_stats)

        return grp

    # ── Log console ───────────────────────────────────────────────────────────

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setStyleSheet(f"background:{_LOG_BG}; color:#fff; border:none;")
        lay.addWidget(self._log)

        bar = QHBoxLayout()
        self._btn_clear = QPushButton("Xóa log")
        self._lbl_rx    = QLabel("0 bản tin nhận")
        bar.addWidget(self._btn_clear)
        bar.addStretch()
        bar.addWidget(self._lbl_rx)
        lay.addLayout(bar)

        return w

    # ── Signals ───────────────────────────────────────────────────────────────

    def _wire(self):
        self._rb_serial.toggled.connect(self._on_mode)
        self._rb_tcp_c.toggled.connect(self._on_mode)
        self._rb_tcp_s.toggled.connect(self._on_mode)
        self._btn_refresh.clicked.connect(self._refresh_ports)
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)
        self._btn_folder.clicked.connect(self._pick_folder)
        self._btn_new_session.clicked.connect(self._new_session)
        self._btn_resume.clicked.connect(self._resume_session)
        self._btn_stop_session.clicked.connect(self._stop_session)
        self._btn_clear.clicked.connect(self._log.clear)
        self._btn_reset_stats.clicked.connect(self._reset_stats)

    # ── Slots ─────────────────────────────────────────────────────────────────

    def _on_mode(self):
        self._w_serial.setVisible(self._rb_serial.isChecked())
        self._w_tcp_c.setVisible(self._rb_tcp_c.isChecked())
        self._w_tcp_s.setVisible(self._rb_tcp_s.isChecked())

    def _refresh_ports(self):
        self._ser_port.clear()
        ports = list_serial_ports()
        self._ser_port.addItems(ports if ports else ["(không tìm thấy cổng)"])

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu log",
                                              self._txt_folder.text())
        if d:
            self._txt_folder.setText(d)

    def _on_connect(self):
        try:
            if self._rb_serial.isChecked():
                mode = 'serial'
                kw   = {'port': self._ser_port.currentText(),
                        'baud': int(self._ser_baud.currentText())}
            elif self._rb_tcp_c.isChecked():
                mode = 'tcp_client'
                kw   = {'host': self._tcp_host.text().strip(),
                        'port': self._tcp_port.value()}
            else:
                mode = 'tcp_server'
                kw   = {'host': self._srv_host.text().strip(),
                        'port': self._srv_port.value()}

            self._receiver = ReceiverThread(mode, **kw)
            self._receiver.sentence_received.connect(self._on_sentence)
            self._receiver.status_changed.connect(self._on_status)
            self._receiver.error.connect(self._on_error)
            self._receiver.start()

            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._btn_new_session.setEnabled(True)
            self._btn_resume.setEnabled(self._last_session is not None)
        except Exception as exc:
            QMessageBox.critical(self, "Lỗi kết nối", str(exc))

    def _on_disconnect(self):
        self._stop_session()
        if self._receiver:
            self._receiver.stop()
            self._receiver = None
        self._btn_connect.setEnabled(True)
        self._btn_disconnect.setEnabled(False)
        self._btn_new_session.setEnabled(False)
        self._btn_stop_session.setEnabled(False)
        self._btn_resume.setEnabled(False)
        self.statusBar().showMessage("Đã ngắt kết nối")

    def _new_session(self):
        self._stop_session()
        folder = self._txt_folder.text().strip()
        prefix = self._txt_prefix.text().strip() or 'session'
        self._logger = SessionLogger(folder, prefix)
        self._last_session = self._logger.path
        self._lbl_session_file.setText(os.path.basename(self._logger.path))
        self._btn_stop_session.setEnabled(True)
        self._btn_resume.setEnabled(False)
        self._log_info(f"Phiên mới: {self._logger.path}")
        self.statusBar().showMessage(f"Đang ghi → {os.path.basename(self._logger.path)}")

    def _resume_session(self):
        if not self._last_session or not os.path.exists(self._last_session):
            QMessageBox.warning(self, "Không tìm thấy", "File phiên trước không còn tồn tại.")
            return
        self._stop_session()
        self._logger = SessionLogger("", existing_path=self._last_session)
        self._lbl_session_file.setText(os.path.basename(self._logger.path))
        self._btn_stop_session.setEnabled(True)
        self._btn_resume.setEnabled(False)
        self._log_info(f"Ghi tiếp: {self._logger.path} ({self._logger.count} records trước đó)")
        self.statusBar().showMessage(f"Đang ghi tiếp → {os.path.basename(self._logger.path)}")

    def _stop_session(self):
        if self._logger and self._logger.is_open:
            self._logger.close()
            self._log_info(
                f"Đã dừng: {self._logger.count} records — "
                f"{os.path.basename(self._logger.path)}"
            )
        self._logger = None
        self._lbl_session_file.setText("—")
        self._lbl_session_info.setText("0 bản tin  |  00:00")
        self._rec_dot.setStyleSheet("color:#555; font-size:14px;")
        self._btn_stop_session.setEnabled(False)
        self._btn_resume.setEnabled(self._last_session is not None)

    @pyqtSlot(str, str)
    def _on_sentence(self, sentence: str, tag: str):
        # Ghi log nếu session đang mở
        if self._logger and self._logger.is_open:
            self._logger.write(sentence, tag)

        # Stats
        self._stats[tag] = self._stats.get(tag, 0) + 1
        self._total_rx  += 1

        # Log console
        from datetime import datetime
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        colour = _tag_colour(tag)
        self._log.append(
            f'<span style="color:#546e7a;">{ts}</span>'
            f'&nbsp;<span style="color:{_COL_INFO};">[{tag}]</span>'
            f'&nbsp;<span style="color:{colour};">{sentence}</span>'
        )
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._lbl_rx.setText(f"{self._total_rx} bản tin nhận")

    @pyqtSlot(str)
    def _on_status(self, msg: str):
        self.statusBar().showMessage(msg)
        self._log_info(msg)

    @pyqtSlot(str)
    def _on_error(self, err: str):
        self._log.append(f'<span style="color:{_COL_ERR};">[LỖI] {err}</span>')
        QMessageBox.warning(self, "Lỗi nhận dữ liệu", err)
        self._on_disconnect()

    def _log_info(self, text: str):
        from datetime import datetime
        ts = datetime.now().strftime('%H:%M:%S.%f')[:-3]
        self._log.append(
            f'<span style="color:#546e7a;">{ts}</span>'
            f'&nbsp;<span style="color:{_COL_INFO};">[INFO] {text}</span>'
        )

    # ── Periodic UI refresh ───────────────────────────────────────────────────

    def _refresh_ui(self):
        # Blink recording dot
        if self._logger and self._logger.is_open:
            self._blink = not self._blink
            colour = _COL_REC if self._blink else "#555"
            self._rec_dot.setStyleSheet(f"color:{colour}; font-size:14px;")

            elapsed = int(self._logger.duration_s)
            mm, ss  = divmod(elapsed, 60)
            hh, mm  = divmod(mm, 60)
            t_str   = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
            self._lbl_session_info.setText(
                f"{self._logger.count} bản tin  |  {t_str}"
            )

        # Stats labels
        self._lbl_total.setText(f"Tổng nhận được: {self._total_rx}")
        self._rebuild_stats()

    def _rebuild_stats(self):
        # Xóa các label cũ
        while self._stats_layout.count():
            item = self._stats_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        for tag in sorted(self._stats, key=lambda t: -self._stats[t]):
            count  = self._stats[tag]
            colour = _tag_colour(tag)
            lbl    = QLabel(f'<span style="color:{colour};">[{tag}]</span>'
                            f'&nbsp;<b>{count}</b>')
            lbl.setTextFormat(Qt.TextFormat.RichText)
            self._stats_layout.addWidget(lbl)

    def _reset_stats(self):
        self._stats   = {}
        self._total_rx = 0

    def closeEvent(self, event):
        self._on_disconnect()
        event.accept()


# ── Entry point ───────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
