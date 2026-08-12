"""NMEA Collector — thu thập và ghi log bản tin NMEA từ thiết bị thật trên tàu.

Hỗ trợ tối đa 5 kết nối đồng thời (TCP Client / TCP Server / Serial),
mỗi kết nối lưu vào file riêng, tự xoay file theo ngày, lưu/tải cấu hình.
"""

import os
import sys
from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QIcon, QTextCursor
from PyQt6.QtWidgets import QMenu, QSystemTrayIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFileDialog,
    QFormLayout,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMessageBox,
    QPushButton,
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
import config as cfg_io
import startup as startup_mgr

# ── Màu ──────────────────────────────────────────────────────────────────────
_LOG_BG    = "#1e1e1e"
_COL_GPS   = "#00e676"
_COL_RADAR = "#ffee58"
_COL_AIS   = "#40c4ff"
_COL_INFO  = "#90a4ae"
_COL_REC   = "#ff6090"

_GPS_TAGS   = {'RMC','GGA','GNS','GLL','VTG','ZDA','GSA','GSV','GBS',
               'HDT','HDM','HDG','ROT','THS','RMB'}
_AIS_TAGS   = {'VDM','VDO'}
_RADAR_TAGS = {'TTM','TTD','OSD','RSD','RCD','RCL'}

MAX_CONNECTIONS = 25

def _tag_colour(tag: str) -> str:
    if tag in _AIS_TAGS:   return _COL_AIS
    if tag in _RADAR_TAGS: return _COL_RADAR
    if tag in _GPS_TAGS:   return _COL_GPS
    return "#ffffff"


def _btn(label: str, normal: str, hover: str, pressed: str,
         text: str = "white", width: int = 0) -> QPushButton:
    b = QPushButton(label)
    b.setStyleSheet(
        f"QPushButton{{background:{normal};color:{text};font-weight:bold;"
        f"border:none;border-radius:4px;padding:4px 10px;}}"
        f"QPushButton:hover{{background:{hover};}}"
        f"QPushButton:pressed{{background:{pressed};}}"
        f"QPushButton:disabled{{background:#3a3a3a;color:#666;}}"
    )
    if width:
        b.setFixedWidth(width)
    return b


# ── Widget một kết nối ───────────────────────────────────────────────────────

