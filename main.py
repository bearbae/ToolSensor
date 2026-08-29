"""Maritime Signal Simulator — main entry point and UI."""

import os
import sys

from PyQt6.QtCore import Qt, QDateTime, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QIcon, QIntValidator
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QScrollArea,
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from generators import (
    AISGenerator,
    GPSGenerator,
    RadarTTMGenerator,
    _bearing_range,
    _latlon_from_bearing_range,
    _move,
)
import ssh_settings
from ssh_tunnel import SSHTunnel, fetch_pod_ip


def _parse_speed_schedule(text: str) -> list:
    """Parse '0:20, 5:8, 12:20' → [(0, 20.0), ...] sorted ascending by waypoint index."""
    result = []
    for part in text.split(','):
        part = part.strip()
        if ':' not in part:
            continue
        wp_str, spd_str = part.split(':', 1)
        try:
            wp = int(wp_str.strip())
            spd = float(spd_str.strip())
            if wp >= 0 and spd >= 0:
                result.append((wp, spd))
        except ValueError:
            continue
    result.sort(key=lambda x: x[0])
    return result


def _sample_zone_point(zone: tuple) -> tuple:
    """Sinh 1 điểm (lat, lon) ngẫu nhiên trong 1 vùng nước.

    zone = (name, kind, lat1, lon1, lat2, lon2, size, zone_type, weight)
    - kind='circle': điểm ngẫu nhiên trong bán kính `size` NM quanh (lat1, lon1)
      — dùng cho biển/vịnh mở, đủ rộng nên full-circle vẫn an toàn.
    - kind='corridor': điểm dọc theo đoạn thẳng xấp xỉ luồng/sông từ
      (lat1, lon1) đến (lat2, lon2), lệch vuông góc tối đa `size` NM — tránh
      full-circle rơi lên bờ như cách sinh cũ, vì sông/kênh thường hẹp.
    """
    import random
    _, kind, lat1, lon1, lat2, lon2, size, _z_type, _w = zone
    if kind == 'circle':
        bearing = random.uniform(0, 360)
        range_nm = random.uniform(0, size)
        return _latlon_from_bearing_range(lat1, lon1, bearing, range_nm)

    axis_brg, length_nm = _bearing_range(lat1, lon1, lat2, lon2)
    dist_along = random.uniform(0, length_nm)
    lat_c, lon_c = _move(lat1, lon1, axis_brg, dist_along, 1.0)
    perp_offset = random.uniform(-size, size)
    perp_brg = (axis_brg + 90.0) % 360
    return _move(lat_c, lon_c, perp_brg, perp_offset, 1.0)
from gpx_parser import parse_gpx
from transmitters import (
    SerialTransmitter,
    TCPServerTransmitter,
    TCPTransmitter,
    TransmitterThread,
    UDPTransmitter,
    list_serial_ports,
)

# ---------------------------------------------------------------------------
# Colour scheme for the dark log console
# ---------------------------------------------------------------------------
_LOG_BG = "#1e1e1e"
_COL_GPS = "#00e676"
_COL_RADAR = "#ffee58"
_COL_AIS = "#40c4ff"
_COL_INFO = "#90a4ae"
_COL_ERROR = "#ef5350"


def _btn_qss(normal: str, hover: str, pressed: str,
             text: str = "white") -> str:
    """Return a full QPushButton stylesheet with hover and pressed states."""
    return (
        f"QPushButton {{"
        f"  background-color:{normal}; color:{text};"
        f"  font-weight:bold; border:none; border-radius:4px;"
        f"  padding:5px 12px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background-color:{hover};"
        f"}}"
        f"QPushButton:pressed {{"
        f"  background-color:{pressed};"
        f"}}"
        f"QPushButton:disabled {{"
        f"  background-color:#4a4a4a; color:#888888;"
        f"}}"
    )


