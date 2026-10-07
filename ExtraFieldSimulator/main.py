"""Extra Field Simulator — Maritime Signal Simulator + cấu hình field EXTRA
để test tính năng "Cấu hình bản tin" (DeviceFieldRule) của enc-sensor-gateway.

Fork từ main.py gốc (tái dùng generators.py/transmitters.py/utils.py/
gpx_parser.py ở thư mục cha) — xem SPEC_ExtraFieldSimulator.md và
ARCHITECTURE_MaritimeSimulator.md ở gốc repo.

`MainWindow` được ghép từ nhiều mixin theo tab (xem ui_connection.py,
ui_gps_tab.py, ui_radar_tab.py, ui_ais_tab.py, ui_vdo_tab.py,
ui_fusion_tab.py, ui_extra_field_tab.py, vietnam_zones.py) — file này chỉ
còn giữ phần điều phối chung: khởi tạo, layout tổng, wiring signal, vòng
đời Start/Stop, và log console.
"""

import collections
import os
import sys

# Cho phép import generators.py/transmitters.py/utils.py/gpx_parser.py/
# ssh_settings.py/ssh_tunnel.py từ thư mục cha (đúng pattern NMEACollector/
# NMEAReplay đang dùng).
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PyQt6.QtCore import Qt, QDateTime, QTimer, pyqtSlot
from PyQt6.QtGui import QFont, QIcon
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSplitter,
    QStatusBar,
    QTabWidget,
    QTextEdit,
    QVBoxLayout,
    QWidget,
)

from generators import AISGenerator, GPSGenerator, RadarTTMGenerator
from utils import nmea_checksum
from ssh_tunnel import SSHTunnel
from transmitters import TCPServerTransmitter, TransmitterThread
from extra_fields import ExtraFieldRule, apply_extra_fields

from ui_common import (
    _APP_QSS,
    _COL_AIS,
    _COL_ERROR,
    _COL_GPS,
    _COL_INFO,
    _COL_RADAR,
    _LOG_BG,
)
from ui_connection import ConnectionPanelMixin
from ui_gps_tab import GPSPanelMixin
from ui_radar_tab import RadarTabMixin
from ui_ais_tab import AISTabMixin
from ui_vdo_tab import VDOTabMixin
from ui_fusion_tab import FusionTabMixin
from ui_extra_field_tab import ExtraFieldTabMixin
from vietnam_zones import ZoneHelperMixin


def _corrupt_checksum(sentence: str) -> str:
    """Thay '*hh' bằng checksum chắc chắn SAI (XOR đúng ^ 0x5A, luôn khác giá trị đúng) — để test
    bộ nhận loại bỏ bản tin lỗi đường truyền. Câu không có '*' thì thêm checksum sai vào cuối."""
    star = sentence.rfind('*')
    if star < 0:
        body, tail = sentence[1:], ''
    else:
        body, tail = sentence[1:star], sentence[star + 3:]
    wrong = int(nmea_checksum(body), 16) ^ 0x5A
    return f"{sentence[0]}{body}*{wrong:02X}{tail}"


class _ExtraFieldSender:
    """Bọc transmitter thật, chèn field EXTRA vào từng câu trước khi gửi —
    để TransmitterThread (transmitters.py, giữ nguyên không sửa) không cần
    biết gì về cấu hình EXTRA field.

    TransmitterThread.run() emit tín hiệu message_sent bằng chuỗi GỐC (trước
    khi qua send()), nên NMEA Log Console sẽ hiện sai nếu chỉ đọc thẳng
    tín hiệu đó — self.sent_log ghi lại đúng chuỗi ĐÃ chèn field, theo đúng
    thứ tự gửi (deque, 1 send() = 1 append), để _on_message_sent lấy ra
    đúng chuỗi thật sự đã đi trên dây thay vì chuỗi gốc."""

    def __init__(self, inner, get_rules, is_bad_checksum=lambda: False) -> None:
        self._inner = inner
        self._get_rules = get_rules
        # Đọc lại mỗi câu (không chốt lúc Start) → bật/tắt ô "sai checksum" có hiệu lực ngay khi đang phát.
        self._is_bad_checksum = is_bad_checksum
        # (chuỗi đã gửi, có bị làm sai checksum không)
        self.sent_log: collections.deque = collections.deque()

    def send(self, data: str) -> None:
        out = apply_extra_fields(data, self._get_rules())
        bad = bool(self._is_bad_checksum())
        if bad:
            out = _corrupt_checksum(out)
        self.sent_log.append((out, bad))
        self._inner.send(out)

    def close(self) -> None:
        self._inner.close()


