"""Fusion Test tab — kịch bản kết hợp thủ công/tự động giữa Radar + AIS."""

from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QComboBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from generators import _bearing_range, _latlon_from_bearing_range
from ui_common import _btn_qss


class FusionTabMixin:
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
