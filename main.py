"""Maritime Signal Simulator — main entry point and UI."""

import sys

from PyQt6.QtCore import Qt, QDateTime, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QIntValidator
from PyQt6.QtWidgets import (
    QApplication,
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QDoubleSpinBox,
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
    QSlider,
    QSpinBox,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from generators import AISGenerator, GPSGenerator, RadarTTMGenerator, _latlon_from_bearing_range
from transmitters import (
    SerialTransmitter,
    TCPTransmitter,
    TransmitterThread,
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

        # Domain objects (shared with the background thread)
        self._gps_gen = GPSGenerator()
        self._radar_gen = RadarTTMGenerator()
        self._ais_gen = AISGenerator()

        self._transmitter = None
        self._thread: TransmitterThread | None = None
        self._fusion_entries: list = []

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

        # ---- Left panel --------------------------------------------------
        left = QWidget()
        left_layout = QVBoxLayout(left)
        left_layout.setSpacing(8)
        left_layout.addWidget(self._build_connection_panel())
        left_layout.addWidget(self._build_generator_panel())
        left_layout.addStretch()

        # ---- Right panel -------------------------------------------------
        right = QWidget()
        right_layout = QVBoxLayout(right)
        right_layout.setSpacing(8)
        right_layout.addWidget(self._build_target_panel(), stretch=2)
        right_layout.addWidget(self._build_log_panel(), stretch=3)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left)
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
        self._rb_serial = QRadioButton("Serial Port")
        self._rb_tcp.setChecked(True)
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self._rb_tcp)
        self._mode_grp.addButton(self._rb_serial)
        mode_row.addWidget(self._rb_tcp)
        mode_row.addWidget(self._rb_serial)
        mode_row.addStretch()
        layout.addLayout(mode_row)

        # TCP sub-panel
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
        gps_form = QFormLayout(gps_grp)

        self._gps_lat = QDoubleSpinBox()
        self._gps_lat.setRange(-90.0, 90.0)
        self._gps_lat.setDecimals(6)
        self._gps_lat.setValue(10.776900)

        self._gps_lon = QDoubleSpinBox()
        self._gps_lon.setRange(-180.0, 180.0)
        self._gps_lon.setDecimals(6)
        self._gps_lon.setValue(106.700900)

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
        gps_form.addRow("Course:", self._gps_course)
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
        self._r_bearing.setDecimals(1)
        self._r_bearing.setSuffix(" °")

        self._r_range = QDoubleSpinBox()
        self._r_range.setRange(0.01, 100.0)
        self._r_range.setDecimals(2)
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
        self._r_auto_count.setRange(1, 50)
        self._r_auto_count.setValue(5)
        self._r_auto_count.setSuffix(" targets")
        self._btn_r_auto = QPushButton("Generate")
        self._btn_r_clear = QPushButton("Clear All")
        r_auto_row.addWidget(self._r_auto_count)
        r_auto_row.addWidget(self._btn_r_auto)
        r_auto_row.addWidget(self._btn_r_clear)
        rt_layout.addLayout(r_auto_row)

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
        self._a_lat.setValue(10.776900)

        self._a_lon = QDoubleSpinBox()
        self._a_lon.setRange(-180.0, 180.0)
        self._a_lon.setDecimals(6)
        self._a_lon.setValue(106.700900)

        self._a_sog = QDoubleSpinBox()
        self._a_sog.setRange(0.0, 102.2)
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

        # Auto generate row
        a_auto_row = QHBoxLayout()
        a_auto_row.addWidget(QLabel("Auto generate:"))
        self._a_auto_count = QSpinBox()
        self._a_auto_count.setRange(1, 50)
        self._a_auto_count.setValue(5)
        self._a_auto_count.setSuffix(" vessels")
        self._btn_a_auto = QPushButton("Generate")
        self._btn_a_clear = QPushButton("Clear All")
        a_auto_row.addWidget(self._a_auto_count)
        a_auto_row.addWidget(self._btn_a_auto)
        a_auto_row.addWidget(self._btn_a_clear)
        at_layout.addLayout(a_auto_row)

        self._ais_list = QListWidget()
        self._ais_list.setMaximumHeight(90)
        at_layout.addWidget(self._ais_list)
        tabs.addTab(ais_tab, "AIS  (VDM)")

        # ---- Fusion Test tab ---------------------------------------------
        tabs.addTab(self._build_fusion_tab(), "Fusion Test")

        layout.addWidget(tabs)
        return group

    def _build_fusion_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        form = QFormLayout()

        self._f_fused_count = QSpinBox()
        self._f_fused_count.setRange(1, 30)
        self._f_fused_count.setValue(3)
        self._f_fused_count.setSuffix("  cặp")

        self._f_radar_only_count = QSpinBox()
        self._f_radar_only_count.setRange(0, 20)
        self._f_radar_only_count.setValue(2)
        self._f_radar_only_count.setSuffix("  targets")

        self._f_ais_only_count = QSpinBox()
        self._f_ais_only_count.setRange(0, 20)
        self._f_ais_only_count.setValue(2)
        self._f_ais_only_count.setSuffix("  vessels")

        self._f_mid = QComboBox()
        self._f_mid.addItem("Mix (random countries)")
        self._f_mid.addItems(self._MID_TABLE.keys())

        form.addRow("Fused (Radar + AIS):", self._f_fused_count)
        form.addRow("Radar-only:", self._f_radar_only_count)
        form.addRow("AIS-only:", self._f_ais_only_count)
        form.addRow("MMSI Country:", self._f_mid)
        layout.addLayout(form)

        btn_row = QHBoxLayout()
        self._btn_fusion_generate = QPushButton("Generate Fusion Scenario")
        self._btn_fusion_clear = QPushButton("Clear All")
        btn_row.addWidget(self._btn_fusion_generate)
        btn_row.addWidget(self._btn_fusion_clear)
        layout.addLayout(btn_row)

        self._fusion_list = QListWidget()
        layout.addWidget(self._fusion_list)

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

        # Serial refresh
        self._btn_refresh.clicked.connect(self._refresh_ports)

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

        # GPS live-update generator
        self._gps_lat.valueChanged.connect(
            lambda v: setattr(self._gps_gen, 'lat', v)
        )
        self._gps_lon.valueChanged.connect(
            lambda v: setattr(self._gps_gen, 'lon', v)
        )
        self._gps_speed.valueChanged.connect(
            lambda v: setattr(self._gps_gen, 'speed', v)
        )
        self._gps_course.valueChanged.connect(
            lambda v: setattr(self._gps_gen, 'course', v)
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

        # Fusion test
        self._btn_fusion_generate.clicked.connect(self._on_fusion_generate)
        self._btn_fusion_clear.clicked.connect(self._on_fusion_clear)

        # Log
        self._btn_clear.clicked.connect(self._log.clear)

    # ------------------------------------------------------------------
    # Slots
    # ------------------------------------------------------------------

    def _on_mode_changed(self) -> None:
        self._tcp_widget.setVisible(self._rb_tcp.isChecked())
        self._serial_widget.setVisible(self._rb_serial.isChecked())

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
                label = f"TCP  {host}:{port}"
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
            self._log_info(f"Connected to {label}")

        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))

    def _on_disconnect(self) -> None:
        self._on_stop()
        if self._transmitter:
            self._transmitter.close()
            self._transmitter = None
        self._btn_connect.setEnabled(True)
        self._btn_disconnect.setEnabled(False)
        self._btn_start.setEnabled(False)
        self.statusBar().showMessage("Disconnected")
        self._log_info("Disconnected")

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
        elif "RATTM" in msg:
            colour = _COL_RADAR
        elif "AIVDM" in msg:
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
        for _ in range(count):
            tid = 1
            while tid in existing:
                tid += 1
            existing.add(tid)
            self._radar_gen.add_or_update_target(
                target_id=tid,
                bearing=round(random.uniform(0, 360), 1),
                range_nm=round(random.uniform(0.5, 15.0), 2),
                speed=round(random.uniform(0, 20), 1),
                course=round(random.uniform(0, 360), 1),
                status='T',
                name=f'TGT{tid:02d}',
            )
        self._refresh_radar_list()

    def _on_radar_clear(self) -> None:
        self._radar_gen.targets.clear()
        self._refresh_radar_list()

    def _on_ais_auto_generate(self) -> None:
        import random
        count = self._a_auto_count.value()
        ship_types = [30, 36, 52, 60, 70, 80, 90]
        for _ in range(count):
            mmsi = self._new_mmsi(mid=0)   # random country each vessel
            idx = len(self._ais_gen.vessels) + 1
            lat = self._gps_gen.lat + random.uniform(-0.15, 0.15)
            lon = self._gps_gen.lon + random.uniform(-0.15, 0.15)
            self._ais_gen.add_or_update_vessel(
                mmsi=mmsi,
                lat=round(lat, 6),
                lon=round(lon, 6),
                sog=round(random.uniform(0, 18), 1),
                cog=round(random.uniform(0, 360), 1),
                heading=random.randint(0, 359),
                nav_status=0,
                shipname=f'VESSEL {idx:02d}',
                shiptype=random.choice(ship_types),
                callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
            )
        self._refresh_ais_list()

    def _on_ais_clear(self) -> None:
        self._ais_gen.vessels.clear()
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
        )
        self._refresh_ais_list()
        self._refresh_fusion_list()

    def _on_ais_remove(self) -> None:
        items = self._ais_list.selectedItems()
        if items:
            mmsi = int(items[0].text().split()[0])
            self._ais_gen.remove_vessel(mmsi)
            self._refresh_ais_list()
            self._refresh_fusion_list()

    def _on_ais_item_clicked(self, item) -> None:
        mmsi = int(item.text().split()[0])
        v = self._ais_gen.vessels.get(mmsi)
        if not v:
            return
        self._a_last_loaded_mmsi = mmsi   # track để detect đổi MMSI
        self._a_mmsi.setText(str(mmsi))
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

    def _refresh_ais_list(self) -> None:
        self._ais_list.clear()
        for mmsi, v in self._ais_gen.vessels.items():
            name = v.get('shipname', '') or '—'
            self._ais_list.addItem(
                f"{mmsi}  [{name}]  "
                f"Lat={v['lat']:10.6f}  Lon={v['lon']:11.6f}  "
                f"SOG={v['sog']:5.1f} kn  COG={v['cog']:6.1f}°"
            )

    # GPS live display ----------------------------------------------------

    def _update_gps_display(self) -> None:
        """Refresh GPS spinboxes and AIS list from generators without triggering signals."""
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

    def _on_fusion_generate(self) -> None:
        import random
        self._radar_gen.targets.clear()
        self._ais_gen.vessels.clear()
        self._fusion_entries = []

        fused_count = self._f_fused_count.value()
        radar_only_count = self._f_radar_only_count.value()
        ais_only_count = self._f_ais_only_count.value()

        ship_types = [30, 36, 52, 60, 70, 80, 90]
        tid = 1

        for i in range(fused_count):
            mmsi = self._new_mmsi()
            bearing = round(random.uniform(0, 360), 1)
            range_nm = round(random.uniform(0.5, 10.0), 2)
            speed = round(random.uniform(2, 18), 1)
            course = round(random.uniform(0, 360), 1)
            name = f'FUS{i + 1:02d}'

            self._radar_gen.add_or_update_target(
                target_id=tid,
                bearing=bearing,
                range_nm=range_nm,
                speed=speed,
                course=course,
                status='T',
                name=name,
            )
            lat, lon = _latlon_from_bearing_range(
                self._gps_gen.lat, self._gps_gen.lon, bearing, range_nm
            )
            self._ais_gen.add_or_update_vessel(
                mmsi=mmsi,
                lat=round(lat, 6),
                lon=round(lon, 6),
                sog=speed,
                cog=course,
                heading=int(course) % 360,
                nav_status=0,
                shipname=name,
                shiptype=random.choice(ship_types),
                callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
            )
            self._fusion_entries.append({'type': 'FUSED', 'tid': tid, 'mmsi': mmsi})
            tid += 1

        for i in range(radar_only_count):
            bearing = round(random.uniform(0, 360), 1)
            range_nm = round(random.uniform(0.5, 10.0), 2)
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

        for i in range(ais_only_count):
            mmsi = self._new_mmsi()
            lat = round(self._gps_gen.lat + random.uniform(-0.2, 0.2), 6)
            lon = round(self._gps_gen.lon + random.uniform(-0.2, 0.2), 6)
            sog = round(random.uniform(0, 18), 1)
            cog = round(random.uniform(0, 360), 1)
            self._ais_gen.add_or_update_vessel(
                mmsi=mmsi,
                lat=lat,
                lon=lon,
                sog=sog,
                cog=cog,
                heading=511,
                nav_status=0,
                shipname=f'AIS{i + 1:02d}',
                shiptype=random.choice(ship_types),
                callsign=f'{mmsi // 1_000_000:03d}{mmsi % 1_000:03d}',
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
    window = MainWindow()
    window.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