class ConnectionRow(QGroupBox):
    """Widget quản lý một kết nối TCP/Serial + file ghi tương ứng."""

    sentence_received = pyqtSignal(str, str, str)   # sentence, tag, label
    request_remove    = pyqtSignal(object)           # self

    def __init__(self, row_id: int, get_folder, get_daily_rotate, get_max_folder_gb):
        super().__init__(f"Kết nối #{row_id}")
        self._id              = row_id
        self._get_folder      = get_folder        # callable → str
        self._get_daily_rot   = get_daily_rotate  # callable → bool
        self._get_max_gb      = get_max_folder_gb # callable → float | None
        self._receiver: ReceiverThread | None = None
        self._logger:   SessionLogger  | None = None
        self._stats:    dict[str, int]        = {}
        self._total     = 0
        self._blink     = False
        self._last_path: str | None           = None
        self._build()

    # ── Build ─────────────────────────────────────────────────────────────

    def _build(self):
        self.setStyleSheet("""
            QGroupBox {
                border: 1px solid #444;
                border-radius: 5px;
                margin-top: 10px;
                font-weight: bold;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 4px;
            }
        """)

        lay = QVBoxLayout(self)
        lay.setContentsMargins(10, 14, 10, 8)
        lay.setSpacing(6)

        # ── Form fields ────────────────────────────────────────────────
        form = QFormLayout()
        form.setSpacing(6)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)

        # Loại kết nối + nút xóa
        mode_row = QHBoxLayout()
        self._mode = QComboBox()
        self._mode.addItems(["TCP Client", "TCP Server", "Cổng Serial"])
        self._mode.currentTextChanged.connect(self._on_mode_changed)
        self._mode.currentTextChanged.connect(self._on_params_changed)
        self._btn_remove = _btn("✕ Xóa", "#555","#dc3545","#a71d2a")
        self._btn_remove.setToolTip("Xóa kết nối này")
        self._btn_remove.clicked.connect(lambda: self.request_remove.emit(self))
        mode_row.addWidget(self._mode)
        mode_row.addStretch()
        mode_row.addWidget(self._btn_remove)
        form.addRow("Loại:", mode_row)

        # TCP: Host + Cổng
        tcp_row = QHBoxLayout()
        self._host = QLineEdit("192.168.1.1")
        self._host.setPlaceholderText("Host / IP")
        self._host.editingFinished.connect(self._on_params_changed)
        self._port = QSpinBox()
        self._port.setRange(1, 65535)
        self._port.setValue(10110)
        self._port.editingFinished.connect(self._on_params_changed)
        self._port.setFixedWidth(80)
        tcp_row.addWidget(self._host, stretch=1)
        tcp_row.addWidget(QLabel("Cổng:"))
        tcp_row.addWidget(self._port)
        self._tcp_widget = QWidget()
        self._tcp_widget.setLayout(tcp_row)
        self._tcp_widget.layout().setContentsMargins(0,0,0,0)
        form.addRow("Host:", self._tcp_widget)

        # Serial: cổng + baud + refresh
        ser_row = QHBoxLayout()
        self._ser_combo = QComboBox()
        self._ser_baud  = QComboBox()
        self._ser_baud.addItems(["4800","9600","19200","38400","115200"])
        self._ser_baud.setFixedWidth(90)
        self._btn_ref_ser = QPushButton("↺")
        self._btn_ref_ser.setFixedWidth(28)
        self._btn_ref_ser.setToolTip("Làm mới danh sách cổng")
        self._btn_ref_ser.clicked.connect(self._refresh_serial)
        ser_row.addWidget(self._ser_combo, stretch=1)
        ser_row.addWidget(self._ser_baud)
        ser_row.addWidget(self._btn_ref_ser)
        self._serial_widget = QWidget()
        self._serial_widget.setLayout(ser_row)
        self._serial_widget.layout().setContentsMargins(0,0,0,0)
        self._serial_widget.setVisible(False)
        form.addRow("COM:", self._serial_widget)

        # Tiền tố tên file
        self._prefix = QLineEdit("session")
        self._prefix.setPlaceholderText("Tiền tố tên file")
        form.addRow("Tiền tố:", self._prefix)

        lay.addLayout(form)

        # ── Đường kẻ ──────────────────────────────────────────────────
        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color:#3a3a3a;")
        lay.addWidget(sep)

        # ── Trạng thái ────────────────────────────────────────────────
        status_row = QHBoxLayout()
        self._dot = QLabel("●")
        self._dot.setStyleSheet("color:#555; font-size:13px;")
        self._lbl_status = QLabel("Chưa kết nối")
        self._lbl_status.setStyleSheet("color:#90a4ae; font-style:italic;")
        self._lbl_count  = QLabel("")
        self._lbl_count.setStyleSheet("color:#90a4ae; font-size:8pt;")
        status_row.addWidget(self._dot)
        status_row.addWidget(self._lbl_status, stretch=1)
        status_row.addWidget(self._lbl_count)
        lay.addLayout(status_row)

        self._lbl_file = QLabel("")
        self._lbl_file.setStyleSheet("color:#ffc107; font-size:8pt; padding-left:18px;")
        self._lbl_file.setWordWrap(True)
        lay.addWidget(self._lbl_file)

        self._refresh_serial()

    def _on_params_changed(self, *_):
        """Nếu đang kết nối mà thông số thay đổi → ngắt ngay để retry dùng giá trị mới."""
        if self.is_connected():
            self.disconnect()
            self._lbl_status.setText("Thông số thay đổi — nhấn Kết nối lại để áp dụng")
            self._dot.setStyleSheet("color:#ffc107; font-size:13px;")

    def _on_mode_changed(self, mode: str):
        is_serial = mode == "Cổng Serial"
        self._tcp_widget.setVisible(not is_serial)
        self._serial_widget.setVisible(is_serial)

    def _refresh_serial(self):
        self._ser_combo.clear()
        ports = list_serial_ports()
        self._ser_combo.addItems(ports if ports else ["(không có cổng)"])

    # ── Config I/O ────────────────────────────────────────────────────────

    def get_config(self) -> dict:
        mode = self._mode.currentText()
        cfg = {
            "mode":   mode,
            "prefix": self._prefix.text().strip() or "session",
        }
        if mode == "Cổng Serial":
            cfg["baud"] = self._ser_baud.currentText()
        else:
            cfg["host"] = self._host.text().strip()
            cfg["port"] = self._port.value()
        return cfg

    def set_config(self, c: dict):
        idx = self._mode.findText(c.get("mode", "TCP Client"))
        if idx >= 0:
            self._mode.setCurrentIndex(idx)
        self._host.setText(c.get("host", "192.168.1.1"))
        self._port.setValue(c.get("port", 10110))
        self._prefix.setText(c.get("prefix", "session"))
        bi = self._ser_baud.findText(str(c.get("baud", "4800")))
        if bi >= 0:
            self._ser_baud.setCurrentIndex(bi)

    # ── Connect / Disconnect ──────────────────────────────────────────────

    def connect(self) -> bool:
        """Khởi động receiver + logger. Trả về False nếu lỗi."""
        if self._receiver and self._receiver.isRunning():
            return True
        try:
            mode = self._mode.currentText()
            if mode == "TCP Client":
                kw = {"host": self._host.text().strip(), "port": self._port.value()}
                rmode = "tcp_client"
            elif mode == "TCP Server":
                kw = {"host": self._host.text().strip(), "port": self._port.value()}
                rmode = "tcp_server"
            else:
                kw    = {"port": self._ser_combo.currentText(),
                         "baud": int(self._ser_baud.currentText())}
                rmode = "serial"

            self._receiver = ReceiverThread(rmode, **kw)
            self._receiver.sentence_received.connect(self._on_sentence)
            self._receiver.status_changed.connect(self._on_status)
            self._receiver.error.connect(self._on_error)
            self._receiver.start()

            folder = self._get_folder()
            prefix = self._prefix.text().strip() or "session"
            max_gb = self._get_max_gb()
            if self._last_path and os.path.exists(self._last_path):
                # Kết nối lại → ghi tiếp vào file cũ
                self._logger = SessionLogger(folder, prefix,
                                             existing_path=self._last_path,
                                             daily_rotate=self._get_daily_rot(),
                                             max_folder_gb=max_gb)
            else:
                # Lần đầu kết nối → tạo file mới
                self._logger = SessionLogger(folder, prefix,
                                             daily_rotate=self._get_daily_rot(),
                                             max_folder_gb=max_gb)
                self._last_path = self._logger.path
            self._lbl_file.setText(os.path.basename(self._logger.path))
            self._lbl_status.setText("Đang kết nối…")
            self._dot.setStyleSheet("color:#ffc107; font-size:13px;")
            return True
        except Exception as exc:
            self._lbl_status.setText(f"Lỗi: {exc}")
            self._dot.setStyleSheet("color:#ef5350; font-size:13px;")
            return False

    def disconnect(self):
        if self._receiver:
            self._receiver.stop()
            self._receiver = None
        if self._logger:
            self._logger.close()
            self._logger = None
        self._dot.setStyleSheet("color:#555; font-size:13px;")
        self._lbl_status.setText("Đã ngắt")
        self._lbl_file.setText("")

    def is_connected(self) -> bool:
        return self._receiver is not None and self._receiver.isRunning()

    # ── Slots ─────────────────────────────────────────────────────────────

    @pyqtSlot(str, str)
    def _on_sentence(self, sentence: str, tag: str):
        if self._logger and self._logger.is_open:
            self._logger.write(sentence, tag)
            # Cập nhật nếu file đã xoay sang ngày mới
            if self._logger.path != self._last_path:
                self._last_path = self._logger.path
                self._lbl_file.setText(os.path.basename(self._logger.path))

        self._stats[tag] = self._stats.get(tag, 0) + 1
        self._total += 1

        mode = self._mode.currentText()
        if mode == "Cổng Serial":
            label = self._ser_combo.currentText()
        else:
            label = f"{self._host.text()}:{self._port.value()}"
        self.sentence_received.emit(sentence, tag, label)

    @pyqtSlot(str)
    def _on_status(self, msg: str):
        self._lbl_status.setText(msg)
        self._dot.setStyleSheet("color:#00e676; font-size:13px;")

    @pyqtSlot(str)
    def _on_error(self, err: str):
        self._lbl_status.setText(f"Lỗi: {err}")
        self._dot.setStyleSheet("color:#ef5350; font-size:13px;")

    # ── Blink & count update (gọi từ timer) ──────────────────────────────

    def tick(self):
        if self._logger and self._logger.is_open:
            self._blink = not self._blink
            col = _COL_REC if self._blink else "#00a040"
            self._dot.setStyleSheet(f"color:{col}; font-size:13px;")

            elapsed = int(self._logger.duration_s)
            mm, ss  = divmod(elapsed, 60)
            hh, mm  = divmod(mm, 60)
            t_str   = f"{hh:02d}:{mm:02d}:{ss:02d}" if hh else f"{mm:02d}:{ss:02d}"
            self._lbl_count.setText(f"{self._logger.count} bản tin | {t_str}")