# Global stylesheet for plain (unstyled) buttons – adds visible hover/press
_APP_QSS = """
QPushButton {
    border: 1px solid #767676;
    border-radius: 4px;
    padding: 4px 10px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #d0e8ff;
    border-color: #0d6efd;
}
QPushButton:pressed {
    background-color: #a8cff8;
    border-color: #0a58ca;
}
QPushButton:disabled {
    color: #a0a0a0;
    border-color: #c0c0c0;
}
"""


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Maritime Signal Simulator")
        self.setMinimumSize(1280, 780)

        # Vị trí xuất phát ngẫu nhiên cho tàu mình (cảng/sông VN, đôi khi
        # ngoài khơi) — tính trước khi build UI để đồng bộ cả generator lẫn
        # giá trị mặc định trên các spinbox.
        self._start_lat, self._start_lon = self._random_own_ship_start()

        # Domain objects (shared with the background thread)
        self._gps_gen = GPSGenerator()
        self._gps_gen.lat = self._start_lat
        self._gps_gen.lon = self._start_lon
        self._radar_gen = RadarTTMGenerator()
        self._radar_gen.own_lat = self._start_lat
        self._radar_gen.own_lon = self._start_lon
        self._ais_gen = AISGenerator()

        self._transmitter = None
        self._ssh_tunnel: SSHTunnel | None = None
        self._thread: TransmitterThread | None = None
        self._fusion_entries: list = []

        self._a_gpx_pending: list | None = None           # waypoints đang chờ gán cho vessel
        self._ais_vessel_routes: dict[int, list] = {}     # mmsi → waypoints
        self._ais_vessel_schedules: dict[int, list] = {}  # mmsi → [(wp_idx, sog_kn), ...]

        self._gps_display_timer = QTimer(self)
        self._gps_display_timer.setInterval(500)
        self._gps_display_timer.timeout.connect(self._update_gps_display)

        self._build_ui()
        self._wire_signals()

    # ------------------------------------------------------------------
    # UI construction
    # ------------------------------------------------------------------

    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)

        # ---- Left panel (scrollable) -------------------------------------
        left_inner = QWidget()
        left_layout = QVBoxLayout(left_inner)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._build_connection_panel())
        left_layout.addWidget(self._build_generator_panel())
        left_layout.addStretch()

        left_scroll = QScrollArea()
        left_scroll.setWidget(left_inner)
        left_scroll.setWidgetResizable(True)
        left_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        left_scroll.setFrameShape(left_scroll.Shape.NoFrame)

        # ---- Right panel -------------------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._build_target_panel(), stretch=2)
        right_layout.addWidget(self._build_log_panel(), stretch=3)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(right)
        splitter.setSizes([400, 860])
        root.addWidget(splitter)

        self.setStatusBar(QStatusBar())
        self.statusBar().showMessage("Disconnected")

    # --- Connection panel -------------------------------------------------

    def _build_connection_panel(self) -> QGroupBox:
        group = QGroupBox("Connection")
        layout = QVBoxLayout(group)

        # Mode radio buttons
        mode_row = QHBoxLayout()
        self._rb_tcp = QRadioButton("TCP Client")
        self._rb_tcp_server = QRadioButton("TCP Server")
        self._rb_serial = QRadioButton("Serial Port")
        self._rb_ssh = QRadioButton("SSH Tunnel")
        self._rb_tcp.setChecked(True)
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self._rb_tcp)
        self._mode_grp.addButton(self._rb_tcp_server)
        self._mode_grp.addButton(self._rb_serial)
        self._mode_grp.addButton(self._rb_ssh)
        mode_row.addWidget(self._rb_tcp)
        mode_row.addWidget(self._rb_tcp_server)
        mode_row.addWidget(self._rb_serial)
        mode_row.addWidget(self._rb_ssh)
        layout.addLayout(mode_row)

        # TCP Client sub-panel
        self._tcp_widget = QWidget()
        tcp_form = QFormLayout(self._tcp_widget)
        tcp_form.setContentsMargins(0, 0, 0, 0)
        self._tcp_host = QLineEdit("127.0.0.1")
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1, 65535)
        self._tcp_port.setValue(10110)
        tcp_form.addRow("Host:", self._tcp_host)
        tcp_form.addRow("Port:", self._tcp_port)
        layout.addWidget(self._tcp_widget)

        # TCP Server sub-panel
        self._tcp_server_widget = QWidget()
        srv_form = QFormLayout(self._tcp_server_widget)
        srv_form.setContentsMargins(0, 0, 0, 0)
        self._srv_host = QLineEdit("0.0.0.0")
        self._srv_port = QSpinBox()
        self._srv_port.setRange(1, 65535)
        self._srv_port.setValue(10110)
        self._lbl_clients = QLabel("0 clients connected")
        self._lbl_clients.setStyleSheet("color: #0d6efd; font-weight: bold;")
        srv_form.addRow("Bind IP:", self._srv_host)
        srv_form.addRow("Port:", self._srv_port)
        srv_form.addRow("", self._lbl_clients)
        self._tcp_server_widget.setVisible(False)
        layout.addWidget(self._tcp_server_widget)

        # Serial sub-panel
        self._serial_widget = QWidget()
        serial_form = QFormLayout(self._serial_widget)
        serial_form.setContentsMargins(0, 0, 0, 0)

        port_row = QHBoxLayout()
        self._serial_port = QComboBox()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setFixedWidth(68)
        port_row.addWidget(self._serial_port, stretch=1)
        port_row.addWidget(self._btn_refresh)

        self._serial_baud = QComboBox()
        self._serial_baud.addItems(["4800", "9600", "19200", "38400", "115200"])

        self._serial_parity = QComboBox()
        self._serial_parity.addItems(["None (N)", "Even (E)", "Odd (O)"])

        self._serial_bits = QComboBox()
        self._serial_bits.addItems(["8", "7"])

        serial_form.addRow("Port:", port_row)
        serial_form.addRow("Baudrate:", self._serial_baud)
        serial_form.addRow("Parity:", self._serial_parity)
        serial_form.addRow("Data bits:", self._serial_bits)

        self._serial_widget.setVisible(False)
        layout.addWidget(self._serial_widget)

        # SSH Tunnel sub-panel — kết nối tới enc-sensor-gateway khi máy
        # không có đường mạng trực tiếp tới server (xem
        # enc-docs/Ket-Noi-Tool-Test-Sensor-Gateway.md). Tự mở SSH local
        # port-forward rồi kết nối TCP Client vào 127.0.0.1:<local_port>.
        self._ssh_widget = QWidget()
        ssh_form = QFormLayout(self._ssh_widget)
        ssh_form.setContentsMargins(0, 0, 0, 0)

        self._ssh_host = QLineEdit()
        self._ssh_host.setPlaceholderText("vd: 171.244.197.133")
        self._ssh_port = QSpinBox()
        self._ssh_port.setRange(1, 65535)
        self._ssh_port.setValue(2222)
        self._ssh_user = QLineEdit("root")

        pass_row = QHBoxLayout()
        self._ssh_pass = QLineEdit()
        self._ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._ssh_remember_pass = QCheckBox("Nhớ mật khẩu")
        self._ssh_remember_pass.setToolTip(
            "Lưu mật khẩu vào ~/.maritime_simulator.json để lần sau tự điền sẵn"
        )
        pass_row.addWidget(self._ssh_pass, stretch=1)
        pass_row.addWidget(self._ssh_remember_pass)

        self._ssh_namespace = QLineEdit("enc-ship")
        self._ssh_label_selector = QLineEdit("app=enc-sensor-gateway")

        pod_row = QHBoxLayout()
        self._ssh_pod_ip = QLineEdit()
        self._ssh_pod_ip.setPlaceholderText("vd: 10.42.0.96")
        self._btn_ssh_fetch_pod_ip = QPushButton("Lấy Pod IP")
        self._btn_ssh_fetch_pod_ip.setToolTip(
            "Chạy 'kubectl get pod' qua SSH để lấy IP hiện tại của pod\n"
            "(đổi mỗi lần pod restart)"
        )
        pod_row.addWidget(self._ssh_pod_ip, stretch=1)
        pod_row.addWidget(self._btn_ssh_fetch_pod_ip)

        self._ssh_remote_port = QSpinBox()
        self._ssh_remote_port.setRange(1, 65535)
        self._ssh_remote_port.setValue(5001)
        self._ssh_remote_port.setToolTip("Cổng thiết bị — lấy từ cột config của bảng device")

        self._ssh_local_port = QSpinBox()
        self._ssh_local_port.setRange(1, 65535)
        self._ssh_local_port.setValue(5001)
        self._ssh_local_port.setToolTip("Cổng local trên máy bạn, tool sẽ kết nối TCP Client vào 127.0.0.1:<cổng này>")

        ssh_form.addRow("SSH Host:", self._ssh_host)
        ssh_form.addRow("SSH Port:", self._ssh_port)
        ssh_form.addRow("Username:", self._ssh_user)
        ssh_form.addRow("Password:", pass_row)
        ssh_form.addRow("k8s Namespace:", self._ssh_namespace)
        ssh_form.addRow("Pod Selector:", self._ssh_label_selector)
        ssh_form.addRow("Pod IP:", pod_row)
        ssh_form.addRow("Cổng thiết bị:", self._ssh_remote_port)
        ssh_form.addRow("Cổng local:", self._ssh_local_port)

        self._ssh_widget.setVisible(False)
        layout.addWidget(self._ssh_widget)
        self._load_ssh_settings()

        # Connect / Disconnect
        conn_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setStyleSheet(
            _btn_qss("#28a745", "#218838", "#1a6b2a")
        )
        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.setStyleSheet(
            _btn_qss("#dc3545", "#c82333", "#a71d2a")
        )
        self._btn_disconnect.setEnabled(False)
        conn_row.addWidget(self._btn_connect)
        conn_row.addWidget(self._btn_disconnect)
        layout.addLayout(conn_row)

        self._refresh_ports()
        return group

    # --- Generator panel --------------------------------------------------

    def _build_generator_panel(self) -> QGroupBox:
        group = QGroupBox("Generator")
        layout = QVBoxLayout(group)

        # Message type checkboxes
        self._chk_gps = QCheckBox("GPS  (GPRMC)")
        self._chk_radar = QCheckBox("Radar (RATTM)")
        self._chk_ais = QCheckBox("AIS   (AIVDM)")
        self._chk_gps.setChecked(True)
        layout.addWidget(self._chk_gps)
        layout.addWidget(self._chk_radar)
        layout.addWidget(self._chk_ais)

        # Interval slider
        interval_row = QHBoxLayout()
        interval_row.addWidget(QLabel("Interval:"))
        self._slider_interval = QSlider(Qt.Orientation.Horizontal)
        self._slider_interval.setRange(100, 5000)
        self._slider_interval.setValue(1000)
        self._lbl_interval = QLabel("1000 ms")
        self._lbl_interval.setMinimumWidth(58)
        interval_row.addWidget(self._slider_interval, stretch=1)
        interval_row.addWidget(self._lbl_interval)
        layout.addLayout(interval_row)

        # GPS settings
        gps_grp = QGroupBox("GPS Settings")
        gps_layout = QVBoxLayout(gps_grp)

        # --- Sentence type checkboxes ---
        sent_row1 = QHBoxLayout()
        self._chk_rmc = QCheckBox("RMC")
        self._chk_zda = QCheckBox("ZDA")
        self._chk_hdt = QCheckBox("HDT")
        self._chk_hdm = QCheckBox("HDM")
        self._chk_rmc.setChecked(True)
        self._chk_zda.setChecked(True)
        for w in (self._chk_rmc, self._chk_zda, self._chk_hdt, self._chk_hdm):
            sent_row1.addWidget(w)
        sent_row1.addStretch()

        sent_row2 = QHBoxLayout()
        self._chk_hdg = QCheckBox("HDG")
        self._chk_rot = QCheckBox("ROT")
        self._chk_ths = QCheckBox("THS")
        self._chk_rmb = QCheckBox("RMB")
        for w in (self._chk_hdg, self._chk_rot, self._chk_ths, self._chk_rmb):
            sent_row2.addWidget(w)
        sent_row2.addStretch()

        gps_layout.addLayout(sent_row1)
        gps_layout.addLayout(sent_row2)

        # --- Position & movement ---
        gps_form = QFormLayout()

        self._gps_lat = QDoubleSpinBox()
        self._gps_lat.setRange(-90.0, 90.0)
        self._gps_lat.setDecimals(6)
        self._gps_lat.setValue(self._start_lat)

        self._gps_lon = QDoubleSpinBox()
        self._gps_lon.setRange(-180.0, 180.0)
        self._gps_lon.setDecimals(6)
        self._gps_lon.setValue(self._start_lon)

        self._gps_speed = QDoubleSpinBox()
        self._gps_speed.setRange(0.0, 200.0)
        self._gps_speed.setDecimals(1)
        self._gps_speed.setValue(5.0)
        self._gps_speed.setSuffix(" kn")

        self._gps_course = QDoubleSpinBox()
        self._gps_course.setRange(0.0, 360.0)
        self._gps_course.setDecimals(1)
        self._gps_course.setValue(45.0)
        self._gps_course.setSuffix(" °")

        gps_form.addRow("Latitude:", self._gps_lat)
        gps_form.addRow("Longitude:", self._gps_lon)
        gps_form.addRow("Speed:", self._gps_speed)
        gps_form.addRow("Course (True):", self._gps_course)

        # --- Heading & rotation (for HDT/HDM/HDG/ROT/THS) ---
        self._gps_hdg_true = QDoubleSpinBox()
        self._gps_hdg_true.setRange(0.0, 360.0)
        self._gps_hdg_true.setDecimals(1)
        self._gps_hdg_true.setValue(45.0)
        self._gps_hdg_true.setSuffix(" °")

        self._gps_hdg_mag = QDoubleSpinBox()
        self._gps_hdg_mag.setRange(0.0, 360.0)
        self._gps_hdg_mag.setDecimals(1)
        self._gps_hdg_mag.setValue(45.0)
        self._gps_hdg_mag.setSuffix(" °")

        # Deviation row
        dev_row = QHBoxLayout()
        self._gps_dev = QDoubleSpinBox()
        self._gps_dev.setRange(0.0, 180.0)
        self._gps_dev.setDecimals(1)
        self._gps_dev.setSuffix(" °")
        self._gps_dev_dir = QComboBox()
        self._gps_dev_dir.addItems(["E", "W"])
        dev_row.addWidget(self._gps_dev)
        dev_row.addWidget(self._gps_dev_dir)

        # Variation row
        var_row = QHBoxLayout()
        self._gps_var = QDoubleSpinBox()
        self._gps_var.setRange(0.0, 180.0)
        self._gps_var.setDecimals(1)
        self._gps_var.setSuffix(" °")
        self._gps_var_dir = QComboBox()
        self._gps_var_dir.addItems(["E", "W"])
        var_row.addWidget(self._gps_var)
        var_row.addWidget(self._gps_var_dir)

        self._gps_rot = QDoubleSpinBox()
        self._gps_rot.setRange(-720.0, 720.0)
        self._gps_rot.setDecimals(1)
        self._gps_rot.setSuffix(" °/min")
        self._gps_rot.setToolTip("Positive = turning right, Negative = turning left")

        gps_form.addRow("Heading (True):", self._gps_hdg_true)
        gps_form.addRow("Heading (Mag):", self._gps_hdg_mag)
        gps_form.addRow("Deviation:", dev_row)
        gps_form.addRow("Variation:", var_row)
        gps_form.addRow("Rate of Turn:", self._gps_rot)

        gps_layout.addLayout(gps_form)

        # RMB waypoint sub-group (visible only when RMB checked)
        self._rmb_grp = QGroupBox("RMB Waypoint")
        self._rmb_grp.setVisible(False)
        rmb_form = QFormLayout(self._rmb_grp)

        self._rmb_origin_id = QLineEdit("WP00")
        self._rmb_origin_id.setMaxLength(10)

        self._rmb_dest_id = QLineEdit("WP01")
        self._rmb_dest_id.setMaxLength(10)

        self._rmb_dest_lat = QDoubleSpinBox()
        self._rmb_dest_lat.setRange(-90.0, 90.0)
        self._rmb_dest_lat.setDecimals(6)
        self._rmb_dest_lat.setValue(self._start_lat)

        self._rmb_dest_lon = QDoubleSpinBox()
        self._rmb_dest_lon.setRange(-180.0, 180.0)
        self._rmb_dest_lon.setDecimals(6)
        self._rmb_dest_lon.setValue(self._start_lon)

        self._rmb_xte = QDoubleSpinBox()
        self._rmb_xte.setRange(0.0, 9.99)
        self._rmb_xte.setDecimals(2)
        self._rmb_xte.setSuffix(" NM")

        self._rmb_steer = QComboBox()
        self._rmb_steer.addItems(["L  (Left)", "R  (Right)"])

        rmb_form.addRow("Origin WP:", self._rmb_origin_id)
        rmb_form.addRow("Dest WP:", self._rmb_dest_id)
        rmb_form.addRow("Dest Lat:", self._rmb_dest_lat)
        rmb_form.addRow("Dest Lon:", self._rmb_dest_lon)
        rmb_form.addRow("Cross-Track Error:", self._rmb_xte)
        rmb_form.addRow("Steer:", self._rmb_steer)

        gps_layout.addWidget(self._rmb_grp)
        layout.addWidget(gps_grp)

        # Start / Stop
        ctrl_row = QHBoxLayout()
        self._btn_start = QPushButton("▶  Start")
        self._btn_start.setStyleSheet(
            _btn_qss("#0d6efd", "#0b5ed7", "#0a52be")
        )
        self._btn_start.setEnabled(False)
        self._btn_stop = QPushButton("■  Stop")
        self._btn_stop.setStyleSheet(
            _btn_qss("#969da3", "#848c92", "#7b848b")
        )
        self._btn_stop.setEnabled(False)
        ctrl_row.addWidget(self._btn_start)
        ctrl_row.addWidget(self._btn_stop)
        layout.addLayout(ctrl_row)

        return group

    # --- Target control panel ---------------------------------------------

    def _build_target_panel(self) -> QGroupBox:
        group = QGroupBox("Target Control")
        layout = QVBoxLayout(group)
        tabs = QTabWidget()

        # ---- Radar tab ---------------------------------------------------
        radar_tab = QWidget()
        rt_layout = QVBoxLayout(radar_tab)
        rt_form = QFormLayout()

        self._r_id = QSpinBox()
        self._r_id.setRange(1, 99)
        self._r_id.setValue(1)

        self._r_bearing = QDoubleSpinBox()
        self._r_bearing.setRange(0.0, 360.0)
        self._r_bearing.setDecimals(4)
        self._r_bearing.setSuffix(" °")

        self._r_range = QDoubleSpinBox()
        self._r_range.setRange(0.0001, 100.0)
        self._r_range.setDecimals(4)
        self._r_range.setValue(1.0)
        self._r_range.setSuffix(" NM")

        self._r_speed = QDoubleSpinBox()
        self._r_speed.setRange(0.0, 100.0)
        self._r_speed.setDecimals(1)
        self._r_speed.setSuffix(" kn")

        self._r_course = QDoubleSpinBox()
        self._r_course.setRange(0.0, 360.0)
        self._r_course.setDecimals(1)
        self._r_course.setSuffix(" °")

        self._r_name = QLineEdit()
        self._r_name.setPlaceholderText("Optional")

        self._r_status = QComboBox()
        self._r_status.addItems(["T  (Tracking)", "L  (Lost)", "Q  (Query)"])

        rt_form.addRow("Target ID:", self._r_id)
        rt_form.addRow("Bearing:", self._r_bearing)
        rt_form.addRow("Range:", self._r_range)
        rt_form.addRow("Speed:", self._r_speed)
        rt_form.addRow("Course:", self._r_course)
        rt_form.addRow("Name:", self._r_name)
        rt_form.addRow("Status:", self._r_status)
        rt_layout.addLayout(rt_form)

        # ── Chuyển đổi tọa độ 2 chiều ────────────────────────────────────────
        latlon_grp = QGroupBox("Chuyển đổi tọa độ")
        latlon_grp.setStyleSheet("QGroupBox { color: #0d6efd; font-weight: bold; }")
        latlon_vl = QVBoxLayout(latlon_grp)

        # Own-ship reference (có thể nhập tay khi không bắn GPS)
        row_ownship = QHBoxLayout()
        row_ownship.addWidget(QLabel("Own-ship:"))
        self._r_own_lat = QDoubleSpinBox()
        self._r_own_lat.setRange(-90.0, 90.0)
        self._r_own_lat.setDecimals(6)
        self._r_own_lat.setPrefix("Lat ")
        self._r_own_lat.setToolTip("Lat tàu chủ dùng để tính Bearing+Range. Nhập tay hoặc bấm '← GPS' để kéo từ GPS.")
        self._r_own_lon = QDoubleSpinBox()
        self._r_own_lon.setRange(-180.0, 180.0)
        self._r_own_lon.setDecimals(6)
        self._r_own_lon.setPrefix("Lon ")
        self._r_own_lon.setToolTip("Lon tàu chủ dùng để tính Bearing+Range. Nhập tay hoặc bấm '← GPS' để kéo từ GPS.")
        self._btn_sync_gps = QPushButton("← GPS")
        self._btn_sync_gps.setFixedWidth(60)
        self._btn_sync_gps.setToolTip("Kéo vị trí GPS hiện tại vào ô Own-ship")
        row_ownship.addWidget(self._r_own_lat, stretch=1)
        row_ownship.addWidget(self._r_own_lon, stretch=1)
        row_ownship.addWidget(self._btn_sync_gps)
        latlon_vl.addLayout(row_ownship)

        # Chiều 1: Bearing+Range → Lat/Lon (tính từ form trên)
        row_br2ll = QHBoxLayout()
        row_br2ll.addWidget(QLabel("Brg+Rng → "))
        self._r_computed_lat = QLineEdit()
        self._r_computed_lat.setReadOnly(True)
        self._r_computed_lat.setPlaceholderText("Lat")
        self._r_computed_lon = QLineEdit()
        self._r_computed_lon.setReadOnly(True)
        self._r_computed_lon.setPlaceholderText("Lon")
        self._btn_r_copy_latlon = QPushButton("Copy")
        self._btn_r_copy_latlon.setFixedWidth(54)
        self._btn_r_copy_latlon.setToolTip("Copy lat,lon vào clipboard")
        row_br2ll.addWidget(self._r_computed_lat, stretch=1)
        row_br2ll.addWidget(self._r_computed_lon, stretch=1)
        row_br2ll.addWidget(self._btn_r_copy_latlon)
        latlon_vl.addLayout(row_br2ll)

        # Chiều 2: Lat/Lon → Bearing+Range (fill vào form trên)
        row_ll2br = QHBoxLayout()
        row_ll2br.addWidget(QLabel("Lat/Lon →  "))
        self._r_input_lat = QDoubleSpinBox()
        self._r_input_lat.setRange(-90.0, 90.0)
        self._r_input_lat.setDecimals(6)
        self._r_input_lat.setPrefix("Lat ")
        self._r_input_lon = QDoubleSpinBox()
        self._r_input_lon.setRange(-180.0, 180.0)
        self._r_input_lon.setDecimals(6)
        self._r_input_lon.setPrefix("Lon ")
        self._btn_r_calc_bearing = QPushButton("Fill")
        self._btn_r_calc_bearing.setFixedWidth(54)
        self._btn_r_calc_bearing.setToolTip("Tính Bearing+Range từ lat/lon rồi điền vào form")
        row_ll2br.addWidget(self._r_input_lat, stretch=1)
        row_ll2br.addWidget(self._r_input_lon, stretch=1)
        row_ll2br.addWidget(self._btn_r_calc_bearing)
        latlon_vl.addLayout(row_ll2br)

        rt_layout.addWidget(latlon_grp)

        rb_row = QHBoxLayout()
        self._btn_r_add = QPushButton("Add / Update")
        self._btn_r_remove = QPushButton("Remove")
        rb_row.addWidget(self._btn_r_add)
        rb_row.addWidget(self._btn_r_remove)
        rt_layout.addLayout(rb_row)

        # Auto generate row
        r_auto_row = QHBoxLayout()
        r_auto_row.addWidget(QLabel("Auto generate:"))
        self._r_auto_count = QSpinBox()
        self._r_auto_count.setRange(1, 9999)
        self._r_auto_count.setValue(5)
        self._r_auto_count.setSuffix(" targets")
        self._btn_r_auto = QPushButton("Generate")
        self._btn_r_clear = QPushButton("Clear All")
        r_auto_row.addWidget(self._r_auto_count)
        r_auto_row.addWidget(self._btn_r_auto)
        r_auto_row.addWidget(self._btn_r_clear)
        rt_layout.addLayout(r_auto_row)

        # OSD / RSD checkboxes
        osd_rsd_row = QHBoxLayout()
        self._chk_osd = QCheckBox("OSD  (Own Ship Data)")
        self._chk_rsd = QCheckBox("RSD  (Radar System Data)")
        osd_rsd_row.addWidget(self._chk_osd)
        osd_rsd_row.addWidget(self._chk_rsd)
        osd_rsd_row.addStretch()
        rt_layout.addLayout(osd_rsd_row)

        # OSD sub-group
        self._osd_grp = QGroupBox("OSD Settings")
        self._osd_grp.setVisible(False)
        osd_form = QFormLayout(self._osd_grp)

        self._osd_set = QDoubleSpinBox()
        self._osd_set.setRange(0.0, 360.0)
        self._osd_set.setDecimals(1)
        self._osd_set.setSuffix(" °")
        self._osd_set.setToolTip("Current set (drift direction, degrees true)")

        self._osd_drift = QDoubleSpinBox()
        self._osd_drift.setRange(0.0, 10.0)
        self._osd_drift.setDecimals(1)
        self._osd_drift.setSuffix(" kn")
        self._osd_drift.setToolTip("Current drift speed (knots)")

        osd_form.addRow("Set:", self._osd_set)
        osd_form.addRow("Drift:", self._osd_drift)
        lbl_osd_note = QLabel("Heading / Course / Speed — auto-sync từ GPS")
        lbl_osd_note.setStyleSheet("color:#90a4ae; font-style:italic;")
        osd_form.addRow("", lbl_osd_note)
        rt_layout.addWidget(self._osd_grp)

        # RSD sub-group
        self._rsd_grp = QGroupBox("RSD Settings")
        self._rsd_grp.setVisible(False)
        rsd_form = QFormLayout(self._rsd_grp)

        self._rsd_vrm1 = QDoubleSpinBox()
        self._rsd_vrm1.setRange(0.0, 200.0)
        self._rsd_vrm1.setDecimals(1)
        self._rsd_vrm1.setValue(1.0)
        self._rsd_vrm1.setSuffix(" NM")

        self._rsd_ebl1 = QDoubleSpinBox()
        self._rsd_ebl1.setRange(0.0, 360.0)
        self._rsd_ebl1.setDecimals(1)
        self._rsd_ebl1.setSuffix(" °")

        self._rsd_vrm2 = QDoubleSpinBox()
        self._rsd_vrm2.setRange(0.0, 200.0)
        self._rsd_vrm2.setDecimals(1)
        self._rsd_vrm2.setValue(3.0)
        self._rsd_vrm2.setSuffix(" NM")

        self._rsd_ebl2 = QDoubleSpinBox()
        self._rsd_ebl2.setRange(0.0, 360.0)
        self._rsd_ebl2.setDecimals(1)
        self._rsd_ebl2.setValue(90.0)
        self._rsd_ebl2.setSuffix(" °")

        self._rsd_range = QDoubleSpinBox()
        self._rsd_range.setRange(0.1, 200.0)
        self._rsd_range.setDecimals(1)
        self._rsd_range.setValue(6.0)
        self._rsd_range.setSuffix(" NM")

        self._rsd_rotation = QComboBox()
        self._rsd_rotation.addItems(["N  (North-up)", "H  (Head-up)", "C  (Course-up)"])

        rsd_form.addRow("VRM 1:", self._rsd_vrm1)
        rsd_form.addRow("EBL 1:", self._rsd_ebl1)
        rsd_form.addRow("VRM 2:", self._rsd_vrm2)
        rsd_form.addRow("EBL 2:", self._rsd_ebl2)
        rsd_form.addRow("Range Scale:", self._rsd_range)
        rsd_form.addRow("Display Rotation:", self._rsd_rotation)
        rt_layout.addWidget(self._rsd_grp)

        self._radar_list = QListWidget()
        self._radar_list.setMaximumHeight(90)
        rt_layout.addWidget(self._radar_list)
        tabs.addTab(radar_tab, "Radar  (TTM)")

        # ---- AIS tab -----------------------------------------------------
        ais_tab = QWidget()
        at_layout = QVBoxLayout(ais_tab)
        at_form = QFormLayout()

        self._a_mmsi = QLineEdit("123456789")
        self._a_mmsi.setValidator(QIntValidator(100_000_000, 999_999_999))
        self._a_mmsi.setPlaceholderText("9-digit MMSI")

        self._a_lat = QDoubleSpinBox()
        self._a_lat.setRange(-90.0, 90.0)
        self._a_lat.setDecimals(6)
        self._a_lat.setValue(self._start_lat)

        self._a_lon = QDoubleSpinBox()
        self._a_lon.setRange(-180.0, 180.0)
        self._a_lon.setDecimals(6)
        self._a_lon.setValue(self._start_lon)

        self._a_sog = QDoubleSpinBox()
        self._a_sog.setRange(0.0, 9999.0)
        self._a_sog.setDecimals(1)
        self._a_sog.setSuffix(" kn")

        self._a_cog = QDoubleSpinBox()
        self._a_cog.setRange(0.0, 360.0)
        self._a_cog.setDecimals(1)
        self._a_cog.setSuffix(" °")

        self._a_heading = QSpinBox()
        self._a_heading.setRange(0, 511)
        self._a_heading.setValue(511)
        self._a_heading.setToolTip("511 = not available")

        self._a_navstatus = QComboBox()
        self._a_navstatus.addItems([
            "0 – Under way (engine)",
            "1 – At anchor",
            "2 – Not under command",
            "3 – Restricted manoeuvrability",
            "5 – Moored",
            "15 – Not defined",
        ])

        self._a_ais_class = QComboBox()
        self._a_ais_class.addItems(["Class A  (Type 1 + Type 5)", "Class B  (Type 18 + Type 24)"])

        self._a_imo = QSpinBox()
        self._a_imo.setRange(0, 9_999_999)
        self._a_imo.setValue(0)
        self._a_imo.setToolTip("IMO number (1000000–9999999). 0 = not available.\nClass B vessels do not transmit IMO.")

        self._a_ais_class.currentIndexChanged.connect(
            lambda i: self._a_imo.setEnabled(i == 0)
        )

        self._a_shipname = QLineEdit()
        self._a_shipname.setPlaceholderText("Max 20 chars")
        self._a_shipname.setMaxLength(20)

        self._a_callsign = QLineEdit()
        self._a_callsign.setPlaceholderText("Max 7 chars")
        self._a_callsign.setMaxLength(7)

        self._a_shiptype = QSpinBox()
        self._a_shiptype.setRange(0, 99)
        self._a_shiptype.setValue(0)
        self._a_shiptype.setToolTip(
            "0=N/A  30=Fishing  36=Sailing  37=Pleasure\n"
            "50=Pilot  52=Tug  60-69=Passenger\n"
            "70-79=Cargo  80-89=Tanker  90-99=Other"
        )

        self._a_destination = QLineEdit()
        self._a_destination.setPlaceholderText("Max 20 chars")
        self._a_destination.setMaxLength(20)

        # ETA — checkbox để bật/tắt, QDateTimeEdit chỉ lấy tháng/ngày/giờ/phút
        eta_row = QHBoxLayout()
        self._a_eta_enabled = QCheckBox("Enable")
        self._a_eta = QDateTimeEdit()
        self._a_eta.setDisplayFormat("MM/dd HH:mm")
        self._a_eta.setEnabled(False)
        self._a_eta_enabled.toggled.connect(self._a_eta.setEnabled)
        eta_row.addWidget(self._a_eta_enabled)
        eta_row.addWidget(self._a_eta, stretch=1)

        at_form.addRow("MMSI:", self._a_mmsi)
        at_form.addRow("AIS Class:", self._a_ais_class)
        at_form.addRow("IMO Number:", self._a_imo)
        at_form.addRow("Ship Name:", self._a_shipname)
        at_form.addRow("Call Sign:", self._a_callsign)
        at_form.addRow("Ship Type:", self._a_shiptype)
        at_form.addRow("Destination:", self._a_destination)
        at_form.addRow("ETA (MM/dd HH:mm):", eta_row)
        at_form.addRow("Latitude:", self._a_lat)
        at_form.addRow("Longitude:", self._a_lon)
        at_form.addRow("SOG:", self._a_sog)
        at_form.addRow("COG:", self._a_cog)
        at_form.addRow("Heading:", self._a_heading)
        at_form.addRow("Nav Status:", self._a_navstatus)
        at_layout.addLayout(at_form)

        ab_row = QHBoxLayout()
        self._btn_a_add = QPushButton("Add / Update")
        self._btn_a_remove = QPushButton("Remove")
        ab_row.addWidget(self._btn_a_add)
        ab_row.addWidget(self._btn_a_remove)
        at_layout.addLayout(ab_row)

        # GPX Route group
        gpx_grp = QGroupBox("GPX Route")
        gpx_lay = QVBoxLayout(gpx_grp)
        gpx_lay.setSpacing(6)
        gpx_lay.setContentsMargins(8, 6, 8, 8)

        gpx_file_row = QHBoxLayout()
        self._a_gpx_label = QLabel("Chưa chọn file")
        self._a_gpx_label.setStyleSheet("color:#90a4ae; font-style:italic;")
        self._btn_a_gpx_load = QPushButton("Tải GPX")
        self._btn_a_gpx_load.setFixedWidth(76)
        self._btn_a_gpx_clear_file = QPushButton("✕")
        self._btn_a_gpx_clear_file.setFixedWidth(28)
        gpx_file_row.addWidget(self._a_gpx_label, stretch=1)
        gpx_file_row.addWidget(self._btn_a_gpx_load)
        gpx_file_row.addWidget(self._btn_a_gpx_clear_file)
        gpx_lay.addLayout(gpx_file_row)

        gpx_opt_row = QHBoxLayout()
        self._a_gpx_loop = QCheckBox("Lặp lại route")
        self._a_gpx_speed_var = QCheckBox("Biến thiên tốc độ")
        self._a_gpx_status = QLabel("—")
        self._a_gpx_status.setStyleSheet("color:#90a4ae;")
        gpx_opt_row.addWidget(self._a_gpx_loop)
        gpx_opt_row.addSpacing(12)
        gpx_opt_row.addWidget(self._a_gpx_speed_var)
        gpx_opt_row.addStretch()
        gpx_opt_row.addWidget(self._a_gpx_status)
        gpx_lay.addLayout(gpx_opt_row)

        # Speed schedule container — ẩn mặc định, chỉ hiện khi bật checkbox
        self._a_gpx_sched_container = QWidget()
        sched_lay = QVBoxLayout(self._a_gpx_sched_container)
        sched_lay.setContentsMargins(0, 2, 0, 0)
        sched_lay.setSpacing(4)

        sched_input_row = QHBoxLayout()
        sched_input_row.addWidget(QLabel("Lịch tốc độ (WP:kn):"))
        self._a_gpx_schedule_edit = QLineEdit()
        self._a_gpx_schedule_edit.setPlaceholderText("VD: 0:20, 5:8, 12:20")
        sched_input_row.addWidget(self._a_gpx_schedule_edit, stretch=1)
        sched_lay.addLayout(sched_input_row)

        self._a_gpx_sched_cur = QLabel("Tốc độ hiện tại: —")
        self._a_gpx_sched_cur.setStyleSheet("color:#90a4ae; font-style:italic;")
        sched_lay.addWidget(self._a_gpx_sched_cur)

        self._a_gpx_sched_container.setVisible(False)
        gpx_lay.addWidget(self._a_gpx_sched_container)

        at_layout.addWidget(gpx_grp)

        # Auto generate row
        a_auto_row = QHBoxLayout()
        a_auto_row.addWidget(QLabel("Auto generate:"))
        self._a_auto_count = QSpinBox()
        self._a_auto_count.setRange(1, 9999)
        self._a_auto_count.setValue(5)
        self._a_auto_count.setSuffix(" vessels")
        self._a_auto_mode = QComboBox()
        self._a_auto_mode.addItems(["Xung quanh tàu mình", "Vùng biển Việt Nam"])
        self._btn_a_auto = QPushButton("Generate")
        self._btn_a_clear = QPushButton("Clear All")
        a_auto_row.addWidget(self._a_auto_count)
        a_auto_row.addWidget(self._a_auto_mode)
        a_auto_row.addWidget(self._btn_a_auto)
        a_auto_row.addWidget(self._btn_a_clear)
        at_layout.addLayout(a_auto_row)

        self._ais_list = QListWidget()
        self._ais_list.setMaximumHeight(90)
        at_layout.addWidget(self._ais_list)
        tabs.addTab(ais_tab, "AIS  (VDM)")

        # ---- VDO tab -----------------------------------------------------
        tabs.addTab(self._build_vdo_tab(), "VDO  (Own Ship)")

        # ---- Fusion Test tab ---------------------------------------------
        tabs.addTab(self._build_fusion_tab(), "Fusion Test")

        layout.addWidget(tabs)
        return group

    def _build_fusion_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        inner_tabs = QTabWidget()

        # ── Sub-tab 1: Tạo thủ công ──────────────────────────────────────
        manual_tab = QWidget()
        ml = QVBoxLayout(manual_tab)
        mf = QFormLayout()

        self._fm_target_id = QSpinBox()
        self._fm_target_id.setRange(1, 99)
        self._fm_target_id.setValue(1)

        self._fm_bearing = QDoubleSpinBox()
        self._fm_bearing.setRange(0.0, 360.0)
        self._fm_bearing.setDecimals(1)
        self._fm_bearing.setSuffix(" °")

        self._fm_range = QDoubleSpinBox()
        self._fm_range.setRange(0.01, 200.0)
        self._fm_range.setDecimals(2)
        self._fm_range.setValue(2.0)
        self._fm_range.setSuffix(" NM")

        self._fm_speed = QDoubleSpinBox()
        self._fm_speed.setRange(0.0, 100.0)
        self._fm_speed.setDecimals(1)
        self._fm_speed.setSuffix(" kn")

        self._fm_course = QDoubleSpinBox()
        self._fm_course.setRange(0.0, 360.0)
        self._fm_course.setDecimals(1)
        self._fm_course.setSuffix(" °")

        self._fm_name = QLineEdit()
        self._fm_name.setPlaceholderText("Tên tàu (dùng cho cả Radar + AIS)")
        self._fm_name.setMaxLength(20)

        self._fm_mmsi = QLineEdit()
        self._fm_mmsi.setValidator(QIntValidator(100_000_000, 999_999_999))
        self._fm_mmsi.setPlaceholderText("9-digit MMSI")

        self._fm_shiptype = QSpinBox()
        self._fm_shiptype.setRange(0, 99)
        self._fm_shiptype.setValue(70)
        self._fm_shiptype.setToolTip(
            "0=N/A  30=Fishing  52=Tug  60-69=Passenger\n"
            "70-79=Cargo  80-89=Tanker  90-99=Other"
        )

        self._fm_ais_class = QComboBox()
        self._fm_ais_class.addItems(["Class A  (Type 1 + Type 5)", "Class B  (Type 18 + Type 24)"])

        self._fm_nav_status = QComboBox()
        self._fm_nav_status.addItems([
            "0 – Under way (engine)",
            "1 – At anchor",
            "5 – Moored",
        ])

        mf.addRow("Target ID (Radar):", self._fm_target_id)
        mf.addRow("Bearing:", self._fm_bearing)
        mf.addRow("Range:", self._fm_range)
        mf.addRow("Speed:", self._fm_speed)
        mf.addRow("Course:", self._fm_course)
        mf.addRow("Tên tàu:", self._fm_name)
        mf.addRow("MMSI:", self._fm_mmsi)
        mf.addRow("Ship Type:", self._fm_shiptype)
        mf.addRow("AIS Class:", self._fm_ais_class)
        mf.addRow("Nav Status:", self._fm_nav_status)
        ml.addLayout(mf)

        self._btn_fm_add = QPushButton("Thêm cặp Fused")
        self._btn_fm_add.setStyleSheet(_btn_qss("#0d6efd", "#0b5ed7", "#0a52be"))
        ml.addWidget(self._btn_fm_add)
        ml.addStretch()
        inner_tabs.addTab(manual_tab, "Thủ công")

        # ── Sub-tab 2: Auto Generate ──────────────────────────────────────
        auto_tab = QWidget()
        al = QVBoxLayout(auto_tab)
        af = QFormLayout()

        self._f_fused_count = QSpinBox()
        self._f_fused_count.setRange(1, 9999)
        self._f_fused_count.setValue(3)
        self._f_fused_count.setSuffix("  cặp")

        self._f_radar_only_count = QSpinBox()
        self._f_radar_only_count.setRange(0, 9999)
        self._f_radar_only_count.setValue(2)
        self._f_radar_only_count.setSuffix("  targets")

        self._f_ais_only_count = QSpinBox()
        self._f_ais_only_count.setRange(0, 9999)
        self._f_ais_only_count.setValue(2)
        self._f_ais_only_count.setSuffix("  vessels")

        self._f_mid = QComboBox()
        self._f_mid.addItem("Mix (random countries)")
        self._f_mid.addItems(self._MID_TABLE.keys())

        self._f_ais_mode = QComboBox()
        self._f_ais_mode.addItems(["Xung quanh tàu mình", "Vùng biển Việt Nam"])

        af.addRow("Fused (Radar + AIS):", self._f_fused_count)
        af.addRow("Radar-only:", self._f_radar_only_count)
        af.addRow("AIS-only:", self._f_ais_only_count)
        af.addRow("AIS-only vị trí:", self._f_ais_mode)
        af.addRow("MMSI Country:", self._f_mid)
        al.addLayout(af)

        btn_row = QHBoxLayout()
        self._btn_fusion_generate = QPushButton("Generate Fusion Scenario")
        self._btn_fusion_clear = QPushButton("Clear All")
        btn_row.addWidget(self._btn_fusion_generate)
        btn_row.addWidget(self._btn_fusion_clear)
        al.addLayout(btn_row)
        inner_tabs.addTab(auto_tab, "Auto Generate")

        layout.addWidget(inner_tabs)

        self._fusion_list = QListWidget()
        layout.addWidget(self._fusion_list)

        return tab

    def _build_vdo_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # Enable checkbox at top
        enable_row = QHBoxLayout()
        self._chk_vdo = QCheckBox("Enable AIVDO  (own-ship AIS transponder)")
        self._chk_vdo.setStyleSheet("font-weight: bold;")
        enable_row.addWidget(self._chk_vdo)
        enable_row.addStretch()
        layout.addLayout(enable_row)

        form = QFormLayout()

        self._vdo_mmsi = QLineEdit("123456789")
        self._vdo_mmsi.setValidator(QIntValidator(100_000_000, 999_999_999))
        self._vdo_mmsi.setPlaceholderText("9-digit MMSI")

        self._vdo_ais_class = QComboBox()
        self._vdo_ais_class.addItems(["Class A  (Type 1 + Type 5)", "Class B  (Type 18 + Type 24)"])

        self._vdo_imo = QSpinBox()
        self._vdo_imo.setRange(0, 9_999_999)
        self._vdo_imo.setValue(0)
        self._vdo_imo.setToolTip("IMO number. 0 = not available. Class B không dùng.")
        self._vdo_ais_class.currentIndexChanged.connect(
            lambda i: self._vdo_imo.setEnabled(i == 0)
        )

        self._vdo_shipname = QLineEdit()
        self._vdo_shipname.setPlaceholderText("Max 20 chars")
        self._vdo_shipname.setMaxLength(20)

        self._vdo_callsign = QLineEdit()
        self._vdo_callsign.setPlaceholderText("Max 7 chars")
        self._vdo_callsign.setMaxLength(7)

        self._vdo_shiptype = QSpinBox()
        self._vdo_shiptype.setRange(0, 99)
        self._vdo_shiptype.setValue(0)
        self._vdo_shiptype.setToolTip(
            "0=N/A  30=Fishing  36=Sailing  37=Pleasure\n"
            "50=Pilot  52=Tug  60-69=Passenger\n"
            "70-79=Cargo  80-89=Tanker  90-99=Other"
        )

        self._vdo_destination = QLineEdit()
        self._vdo_destination.setPlaceholderText("Max 20 chars")
        self._vdo_destination.setMaxLength(20)

        vdo_eta_row = QHBoxLayout()
        self._vdo_eta_enabled = QCheckBox("Enable")
        self._vdo_eta = QDateTimeEdit()
        self._vdo_eta.setDisplayFormat("MM/dd HH:mm")
        self._vdo_eta.setEnabled(False)
        self._vdo_eta_enabled.toggled.connect(self._vdo_eta.setEnabled)
        vdo_eta_row.addWidget(self._vdo_eta_enabled)
        vdo_eta_row.addWidget(self._vdo_eta, stretch=1)

        self._vdo_nav_status = QComboBox()
        self._vdo_nav_status.addItems([
            "0 – Under way (engine)",
            "1 – At anchor",
            "2 – Not under command",
            "3 – Restricted manoeuvrability",
            "5 – Moored",
            "15 – Not defined",
        ])

        form.addRow("MMSI:", self._vdo_mmsi)
        form.addRow("AIS Class:", self._vdo_ais_class)
        form.addRow("IMO Number:", self._vdo_imo)
        form.addRow("Ship Name:", self._vdo_shipname)
        form.addRow("Call Sign:", self._vdo_callsign)
        form.addRow("Ship Type:", self._vdo_shiptype)
        form.addRow("Destination:", self._vdo_destination)
        form.addRow("ETA (MM/dd HH:mm):", vdo_eta_row)
        form.addRow("Nav Status:", self._vdo_nav_status)
        layout.addLayout(form)

        lbl_note = QLabel("Lat / Lon / Speed / Course / Heading — tự động sync từ GPS")
        lbl_note.setStyleSheet("color:#90a4ae; font-style:italic;")
        layout.addWidget(lbl_note)
        layout.addStretch()

        return tab

    # --- Log console ------------------------------------------------------

    def _build_log_panel(self) -> QGroupBox:
        group = QGroupBox("NMEA Log Console")
        layout = QVBoxLayout(group)

        self._log = QTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setStyleSheet(
            f"background-color:{_LOG_BG}; color:#ffffff; border:none;"
        )
        layout.addWidget(self._log)

        bar = QHBoxLayout()
        self._btn_clear = QPushButton("Clear")
        self._chk_scroll = QCheckBox("Auto-scroll")
        self._chk_scroll.setChecked(True)
        self._lbl_count = QLabel("0 messages sent")
        bar.addWidget(self._btn_clear)
        bar.addWidget(self._chk_scroll)
        bar.addStretch()
        bar.addWidget(self._lbl_count)
        layout.addLayout(bar)

        return group

    # ------------------------------------------------------------------
    # Signal wiring
    # ------------------------------------------------------------------

    def _wire_signals(self) -> None:
        # Mode toggle
        self._rb_tcp.toggled.connect(self._on_mode_changed)
        self._rb_tcp_server.toggled.connect(self._on_mode_changed)
        self._rb_ssh.toggled.connect(self._on_mode_changed)

        # Serial refresh
        self._btn_refresh.clicked.connect(self._refresh_ports)

        # SSH Tunnel
        self._btn_ssh_fetch_pod_ip.clicked.connect(self._on_ssh_fetch_pod_ip)

        # Connection
        self._btn_connect.clicked.connect(self._on_connect)
        self._btn_disconnect.clicked.connect(self._on_disconnect)

        # Interval slider
        self._slider_interval.valueChanged.connect(
            lambda v: self._lbl_interval.setText(f"{v} ms")
        )

        # Start / Stop
        self._btn_start.clicked.connect(self._on_start)
        self._btn_stop.clicked.connect(self._on_stop)

        # GPS live-update generator — position & movement
        self._gps_lat.valueChanged.connect(lambda v: setattr(self._gps_gen, 'lat', v))
        self._gps_lon.valueChanged.connect(lambda v: setattr(self._gps_gen, 'lon', v))
        self._gps_speed.valueChanged.connect(lambda v: setattr(self._gps_gen, 'speed', v))
        self._gps_course.valueChanged.connect(lambda v: setattr(self._gps_gen, 'course', v))

        # GPS — heading & rotation
        self._gps_hdg_true.valueChanged.connect(lambda v: setattr(self._gps_gen, 'heading_true', v))
        self._gps_hdg_mag.valueChanged.connect(lambda v: setattr(self._gps_gen, 'heading_mag', v))
        self._gps_dev.valueChanged.connect(lambda v: setattr(self._gps_gen, 'mag_deviation', v))
        self._gps_dev_dir.currentTextChanged.connect(lambda v: setattr(self._gps_gen, 'mag_dev_dir', v))
        self._gps_var.valueChanged.connect(lambda v: setattr(self._gps_gen, 'mag_variation', v))
        self._gps_var_dir.currentTextChanged.connect(lambda v: setattr(self._gps_gen, 'mag_var_dir', v))
        self._gps_rot.valueChanged.connect(lambda v: setattr(self._gps_gen, 'rate_of_turn', v))

        # GPS — sentence type toggles
        self._chk_rmc.toggled.connect(lambda v: setattr(self._gps_gen, 'send_rmc', v))
        self._chk_zda.toggled.connect(lambda v: setattr(self._gps_gen, 'send_zda', v))
        self._chk_hdt.toggled.connect(lambda v: setattr(self._gps_gen, 'send_hdt', v))
        self._chk_hdm.toggled.connect(lambda v: setattr(self._gps_gen, 'send_hdm', v))
        self._chk_hdg.toggled.connect(lambda v: setattr(self._gps_gen, 'send_hdg', v))
        self._chk_rot.toggled.connect(lambda v: setattr(self._gps_gen, 'send_rot', v))
        self._chk_ths.toggled.connect(lambda v: setattr(self._gps_gen, 'send_ths', v))
        self._chk_rmb.toggled.connect(self._rmb_grp.setVisible)
        self._chk_rmb.toggled.connect(lambda v: setattr(self._gps_gen, 'send_rmb', v))
        self._chk_vdo.toggled.connect(lambda v: setattr(self._gps_gen, 'send_vdo', v))
        self._vdo_mmsi.textChanged.connect(
            lambda v: setattr(self._gps_gen, 'vdo_mmsi', int(v)) if v.isdigit() else None
        )
        self._vdo_ais_class.currentIndexChanged.connect(
            lambda i: setattr(self._gps_gen, 'vdo_ais_class', 'A' if i == 0 else 'B')
        )
        self._vdo_nav_status.currentTextChanged.connect(
            lambda v: setattr(self._gps_gen, 'vdo_nav_status', int(v.split(' – ')[0]))
        )
        self._vdo_imo.valueChanged.connect(lambda v: setattr(self._gps_gen, 'vdo_imo', v))
        self._vdo_shipname.textChanged.connect(lambda v: setattr(self._gps_gen, 'vdo_shipname', v))
        self._vdo_callsign.textChanged.connect(lambda v: setattr(self._gps_gen, 'vdo_callsign', v))
        self._vdo_shiptype.valueChanged.connect(lambda v: setattr(self._gps_gen, 'vdo_shiptype', v))
        self._vdo_destination.textChanged.connect(lambda v: setattr(self._gps_gen, 'vdo_destination', v))
        self._vdo_eta_enabled.toggled.connect(self._on_vdo_eta_changed)
        self._vdo_eta.dateTimeChanged.connect(self._on_vdo_eta_changed)
        self._rmb_origin_id.textChanged.connect(lambda v: setattr(self._gps_gen, 'rmb_origin_id', v))
        self._rmb_dest_id.textChanged.connect(lambda v: setattr(self._gps_gen, 'rmb_dest_id', v))
        self._rmb_dest_lat.valueChanged.connect(lambda v: setattr(self._gps_gen, 'rmb_dest_lat', v))
        self._rmb_dest_lon.valueChanged.connect(lambda v: setattr(self._gps_gen, 'rmb_dest_lon', v))
        self._rmb_xte.valueChanged.connect(lambda v: setattr(self._gps_gen, 'rmb_xte', v))
        self._rmb_steer.currentTextChanged.connect(lambda v: setattr(self._gps_gen, 'rmb_steer', v[0]))

        # Radar computed lat/lon (live update khi thay đổi bearing/range hoặc own-ship)
        self._r_bearing.valueChanged.connect(self._update_radar_computed_pos)
        self._r_range.valueChanged.connect(self._update_radar_computed_pos)
        self._r_own_lat.valueChanged.connect(self._update_radar_computed_pos)
        self._r_own_lon.valueChanged.connect(self._update_radar_computed_pos)
        self._btn_r_copy_latlon.clicked.connect(self._copy_radar_latlon)
        self._btn_r_calc_bearing.clicked.connect(self._calc_bearing_from_latlon)
        self._btn_sync_gps.clicked.connect(self._sync_ownship_from_gps)

        # OSD / RSD
        self._chk_osd.toggled.connect(self._osd_grp.setVisible)
        self._chk_osd.toggled.connect(lambda v: setattr(self._radar_gen, 'send_osd', v))
        self._osd_set.valueChanged.connect(lambda v: setattr(self._radar_gen, 'osd_set', v))
        self._osd_drift.valueChanged.connect(lambda v: setattr(self._radar_gen, 'osd_drift', v))
        self._chk_rsd.toggled.connect(self._rsd_grp.setVisible)
        self._chk_rsd.toggled.connect(lambda v: setattr(self._radar_gen, 'send_rsd', v))
        self._rsd_vrm1.valueChanged.connect(lambda v: setattr(self._radar_gen, 'rsd_vrm1', v))
        self._rsd_ebl1.valueChanged.connect(lambda v: setattr(self._radar_gen, 'rsd_ebl1', v))
        self._rsd_vrm2.valueChanged.connect(lambda v: setattr(self._radar_gen, 'rsd_vrm2', v))
        self._rsd_ebl2.valueChanged.connect(lambda v: setattr(self._radar_gen, 'rsd_ebl2', v))
        self._rsd_range.valueChanged.connect(lambda v: setattr(self._radar_gen, 'rsd_range', v))
        self._rsd_rotation.currentTextChanged.connect(
            lambda v: setattr(self._radar_gen, 'rsd_rotation', v[0])
        )

        # Radar targets
        self._btn_r_add.clicked.connect(self._on_radar_add)
        self._btn_r_remove.clicked.connect(self._on_radar_remove)
        self._btn_r_auto.clicked.connect(self._on_radar_auto_generate)
        self._btn_r_clear.clicked.connect(self._on_radar_clear)
        self._radar_list.itemClicked.connect(self._on_radar_item_clicked)

        # AIS vessels
        self._btn_a_add.clicked.connect(self._on_ais_add)
        self._btn_a_remove.clicked.connect(self._on_ais_remove)
        self._btn_a_auto.clicked.connect(self._on_ais_auto_generate)
        self._btn_a_clear.clicked.connect(self._on_ais_clear)
        self._ais_list.itemClicked.connect(self._on_ais_item_clicked)
        self._btn_a_gpx_load.clicked.connect(self._on_ais_gpx_load)
        self._btn_a_gpx_clear_file.clicked.connect(self._on_ais_gpx_clear_file)
        self._a_gpx_speed_var.toggled.connect(self._a_gpx_sched_container.setVisible)

        # Fusion test
        self._btn_fm_add.clicked.connect(self._on_fusion_manual_add)
        self._btn_fusion_generate.clicked.connect(self._on_fusion_generate)
        self._btn_fusion_clear.clicked.connect(self._on_fusion_clear)

        # Log
        self._btn_clear.clicked.connect(self._log.clear)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        self._tcp_widget.setVisible(self._rb_tcp.isChecked())
        self._tcp_server_widget.setVisible(self._rb_tcp_server.isChecked())
        self._serial_widget.setVisible(self._rb_serial.isChecked())
        self._ssh_widget.setVisible(self._rb_ssh.isChecked())

    def _refresh_ports(self) -> None:
        self._serial_port.clear()
        ports = list_serial_ports()
        if ports:
            self._serial_port.addItems(ports)
        else:
            self._serial_port.addItem("(no ports found)")

    # Connection ----------------------------------------------------------

    def _on_connect(self) -> None:
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
            elif self._rb_ssh.isChecked():
                ssh_host = self._ssh_host.text().strip()
                pod_ip = self._ssh_pod_ip.text().strip()
                if not ssh_host or not pod_ip:
                    raise ValueError("Cần nhập SSH Host và Pod IP trước khi kết nối")
                local_port = self._ssh_local_port.value()
                tunnel = SSHTunnel(
                    ssh_host=ssh_host,
                    ssh_port=self._ssh_port.value(),
                    ssh_username=self._ssh_user.text().strip(),
                    ssh_password=self._ssh_pass.text(),
                    remote_host=pod_ip,
                    remote_port=self._ssh_remote_port.value(),
                    local_port=local_port,
                )
                try:
                    self._transmitter = TCPTransmitter("127.0.0.1", tunnel.local_port)
                except Exception:
                    tunnel.close()
                    raise
                self._ssh_tunnel = tunnel
                label = f"SSH Tunnel  127.0.0.1:{tunnel.local_port}  →  {pod_ip}:{self._ssh_remote_port.value()}"
                self._save_ssh_settings()
            else:
                port_name = self._serial_port.currentText()
                baud = int(self._serial_baud.currentText())
                parity_map = {"None (N)": "N", "Even (E)": "E", "Odd (O)": "O"}
                parity = parity_map.get(self._serial_parity.currentText(), "N")
                bits = int(self._serial_bits.currentText())
                self._transmitter = SerialTransmitter(port_name, baud, parity, bits)
                label = f"Serial  {port_name} @ {baud}"

            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._btn_start.setEnabled(True)
            self.statusBar().showMessage(f"Connected — {label}")
            self._log_info(f"Connected: {label}")

        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))

    def _on_disconnect(self) -> None:
        self._on_stop()
        if self._transmitter:
            self._transmitter.close()
            self._transmitter = None
        if self._ssh_tunnel:
            self._ssh_tunnel.close()
            self._ssh_tunnel = None
        self._btn_connect.setEnabled(True)
        self._btn_disconnect.setEnabled(False)
        self._btn_start.setEnabled(False)
        self.statusBar().showMessage("Disconnected")
        self._log_info("Disconnected")

    def _load_ssh_settings(self) -> None:
        """Điền sẵn panel SSH Tunnel từ ~/.maritime_simulator.json (nếu có),
        hoặc giá trị mặc định (SSH Host = 171.244.197.133) nếu chưa từng lưu."""
        cfg = ssh_settings.load()
        self._ssh_host.setText(cfg["ssh_host"])
        self._ssh_port.setValue(cfg["ssh_port"])
        self._ssh_user.setText(cfg["ssh_user"])
        self._ssh_namespace.setText(cfg["ssh_namespace"])
        self._ssh_label_selector.setText(cfg["ssh_label_selector"])
        self._ssh_pod_ip.setText(cfg["ssh_pod_ip"])
        self._ssh_remote_port.setValue(cfg["ssh_remote_port"])
        self._ssh_local_port.setValue(cfg["ssh_local_port"])
        self._ssh_remember_pass.setChecked(cfg["ssh_remember_password"])
        if cfg["ssh_remember_password"]:
            self._ssh_pass.setText(cfg["ssh_password"])

    def _save_ssh_settings(self) -> None:
        """Lưu panel SSH Tunnel vào ~/.maritime_simulator.json sau khi kết
        nối thành công lần đầu — mật khẩu chỉ lưu nếu tick 'Nhớ mật khẩu'."""
        remember = self._ssh_remember_pass.isChecked()
        cfg = {
            "ssh_host": self._ssh_host.text().strip(),
            "ssh_port": self._ssh_port.value(),
            "ssh_user": self._ssh_user.text().strip(),
            "ssh_password": self._ssh_pass.text() if remember else "",
            "ssh_remember_password": remember,
            "ssh_namespace": self._ssh_namespace.text().strip(),
            "ssh_label_selector": self._ssh_label_selector.text().strip(),
            "ssh_pod_ip": self._ssh_pod_ip.text().strip(),
            "ssh_remote_port": self._ssh_remote_port.value(),
            "ssh_local_port": self._ssh_local_port.value(),
        }
        try:
            ssh_settings.save(cfg)
        except Exception:
            pass

    def _on_ssh_fetch_pod_ip(self) -> None:
        ssh_host = self._ssh_host.text().strip()
        if not ssh_host:
            QMessageBox.warning(self, "Thiếu thông tin", "Nhập SSH Host trước")
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        self._btn_ssh_fetch_pod_ip.setEnabled(False)
        try:
            pod_ip = fetch_pod_ip(
                ssh_host=ssh_host,
                ssh_port=self._ssh_port.value(),
                ssh_username=self._ssh_user.text().strip(),
                ssh_password=self._ssh_pass.text(),
                namespace=self._ssh_namespace.text().strip(),
                label_selector=self._ssh_label_selector.text().strip(),
            )
            self._ssh_pod_ip.setText(pod_ip)
            self._log_info(f"Đã lấy Pod IP: {pod_ip}")
        except Exception as exc:
            QMessageBox.critical(self, "Lấy Pod IP thất bại", str(exc))
        finally:
            self._btn_ssh_fetch_pod_ip.setEnabled(True)
            self.unsetCursor()

    # Transmit control ----------------------------------------------------

    def _on_start(self) -> None:
        if not self._transmitter:
            return
        interval = self._slider_interval.value()
        gps = self._gps_gen if self._chk_gps.isChecked() else None
        radar = self._radar_gen if self._chk_radar.isChecked() else None
        ais = self._ais_gen if self._chk_ais.isChecked() else None

        self._msg_count = 0
        self._thread = TransmitterThread(self._transmitter, gps, radar, ais, interval)
        self._thread.message_sent.connect(self._on_message_sent)
        self._thread.error_occurred.connect(self._on_error)
        self._thread.start()

        self._btn_start.setEnabled(False)
        self._btn_stop.setEnabled(True)
        self.statusBar().showMessage(f"Transmitting  —  interval {interval} ms")
        self._gps_display_timer.start()

    def _on_stop(self) -> None:
        self._gps_display_timer.stop()
        if self._thread:
            self._thread.stop()
            self._thread = None
        self._btn_start.setEnabled(self._transmitter is not None)
        self._btn_stop.setEnabled(False)
        if self._transmitter:
            self.statusBar().showMessage("Connected  (stopped)")

    @pyqtSlot(str)
    def _on_message_sent(self, msg: str) -> None:
        ts = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        if "GPRMC" in msg:
            colour = _COL_GPS
        elif "RATTM" in msg or "RAOSD" in msg or "RARSD" in msg:
            colour = _COL_RADAR
        elif "AIVDM" in msg or "AIVDO" in msg:
            colour = _COL_AIS
        else:
            colour = "#ffffff"
        self._log.append(
            f'<span style="color:{_COL_INFO};">[{ts}]</span>'
            f'&nbsp;<span style="color:{colour};">{msg}</span>'
        )
        if self._chk_scroll.isChecked():
            sb = self._log.verticalScrollBar()
            sb.setValue(sb.maximum())
        self._msg_count = getattr(self, '_msg_count', 0) + 1
        self._lbl_count.setText(f"{self._msg_count} messages sent")

    @pyqtSlot(str)
    def _on_error(self, err: str) -> None:
        self._log.append(
            f'<span style="color:{_COL_ERROR};">[ERROR] {err}</span>'
        )
        QMessageBox.warning(self, "Transmission Error", err)
        self._on_stop()

    def _log_info(self, text: str) -> None:
        self._log.append(
            f'<span style="color:{_COL_INFO};">[INFO] {text}</span>'
        )

    # Radar target management ---------------------------------------------

    def _update_radar_computed_pos(self) -> None:
        own_lat = self._r_own_lat.value()
        own_lon = self._r_own_lon.value()
        lat, lon = _latlon_from_bearing_range(
            own_lat, own_lon,
            self._r_bearing.value(), self._r_range.value(),
        )
        self._r_computed_lat.setText(f"{lat:.6f}")
        self._r_computed_lon.setText(f"{lon:.6f}")

    def _sync_ownship_from_gps(self) -> None:
        self._r_own_lat.setValue(self._gps_gen.lat)
        self._r_own_lon.setValue(self._gps_gen.lon)

    def _copy_radar_latlon(self) -> None:
        lat = self._r_computed_lat.text()
        lon = self._r_computed_lon.text()
        if lat and lon:
            QApplication.clipboard().setText(f"{lat}, {lon}")
            self._log_info(f"Copied to clipboard: {lat}, {lon}")

    def _calc_bearing_from_latlon(self) -> None:
        from generators import _bearing_range
        own_lat = self._r_own_lat.value()
        own_lon = self._r_own_lon.value()
        tgt_lat = self._r_input_lat.value()
        tgt_lon = self._r_input_lon.value()
        bearing, range_nm = _bearing_range(
            own_lat, own_lon, tgt_lat, tgt_lon
        )
        # Block signals để tránh _update_radar_computed_pos ghi đè display
        self._r_bearing.blockSignals(True)
        self._r_range.blockSignals(True)
        self._r_bearing.setValue(round(bearing, 4))
        self._r_range.setValue(round(range_nm, 4))
        self._r_bearing.blockSignals(False)
        self._r_range.blockSignals(False)
        # Hiển thị đúng lat/lon gốc người dùng đã nhập
        self._r_computed_lat.setText(f"{tgt_lat:.6f}")
        self._r_computed_lon.setText(f"{tgt_lon:.6f}")
        self._log_info(
            f"Lat/Lon ({tgt_lat:.6f}, {tgt_lon:.6f}) "
            f"→ Bearing={bearing:.4f}°  Range={range_nm:.4f} NM"
        )

    def _on_vdo_eta_changed(self) -> None:
        if self._vdo_eta_enabled.isChecked():
            dt = self._vdo_eta.dateTime()
            eta = (dt.date().month(), dt.date().day(),
                   dt.time().hour(), dt.time().minute())
        else:
            eta = (0, 0, 24, 60)
        self._gps_gen.vdo_eta = eta

    def _on_radar_add(self) -> None:
        status_map = {
            "T  (Tracking)": "T",
            "L  (Lost)": "L",
            "Q  (Query)": "Q",
        }
        self._radar_gen.add_or_update_target(
            target_id=self._r_id.value(),
            bearing=self._r_bearing.value(),
            range_nm=self._r_range.value(),
            speed=self._r_speed.value(),
            course=self._r_course.value(),
            status=status_map.get(self._r_status.currentText(), "T"),
            name=self._r_name.text().strip(),
        )
        self._refresh_radar_list()
        self._refresh_fusion_list()

    def _on_radar_remove(self) -> None:
        items = self._radar_list.selectedItems()
        if items:
            tid = int(items[0].text().split(':')[0].strip())
            self._radar_gen.remove_target(tid)
            self._refresh_radar_list()
            self._refresh_fusion_list()

    def _on_radar_item_clicked(self, item) -> None:
        tid = int(item.text().split(':')[0].strip())
        t = self._radar_gen.targets.get(tid)
        if not t:
            return
        self._r_id.setValue(tid)
        self._r_bearing.setValue(t['bearing'])
        self._r_range.setValue(t['range'])
        self._r_speed.setValue(t['speed'])
        self._r_course.setValue(t['course'])
        self._r_name.setText(t['name'])
        rev = {"T": "T  (Tracking)", "L": "L  (Lost)", "Q": "Q  (Query)"}
        self._r_status.setCurrentText(rev.get(t['status'], "T  (Tracking)"))

    def _on_radar_auto_generate(self) -> None:
        import random
        count = self._r_auto_count.value()
        existing = set(self._radar_gen.targets.keys())
        own_lat, own_lon = self._radar_gen.own_lat, self._radar_gen.own_lon
        for _ in range(count):
            tid = 1
            while tid in existing:
                tid += 1
            existing.add(tid)
            lat, lon = self._sample_near_own_ship(own_lat, own_lon, random.uniform(0.5, 15.0))
            bearing, range_nm = _bearing_range(own_lat, own_lon, lat, lon)
            self._radar_gen.add_or_update_target(
                target_id=tid,
                bearing=round(bearing, 1),
                range_nm=round(max(range_nm, 0.05), 2),
                speed=round(random.uniform(0, 20), 1),
                course=round(random.uniform(0, 360), 1),
                status='T',
                name=f'TGT{tid:02d}',
            )
        self._refresh_radar_list()

    def _on_radar_clear(self) -> None:
        self._radar_gen.targets.clear()
        self._refresh_radar_list()

    # Ship types that require Class A transponder (large commercial vessels)
    _CLASS_A_TYPES = {52, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
                      70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
                      80, 81, 82, 83, 84, 85, 86, 87, 88, 89}

    # Vùng biển/cảng/sông Việt Nam — dùng để sinh toạ độ luôn nằm trên mặt
    # nước (không rơi lên đất liền).
    # (tên, kind, lat1, lon1, lat2, lon2, size, loại_vùng, trọng_số)
    #   kind='circle'   : vùng biển/vịnh mở — tròn bán kính `size` NM quanh
    #                     (lat1, lon1); đủ rộng nên full-circle vẫn an toàn.
    #   kind='corridor' : luồng/sông hẹp — dải NM `size` (nửa bề rộng) dọc
    #                     theo đoạn thẳng xấp xỉ lòng sông/luồng từ
    #                     (lat1, lon1) đến (lat2, lon2); tránh full-circle
    #                     rơi lên bờ như cách sinh cũ.
    # loại_vùng: 'port' | 'sea' | 'river' — quyết định loại tàu/tốc độ điển hình.
    _VIETNAM_ZONES = [
        # ── Biển / vịnh mở (circle) ──────────────────────────────────────
        ('Vịnh Bắc Bộ',              'circle', 19.700, 107.500, None, None, 45.0, 'sea', 9),
        ('Ven biển Trung Bộ',        'circle', 15.300, 109.800, None, None, 45.0, 'sea', 8),
        ('Ven biển Nam Trung Bộ',    'circle', 12.300, 110.300, None, None, 45.0, 'sea', 8),
        ('Biển Đông (Nam)',          'circle',  9.500, 110.500, None, None, 55.0, 'sea', 7),
        ('Vịnh Thái Lan',            'circle',  9.300, 103.800, None, None, 35.0, 'sea', 6),
        ('Quần đảo Trường Sa',       'circle',  9.000, 113.000, None, None, 45.0, 'sea', 3),
        ('Vịnh Đà Nẵng (ngoài khơi)','circle', 16.150, 108.260, None, None,  1.5, 'sea', 5),
        ('Vịnh Nha Trang (ngoài khơi)','circle',12.190, 109.260, None, None,  1.8, 'sea', 5),
        ('Vịnh Quy Nhơn (ngoài khơi)','circle', 13.740, 109.300, None, None,  1.5, 'sea', 4),
        ('Vũng neo Vũng Tàu',        'circle', 10.300, 107.200, None, None,  3.0, 'sea', 9),
        ('Cửa Mekong (ngoài khơi)',  'circle',  9.450, 106.750, None, None,  4.0, 'sea', 5),
        ('Vịnh Hạ Long (mở)',        'circle', 20.900, 107.150, None, None,  3.0, 'sea', 6),
        # ── Luồng cảng / sông hẹp (corridor) ─────────────────────────────
        ('Sông Sài Gòn (nội đô)',    'corridor', 10.7820, 106.7040, 10.7550, 106.7430, 0.25, 'river', 6),
        ('Sông Sài Gòn (Cát Lái)',   'corridor', 10.7550, 106.7430, 10.7150, 106.7900, 0.35, 'port', 10),
        ('Luồng Cái Mép - Thị Vải',  'corridor', 10.5800, 107.0150, 10.4300, 107.0300, 0.60, 'port', 10),
        ('Sông Hậu (Cần Thơ)',       'corridor', 10.0700, 105.7300,  9.9600, 105.8500, 0.50, 'river', 6),
        ('Sông Tiền (Mỹ Tho)',       'corridor', 10.3600, 106.3400, 10.2000, 106.5600, 0.40, 'river', 5),
        ('Luồng Hải Phòng (Bạch Đằng)','corridor', 20.8700, 106.8000, 20.7500, 106.9600, 0.60, 'port', 10),
        ('Sông Cấm (Hải Phòng)',     'corridor', 20.9000, 106.6500, 20.8500, 106.7500, 0.35, 'river', 5),
    ]

    # Tàu phù hợp theo loại vùng
    _ZONE_SHIP_TYPES = {
        'port':  [52, 60, 70, 71, 72, 73, 74, 80, 81, 82, 83, 90],
        'sea':   [70, 71, 72, 73, 74, 80, 81, 82, 83, 84],
        'river': [30, 36, 37, 52, 90],
    }

    def _random_own_ship_start(self) -> tuple:
        """Chọn vị trí xuất phát ngẫu nhiên cho tàu mình — ưu tiên các
        cảng/sông Việt Nam, thỉnh thoảng ở ngoài khơi. Thay cho toạ độ cố
        định cũ (nằm trên đất liền giữa TP.HCM)."""
        import random
        port_zones = [z for z in self._VIETNAM_ZONES if z[7] in ('port', 'river')]
        sea_zones = [z for z in self._VIETNAM_ZONES if z[7] == 'sea']
        zones = port_zones if random.random() < 0.75 else sea_zones
        weights = [z[8] for z in zones]
        zone = random.choices(zones, weights=weights, k=1)[0]
        lat, lon = _sample_zone_point(zone)
        return round(lat, 6), round(lon, 6)

    def _nearest_water_zone(self, lat: float, lon: float):
        """Trả về zone (trong _VIETNAM_ZONES) có điểm tham chiếu gần
        (lat, lon) nhất — dùng để sinh mục tiêu Radar/AIS "quanh tàu mình"
        bám theo đúng vùng nước tàu mình đang ở, tránh rơi lên bờ."""
        best, best_d = None, float('inf')
        for zone in self._VIETNAM_ZONES:
            _, kind, lat1, lon1, lat2, lon2, *_rest = zone
            if kind == 'circle':
                ref_lat, ref_lon = lat1, lon1
            else:
                ref_lat, ref_lon = (lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0
            _, d = _bearing_range(lat, lon, ref_lat, ref_lon)
            if d < best_d:
                best_d, best = d, zone
        return best

    def _sample_near_own_ship(self, own_lat: float, own_lon: float, range_nm: float) -> tuple:
        """Sinh 1 điểm cách tàu mình khoảng `range_nm` NM, bám theo vùng
        nước (biển mở / luồng / sông) gần tàu mình nhất — mục tiêu Radar/AIS
        "quanh tàu mình" luôn nằm trên mặt nước thay vì rơi lên bờ."""
        import random
        zone = self._nearest_water_zone(own_lat, own_lon)
        if zone is None or zone[1] == 'circle':
            bearing = random.uniform(0, 360)
            return _latlon_from_bearing_range(own_lat, own_lon, bearing, range_nm)

        # corridor: rải trong 1 dải hình chữ nhật quanh VỊ TRÍ TÀU MÌNH, dọc
        # theo trục sông/luồng (không phải từ đầu đoạn zone — trước đây tính
        # từ đầu đoạn rồi clamp vào [0, length_nm] khiến hầu hết mục tiêu bị
        # dồn về đúng 1 điểm đầu/cuối đoạn). Thành phần dọc trục lấy ngẫu
        # nhiên trong [-range_nm, range_nm] thay vì cố định đúng range_nm —
        # nếu không, mọi mục tiêu chỉ rơi vào đúng 2 tia (trước/sau tàu
        # mình), nhìn như nằm thẳng hàng trên 1 đường thẳng.
        _, _kind, lat1, lon1, lat2, lon2, half_width, _z_type, _w = zone
        axis_brg, _length_nm = _bearing_range(lat1, lon1, lat2, lon2)
        along = random.uniform(-range_nm, range_nm)
        perp = random.uniform(-half_width, half_width)
        lat_c, lon_c = _move(own_lat, own_lon, axis_brg, along, 1.0)
        perp_brg = (axis_brg + 90.0) % 360
        return _move(lat_c, lon_c, perp_brg, perp, 1.0)

    def _random_vietnam_vessel(self) -> dict:
        """Tạo một tàu tại vị trí thực tế ở vùng biển Việt Nam."""
        import random
        zones = self._VIETNAM_ZONES
        weights = [z[8] for z in zones]
        zone = random.choices(zones, weights=weights, k=1)[0]
        z_type = zone[7]
        lat, lon = _sample_zone_point(zone)

        ship_type = random.choice(self._ZONE_SHIP_TYPES[z_type])
        ais_class = 'A' if ship_type in self._CLASS_A_TYPES else 'B'

        if z_type == 'port':
            speed = round(random.uniform(0.0, 0.3), 1)
            nav_status = random.choice([1, 1, 5])   # chủ yếu neo/cập bến
            heading = 511
        elif z_type == 'sea':
            speed = round(random.uniform(8.0, 18.0), 1)
            nav_status = 0
            heading = random.randint(0, 359)
        else:  # river
            speed = round(random.uniform(2.0, 8.0), 1)
            nav_status = 0
            heading = random.randint(0, 359)

        cog = round(random.uniform(0, 360), 1)

        # MMSI: cảng/sông → Việt Nam (574); biển → đa quốc gia
        if z_type == 'sea':
            mid_pool = [574, 574, 574, 413, 431, 440, 563, 533, 338]
            mid = random.choice(mid_pool)
        else:
            mid = 574

        return {
            'lat': round(lat, 6), 'lon': round(lon, 6),
            'speed': speed, 'cog': cog, 'heading': heading,
            'nav_status': nav_status, 'ship_type': ship_type,
            'ais_class': ais_class, 'mid': mid, 'zone_type': z_type,
        }

    def _on_ais_auto_generate(self) -> None:
        import random
        count = self._a_auto_count.value()
        vietnam_mode = self._a_auto_mode.currentIndex() == 1

        for _ in range(count):
            idx = len(self._ais_gen.vessels) + 1

            if vietnam_mode:
                v = self._random_vietnam_vessel()
                mmsi = self._new_mmsi(mid=v['mid'])
                imo = random.randint(1_000_000, 9_999_999) if v['ais_class'] == 'A' else 0
                self._ais_gen.add_or_update_vessel(
                    mmsi=mmsi,
                    lat=v['lat'], lon=v['lon'],
                    sog=v['speed'], cog=v['cog'], heading=v['heading'],
                    nav_status=v['nav_status'],
                    shipname=f'VN {idx:04d}',
                    shiptype=v['ship_type'],
                    callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
                    imo=imo, ais_class=v['ais_class'],
                )
            else:
                # Phân bố theo cự ly thực tế như AIS/Radar trên tàu thật
                band = random.choices(
                    ['near', 'mid', 'far'],
                    weights=[25, 45, 30]
                )[0]
                if band == 'near':       # 0.3–5 NM: tàu nhỏ, tàu cá, tàu kéo
                    range_nm = random.uniform(0.3, 5.0)
                    ship_types = [30, 36, 37, 52, 90]
                    sog = round(random.uniform(0, 8), 1)
                    nav_status = random.choice([0, 0, 1])
                elif band == 'mid':      # 5–20 NM: tàu hàng, tàu khách hỗn hợp
                    range_nm = random.uniform(5.0, 20.0)
                    ship_types = [52, 60, 70, 71, 72, 80, 81, 90]
                    sog = round(random.uniform(4, 15), 1)
                    nav_status = 0
                else:                    # 20–40 NM: tàu lớn trên tuyến biển
                    range_nm = random.uniform(20.0, 40.0)
                    ship_types = [70, 71, 72, 73, 74, 80, 81, 82, 83, 84]
                    sog = round(random.uniform(10, 18), 1)
                    nav_status = 0

                shiptype = random.choice(ship_types)
                ais_class = 'A' if shiptype in self._CLASS_A_TYPES else 'B'
                mmsi = self._new_mmsi(mid=0)
                lat, lon = self._sample_near_own_ship(
                    self._gps_gen.lat, self._gps_gen.lon, range_nm
                )
                cog = round(random.uniform(0, 360), 1)
                heading = int(cog) % 360 if sog > 0.5 else 511
                imo = random.randint(1_000_000, 9_999_999) if ais_class == 'A' else 0
                self._ais_gen.add_or_update_vessel(
                    mmsi=mmsi,
                    lat=round(lat, 6), lon=round(lon, 6),
                    sog=sog, cog=cog, heading=heading,
                    nav_status=nav_status,
                    shipname=f'VESSEL {idx:04d}',
                    shiptype=shiptype,
                    callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
                    imo=imo, ais_class=ais_class,
                )
        self._refresh_ais_list()

    def _on_ais_clear(self) -> None:
        self._ais_gen.vessels.clear()
        self._ais_vessel_routes.clear()
        self._ais_vessel_schedules.clear()
        self._refresh_ais_list()

    def _refresh_radar_list(self) -> None:
        self._radar_list.clear()
        for tid, t in self._radar_gen.targets.items():
            self._radar_list.addItem(
                f"{tid:2d}: Brg={t['bearing']:6.1f}°  "
                f"Rng={t['range']:6.2f} NM  "
                f"Spd={t['speed']:5.1f} kn  "
                f"Crs={t['course']:6.1f}°  [{t['status']}]"
            )

    # AIS vessel management -----------------------------------------------

    def _on_ais_add(self) -> None:
        nav_raw = self._a_navstatus.currentText().split(' – ')[0].strip()
        if self._a_eta_enabled.isChecked():
            dt = self._a_eta.dateTime()
            eta = (dt.date().month(), dt.date().day(),
                   dt.time().hour(), dt.time().minute())
        else:
            eta = (0, 0, 24, 60)   # not available

        new_mmsi = int(self._a_mmsi.text())
        old_mmsi = getattr(self, '_a_last_loaded_mmsi', None)

        # Nếu user đổi MMSI của một vessel đang có trong fusion entry → cập nhật entry + xóa vessel cũ
        if old_mmsi is not None and old_mmsi != new_mmsi:
            for e in self._fusion_entries:
                if e.get('mmsi') == old_mmsi:
                    e['mmsi'] = new_mmsi
                    self._ais_gen.vessels.pop(old_mmsi, None)
                    break
        self._a_last_loaded_mmsi = new_mmsi

        ais_class = 'A' if self._a_ais_class.currentIndex() == 0 else 'B'
        self._ais_gen.add_or_update_vessel(
            mmsi=new_mmsi,
            lat=self._a_lat.value(),
            lon=self._a_lon.value(),
            sog=self._a_sog.value(),
            cog=self._a_cog.value(),
            heading=self._a_heading.value(),
            nav_status=int(nav_raw),
            shipname=self._a_shipname.text().strip(),
            shiptype=self._a_shiptype.value(),
            callsign=self._a_callsign.text().strip(),
            destination=self._a_destination.text().strip(),
            eta=eta,
            imo=self._a_imo.value() if ais_class == 'A' else 0,
            ais_class=ais_class,
        )
        if self._a_gpx_pending is not None:
            # User tải GPX mới tường minh → gán route + reset vị trí về đầu route
            self._ais_gen.set_vessel_route(
                new_mmsi, self._a_gpx_pending, self._a_gpx_loop.isChecked()
            )
            self._ais_vessel_routes[new_mmsi] = self._a_gpx_pending
            self._a_gpx_pending = None
            fname = self._a_gpx_label.text()
            self._a_gpx_label.setText(f"Đã gán — {fname}")
        elif new_mmsi in self._ais_vessel_routes:
            # Route đang chạy → add_or_update_vessel đã giữ nguyên _route trong dict;
            # chỉ cập nhật loop flag nếu user thay đổi
            v_live = self._ais_gen.vessels.get(new_mmsi)
            if v_live:
                v_live['_route_loop'] = self._a_gpx_loop.isChecked()
        else:
            self._ais_gen.clear_vessel_route(new_mmsi)

        # Speed schedule
        v_live = self._ais_gen.vessels.get(new_mmsi)
        if v_live is not None:
            if self._a_gpx_speed_var.isChecked():
                schedule = _parse_speed_schedule(self._a_gpx_schedule_edit.text())
                if schedule:
                    v_live['_speed_schedule'] = schedule
                    self._ais_vessel_schedules[new_mmsi] = schedule
                else:
                    v_live.pop('_speed_schedule', None)
                    self._ais_vessel_schedules.pop(new_mmsi, None)
            else:
                v_live.pop('_speed_schedule', None)
                self._ais_vessel_schedules.pop(new_mmsi, None)

        self._refresh_ais_list()
        self._refresh_fusion_list()

    def _on_ais_remove(self) -> None:
        items = self._ais_list.selectedItems()
        if items:
            mmsi = int(items[0].text().split()[0])
            self._ais_gen.remove_vessel(mmsi)
            self._ais_vessel_routes.pop(mmsi, None)
            self._ais_vessel_schedules.pop(mmsi, None)
            self._refresh_ais_list()
            self._refresh_fusion_list()

    def _on_ais_item_clicked(self, item) -> None:
        mmsi = int(item.text().split()[0])
        v = self._ais_gen.vessels.get(mmsi)
        if not v:
            return
        self._a_last_loaded_mmsi = mmsi   # track để detect đổi MMSI
        self._a_mmsi.setText(str(mmsi))
        cls = v.get('ais_class', 'A')
        self._a_ais_class.setCurrentIndex(0 if cls == 'A' else 1)
        self._a_imo.setValue(v.get('imo', 0))
        self._a_shipname.setText(v.get('shipname', ''))
        self._a_callsign.setText(v.get('callsign', ''))
        self._a_destination.setText(v.get('destination', ''))
        self._a_lat.setValue(v['lat'])
        self._a_lon.setValue(v['lon'])
        self._a_sog.setValue(v['sog'])
        self._a_cog.setValue(v['cog'])
        self._a_heading.setValue(v['heading'])
        self._a_shiptype.setValue(v.get('shiptype', 0))
        eta = v.get('eta', (0, 0, 24, 60))
        has_eta = eta != (0, 0, 24, 60)
        self._a_eta_enabled.setChecked(has_eta)
        if has_eta:
            from PyQt6.QtCore import QDateTime
            self._a_eta.setDateTime(
                QDateTime(2000, eta[0] or 1, eta[1] or 1, eta[2], eta[3])
            )
        # Khôi phục GPX state — KHÔNG set _a_gpx_pending từ route cũ;
        # user phải tải file GPX mới tường minh để thay đổi route
        self._a_gpx_pending = None
        route = self._ais_vessel_routes.get(mmsi)
        if route:
            idx = v.get('_route_idx', 0)
            n = len(route)
            self._a_gpx_label.setText(f"Route đã gán ({n} điểm)")
            self._a_gpx_label.setStyleSheet("color:#00e676;")
            self._a_gpx_loop.setChecked(v.get('_route_loop', False))
            done = v.get('_route_done', False)
            self._a_gpx_status.setText(
                f"Đã đến điểm cuối ({n}/{n})" if done else f"Waypoint {idx + 1}/{n}"
            )
        else:
            self._a_gpx_label.setText("Chưa chọn file")
            self._a_gpx_label.setStyleSheet("color:#90a4ae; font-style:italic;")
            self._a_gpx_status.setText("—")

        # Khôi phục speed schedule state
        schedule = self._ais_vessel_schedules.get(mmsi)
        if schedule:
            self._a_gpx_speed_var.setChecked(True)
            self._a_gpx_schedule_edit.setText(
                ', '.join(f"{wp}:{sog:g}" for wp, sog in schedule)
            )
            eff_sog = self._ais_gen.get_vessel_effective_sog(mmsi)
            self._a_gpx_sched_cur.setText(
                f"Tốc độ hiện tại: {eff_sog:.1f} kn" if eff_sog is not None else "Tốc độ hiện tại: —"
            )
        else:
            self._a_gpx_speed_var.setChecked(False)
            self._a_gpx_schedule_edit.setText('')
            self._a_gpx_sched_cur.setText("Tốc độ hiện tại: —")

    def _on_ais_gpx_load(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Chọn file GPX", "", "GPX Files (*.gpx);;All Files (*)"
        )
        if not path:
            return
        try:
            wpts = parse_gpx(path)
        except Exception as exc:
            QMessageBox.warning(self, "Lỗi GPX", f"Không đọc được file:\n{exc}")
            return
        if len(wpts) < 2:
            QMessageBox.warning(self, "GPX quá ít điểm",
                                "File GPX phải có ít nhất 2 điểm waypoint.")
            return
        self._a_gpx_pending = wpts
        fname = os.path.basename(path)
        self._a_gpx_label.setText(f"{fname}  ({len(wpts)} điểm)")
        self._a_gpx_label.setStyleSheet("color:#00e676;")
        self._a_gpx_status.setText(f"Waypoint 1/{len(wpts)}")

    def _on_ais_gpx_clear_file(self) -> None:
        self._a_gpx_pending = None
        cur_mmsi = getattr(self, '_a_last_loaded_mmsi', None)
        if cur_mmsi is not None:
            self._ais_vessel_routes.pop(cur_mmsi, None)
            self._ais_vessel_schedules.pop(cur_mmsi, None)
        self._a_gpx_label.setText("Chưa chọn file")
        self._a_gpx_label.setStyleSheet("color:#90a4ae; font-style:italic;")
        self._a_gpx_status.setText("—")
        self._a_gpx_speed_var.setChecked(False)
        self._a_gpx_schedule_edit.setText('')
        self._a_gpx_sched_cur.setText("Tốc độ hiện tại: —")

    def _refresh_ais_list(self) -> None:
        self._ais_list.clear()
        for mmsi, v in self._ais_gen.vessels.items():
            name = v.get('shipname', '') or '—'
            cls = v.get('ais_class', 'A')
            route_tag = ''
            if mmsi in self._ais_vessel_routes:
                idx = v.get('_route_idx', 0)
                n = len(self._ais_vessel_routes[mmsi])
                route_tag = f'  [GPX {idx + 1}/{n}]'
            # Hiện effective SOG (từ schedule nếu có) thay vì base SOG
            eff_sog = self._ais_gen.get_vessel_effective_sog(mmsi)
            sog_display = eff_sog if eff_sog is not None else v['sog']
            self._ais_list.addItem(
                f"{mmsi}  [{name}]  Cls={cls}{route_tag}  "
                f"Lat={v['lat']:10.6f}  Lon={v['lon']:11.6f}  "
                f"SOG={sog_display:5.1f} kn  COG={v['cog']:6.1f}°"
            )

    # GPS live display ----------------------------------------------------

    def _update_gps_display(self) -> None:
        """Refresh GPS spinboxes, AIS list, and TCP Server client count."""
        # TCP Server client count
        if isinstance(self._transmitter, TCPServerTransmitter):
            n = self._transmitter.client_count()
            self._lbl_clients.setText(
                f"{n} client{'s' if n != 1 else ''} connected"
            )

        # Cập nhật lat/lon tuyệt đối của radar target theo vị trí GPS hiện tại
        self._update_radar_computed_pos()

        # Sync OSD own-ship values from GPS generator
        if self._chk_osd.isChecked():
            self._radar_gen.osd_heading = self._gps_gen.heading_true
            self._radar_gen.osd_course = self._gps_gen.course
            self._radar_gen.osd_speed = self._gps_gen.speed

        # GPS spinboxes
        self._gps_lat.blockSignals(True)
        self._gps_lon.blockSignals(True)
        self._gps_lat.setValue(self._gps_gen.lat)
        self._gps_lon.setValue(self._gps_gen.lon)
        self._gps_lat.blockSignals(False)
        self._gps_lon.blockSignals(False)

        # AIS list — giữ lại dòng đang chọn
        selected = self._ais_list.currentRow()
        self._refresh_ais_list()
        if selected >= 0:
            self._ais_list.setCurrentRow(selected)

        # AIS form — chỉ cập nhật lat/lon khi user không đang chỉnh sửa các ô đó
        any_focused = any(w.hasFocus() for w in (
            self._a_lat, self._a_lon, self._a_sog, self._a_cog,
            self._a_heading, self._a_mmsi, self._a_shipname,
            self._a_callsign, self._a_destination,
        ))
        if not any_focused:
            items = self._ais_list.selectedItems()
            if items:
                mmsi = int(items[0].text().split()[0])
                v = self._ais_gen.vessels.get(mmsi)
                if v:
                    self._a_lat.blockSignals(True)
                    self._a_lon.blockSignals(True)
                    self._a_lat.setValue(v['lat'])
                    self._a_lon.setValue(v['lon'])
                    self._a_lat.blockSignals(False)
                    self._a_lon.blockSignals(False)
                    # Cập nhật live waypoint status và speed schedule label
                    if mmsi in self._ais_vessel_routes and v.get('_route'):
                        idx = v.get('_route_idx', 0)
                        n = len(self._ais_vessel_routes[mmsi])
                        done = v.get('_route_done', False)
                        self._a_gpx_status.setText(
                            f"Đã đến điểm cuối ({n}/{n})" if done
                            else f"Waypoint {idx + 1}/{n}"
                        )
                        if self._a_gpx_speed_var.isChecked():
                            eff = self._ais_gen.get_vessel_effective_sog(mmsi)
                            if eff is not None:
                                self._a_gpx_sched_cur.setText(
                                    f"Tốc độ hiện tại: {eff:.1f} kn  ←  WP {idx}"
                                )

    # Fusion test scenario ------------------------------------------------

    # ITU-R M.585 Maritime Identification Digits
    _MID_TABLE: dict[str, int] = {
        "Vietnam (574)":      574,
        "China (413)":        413,
        "Japan (431)":        431,
        "South Korea (440)":  440,
        "Singapore (563)":    563,
        "Malaysia (533)":     533,
        "Philippines (548)":  548,
        "Indonesia (525)":    525,
        "Thailand (567)":     567,
        "Hong Kong (477)":    477,
        "USA (338)":          338,
        "UK (235)":           235,
        "Australia (503)":    503,
        "India (419)":        419,
    }

    def _new_mmsi(self, mid: int | None = None) -> int:
        """Return a unique, standards-compliant MMSI (MID × 10⁶ + 6-digit suffix).

        mid=None → read from the Fusion Test combo (Mix = random country each call).
        mid=0    → pick a random country from _MID_TABLE.
        mid=N    → use that MID directly.
        """
        import random
        if mid is None:
            sel = self._f_mid.currentText()
            mid = random.choice(list(self._MID_TABLE.values())) if sel.startswith("Mix") \
                else self._MID_TABLE.get(sel, 574)
        elif mid == 0:
            mid = random.choice(list(self._MID_TABLE.values()))
        existing = set(self._ais_gen.vessels)
        for _ in range(10_000):
            mmsi = mid * 1_000_000 + random.randint(0, 999_999)
            if mmsi not in existing:
                return mmsi
        raise RuntimeError("Cannot generate a unique MMSI")

    def _on_fusion_manual_add(self) -> None:
        import random
        mmsi_text = self._fm_mmsi.text().strip()
        if not mmsi_text.isdigit() or len(mmsi_text) != 9:
            QMessageBox.warning(self, "MMSI không hợp lệ", "MMSI phải là đúng 9 chữ số.")
            return

        tid      = self._fm_target_id.value()
        bearing  = self._fm_bearing.value()
        range_nm = self._fm_range.value()
        speed    = self._fm_speed.value()
        course   = self._fm_course.value()
        name     = self._fm_name.text().strip() or f'FUS{tid:02d}'
        mmsi     = int(mmsi_text)
        shiptype = self._fm_shiptype.value()
        ais_class = 'A' if self._fm_ais_class.currentIndex() == 0 else 'B'
        nav_raw  = self._fm_nav_status.currentText().split(' – ')[0].strip()
        nav_status = int(nav_raw)

        # Sync own-ship reference
        self._radar_gen.own_lat = self._gps_gen.lat
        self._radar_gen.own_lon = self._gps_gen.lon

        # Radar target
        self._radar_gen.add_or_update_target(
            target_id=tid, bearing=bearing, range_nm=range_nm,
            speed=speed, course=course, status='T', name=name,
        )

        # AIS vessel tại đúng lat/lon tính từ bearing + range
        lat, lon = _latlon_from_bearing_range(
            self._gps_gen.lat, self._gps_gen.lon, bearing, range_nm
        )
        heading = int(course) % 360 if speed > 0.5 else 511
        imo = random.randint(1_000_000, 9_999_999) if ais_class == 'A' else 0
        self._ais_gen.add_or_update_vessel(
            mmsi=mmsi, lat=round(lat, 6), lon=round(lon, 6),
            sog=speed, cog=course, heading=heading,
            nav_status=nav_status, shipname=name, shiptype=shiptype,
            callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
            imo=imo, ais_class=ais_class,
        )

        # Xoá entry cũ nếu trùng tid hoặc mmsi, rồi thêm mới
        self._fusion_entries = [
            e for e in self._fusion_entries
            if not (e.get('tid') == tid or e.get('mmsi') == mmsi)
        ]
        self._fusion_entries.append({'type': 'FUSED', 'tid': tid, 'mmsi': mmsi})

        self._refresh_radar_list()
        self._refresh_ais_list()
        self._refresh_fusion_list()
        self._log_info(f"Manual fused: Radar#{tid} ↔ MMSI={mmsi}  [{name}]")

    def _on_fusion_generate(self) -> None:
        import random
        # Sync own-ship reference so radar and AIS targets share the same origin
        self._radar_gen.own_lat = self._gps_gen.lat
        self._radar_gen.own_lon = self._gps_gen.lon
        self._radar_gen.targets.clear()
        self._ais_gen.vessels.clear()
        self._fusion_entries = []

        fused_count = self._f_fused_count.value()
        radar_only_count = self._f_radar_only_count.value()
        ais_only_count = self._f_ais_only_count.value()

        tid = 1

        for i in range(fused_count):
            mmsi = self._new_mmsi()
            speed = round(random.uniform(2, 18), 1)
            course = round(random.uniform(0, 360), 1)
            name = f'FUS{i + 1:02d}'

            lat, lon = self._sample_near_own_ship(
                self._gps_gen.lat, self._gps_gen.lon, random.uniform(0.5, 10.0)
            )
            bearing, range_nm = _bearing_range(self._gps_gen.lat, self._gps_gen.lon, lat, lon)
            bearing, range_nm = round(bearing, 1), round(max(range_nm, 0.05), 2)

            self._radar_gen.add_or_update_target(
                target_id=tid,
                bearing=bearing,
                range_nm=range_nm,
                speed=speed,
                course=course,
                status='T',
                name=name,
            )
            # Fused vessels are large commercial ships → always Class A with IMO
            fused_shiptype = random.choice([70, 71, 72, 73, 74, 80, 81, 82, 83, 84])
            self._ais_gen.add_or_update_vessel(
                mmsi=mmsi,
                lat=round(lat, 6),
                lon=round(lon, 6),
                sog=speed,
                cog=course,
                heading=int(course) % 360,
                nav_status=0,
                shipname=name,
                shiptype=fused_shiptype,
                callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
                imo=random.randint(1_000_000, 9_999_999),
                ais_class='A',
            )
            self._fusion_entries.append({'type': 'FUSED', 'tid': tid, 'mmsi': mmsi})
            tid += 1

        for i in range(radar_only_count):
            lat, lon = self._sample_near_own_ship(
                self._gps_gen.lat, self._gps_gen.lon, random.uniform(0.5, 10.0)
            )
            bearing, range_nm = _bearing_range(self._gps_gen.lat, self._gps_gen.lon, lat, lon)
            bearing, range_nm = round(bearing, 1), round(max(range_nm, 0.05), 2)
            speed = round(random.uniform(0, 20), 1)
            course = round(random.uniform(0, 360), 1)
            self._radar_gen.add_or_update_target(
                target_id=tid,
                bearing=bearing,
                range_nm=range_nm,
                speed=speed,
                course=course,
                status='T',
                name=f'RDR{tid:02d}',
            )
            self._fusion_entries.append({'type': 'RADAR', 'tid': tid})
            tid += 1

        vietnam_ais = self._f_ais_mode.currentIndex() == 1
        for i in range(ais_only_count):
            if vietnam_ais:
                v = self._random_vietnam_vessel()
                mmsi = self._new_mmsi(mid=v['mid'])
                self._ais_gen.add_or_update_vessel(
                    mmsi=mmsi,
                    lat=v['lat'], lon=v['lon'],
                    sog=v['speed'], cog=v['cog'], heading=v['heading'],
                    nav_status=v['nav_status'],
                    shipname=f'AIS{i + 1:03d}',
                    shiptype=v['ship_type'],
                    callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
                    imo=random.randint(1_000_000, 9_999_999) if v['ais_class'] == 'A' else 0,
                    ais_class=v['ais_class'],
                )
            else:
                mmsi = self._new_mmsi()
                band = random.choices(['near', 'mid', 'far'], weights=[25, 45, 30])[0]
                if band == 'near':
                    range_nm = random.uniform(0.3, 5.0)
                    ao_shiptype = random.choice([30, 36, 37, 52, 90])
                    sog = round(random.uniform(0, 8), 1)
                    nav_status = random.choice([0, 0, 1])
                elif band == 'mid':
                    range_nm = random.uniform(5.0, 20.0)
                    ao_shiptype = random.choice([52, 60, 70, 71, 72, 80, 81, 90])
                    sog = round(random.uniform(4, 15), 1)
                    nav_status = 0
                else:
                    range_nm = random.uniform(20.0, 40.0)
                    ao_shiptype = random.choice([70, 71, 72, 73, 80, 81, 82, 83])
                    sog = round(random.uniform(10, 18), 1)
                    nav_status = 0
                ao_class = 'A' if ao_shiptype in self._CLASS_A_TYPES else 'B'
                lat, lon = self._sample_near_own_ship(
                    self._gps_gen.lat, self._gps_gen.lon, range_nm
                )
                cog = round(random.uniform(0, 360), 1)
                self._ais_gen.add_or_update_vessel(
                    mmsi=mmsi,
                    lat=round(lat, 6), lon=round(lon, 6),
                    sog=sog, cog=cog,
                    heading=int(cog) % 360 if sog > 0.5 else 511,
                    nav_status=nav_status,
                    shipname=f'AIS{i + 1:03d}',
                    shiptype=ao_shiptype,
                    callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
                    imo=random.randint(1_000_000, 9_999_999) if ao_class == 'A' else 0,
                    ais_class=ao_class,
                )
            self._fusion_entries.append({'type': 'AIS', 'mmsi': mmsi})

        self._refresh_radar_list()
        self._refresh_ais_list()
        self._refresh_fusion_list()
        self._log_info(
            f"Fusion scenario: {fused_count} fused, "
            f"{radar_only_count} radar-only, {ais_only_count} AIS-only"
        )

    def _on_fusion_clear(self) -> None:
        self._radar_gen.targets.clear()
        self._ais_gen.vessels.clear()
        self._fusion_entries = []
        self._refresh_radar_list()
        self._refresh_ais_list()
        self._refresh_fusion_list()

    def _refresh_fusion_list(self) -> None:
        self._fusion_list.clear()
        for e in self._fusion_entries:
            if e['type'] == 'FUSED':
                t = self._radar_gen.targets.get(e['tid'])
                v = self._ais_gen.vessels.get(e['mmsi'])
                if t and v:
                    self._fusion_list.addItem(
                        f"[FUSED] Radar={e['tid']:02d} ↔ MMSI={e['mmsi']}  "
                        f"Brg={t['bearing']:5.1f}°  Rng={t['range']:4.2f} NM  "
                        f"Spd={t['speed']:4.1f} kn  Crs={t['course']:5.1f}°"
                    )
                else:
                    missing = []
                    if not t:
                        missing.append(f"Radar={e['tid']:02d}")
                    if not v:
                        missing.append(f"MMSI={e['mmsi']}")
                    self._fusion_list.addItem(
                        f"[FUSED] Radar={e['tid']:02d} ↔ MMSI={e['mmsi']}  "
                        f"[MISSING: {', '.join(missing)}]"
                    )
            elif e['type'] == 'RADAR':
                t = self._radar_gen.targets.get(e['tid'])
                if t:
                    self._fusion_list.addItem(
                        f"[RADAR] ID={e['tid']:02d}  "
                        f"Brg={t['bearing']:5.1f}°  Rng={t['range']:4.2f} NM  "
                        f"Spd={t['speed']:4.1f} kn  Crs={t['course']:5.1f}°"
                    )
                else:
                    self._fusion_list.addItem(f"[RADAR] ID={e['tid']:02d}  [MISSING]")
            else:
                v = self._ais_gen.vessels.get(e['mmsi'])
                if v:
                    self._fusion_list.addItem(
                        f"[AIS  ] MMSI={e['mmsi']}  "
                        f"Lat={v['lat']:.6f}  Lon={v['lon']:.6f}  "
                        f"SOG={v['sog']:4.1f} kn  COG={v['cog']:5.1f}°"
                    )
                else:
                    self._fusion_list.addItem(f"[AIS  ] MMSI={e['mmsi']}  [MISSING]")

    # Cleanup -------------------------------------------------------------

    def closeEvent(self, event) -> None:
        self._on_disconnect()
        event.accept()


# ---------------------------------------------------------------------------

def main() -> None:
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    app.setStyleSheet(_APP_QSS)

    if getattr(sys, 'frozen', False):
        base_dir = sys._MEIPASS
    else:
        base_dir = os.path.dirname(os.path.abspath(__file__))
    icon_path = os.path.join(base_dir, "icon.ico")
    if os.path.exists(icon_path):
        icon = QIcon(icon_path)
        app.setWindowIcon(icon)

    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