class MainWindow(
    ConnectionPanelMixin,
    GPSPanelMixin,
    RadarTabMixin,
    AISTabMixin,
    VDOTabMixin,
    FusionTabMixin,
    ExtraFieldTabMixin,
    ZoneHelperMixin,
    QMainWindow,
):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Extra Field Simulator")
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
        self._extra_sender: _ExtraFieldSender | None = None
        self._fusion_entries: list = []
        self._extra_rules: list[ExtraFieldRule] = []

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

    # --- Target control panel (orchestrator — mỗi tab tự xây trong mixin riêng) ---

    def _build_target_panel(self) -> QGroupBox:
        group = QGroupBox("Target Control")
        layout = QVBoxLayout(group)
        tabs = QTabWidget()

        tabs.addTab(self._build_radar_tab(), "Radar  (TTM)")
        tabs.addTab(self._build_ais_tab(), "AIS  (VDM)")
        tabs.addTab(self._build_vdo_tab(), "VDO  (Own Ship)")
        tabs.addTab(self._build_fusion_tab(), "Fusion Test")
        tabs.addTab(self._build_extra_field_tab(), "EXTRA Field")

        layout.addWidget(tabs)
        return group

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
        self._rb_udp.toggled.connect(self._on_mode_changed)
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
        self._chk_vbw.toggled.connect(lambda v: setattr(self._gps_gen, 'send_vbw', v))
        self._chk_gga.toggled.connect(lambda v: setattr(self._gps_gen, 'send_gga', v))
        self._chk_vtg.toggled.connect(lambda v: setattr(self._gps_gen, 'send_vtg', v))
        self._chk_gll.toggled.connect(lambda v: setattr(self._gps_gen, 'send_gll', v))
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

        # TLL / OSD / RSD
        self._chk_tll.toggled.connect(lambda v: setattr(self._radar_gen, 'send_tll', v))
        self._chk_osd.toggled.connect(self._osd_grp.setVisible)
        self._chk_osd.toggled.connect(lambda v: setattr(self._radar_gen, 'send_osd', v))
        self._osd_set.valueChanged.connect(lambda v: setattr(self._radar_gen, 'osd_set', v))
        self._osd_drift.valueChanged.connect(lambda v: setattr(self._radar_gen, 'osd_drift', v))
        # Nguồn hướng đi/tốc độ: dùng mã chuẩn NMEA (P/B/W/R/M) — generator mặc định 'T'/'N'
        # (giữ cho MaritimeSimulator) không có trong chuẩn, gateway sẽ hiển thị "—".
        self._radar_gen.osd_course_ref = self._osd_course_ref.currentText()[0]
        self._radar_gen.osd_speed_ref = self._osd_speed_ref.currentText()[0]
        self._osd_course_ref.currentTextChanged.connect(
            lambda v: setattr(self._radar_gen, 'osd_course_ref', v[0])
        )
        self._osd_speed_ref.currentTextChanged.connect(
            lambda v: setattr(self._radar_gen, 'osd_speed_ref', v[0])
        )
        self._chk_rsd.toggled.connect(self._rsd_grp.setVisible)
        self._chk_rsd.toggled.connect(lambda v: setattr(self._radar_gen, 'send_rsd', v))
        self._radar_gen.rsd_cursor_decimals = 3
        self._rsd_cursor_range.valueChanged.connect(
            lambda v: setattr(self._radar_gen, 'rsd_cursor_range', v)
        )
        self._rsd_cursor_bearing.valueChanged.connect(
            lambda v: setattr(self._radar_gen, 'rsd_cursor_bearing', v)
        )
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

    # Transmit control ----------------------------------------------------

    def _on_start(self) -> None:
        if not self._transmitter:
            return
        interval = self._slider_interval.value()
        gps = self._gps_gen if self._chk_gps.isChecked() else None
        radar = self._radar_gen if self._chk_radar.isChecked() else None
        ais = self._ais_gen if self._chk_ais.isChecked() else None

        self._msg_count = 0
        self._extra_sender = _ExtraFieldSender(
            self._transmitter,
            lambda: self._extra_rules,
            lambda: self._chk_bad_checksum.isChecked(),
        )
        self._thread = TransmitterThread(self._extra_sender, gps, radar, ais, interval)
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
        # `msg` là chuỗi GỐC trước khi qua field EXTRA (TransmitterThread ở
        # transmitters.py emit thẳng biến cục bộ, không biết _ExtraFieldSender
        # đã biến đổi gì) — lấy đúng chuỗi ĐÃ gửi từ hàng đợi để log không bị
        # sai lệch với dữ liệu thật sự đi trên dây.
        bad = False
        if self._extra_sender and self._extra_sender.sent_log:
            msg, bad = self._extra_sender.sent_log.popleft()
        ts = QDateTime.currentDateTime().toString("HH:mm:ss.zzz")
        if "GPRMC" in msg:
            colour = _COL_GPS
        elif "RATTM" in msg or "RATLL" in msg or "RAOSD" in msg or "RARSD" in msg:
            colour = _COL_RADAR
        elif "AIVDM" in msg or "AIVDO" in msg:
            colour = _COL_AIS
        else:
            colour = "#ffffff"
        bad_tag = f'<span style="color:{_COL_ERROR};">[SAI CHECKSUM]</span>&nbsp;' if bad else ''
        self._log.append(
            f'<span style="color:{_COL_INFO};">[{ts}]</span>'
            f'&nbsp;{bad_tag}<span style="color:{colour};">{msg}</span>'
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
