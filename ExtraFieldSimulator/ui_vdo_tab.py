"""VDO (Own Ship) tab — cấu hình bản tin AIVDO (own-ship AIS transponder)."""

from PyQt6.QtGui import QIntValidator
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDateTimeEdit,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)


class VDOTabMixin:
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

    def _on_vdo_eta_changed(self) -> None:
        if self._vdo_eta_enabled.isChecked():
            dt = self._vdo_eta.dateTime()
            eta = (dt.date().month(), dt.date().day(),
                   dt.time().hour(), dt.time().minute())
        else:
            eta = (0, 0, 24, 60)
        self._gps_gen.vdo_eta = eta
