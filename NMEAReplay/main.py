"""NMEA Replay Tool — phát lại bản tin từ file log .bin thu từ tàu thật."""

import sys
import os

# Import transmitters từ thư mục cha
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from transmitters import (
    TCPTransmitter,
    TCPServerTransmitter,
    SerialTransmitter,
    list_serial_ports,
)

from PyQt6.QtCore import Qt, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QComboBox,
    QDoubleSpinBox,
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
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from bin_parser import parse_log_file, merge_logs, count_by_type
from replay_engine import ReplayThread

# ── Màu log ────────────────────────────────────────────────────────────────
_LOG_BG    = "#1e1e1e"
_COL_GPS   = "#00e676"
_COL_RADAR = "#ffee58"
_COL_AIS   = "#40c4ff"
_COL_INFO  = "#90a4ae"
_COL_ERROR = "#ef5350"

_GPS_TAGS   = {'RMC', 'GGA', 'GNS', 'GLL', 'VTG', 'ZDA', 'GSA', 'GSV',
               'GBS', 'HDT', 'HDM', 'HDG', 'ROT', 'THS', 'RMB', 'TT'}
_AIS_TAGS   = {'VDM', 'VDO'}
_RADAR_TAGS = {'TTM', 'TTD', 'OSD', 'RSD', 'RCD', 'RCL'}


def _tag_colour(type_tag: str) -> str:
    if type_tag in _AIS_TAGS:
        return _COL_AIS
    if type_tag in _RADAR_TAGS:
        return _COL_RADAR
    if type_tag in _GPS_TAGS:
        return _COL_GPS
    return "#ffffff"


