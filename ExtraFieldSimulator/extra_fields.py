"""Cấu hình field EXTRA/DISABLE cho bản tin NMEA — hỗ trợ test tính năng
"Cấu hình bản tin" (DeviceFieldRule) của enc-sensor-gateway.

Xem SPEC_ExtraFieldSimulator.md (thư mục gốc repo) cho đặc tả đầy đủ.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field

import yaml

from utils import nmea_checksum

# sentence_type → device_type (ENC: GPS | RADAR | AIS | COMPASS | NMEA | INS).
# Suy ra tự động từ sentence để người dùng không phải chọn tay generator.
SENTENCE_DEVICE_TYPE = {
    'RMC': 'GPS', 'ZDA': 'GPS', 'HDT': 'GPS', 'HDM': 'GPS', 'HDG': 'GPS',
    'ROT': 'GPS', 'THS': 'GPS', 'RMB': 'GPS', 'VBW': 'GPS', 'GGA': 'GPS',
    'VTG': 'GPS',
    'TTM': 'RADAR', 'OSD': 'RADAR', 'RSD': 'RADAR',
    'VDM': 'AIS', 'VDO': 'AIS',
}

DATA_TYPES = ('STRING', 'NUMBER', 'BOOLEAN')
ACTIONS = ('EXTRA', 'DISABLE')

# sentence có nhiều instance cùng lúc (nhiều target radar / nhiều tàu AIS)
# → mới có khái niệm "target_key" để phân biệt rule mặc định (mọi target)
# với rule ghi đè cho đúng 1 target cụ thể. Các sentence GPS (RMC/GGA/...),
# OSD/RSD, VDO chỉ có đúng 1 instance (tàu mình) nên không cần khái niệm này.
TARGET_SCOPED_SENTENCES = ('TTM', 'VDM')


@dataclass
class ExtraFieldRule:
    sentence_type: str
    field_index: int
    field_name: str = ''
    data_type: str = 'STRING'          # STRING | NUMBER | BOOLEAN
    action: str = 'EXTRA'              # EXTRA | DISABLE
    value_mode: str = 'fixed'          # fixed | random_range | increment | random_bool
    fixed_value: str = ''
    range_min: float = 0.0             # cũng dùng làm "giá trị bắt đầu" khi value_mode=increment
    range_max: float = 0.0
    step: float = 1.0
    target_key: str = ''               # '' = áp dụng mọi target; TTM: Target ID; VDM: MMSI
    _runtime: float | None = field(default=None, repr=False, compare=False)

    @property
    def device_type(self) -> str:
        return SENTENCE_DEVICE_TYPE.get(self.sentence_type, 'NMEA')

    def next_value(self) -> str:
        """Tính giá trị phát cho tick hiện tại (có trạng thái, dùng cho increment)."""
        if self.data_type == 'STRING':
            return self.fixed_value
        if self.data_type == 'BOOLEAN':
            if self.value_mode == 'random_bool':
                return random.choice(('1', '0'))
            return '1' if self.fixed_value == '1' else '0'
        # NUMBER
        if self.value_mode == 'random_range':
            lo, hi = sorted((self.range_min, self.range_max))
            return f"{random.uniform(lo, hi):g}"
        if self.value_mode == 'increment':
            self._runtime = self.range_min if self._runtime is None else self._runtime + self.step
            return f"{self._runtime:g}"
        return self.fixed_value or '0'


def _sentence_type_of(header: str) -> str:
    """'GPRMC' -> 'RMC', 'AIVDM' -> 'VDM' — mọi sentence trong repo đều theo
    quy ước talkerId(2 ký tự) + sentenceId(3 ký tự)."""
    return header[-3:] if len(header) >= 3 else header


def _decode_ais_mmsi(payload: str) -> str | None:
    """Giải mã MMSI (30 bit, sau 6 bit message type + 2 bit repeat) từ phần
    payload 6-bit ASCII của câu AIVDM/AIVDO — đảo ngược đúng bảng mã trong
    generators.py (`_bits_to_payload`/`add_uint`). Mọi loại message AIS (1,
    5, 18, 24...) đều có MMSI ở cùng vị trí này nên dùng chung được."""
    bits: list[int] = []
    for ch in payload:
        v = ord(ch) - 48
        if v > 40:
            v -= 8
        for i in range(5, -1, -1):
            bits.append((v >> i) & 1)
    if len(bits) < 38:
        return None
    mmsi = 0
    for b in bits[8:38]:
        mmsi = (mmsi << 1) | b
    return str(mmsi)


def _extract_target_key(stype: str, fields: list[str]) -> str:
    """'' nếu sentence không có nhiều instance (xem TARGET_SCOPED_SENTENCES)
    hoặc không trích được — dùng để so khớp rule ghi đè theo từng target."""
    if stype == 'TTM':
        try:
            return str(int(fields[0]))
        except (ValueError, IndexError):
            return ''
    if stype == 'VDM':
        try:
            return _decode_ais_mmsi(fields[4]) or ''
        except IndexError:
            return ''
    return ''


def apply_extra_fields(sentence: str, rules: list[ExtraFieldRule]) -> str:
    """Chèn field EXTRA vào 1 câu NMEA đã build xong, tính lại checksum.

    Chỉ áp dụng rule action=='EXTRA' (DISABLE là chỉ thị riêng cho bộ giải
    mã bên ENC, không làm thay đổi dữ liệu simulator gửi đi — xem mục 4 của
    spec). Nếu không có rule nào khớp sentence_type, trả về nguyên văn.

    Với TTM/VDM (nhiều target cùng lúc): rule có target_key rỗng là "mặc
    định" áp dụng cho mọi target; rule có target_key cụ thể (Target ID hoặc
    MMSI) chỉ áp dụng cho đúng target đó và ghi đè rule mặc định ở cùng
    field_index — các target khác vẫn dùng giá trị mặc định.
    """
    if not sentence or sentence[0] not in ('$', '!'):
        return sentence

    prefix = sentence[0]
    body = sentence[1:].rsplit('*', 1)[0]
    parts = body.split(',')
    header = parts[0]
    stype = _sentence_type_of(header)
    fields = parts[1:]

    matching = [r for r in rules if r.action == 'EXTRA' and r.sentence_type == stype]
    if not matching:
        return sentence

    target_key = _extract_target_key(stype, fields) if stype in TARGET_SCOPED_SENTENCES else ''

    # Mặc định trước, rule khớp đúng target ghi đè sau — theo field_index.
    by_index: dict[int, ExtraFieldRule] = {}
    for r in matching:
        if not r.target_key:
            by_index[r.field_index] = r
    if target_key:
        for r in matching:
            if r.target_key == target_key:
                by_index[r.field_index] = r

    if not by_index:
        return sentence

    for field_index in sorted(by_index):
        rule = by_index[field_index]
        value = str(rule.next_value()).replace(',', ' ')
        while len(fields) < field_index:
            fields.append('')
        fields.insert(field_index, value)

    new_body = ','.join([header] + fields)
    return f"{prefix}{new_body}*{nmea_checksum(new_body)}"


# ---------------------------------------------------------------------------
# YAML export / import — schema bắt buộc theo SPEC_ExtraFieldSimulator.md mục 3.
# Các key ngoài schema (value_mode/fixed_value/range_min/range_max/step) được
# thêm kèm để Import khôi phục đúng cấu hình phát trong simulator (round-trip
# nội bộ) — bộ import của ENC chỉ đọc các key nó biết nên bỏ qua phần này an toàn.
#
# `target_key` KHÔNG được đưa vào export: DTO nhận file bên ENC
# (DeviceFieldRuleExportItem) chỉ có đúng 7 field cố định (device_name,
# device_type, sentence_type, field_index, action, field_name, data_type) —
# không có chỗ lưu "áp dụng cho target nào" hay "giá trị bao nhiêu".
# DeviceFieldRule bên ENC cũng chỉ khoá theo (device, sentence_type,
# field_index) — không theo target — nên nhiều rule trong simulator cùng
# (sentence_type, field_index) nhưng khác target_key/giá trị, dưới góc nhìn
# ENC là HỆT NHAU: import sẽ chỉ tạo/update đúng 1 DeviceFieldRule, các dòng
# sau chỉ ghi đè lại dòng đầu — xuất thừa nhiều dòng chỉ gây nhiễu. Giá trị
# khác nhau theo từng target vẫn đúng ở tầng phát thật (apply_extra_fields
# đọc target_key nội bộ) — không liên quan gì tới file YAML này.
# ---------------------------------------------------------------------------

def export_yaml(path: str, rules: list[ExtraFieldRule], device_names: dict[str, str]) -> int:
    """Ghi file YAML, trả về số dòng THỰC SỰ ghi ra (sau khi gộp theo
    (device_type, sentence_type, field_index)) — có thể ít hơn len(rules)."""
    # Gom về đúng 1 dòng đại diện mỗi (device_type, sentence_type,
    # field_index) — ưu tiên rule mặc định (target_key rỗng) làm đại diện
    # nếu có, không thì lấy rule đầu tiên gặp.
    representative: dict[tuple, ExtraFieldRule] = {}
    for r in rules:
        key = (r.device_type, r.sentence_type, r.field_index)
        cur = representative.get(key)
        if cur is None or (cur.target_key and not r.target_key):
            representative[key] = r

    out_rules = []
    for r in representative.values():
        entry = {
            'device_name': device_names.get(r.device_type, r.device_type),
            'device_type': r.device_type,
            'sentence_type': r.sentence_type,
            'field_index': r.field_index,
            'action': r.action,
        }
        if r.action == 'EXTRA':
            entry['field_name'] = r.field_name
            entry['data_type'] = r.data_type
            entry['value_mode'] = r.value_mode
            entry['fixed_value'] = r.fixed_value
            entry['range_min'] = r.range_min
            entry['range_max'] = r.range_max
            entry['step'] = r.step
        out_rules.append(entry)

    with open(path, 'w', encoding='utf-8') as f:
        yaml.safe_dump(
            {'device_field_rules': out_rules}, f,
            allow_unicode=True, sort_keys=False,
        )
    return len(out_rules)


def import_yaml(path: str) -> tuple[list[ExtraFieldRule], dict[str, str]]:
    with open(path, 'r', encoding='utf-8') as f:
        data = yaml.safe_load(f) or {}

    rules: list[ExtraFieldRule] = []
    device_names: dict[str, str] = {}

    for entry in data.get('device_field_rules', []) or []:
        rule = ExtraFieldRule(
            sentence_type=str(entry.get('sentence_type', '')).strip().upper(),
            field_index=int(entry.get('field_index', 0)),
            field_name=entry.get('field_name', '') or '',
            data_type=entry.get('data_type', 'STRING') or 'STRING',
            action=entry.get('action', 'EXTRA') or 'EXTRA',
            value_mode=entry.get('value_mode', 'fixed') or 'fixed',
            fixed_value=str(entry.get('fixed_value', '') or ''),
            range_min=float(entry.get('range_min', 0.0) or 0.0),
            range_max=float(entry.get('range_max', 0.0) or 0.0),
            step=float(entry.get('step', 1.0) or 1.0),
            target_key=str(entry.get('target_key', '') or ''),
        )
        rules.append(rule)
        dtype = entry.get('device_type') or rule.device_type
        dname = entry.get('device_name')
        if dname:
            device_names[dtype] = dname

    return rules, device_names