# ── Main Window ───────────────────────────────────────────────────────────────

class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("NMEA Collector")
        self.setMinimumSize(1120, 680)

        self._cfg  = cfg_io.load()
        self._rows: list[ConnectionRow] = []
        self._stats_global: dict[str, int] = {}
        self._stat_labels: dict[str, QLabel] = {}   # cache label widget để không tạo lại
        self._total_rx = 0
        self._log_line_count = 0

        self._build_ui()
        self._build_tray()
        self._load_config_to_ui()

        self._timer = QTimer(self)
        self._timer.setInterval(500)
        self._timer.timeout.connect(self._tick)
        self._timer.start()

        # Tự động kết nối nếu được bật
        if self._chk_auto.isChecked() and self._rows:
            QTimer.singleShot(300, self._connect_all)

    # ── Build UI ──────────────────────────────────────────────────────────

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        spl = QSplitter(Qt.Orientation.Horizontal)
        spl.addWidget(self._build_left())
        spl.addWidget(self._build_right())
        spl.setSizes([400, 700])
        root.addWidget(spl)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Chưa kết nối")

    # ── Left panel ────────────────────────────────────────────────────────

    def _build_left(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setSpacing(8)
        lay.addWidget(self._build_global())
        lay.addWidget(self._build_connections_panel(), stretch=1)
        lay.addWidget(self._build_stats_panel())
        return w

    def _build_global(self) -> QGroupBox:
        grp = QGroupBox("Cài đặt chung")
        f = QFormLayout(grp)

        folder_row = QHBoxLayout()
        self._txt_folder = QLineEdit()
        self._txt_folder.setReadOnly(True)
        btn_f = QPushButton("...")
        btn_f.setFixedWidth(32)
        btn_f.clicked.connect(self._pick_folder)
        folder_row.addWidget(self._txt_folder, stretch=1)
        folder_row.addWidget(btn_f)
        f.addRow("Lưu vào:", folder_row)

        limit_row = QHBoxLayout()
        self._txt_max_gb = QLineEdit()
        self._txt_max_gb.setPlaceholderText("Không giới hạn")
        self._txt_max_gb.setFixedWidth(80)
        limit_row.addWidget(self._txt_max_gb)
        limit_row.addWidget(QLabel("GB"))
        limit_row.addStretch()
        f.addRow("Giới hạn thư mục log:", limit_row)

        self._chk_rotate   = QCheckBox("Tự tạo file khi sang ngày mới")
        self._chk_auto     = QCheckBox("Tự động kết nối khi khởi động")
        self._chk_startup  = QCheckBox("Tự khởi động cùng hệ thống")
        self._chk_startup.setChecked(startup_mgr.is_enabled())
        import sys as _sys
        if _sys.platform.startswith("linux"):
            _startup_tip = (
                "Tạo file ~/.config/autostart/nmea-collector.desktop\n"
                "để tool tự mở khi đăng nhập (hỗ trợ GNOME, KDE, XFCE…)."
            )
        else:
            _startup_tip = (
                "Đăng ký vào Windows Registry (HKCU) để tool tự mở khi máy tính khởi động.\n"
                "Không cần quyền Administrator."
            )
        self._chk_startup.setToolTip(_startup_tip)
        self._chk_startup.toggled.connect(self._on_startup_toggled)
        f.addRow("", self._chk_rotate)
        f.addRow("", self._chk_auto)
        f.addRow("", self._chk_startup)

        return grp

    def _build_connections_panel(self) -> QGroupBox:
        grp = QGroupBox("Các kết nối (tối đa 25)")
        lay = QVBoxLayout(grp)

        # Toolbar
        tb = QHBoxLayout()
        self._btn_add     = _btn("+ Thêm kết nối", "#6f42c1","#5a32a3","#4a2888")
        self._btn_conn_all= _btn("Kết nối tất cả", "#28a745","#218838","#1a6b2a")
        self._btn_disc_all= _btn("Ngắt tất cả",    "#dc3545","#c82333","#a71d2a")
        self._btn_save_cfg= _btn("Lưu cấu hình",   "#0d6efd","#0b5ed7","#0a52be")
        tb.addWidget(self._btn_add)
        tb.addWidget(self._btn_conn_all)
        tb.addWidget(self._btn_disc_all)
        tb.addWidget(self._btn_save_cfg)
        lay.addLayout(tb)

        # Scrollable area chứa các ConnectionRow
        self._rows_widget = QWidget()
        self._rows_layout = QVBoxLayout(self._rows_widget)
        self._rows_layout.setSpacing(6)
        self._rows_layout.setContentsMargins(0,0,0,0)

        scroll = QScrollArea()
        scroll.setWidget(self._rows_widget)
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet("border:none;")
        scroll.setMinimumHeight(80)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        lay.addWidget(scroll, stretch=1)

        self._btn_add.clicked.connect(self._add_row)
        self._btn_conn_all.clicked.connect(self._connect_all)
        self._btn_disc_all.clicked.connect(self._disconnect_all)
        self._btn_save_cfg.clicked.connect(self._save_config)

        return grp

    def _build_stats_panel(self) -> QGroupBox:
        grp = QGroupBox("Thống kê")
        lay = QVBoxLayout(grp)

        self._lbl_total = QLabel("Tổng nhận: 0")
        self._lbl_total.setStyleSheet("font-weight:bold;")
        lay.addWidget(self._lbl_total)

        self._stats_inner = QWidget()
        self._stats_lay   = QVBoxLayout(self._stats_inner)
        self._stats_lay.setSpacing(2)
        self._stats_lay.setContentsMargins(0,0,0,0)

        sc = QScrollArea()
        sc.setWidget(self._stats_inner)
        sc.setWidgetResizable(True)
        sc.setMaximumHeight(140)
        sc.setStyleSheet("border:none;")
        lay.addWidget(sc)

        self._btn_rst = QPushButton("Đặt lại thống kê")
        self._btn_rst.setStyleSheet("color:#90a4ae;")
        self._btn_rst.clicked.connect(self._reset_stats)
        lay.addWidget(self._btn_rst)

        return grp

    # ── Right panel (log) ─────────────────────────────────────────────────

    def _build_right(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        lbl = QLabel("Nhật ký NMEA")
        lbl.setStyleSheet("font-weight:bold;")
        lay.addWidget(lbl)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setStyleSheet(f"background:{_LOG_BG}; color:#fff; border:none;")
        lay.addWidget(self._log)

        bar = QHBoxLayout()
        btn_clr = QPushButton("Xóa log")
        self._lbl_rx = QLabel("0 bản tin nhận")
        btn_clr.clicked.connect(self._log.clear)
        bar.addWidget(btn_clr)
        bar.addStretch()
        bar.addWidget(self._lbl_rx)
        lay.addLayout(bar)

        return w

    # ── Config ────────────────────────────────────────────────────────────

    def _load_config_to_ui(self):
        max_gb = self._cfg.get("max_folder_gb")
        self._txt_max_gb.setText(str(max_gb) if max_gb else "")
        self._txt_folder.setText(self._cfg.get("output_folder",
            os.path.expanduser("~/Documents/NMEA_Logs")))
        self._chk_rotate.setChecked(self._cfg.get("daily_rotate", True))
        self._chk_auto.setChecked(self._cfg.get("auto_connect", False))
        for conn_cfg in self._cfg.get("connections", []):
            row = self._add_row()
            row.set_config(conn_cfg)

    def _save_config(self):
        self._cfg["output_folder"]  = self._txt_folder.text()
        self._cfg["daily_rotate"]   = self._chk_rotate.isChecked()
        self._cfg["auto_connect"]   = self._chk_auto.isChecked()
        try:
            self._cfg["max_folder_gb"] = float(self._txt_max_gb.text()) or None
        except ValueError:
            self._cfg["max_folder_gb"] = None
        self._cfg["connections"]    = [r.get_config() for r in self._rows]
        cfg_io.save(self._cfg)
        self.statusBar().showMessage("Đã lưu cấu hình", 3000)

    # ── Row management ────────────────────────────────────────────────────

    def _add_row(self) -> ConnectionRow:
        if len(self._rows) >= MAX_CONNECTIONS:
            QMessageBox.information(self, "Đã đủ",
                f"Tối đa {MAX_CONNECTIONS} kết nối đồng thời.")
            return self._rows[-1]
        row_id = len(self._rows) + 1
        row = ConnectionRow(
            row_id,
            get_folder       = lambda: self._txt_folder.text(),
            get_daily_rotate = lambda: self._chk_rotate.isChecked(),
            get_max_folder_gb= lambda: float(self._txt_max_gb.text()) if self._txt_max_gb.text() else None,
        )
        row.sentence_received.connect(self._on_sentence)
        row.request_remove.connect(self._remove_row)
        self._rows.append(row)
        self._rows_layout.addWidget(row)
        self._btn_add.setEnabled(len(self._rows) < MAX_CONNECTIONS)
        return row

    def _remove_row(self, row: ConnectionRow):
        row.disconnect()
        self._rows.remove(row)
        self._rows_layout.removeWidget(row)
        row.deleteLater()
        # Đánh lại số thứ tự
        for i, r in enumerate(self._rows):
            r.setTitle(f"Kết nối #{i+1}")
        self._btn_add.setEnabled(len(self._rows) < MAX_CONNECTIONS)

    # ── Connect / Disconnect all ──────────────────────────────────────────

    def _connect_all(self):
        ok = 0
        for row in self._rows:
            if row.connect():
                ok += 1
        self.statusBar().showMessage(f"Đã kết nối {ok}/{len(self._rows)} cổng")

    def _disconnect_all(self):
        for row in self._rows:
            row.disconnect()
        self.statusBar().showMessage("Đã ngắt tất cả kết nối")

    # ── Windows startup ───────────────────────────────────────────────────

    def _on_startup_toggled(self, checked: bool):
        try:
            startup_mgr.set_enabled(checked)
            msg = "Đã bật tự khởi động cùng Windows." if checked else "Đã tắt tự khởi động."
            self.statusBar().showMessage(msg, 4000)
        except Exception as exc:
            self._chk_startup.blockSignals(True)
            self._chk_startup.setChecked(not checked)   # hoàn tác nếu lỗi
            self._chk_startup.blockSignals(False)
            QMessageBox.warning(self, "Lỗi Registry", str(exc))

    # ── Pick folder ───────────────────────────────────────────────────────

    def _pick_folder(self):
        d = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu log",
                                              self._txt_folder.text())
        if d:
            self._txt_folder.setText(d)

    # ── Sentence received ─────────────────────────────────────────────────

    _MAX_LOG_LINES = 3000    # giữ tối đa N dòng trong console
    _TRIM_TO_LINES = 2000    # cắt xuống còn N dòng khi vượt ngưỡng

    @pyqtSlot(str, str, str)
    def _on_sentence(self, sentence: str, tag: str, label: str):
        self._stats_global[tag] = self._stats_global.get(tag, 0) + 1
        self._total_rx += 1

        ts     = datetime.now().strftime("%H:%M:%S.%f")[:-3]
        colour = _tag_colour(tag)
        self._log.append(
            f'<span style="color:#546e7a;">{ts}</span>'
            f'&nbsp;<span style="color:#607d8b;">[{label}]</span>'
            f'&nbsp;<span style="color:{_COL_INFO};">[{tag}]</span>'
            f'&nbsp;<span style="color:{colour};">{sentence}</span>'
        )
        self._log_line_count += 1

        # Tự cắt log khi quá nhiều dòng để tránh rò bộ nhớ
        if self._log_line_count >= self._MAX_LOG_LINES:
            doc    = self._log.document()
            cursor = QTextCursor(doc)
            cursor.movePosition(QTextCursor.MoveOperation.Start)
            cursor.movePosition(
                QTextCursor.MoveOperation.Down,
                QTextCursor.MoveMode.KeepAnchor,
                doc.blockCount() - self._TRIM_TO_LINES,
            )
            cursor.removeSelectedText()
            self._log_line_count = self._TRIM_TO_LINES

        sb = self._log.verticalScrollBar()
        sb.setValue(sb.maximum())
        self._lbl_rx.setText(f"{self._total_rx} bản tin nhận")

    # ── Timer tick ────────────────────────────────────────────────────────

    def _tick(self):
        for row in self._rows:
            row.tick()
        self._lbl_total.setText(f"Tổng nhận: {self._total_rx}")
        self._rebuild_stats()

    def _rebuild_stats(self):
        # Chỉ tạo label mới cho tag chưa có, cập nhật text thay vì tạo lại từ đầu
        for tag, count in self._stats_global.items():
            colour = _tag_colour(tag)
            if tag not in self._stat_labels:
                lbl = QLabel()
                lbl.setTextFormat(Qt.TextFormat.RichText)
                self._stats_lay.addWidget(lbl)
                self._stat_labels[tag] = lbl
            self._stat_labels[tag].setText(
                f'<span style="color:{colour};">[{tag}]</span> <b>{count}</b>'
            )

    def _reset_stats(self):
        self._stats_global = {}
        self._total_rx     = 0
        # Xóa các label stats
        for lbl in self._stat_labels.values():
            self._stats_lay.removeWidget(lbl)
            lbl.deleteLater()
        self._stat_labels.clear()
        self._log_line_count = 0

    # ── System tray ───────────────────────────────────────────────────────

    def _build_tray(self):
        # Khi đóng gói PyInstaller --onefile, file tạm được giải nén vào sys._MEIPASS
        if getattr(sys, 'frozen', False):
            base_dir = sys._MEIPASS
        else:
            base_dir = os.path.dirname(os.path.abspath(__file__))
        icon_path = os.path.join(base_dir, "icon.ico")
        icon = QIcon(icon_path) if os.path.exists(icon_path) else self.style().standardIcon(
            self.style().StandardPixmap.SP_ComputerIcon
        )

        # Gán icon cho cửa sổ chính và thanh taskbar
        self.setWindowIcon(icon)
        QApplication.instance().setWindowIcon(icon)

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("NMEA Collector — đang chạy ngầm")

        menu = QMenu()
        act_show = menu.addAction("Hiển thị / Ẩn")
        act_show.triggered.connect(self._toggle_window)
        menu.addSeparator()
        act_quit = menu.addAction("Thoát")
        act_quit.triggered.connect(self._quit_app)
        self._tray.setContextMenu(menu)

        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _toggle_window(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.DoubleClick:
            self._toggle_window()

    def _quit_app(self):
        self._disconnect_all()
        QApplication.quit()

    # ── Close ─────────────────────────────────────────────────────────────

    def closeEvent(self, event):
        if hasattr(self, '_tray') and self._tray.isVisible():
            self.hide()
            self._tray.showMessage(
                "NMEA Collector",
                "Đang chạy ngầm. Double-click vào biểu tượng dưới thanh taskbar để mở lại.",
                QSystemTrayIcon.MessageIcon.Information,
                2500,
            )
            event.ignore()
        else:
            self._disconnect_all()
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