def _btn_qss(normal, hover, pressed, text="white"):
    return (
        f"QPushButton{{background:{normal};color:{text};font-weight:bold;"
        f"border:none;border-radius:4px;padding:5px 12px;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:pressed{{background:{pressed};}}"
        f"QPushButton:disabled{{background:#4a4a4a;color:#888;}}"
    )


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NMEA Replay Tool")
        self.setMinimumSize(1100, 680)

        self._transmitter = None
        self._thread: ReplayThread | None = None
        self._records: list = []

        self._build_ui()
        self._wire_signals()

    # ── UI ─────────────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setSpacing(8)
        ll.addWidget(self._build_connection_panel())
        ll.addWidget(self._build_file_panel())
        ll.addWidget(self._build_control_panel())
        ll.addStretch()

        right = QWidget()
        rl = QVBoxLayout(right)
        rl.addWidget(self._build_log_panel())

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([380, 700])
        root.addWidget(splitter)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Disconnected")

    # ── Connection panel ────────────────────────────────────────────────────

    def _build_connection_panel(self):
        grp = QGroupBox("Connection")
        lay = QVBoxLayout(grp)

        mode_row = QHBoxLayout()
        self._rb_tcp        = QRadioButton("TCP Client")
        self._rb_tcp_server = QRadioButton("TCP Server")
        self._rb_serial     = QRadioButton("Serial Port")
        self._rb_tcp.setChecked(True)
        self._mode_grp = QButtonGroup(self)
        for rb in (self._rb_tcp, self._rb_tcp_server, self._rb_serial):
            self._mode_grp.addButton(rb)
            mode_row.addWidget(rb)
        lay.addLayout(mode_row)

        # TCP Client
        self._tcp_widget = QWidget()
        tf = QFormLayout(self._tcp_widget)
        tf.setContentsMargins(0, 0, 0, 0)
        self._tcp_host = QLineEdit("127.0.0.1")
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1, 65535)
        self._tcp_port.setValue(10110)
        tf.addRow("Host:", self._tcp_host)
        tf.addRow("Port:", self._tcp_port)
        lay.addWidget(self._tcp_widget)

        # TCP Server
        self._tcp_server_widget = QWidget()
        sf = QFormLayout(self._tcp_server_widget)
        sf.setContentsMargins(0, 0, 0, 0)
        self._srv_host = QLineEdit("0.0.0.0")
        self._srv_port = QSpinBox()
        self._srv_port.setRange(1, 65535)
        self._srv_port.setValue(10110)
        self._lbl_clients = QLabel("0 clients connected")
        self._lbl_clients.setStyleSheet("color:#0d6efd;font-weight:bold;")
        sf.addRow("Bind IP:", self._srv_host)
        sf.addRow("Port:", self._srv_port)
        sf.addRow("", self._lbl_clients)
        self._tcp_server_widget.setVisible(False)
        lay.addWidget(self._tcp_server_widget)

        # Serial
        self._serial_widget = QWidget()
        serf = QFormLayout(self._serial_widget)
        serf.setContentsMargins(0, 0, 0, 0)
        port_row = QHBoxLayout()
        self._serial_port = QComboBox()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setFixedWidth(68)
        port_row.addWidget(self._serial_port, stretch=1)
        port_row.addWidget(self._btn_refresh)
        self._serial_baud = QComboBox()
        self._serial_baud.addItems(["4800", "9600", "19200", "38400", "115200"])
        serf.addRow("Port:", port_row)
        serf.addRow("Baud:", self._serial_baud)
        self._serial_widget.setVisible(False)
        lay.addWidget(self._serial_widget)

        conn_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setStyleSheet(_btn_qss("#28a745", "#218838", "#1a6b2a"))
        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.setStyleSheet(_btn_qss("#dc3545", "#c82333", "#a71d2a"))
        self._btn_disconnect.setEnabled(False)
        conn_row.addWidget(self._btn_connect)
        conn_row.addWidget(self._btn_disconnect)
        lay.addLayout(conn_row)

        self._refresh_ports()
        return grp

    # ── File loader panel ────────────────────────────────────────────────────

    def _build_file_panel(self):
        grp = QGroupBox("Log Files (.bin)")
        lay = QVBoxLayout(grp)

        self._file_rows = {}
        for label, key in [("GPS", "gps"), ("AIS", "ais"), ("Radar", "radar")]:
            row = QHBoxLayout()
            lbl = QLabel(f"{label}:")
            lbl.setFixedWidth(46)
            path_edit = QLineEdit()
            path_edit.setReadOnly(True)
            path_edit.setPlaceholderText(f"Chưa chọn file {label}")
            btn_browse = QPushButton("...")
            btn_browse.setFixedWidth(32)
            btn_clear  = QPushButton("✕")
            btn_clear.setFixedWidth(28)
            row.addWidget(lbl)
            row.addWidget(path_edit, stretch=1)
            row.addWidget(btn_browse)
            row.addWidget(btn_clear)
            lay.addLayout(row)
            self._file_rows[key] = (path_edit, btn_browse, btn_clear)

        self._btn_load = QPushButton("Load Files")
        self._btn_load.setStyleSheet(_btn_qss("#6f42c1", "#5a32a3", "#4a2888"))
        lay.addWidget(self._btn_load)

        # Summary
        self._lbl_summary = QLabel("Chưa load file nào.")
        self._lbl_summary.setStyleSheet("color:#90a4ae; font-style:italic;")
        self._lbl_summary.setWordWrap(True)
        lay.addWidget(self._lbl_summary)

        return grp

    # ── Playback control panel ───────────────────────────────────────────────

    def _build_control_panel(self):
        grp = QGroupBox("Playback")
        lay = QVBoxLayout(grp)

        # Speed
        speed_row = QHBoxLayout()
        speed_row.addWidget(QLabel("Speed:"))
        self._speed_spin = QDoubleSpinBox()
        self._speed_spin.setRange(0.1, 100.0)
        self._speed_spin.setValue(1.0)
        self._speed_spin.setDecimals(1)
        self._speed_spin.setSuffix(" ×")
        self._speed_spin.setToolTip("1.0 = tốc độ thực, 2.0 = nhanh gấp đôi, v.v.")
        speed_row.addWidget(self._speed_spin)
        speed_row.addStretch()
        lay.addLayout(speed_row)

        # Progress
        self._progress = QProgressBar()
        self._progress.setValue(0)
        lay.addWidget(self._progress)

        self._lbl_progress = QLabel("0 / 0")
        self._lbl_progress.setAlignment(Qt.AlignmentFlag.AlignCenter)
        lay.addWidget(self._lbl_progress)

        # Buttons
        btn_row = QHBoxLayout()
        self._btn_play  = QPushButton("▶  Play")
        self._btn_play.setStyleSheet(_btn_qss("#0d6efd", "#0b5ed7", "#0a52be"))
        self._btn_play.setEnabled(False)
        self._btn_pause = QPushButton("⏸  Pause")
        self._btn_pause.setStyleSheet(_btn_qss("#fd7e14", "#e06c0d", "#c25c0b"))
        self._btn_pause.setEnabled(False)
        self._btn_stop  = QPushButton("■  Stop")
        self._btn_stop.setStyleSheet(_btn_qss("#969da3", "#848c92", "#7b848b"))
        self._btn_stop.setEnabled(False)
        btn_row.addWidget(self._btn_play)
        btn_row.addWidget(self._btn_pause)
        btn_row.addWidget(self._btn_stop)
        lay.addLayout(btn_row)

        return grp

    # ── Log panel ────────────────────────────────────────────────────────────

    def _build_log_panel(self):
        grp = QGroupBox("NMEA Log")
        lay = QVBoxLayout(grp)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setStyleSheet(
            f"background:{_LOG_BG}; color:#fff; border:none;"
        )
        lay.addWidget(self._log)

        bar = QHBoxLayout()
        self._btn_clear_log = QPushButton("Clear")
        self._lbl_count = QLabel("0 sentences sent")
        bar.addWidget(self._btn_clear_log)
        bar.addStretch()
        bar.addWidget(self._lbl_count)
        lay.addLayout(bar)

        return grp

    # ── Signals ──────────────────────────────────────────────────────────────

    def _wire_signals(self):
        self._rb_tcp.toggled.connect(self._on_mode_changed)
        self._rb_tcp_server.toggled.connect(self._on_mode_changed)
        self._btn_refresh.clicked.connect(self._refresh_ports)
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)

        for key, (path_edit, btn_browse, btn_clear) in self._file_rows.items():
            btn_browse.clicked.connect(lambda _, k=key: self._browse_file(k))
            btn_clear.clicked.connect(lambda _, k=key: self._clear_file(k))

        self._btn_load.clicked.connect(self._on_load)
        self._btn_play.clicked.connect(self._on_play)
        self._btn_pause.clicked.connect(self._on_pause)
        self._btn_stop.clicked.connect(self._on_stop)
        self._btn_clear_log.clicked.connect(self._log.clear)
        self._speed_spin.valueChanged.connect(self._on_speed_changed)

    # ── Slots ────────────────────────────────────────────────────────────────

    def _on_mode_changed(self):
        self._tcp_widget.setVisible(self._rb_tcp.isChecked())
        self._tcp_server_widget.setVisible(self._rb_tcp_server.isChecked())
        self._serial_widget.setVisible(self._rb_serial.isChecked())

    def _refresh_ports(self):
        self._serial_port.clear()
        ports = list_serial_ports()
        self._serial_port.addItems(ports if ports else ["(no ports found)"])

    def _browse_file(self, key: str):
        path, _ = QFileDialog.getOpenFileName(
            self, f"Chọn file {key.upper()} log", "", "Log files (*.bin *.log *.txt);;All files (*)"
        )
        if path:
            self._file_rows[key][0].setText(path)

    def _clear_file(self, key: str):
        self._file_rows[key][0].clear()

    def _on_connect(self):
        try:
            if self._rb_tcp.isChecked():
                host = self._tcp_host.text().strip()
                port = self._tcp_port.value()
                self._transmitter = TCPTransmitter(host, port)
                label = f"TCP Client  {host}:{port}"
            elif self._rb_tcp_server.isChecked():
                host = self._srv_host.text().strip()
                port = self._srv_port.value()
                self._transmitter = TCPServerTransmitter(host, port)
                label = f"TCP Server  {host}:{port}"
            else:
                port_name = self._serial_port.currentText()
                baud = int(self._serial_baud.currentText())
                self._transmitter = SerialTransmitter(port_name, baud)
                label = f"Serial  {port_name} @ {baud}"

            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._statusbar_msg(f"Connected — {label}")
            self._log_info(f"Connected: {label}")
            self._update_play_btn()
        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))

    def _on_disconnect(self):
        self._on_stop()
        if self._transmitter:
            self._transmitter.close()
            self._transmitter = None
        self._btn_connect.setEnabled(True)
        self._btn_disconnect.setEnabled(False)
        self._btn_play.setEnabled(False)
        self._statusbar_msg("Disconnected")

    def _on_load(self):
        record_lists = []
        labels = []
        for key, label in [("gps", "GPS"), ("ais", "AIS"), ("radar", "Radar")]:
            path = self._file_rows[key][0].text().strip()
            if not path:
                continue
            try:
                recs = parse_log_file(path)
                record_lists.append(recs)
                counts = count_by_type(recs)
                top = sorted(counts.items(), key=lambda x: -x[1])[:5]
                top_str = "  ".join(f"{t}:{n}" for t, n in top)
                labels.append(f"{label}: {len(recs)} records  [{top_str}]")
            except Exception as exc:
                QMessageBox.warning(self, "Load Error", f"{label}: {exc}")

        if not record_lists:
            QMessageBox.warning(self, "Không có file", "Hãy chọn ít nhất 1 file log.")
            return

        self._records = merge_logs(*record_lists)
        self._lbl_summary.setText("\n".join(labels) + f"\n→ Tổng: {len(self._records)} records")
        self._progress.setMaximum(len(self._records))
        self._progress.setValue(0)
        self._lbl_progress.setText(f"0 / {len(self._records)}")
        self._log_info(f"Loaded {len(self._records)} records từ {len(record_lists)} file(s)")
        self._update_play_btn()

    def _on_play(self):
        if not self._transmitter or not self._records:
            return
        self._msg_count = 0
        self._thread = ReplayThread(
            self._records, self._transmitter, self._speed_spin.value()
        )
        self._thread.sentence_sent.connect(self._on_sentence_sent)
        self._thread.progress.connect(self._on_progress)
        self._thread.finished.connect(self._on_finished)
        self._thread.error.connect(self._on_error)
        self._thread.start()

        self._btn_play.setEnabled(False)
        self._btn_pause.setEnabled(True)
        self._btn_stop.setEnabled(True)
        self._statusbar_msg("Replaying…")

    def _on_pause(self):
        if self._thread:
            if self._btn_pause.text().startswith("⏸"):
                self._thread.pause()
                self._btn_pause.setText("▶  Resume")
                self._statusbar_msg("Paused")
            else:
                self._thread.resume()
                self._btn_pause.setText("⏸  Pause")
                self._statusbar_msg("Replaying…")

    def _on_stop(self):
        if self._thread:
            self._thread.stop()
            self._thread = None
        self._btn_play.setEnabled(bool(self._transmitter and self._records))
        self._btn_pause.setEnabled(False)
        self._btn_pause.setText("⏸  Pause")
        self._btn_stop.setEnabled(False)
        if self._transmitter:
            self._statusbar_msg("Connected  (stopped)")

    def _on_speed_changed(self, value: float):
        if self._thread:
            self._thread.set_speed(value)

    @pyqtSlot(str, str)
    def _on_sentence_sent(self, sentence: str, type_tag: str):
        colour = _tag_colour(type_tag)
        self._log.append(
            f'<span style="color:{_COL_INFO};">[{type_tag}]</span>'
            f'&nbsp;<span style="color:{colour};">{sentence}</span>'
        )
        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._msg_count = getattr(self, '_msg_count', 0) + 1
        self._lbl_count.setText(f"{self._msg_count} sentences sent")

    @pyqtSlot(int, int)
    def _on_progress(self, current: int, total: int):
        self._progress.setValue(current)
        self._lbl_progress.setText(f"{current} / {total}")

    @pyqtSlot()
    def _on_finished(self):
        self._on_stop()
        self._log_info("Replay finished.")
        self._statusbar_msg("Replay finished")

    @pyqtSlot(str)
    def _on_error(self, err: str):
        self._log.append(f'<span style="color:{_COL_ERROR};">[ERROR] {err}</span>')
        QMessageBox.warning(self, "Replay Error", err)
        self._on_stop()

    def _log_info(self, text: str):
        self._log.append(f'<span style="color:{_COL_INFO};">[INFO] {text}</span>')

    def _statusbar_msg(self, msg: str):
        self.statusBar().showMessage(msg)

    def _update_play_btn(self):
        self._btn_play.setEnabled(
            bool(self._transmitter) and bool(self._records)
        )

    def closeEvent(self, event):
        self._on_stop()
        if self._transmitter:
            self._transmitter.close()
        event.accept()


# ── Entry point ─────────────────────────────────────────────────────────────

def main():
    app = QApplication(sys.argv)
    app.setStyle("Fusion")

    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "icon.ico")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        app.setWindowIcon(icon)

    win = MainWindow()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
