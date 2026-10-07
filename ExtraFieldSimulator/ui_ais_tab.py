"""AIS (VDM) tab — vessel form, GPX route, speed schedule, auto-generate."""

import os

from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
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
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from gpx_parser import parse_gpx
from ui_common import _parse_speed_schedule


class AISTabMixin:
    def _build_ais_tab(self) -> QWidget:
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

        self._a_rot = QDoubleSpinBox()
        self._a_rot.setRange(-720.0, 720.0)
        self._a_rot.setDecimals(1)
        self._a_rot.setSuffix(" °/min")
        self._a_rot.setToolTip(
            "Rate of Turn — chỉ áp dụng cho Class A (Type 1).\n"
            "Positive = quay phải, Negative = quay trái. 0 = không quay."
        )

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
        at_form.addRow("Rate of Turn:", self._a_rot)
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
        return ais_tab

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
            rot=self._a_rot.value(),
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
        self._a_rot.setValue(v.get('rot', 0.0))
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
