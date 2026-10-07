"""EXTRA Field tab — cấu hình field EXTRA/DISABLE cho ENC DeviceFieldRule."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from extra_fields import (
    SENTENCE_DEVICE_TYPE,
    TARGET_SCOPED_SENTENCES,
    ExtraFieldRule,
    export_yaml,
    import_yaml,
)


class ExtraFieldTabMixin:
    _EF_MODE_MAP = {
        ('STRING', 'Cố định'): 'fixed',
        ('NUMBER', 'Cố định'): 'fixed',
        ('NUMBER', 'Ngẫu nhiên trong khoảng'): 'random_range',
        ('NUMBER', 'Tăng dần mỗi tick'): 'increment',
        ('BOOLEAN', 'Cố định'): 'fixed',
        ('BOOLEAN', 'Ngẫu nhiên'): 'random_bool',
    }

    def _build_extra_field_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)

        # ── Form nhập rule ───────────────────────────────────────────────
        form = QFormLayout()

        self._ef_sentence_type = QComboBox()
        # Không mặc định chọn sẵn sentence nào — tránh gõ Field Index/Giá
        # trị rồi Add mà quên đổi mục này, khiến rule bị gắn nhầm vào mục
        # đầu danh sách một cách âm thầm.
        self._ef_sentence_type.addItem("— Chọn sentence —", None)
        for stype, dtype in SENTENCE_DEVICE_TYPE.items():
            self._ef_sentence_type.addItem(f"{stype}  ({dtype})", stype)

        self._ef_field_index = QSpinBox()
        self._ef_field_index.setRange(0, 100)
        self._ef_field_index.setToolTip(
            "0-based, tính trên mảng field sau khi bỏ header talkerId+sentenceType.\n"
            "Với VDM/VDO chỉ nên dùng 0–5 (phần wrapper) — không chèn được vào payload 6-bit."
        )

        # Chỉ hiện với TTM (nhiều target radar)/VDM (nhiều tàu AIS) — để
        # trống thì rule áp dụng cho MỌI target (mặc định, giữ hành vi cũ);
        # điền Target ID (TTM) hoặc MMSI (VDM) cụ thể thì chỉ ghi đè đúng
        # target đó, các target khác vẫn nhận giá trị mặc định.
        self._ef_target_key_label = QLabel("Target ID / MMSI:")
        self._ef_target_key = QLineEdit()
        self._ef_target_key.setPlaceholderText("Để trống = áp dụng mọi target (mặc định)")
        self._ef_target_key.setToolTip(
            "TTM/TLL: nhập Target ID (vd 1). VDM: nhập MMSI (vd 123456789).\n"
            "Để trống → rule là mặc định, áp dụng cho mọi target/tàu chưa có rule riêng."
        )

        self._ef_field_name = QLineEdit()
        self._ef_field_name.setPlaceholderText("VD: battery_voltage")

        self._ef_action = QComboBox()
        self._ef_action.addItems(["EXTRA", "DISABLE"])

        self._ef_data_type = QComboBox()
        self._ef_data_type.addItems(["STRING", "NUMBER", "BOOLEAN"])

        self._ef_value_mode = QComboBox()

        form.addRow("Sentence Type:", self._ef_sentence_type)
        form.addRow(self._ef_target_key_label, self._ef_target_key)
        form.addRow("Field Index:", self._ef_field_index)
        form.addRow("Field Name:", self._ef_field_name)
        form.addRow("Action:", self._ef_action)
        form.addRow("Data Type:", self._ef_data_type)
        form.addRow("Giá trị phát:", self._ef_value_mode)
        layout.addLayout(form)

        # ── Ô nhập giá trị — hiện/ẩn theo Data Type + Value Mode ─────────
        self._ef_row_fixed_text = QWidget()
        r = QHBoxLayout(self._ef_row_fixed_text)
        r.setContentsMargins(0, 0, 0, 0)
        self._ef_fixed_text = QLineEdit()
        self._ef_fixed_text.setPlaceholderText("Giá trị cố định (text)")
        r.addWidget(QLabel("Giá trị:"))
        r.addWidget(self._ef_fixed_text, stretch=1)
        layout.addWidget(self._ef_row_fixed_text)

        self._ef_row_fixed_number = QWidget()
        r = QHBoxLayout(self._ef_row_fixed_number)
        r.setContentsMargins(0, 0, 0, 0)
        self._ef_fixed_number = QDoubleSpinBox()
        self._ef_fixed_number.setRange(-1_000_000.0, 1_000_000.0)
        self._ef_fixed_number.setDecimals(3)
        r.addWidget(QLabel("Giá trị:"))
        r.addWidget(self._ef_fixed_number, stretch=1)
        layout.addWidget(self._ef_row_fixed_number)

        self._ef_row_range = QWidget()
        r = QHBoxLayout(self._ef_row_range)
        r.setContentsMargins(0, 0, 0, 0)
        self._ef_range_min = QDoubleSpinBox()
        self._ef_range_min.setRange(-1_000_000.0, 1_000_000.0)
        self._ef_range_min.setDecimals(3)
        self._ef_range_max = QDoubleSpinBox()
        self._ef_range_max.setRange(-1_000_000.0, 1_000_000.0)
        self._ef_range_max.setDecimals(3)
        self._ef_range_max.setValue(100.0)
        r.addWidget(QLabel("Từ:"))
        r.addWidget(self._ef_range_min)
        r.addWidget(QLabel("Đến:"))
        r.addWidget(self._ef_range_max)
        layout.addWidget(self._ef_row_range)

        self._ef_row_increment = QWidget()
        r = QHBoxLayout(self._ef_row_increment)
        r.setContentsMargins(0, 0, 0, 0)
        self._ef_inc_start = QDoubleSpinBox()
        self._ef_inc_start.setRange(-1_000_000.0, 1_000_000.0)
        self._ef_inc_start.setDecimals(3)
        self._ef_inc_step = QDoubleSpinBox()
        self._ef_inc_step.setRange(-1_000_000.0, 1_000_000.0)
        self._ef_inc_step.setDecimals(3)
        self._ef_inc_step.setValue(1.0)
        r.addWidget(QLabel("Bắt đầu:"))
        r.addWidget(self._ef_inc_start)
        r.addWidget(QLabel("Bước tăng mỗi tick:"))
        r.addWidget(self._ef_inc_step)
        layout.addWidget(self._ef_row_increment)

        self._ef_row_fixed_bool = QWidget()
        r = QHBoxLayout(self._ef_row_fixed_bool)
        r.setContentsMargins(0, 0, 0, 0)
        self._ef_fixed_bool = QCheckBox("TRUE  (bỏ tick = FALSE)")
        r.addWidget(self._ef_fixed_bool)
        layout.addWidget(self._ef_row_fixed_bool)

        # Add/Update + Remove
        btn_row = QHBoxLayout()
        self._btn_ef_add = QPushButton("Add / Update")
        self._btn_ef_remove = QPushButton("Remove")
        btn_row.addWidget(self._btn_ef_add)
        btn_row.addWidget(self._btn_ef_remove)
        layout.addLayout(btn_row)

        self._ef_list = QListWidget()
        self._ef_list.setMaximumHeight(140)
        layout.addWidget(self._ef_list)

        # Export / Import YAML
        yaml_row = QHBoxLayout()
        self._btn_ef_export = QPushButton("Export YAML")
        self._btn_ef_import = QPushButton("Import YAML")
        yaml_row.addWidget(self._btn_ef_export)
        yaml_row.addWidget(self._btn_ef_import)
        layout.addLayout(yaml_row)

        layout.addStretch()

        # Wiring nội bộ tab (đặt ở đây vì các widget vừa tạo)
        self._ef_sentence_type.currentIndexChanged.connect(self._update_extra_target_key_visibility)
        self._ef_action.currentTextChanged.connect(self._update_extra_value_widgets)
        self._ef_data_type.currentTextChanged.connect(self._on_extra_data_type_changed)
        self._ef_value_mode.currentTextChanged.connect(self._update_extra_value_widgets)
        self._btn_ef_add.clicked.connect(self._on_extra_add)
        self._btn_ef_remove.clicked.connect(self._on_extra_remove)
        self._ef_list.itemClicked.connect(self._on_extra_item_clicked)
        self._btn_ef_export.clicked.connect(self._on_extra_export)
        self._btn_ef_import.clicked.connect(self._on_extra_import)

        self._on_extra_data_type_changed(self._ef_data_type.currentText())
        self._update_extra_target_key_visibility()
        return tab

    def _update_extra_target_key_visibility(self, *_args) -> None:
        stype = self._ef_sentence_type.currentData()
        show = stype in TARGET_SCOPED_SENTENCES
        self._ef_target_key_label.setVisible(show)
        self._ef_target_key.setVisible(show)
        if not show:
            self._ef_target_key.clear()

    def _normalize_target_key(self, stype: str, text: str) -> str:
        text = text.strip()
        if not text:
            return ''
        if stype in ('TTM', 'TLL'):
            try:
                return str(int(text))
            except ValueError:
                return text
        return text  # VDM: MMSI — so sánh dạng chuỗi số, giữ nguyên

    def _on_extra_data_type_changed(self, data_type: str) -> None:
        self._ef_value_mode.blockSignals(True)
        self._ef_value_mode.clear()
        if data_type == 'STRING':
            self._ef_value_mode.addItems(["Cố định"])
        elif data_type == 'NUMBER':
            self._ef_value_mode.addItems(
                ["Cố định", "Ngẫu nhiên trong khoảng", "Tăng dần mỗi tick"]
            )
        else:  # BOOLEAN
            self._ef_value_mode.addItems(["Cố định", "Ngẫu nhiên"])
        self._ef_value_mode.blockSignals(False)
        self._update_extra_value_widgets()

    def _update_extra_value_widgets(self, *_args) -> None:
        is_extra = self._ef_action.currentText() == 'EXTRA'
        self._ef_data_type.setEnabled(is_extra)
        self._ef_value_mode.setEnabled(is_extra)

        data_type = self._ef_data_type.currentText()
        mode = self._ef_value_mode.currentText()

        self._ef_row_fixed_text.setVisible(is_extra and data_type == 'STRING')
        self._ef_row_fixed_number.setVisible(
            is_extra and data_type == 'NUMBER' and mode == 'Cố định'
        )
        self._ef_row_range.setVisible(
            is_extra and data_type == 'NUMBER' and mode == 'Ngẫu nhiên trong khoảng'
        )
        self._ef_row_increment.setVisible(
            is_extra and data_type == 'NUMBER' and mode == 'Tăng dần mỗi tick'
        )
        self._ef_row_fixed_bool.setVisible(
            is_extra and data_type == 'BOOLEAN' and mode == 'Cố định'
        )

    def _on_extra_add(self) -> None:
        stype = self._ef_sentence_type.currentData()
        if not stype:
            QMessageBox.warning(
                self, "Thiếu Sentence Type",
                "Chưa chọn Sentence Type — chọn 1 sentence cụ thể (vd GGA) trước khi Add/Update."
            )
            return
        action = self._ef_action.currentText()
        data_type = self._ef_data_type.currentText()
        mode_label = self._ef_value_mode.currentText()
        value_mode = self._EF_MODE_MAP.get((data_type, mode_label), 'fixed')
        target_key = (
            self._normalize_target_key(stype, self._ef_target_key.text())
            if stype in TARGET_SCOPED_SENTENCES else ''
        )

        rule = ExtraFieldRule(
            sentence_type=stype,
            field_index=self._ef_field_index.value(),
            field_name=self._ef_field_name.text().strip(),
            data_type=data_type,
            action=action,
            value_mode=value_mode,
            target_key=target_key,
        )
        if data_type == 'STRING':
            rule.fixed_value = self._ef_fixed_text.text()
        elif data_type == 'NUMBER':
            if value_mode == 'random_range':
                rule.range_min = self._ef_range_min.value()
                rule.range_max = self._ef_range_max.value()
            elif value_mode == 'increment':
                rule.range_min = self._ef_inc_start.value()
                rule.step = self._ef_inc_step.value()
            else:
                rule.fixed_value = f"{self._ef_fixed_number.value():g}"
        elif data_type == 'BOOLEAN' and value_mode == 'fixed':
            rule.fixed_value = '1' if self._ef_fixed_bool.isChecked() else '0'

        # Upsert theo (sentence_type, field_index, target_key) — target_key
        # rỗng (mặc định) và target_key cụ thể là 2 rule độc lập, không đè
        # nhau, dù cùng sentence_type + field_index.
        self._extra_rules = [
            r for r in self._extra_rules
            if not (
                r.sentence_type == rule.sentence_type
                and r.field_index == rule.field_index
                and r.target_key == rule.target_key
            )
        ]
        self._extra_rules.append(rule)
        self._refresh_extra_list()
        target_desc = f"target={target_key}" if target_key else "mặc định (mọi target)"
        self._log_info(f"Đã lưu rule {action}: {stype} #{rule.field_index} [{target_desc}] {rule.field_name}")

    def _on_extra_remove(self) -> None:
        items = self._ef_list.selectedItems()
        if not items:
            return
        rule = items[0].data(Qt.ItemDataRole.UserRole)
        self._extra_rules = [r for r in self._extra_rules if r is not rule]
        self._refresh_extra_list()

    def _on_extra_item_clicked(self, item: QListWidgetItem) -> None:
        rule: ExtraFieldRule = item.data(Qt.ItemDataRole.UserRole)
        idx = self._ef_sentence_type.findData(rule.sentence_type)
        if idx >= 0:
            self._ef_sentence_type.setCurrentIndex(idx)
        self._update_extra_target_key_visibility()
        self._ef_target_key.setText(rule.target_key)
        self._ef_field_index.setValue(rule.field_index)
        self._ef_field_name.setText(rule.field_name)
        self._ef_action.setCurrentText(rule.action)
        self._ef_data_type.setCurrentText(rule.data_type)

        mode_label = next(
            (label for (dtype, label), mode in self._EF_MODE_MAP.items()
             if dtype == rule.data_type and mode == rule.value_mode),
            None,
        )
        if mode_label:
            self._ef_value_mode.setCurrentText(mode_label)

        if rule.data_type == 'STRING':
            self._ef_fixed_text.setText(rule.fixed_value)
        elif rule.data_type == 'NUMBER':
            if rule.value_mode == 'random_range':
                self._ef_range_min.setValue(rule.range_min)
                self._ef_range_max.setValue(rule.range_max)
            elif rule.value_mode == 'increment':
                self._ef_inc_start.setValue(rule.range_min)
                self._ef_inc_step.setValue(rule.step)
            else:
                try:
                    self._ef_fixed_number.setValue(float(rule.fixed_value or 0))
                except ValueError:
                    pass
        elif rule.data_type == 'BOOLEAN':
            self._ef_fixed_bool.setChecked(rule.fixed_value == '1')

    def _refresh_extra_list(self) -> None:
        self._ef_list.clear()
        for r in sorted(
            self._extra_rules, key=lambda x: (x.device_type, x.sentence_type, x.field_index)
        ):
            target_tag = f"  [target={r.target_key}]" if r.target_key else ""
            if r.action == 'DISABLE':
                text = f"[{r.device_type}] {r.sentence_type} #{r.field_index}{target_tag}  DISABLE"
            else:
                text = (
                    f"[{r.device_type}] {r.sentence_type} #{r.field_index}{target_tag}  "
                    f"{r.field_name}  ({r.data_type}, {r.value_mode})"
                )
            item = QListWidgetItem(text)
            item.setData(Qt.ItemDataRole.UserRole, r)
            self._ef_list.addItem(item)

    def _on_extra_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export YAML", "device_field_rules.yaml", "YAML (*.yaml *.yml)"
        )
        if not path:
            return
        # device_name không còn được ENC đọc (nút Import trên màn Device đã
        # chọn sẵn thiết bị đích) — truyền dict rỗng, export_yaml tự điền
        # device_type ("GPS"/"RADAR"/"AIS") làm placeholder cho có giá trị.
        try:
            n_exported = export_yaml(path, self._extra_rules, {})
            n_total = len(self._extra_rules)
            note = f" (gộp từ {n_total} rule nội bộ theo target)" if n_exported < n_total else ""
            self._log_info(f"Đã export {n_exported} dòng ra {path}{note}")
        except Exception as exc:
            QMessageBox.critical(self, "Export thất bại", str(exc))

    def _on_extra_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Import YAML", "", "YAML (*.yaml *.yml)")
        if not path:
            return
        try:
            rules, _device_names = import_yaml(path)
        except Exception as exc:
            QMessageBox.critical(self, "Import thất bại", str(exc))
            return
        self._extra_rules = rules
        self._refresh_extra_list()
        self._log_info(f"Đã import {len(rules)} rule từ {path}")
