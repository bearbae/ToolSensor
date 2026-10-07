"""Radar (TTM) tab — target list, bearing/range ↔ lat/lon conversion,
TLL/OSD/RSD settings, auto-generate."""

from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QFrame,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from generators import _bearing_range, _latlon_from_bearing_range


class RadarTabMixin:
    def _build_radar_tab(self) -> QWidget:
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

        self._radar_list = QListWidget()
        self._radar_list.setMinimumHeight(90)
        self._radar_list.setMaximumHeight(130)
        rt_layout.addWidget(self._radar_list)

        rt_layout.addWidget(self._build_radar_extra_sentences())
        rt_layout.addStretch()

        # Bọc trong vùng cuộn: tích OSD/RSD mở thêm khung nhập → nội dung dài ra và cuộn
        # được, thay vì bị ép co lại khiến các ô nhập dính sát nhau.
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.Shape.NoFrame)
        scroll.setWidget(radar_tab)
        return scroll

    # ------------------------------------------------------------------
    # TLL / OSD / RSD — bản tin radar bổ sung ngoài TTM
    # ------------------------------------------------------------------

    @staticmethod
    def _spin(lo: float, hi: float, decimals: int, suffix: str, value: float = 0.0,
              tooltip: str = '') -> QDoubleSpinBox:
        sp = QDoubleSpinBox()
        sp.setRange(lo, hi)
        sp.setDecimals(decimals)
        sp.setSuffix(suffix)
        sp.setValue(value)
        sp.setMinimumHeight(26)
        sp.setMinimumWidth(110)
        if tooltip:
            sp.setToolTip(tooltip)
        return sp

    @staticmethod
    def _grid_group(title: str) -> tuple[QGroupBox, QGridLayout]:
        """GroupBox + lưới 4 cột (nhãn | ô | nhãn | ô) có khoảng cách rõ ràng."""
        grp = QGroupBox(title)
        grp.setStyleSheet(
            "QGroupBox { font-weight: bold; margin-top: 10px; padding-top: 6px; }"
            "QGroupBox::title { subcontrol-origin: margin; left: 8px; padding: 0 4px; }"
        )
        grid = QGridLayout(grp)
        grid.setContentsMargins(12, 14, 12, 12)
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(10)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        return grp, grid

    @staticmethod
    def _add_pair(grid: QGridLayout, row: int, col: int, label: str, widget: QWidget) -> None:
        lbl = QLabel(label)
        lbl.setStyleSheet("font-weight: normal;")
        grid.addWidget(lbl, row, col * 2)
        grid.addWidget(widget, row, col * 2 + 1)

    def _build_radar_extra_sentences(self) -> QWidget:
        box = QGroupBox("Bản tin radar bổ sung")
        box.setStyleSheet("QGroupBox { color: #0d6efd; font-weight: bold; }")
        vl = QVBoxLayout(box)
        vl.setContentsMargins(10, 12, 10, 10)
        vl.setSpacing(8)

        chk_row = QHBoxLayout()
        chk_row.setSpacing(18)
        self._chk_tll = QCheckBox("TLL  (Target Lat/Lon)")
        self._chk_tll.setToolTip("Mỗi target phát thêm 1 câu RATLL (vị trí lat/lon tuyệt đối) đi kèm RATTM")
        self._chk_osd = QCheckBox("OSD  (Own Ship Data)")
        self._chk_rsd = QCheckBox("RSD  (Radar System Data)")
        for chk in (self._chk_tll, self._chk_osd, self._chk_rsd):
            chk.setStyleSheet("color: black; font-weight: normal;")
            chk_row.addWidget(chk)
        chk_row.addStretch()
        vl.addLayout(chk_row)

        # ── OSD ──────────────────────────────────────────────────────────
        self._osd_grp, osd_grid = self._grid_group("OSD Settings")
        self._osd_grp.setVisible(False)

        ref_items = ["P  (GPS)", "B  (Theo đáy)", "W  (Theo nước)", "R  (Bám mục tiêu radar)", "M  (Nhập tay)"]
        self._osd_course_ref = QComboBox()
        self._osd_course_ref.addItems(ref_items)
        self._osd_course_ref.setMinimumHeight(26)
        self._osd_speed_ref = QComboBox()
        self._osd_speed_ref.addItems(ref_items)
        self._osd_speed_ref.setMinimumHeight(26)
        self._osd_set = self._spin(0.0, 360.0, 1, " °", tooltip="Hướng dòng chảy (set), độ thật")
        self._osd_drift = self._spin(0.0, 10.0, 1, " kn", tooltip="Tốc độ dòng chảy (drift), knots")

        self._add_pair(osd_grid, 0, 0, "Nguồn hướng đi:", self._osd_course_ref)
        self._add_pair(osd_grid, 0, 1, "Nguồn tốc độ:", self._osd_speed_ref)
        self._add_pair(osd_grid, 1, 0, "Set:", self._osd_set)
        self._add_pair(osd_grid, 1, 1, "Drift:", self._osd_drift)
        lbl_osd_note = QLabel("Heading / Course / Speed — tự lấy từ GPS")
        lbl_osd_note.setStyleSheet("color:#90a4ae; font-style:italic; font-weight: normal;")
        osd_grid.addWidget(lbl_osd_note, 2, 0, 1, 4)
        vl.addWidget(self._osd_grp)

        # ── RSD ──────────────────────────────────────────────────────────
        self._rsd_grp, rsd_grid = self._grid_group("RSD Settings")
        self._rsd_grp.setVisible(False)

        self._rsd_vrm1 = self._spin(0.0, 200.0, 1, " NM", 1.0, "VRM 1 — vòng đo cự ly")
        self._rsd_ebl1 = self._spin(0.0, 360.0, 1, " °", 0.0, "EBL 1 — đường đo phương vị")
        self._rsd_vrm2 = self._spin(0.0, 200.0, 1, " NM", 3.0, "VRM 2 — vòng đo cự ly")
        self._rsd_ebl2 = self._spin(0.0, 360.0, 1, " °", 90.0, "EBL 2 — đường đo phương vị")
        self._rsd_cursor_range = self._spin(
            0.0, 200.0, 3, " NM", 0.0, "Khoảng cách từ tàu tới con trỏ trên màn radar (RSD field 8)")
        self._rsd_cursor_bearing = self._spin(
            0.0, 360.0, 1, " °", 0.0, "Phương vị từ tàu tới con trỏ trên màn radar (RSD field 9)")
        self._rsd_range = self._spin(0.1, 200.0, 1, " NM", 6.0, "Tầm quét đang chọn (range scale)")
        self._rsd_rotation = QComboBox()
        self._rsd_rotation.addItems(["N  (North-up)", "H  (Head-up)", "C  (Course-up)"])
        self._rsd_rotation.setMinimumHeight(26)

        self._add_pair(rsd_grid, 0, 0, "VRM 1:", self._rsd_vrm1)
        self._add_pair(rsd_grid, 0, 1, "EBL 1:", self._rsd_ebl1)
        self._add_pair(rsd_grid, 1, 0, "VRM 2:", self._rsd_vrm2)
        self._add_pair(rsd_grid, 1, 1, "EBL 2:", self._rsd_ebl2)
        self._add_pair(rsd_grid, 2, 0, "Con trỏ – khoảng cách:", self._rsd_cursor_range)
        self._add_pair(rsd_grid, 2, 1, "Con trỏ – phương vị:", self._rsd_cursor_bearing)
        self._add_pair(rsd_grid, 3, 0, "Range Scale:", self._rsd_range)
        self._add_pair(rsd_grid, 3, 1, "Display Rotation:", self._rsd_rotation)
        vl.addWidget(self._rsd_grp)

        return box

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

    def _refresh_radar_list(self) -> None:
        self._radar_list.clear()
        for tid, t in self._radar_gen.targets.items():
            self._radar_list.addItem(
                f"{tid:2d}: Brg={t['bearing']:6.1f}°  "
                f"Rng={t['range']:6.2f} NM  "
                f"Spd={t['speed']:5.1f} kn  "
                f"Crs={t['course']:6.1f}°  [{t['status']}]"
            )
