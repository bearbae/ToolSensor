"""Generator panel — message-type toggles, interval, GPS Settings (RMC/ZDA/
HDT/HDM/HDG/ROT/THS/RMB/VBW/GGA/VTG), RMB waypoint, Start/Stop buttons."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QVBoxLayout,
)

from ui_common import _btn_qss


class GPSPanelMixin:
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

        # Bắn bản tin sai checksum — áp dụng cho MỌI câu (GPS/Radar/AIS), bật/tắt được khi đang phát.
        self._chk_bad_checksum = QCheckBox("Bắn bản tin sai checksum")
        self._chk_bad_checksum.setStyleSheet("color: #dc3545; font-weight: bold;")
        self._chk_bad_checksum.setToolTip(
            "Tích: mọi câu gửi đi đều có checksum (*hh) sai — không gửi câu hợp lệ nào.\n"
            "Dùng để kiểm tra bên nhận kiểm checksum và loại bỏ bản tin lỗi đường truyền.\n"
            "Bỏ tích: gửi bình thường."
        )
        layout.addWidget(self._chk_bad_checksum)

        # GPS settings
        gps_grp = QGroupBox("GPS Settings")
        gps_layout = QVBoxLayout(gps_grp)

        # --- Sentence type checkboxes ---
        sent_row1 = QHBoxLayout()
        self._chk_rmc = QCheckBox("RMC")
        self._chk_zda = QCheckBox("ZDA")
        self._chk_hdt = QCheckBox("HDT")
        self._chk_hdm = QCheckBox("HDM")
        self._chk_gll = QCheckBox("GLL")
        self._chk_rmc.setChecked(True)
        self._chk_zda.setChecked(True)
        for w in (self._chk_rmc, self._chk_zda, self._chk_gll, self._chk_hdt, self._chk_hdm):
            sent_row1.addWidget(w)
        sent_row1.addStretch()

        sent_row2 = QHBoxLayout()
        self._chk_hdg = QCheckBox("HDG")
        self._chk_rot = QCheckBox("ROT")
        self._chk_ths = QCheckBox("THS")
        self._chk_rmb = QCheckBox("RMB")
        self._chk_vbw = QCheckBox("VBW")
        self._chk_gga = QCheckBox("GGA")
        self._chk_vtg = QCheckBox("VTG")
        for w in (self._chk_hdg, self._chk_rot, self._chk_ths, self._chk_rmb,
                  self._chk_vbw, self._chk_gga, self._chk_vtg):
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
