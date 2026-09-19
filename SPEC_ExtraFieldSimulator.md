# Spec — Cấu hình field EXTRA cho Maritime Signal Simulator

> Tài liệu yêu cầu tính năng mới cho **Maritime Signal Simulator** (xem
> `ARCHITECTURE_MaritimeSimulator.md` để hiểu kiến trúc hiện tại — `generators.py`,
> `transmitters.py`, luồng Connect→Start→Stop→Disconnect giữ nguyên, không đổi).
> Mục tiêu: simulator có thể tự cấu hình thêm "field EXTRA" vào bản tin NMEA phát ra, và xuất
> cấu hình đó ra file YAML để nạp trực tiếp vào hệ thống ENC.

## 1. Bối cảnh

Hệ thống ENC (`enc-sensor-gateway`) có tính năng **"Cấu hình bản tin"** (`DeviceFieldRule`) cho
phép, với mỗi thiết bị + loại bản tin NMEA, khai báo:
- **EXTRA**: đọc thêm 1 field vượt chuẩn NMEA tại vị trí (`field_index`, 0-based, tính trên mảng
  field sau khi đã bỏ header talkerId+sentenceType), đặt tên (`field_name`) và kiểu dữ liệu
  (`data_type`: `STRING`/`NUMBER`/`BOOLEAN`).
- **DISABLE**: loại field đó (hoặc cả bản tin nếu `field_index = -1`) khỏi dữ liệu giải mã.

Để test tính năng này với dữ liệu giả lập, simulator cần **tự phát ra** field EXTRA đúng vị trí
đã cấu hình, và cho phép **xuất cấu hình đó ra YAML** để nạp thẳng vào màn "Cấu hình bản tin"
bên ENC — tránh phải cấu hình tay 2 lần (1 lần bên simulator để build câu, 1 lần bên ENC để đọc).

## 2. Yêu cầu tính năng mới

### 2.1. Panel "Cấu hình field EXTRA" (UI mới, tự phục vụ)

Thêm 1 tab/panel mới trong `MainWindow`, độc lập theo từng generator đang cấu hình (GPS/Radar/
AIS — xem mục 4 "Cấu hình bản tin" trong `ARCHITECTURE_MaritimeSimulator.md`). Mỗi rule gồm:

| Trường | Kiểu | Ghi chú |
|---|---|---|
| `sentence_type` | dropdown | Danh sách sentence mà generator đang bật hỗ trợ (VD generator GPS: RMC/ZDA/HDT/HDM/HDG/ROT/THS/RMB/VBW/GGA...) |
| `field_index` | số nguyên | 0-based, vị trí chèn field EXTRA (có thể vượt số field chuẩn của sentence — xem 2.2) |
| `field_name` | text | Tên field, tự do (đây chính là key hiển thị bên ENC — không có bước chuẩn hoá) |
| `data_type` | dropdown | `STRING` / `NUMBER` / `BOOLEAN` |
| Giá trị phát | cố định / sinh tự động | Cố định (nhập tay) hoặc sinh: số ngẫu nhiên trong khoảng, số tăng dần mỗi tick, boolean random |

Thao tác: thêm/sửa/xoá rule ngay trên UI (bảng danh sách, giống style panel Radar TTM hiện có
— nút "Generate"/thêm dòng, xoá dòng). Không cần lưu file cấu hình riêng ngoài YAML export/import
ở mục 2.3 (đủ dùng làm nơi lưu/khôi phục).

### 2.2. Chèn field EXTRA vào câu NMEA khi build

Ở bước build câu (`generate_all()` trong từng Generator — `generators.py`): sau khi build xong
mảng field chuẩn của 1 sentence, với mỗi rule EXTRA khớp `sentence_type`:
- Nếu `field_index` nằm trong số field hiện có → **chèn xen** vào đúng vị trí (đẩy các field
  sau lùi lại — không ghi đè field chuẩn).
- Nếu `field_index` vượt quá số field hiện có → **pad thêm field rỗng** cho tới đúng vị trí rồi
  đặt giá trị.
- Tính lại checksum NMEA sau khi đã chèn (dùng `utils.py` sẵn có).

> Lưu ý quan trọng: với bản tin **VDM/VDO (AIS)**, field theo field-index chỉ nằm ở phần
> **wrapper** của giao thức AIVDM (`total fragment, frag number, seq id, channel, payload,
> fill bits` — 6 field cố định theo chuẩn), **không** chèn được vào bên trong payload 6-bit đã
> mã hoá. Nếu cần test EXTRA cho AIS, chỉ nên dùng `field_index` trong khoảng 0–5 (mở rộng thêm
> field sau field 5), không cố chèn vào giữa payload.

### 2.3. Export/Import YAML (trong chính simulator)

- Nút **Export**: xuất toàn bộ rule EXTRA đang cấu hình (mọi generator) ra 1 file YAML theo
  đúng schema ở mục 3. `device_name`/`device_type` lấy từ tên người dùng đặt cho generator/kết
  nối (cần thêm 1 ô nhập "Tên thiết bị" nếu chưa có — dùng để khớp với `Device.name` bên ENC).
- Nút **Import**: nạp lại 1 file YAML đã export trước đó, khôi phục toàn bộ rule vào panel 2.1
  (round-trip nội bộ, không gọi API nào ra ngoài).

## 3. Định dạng YAML (hợp đồng bắt buộc — đã cài đặt sẵn ở phía ENC)

```yaml
device_field_rules:
  - device_name: "AIS Receiver 01"   # PHẢI khớp đúng Device.name đã tạo sẵn bên ENC (Device screen)
    device_type: "AIS"                # PHẢI khớp đúng Device.device_type: GPS | RADAR | AIS | COMPASS | NMEA | INS
    sentence_type: "VDM"              # Loại sentence NMEA (VD: GGA, RMC, TTM, VDM, HDT...)
    field_index: 6                    # 0-based
    action: "EXTRA"                   # EXTRA (đọc thêm field) | DISABLE (loại field/cả bản tin)
    field_name: "custom_temp"         # Bắt buộc khi action=EXTRA — tên hiển thị bên ENC, tuỳ ý đặt
    data_type: "NUMBER"                # Bắt buộc khi action=EXTRA — STRING | NUMBER | BOOLEAN
  - device_name: "GPS Chính"
    device_type: "GPS"
    sentence_type: "GGA"
    field_index: 15
    action: "EXTRA"
    field_name: "battery_voltage"
    data_type: "NUMBER"
```

Quy tắc:
- `device_name` + `device_type` là khoá match chính (không dùng ID nội bộ — ENC tự tra thiết bị
  theo tên+loại khi import, khớp không phân biệt hoa/thường/khoảng trắng thừa).
- Có thể có nhiều dòng cho cùng 1 thiết bị (nhiều sentence, nhiều field).
- `action=DISABLE` cũng hợp lệ (dùng `field_index=-1` để disable cả sentence) nếu cần test,
  nhưng trọng tâm tính năng lần này là `EXTRA`.

## 4. Phía nhận (ENC) — chỉ để hiểu round-trip, KHÔNG thuộc phạm vi bên build simulator

Màn **"Cấu hình bản tin"** trong ENC (`enc-ship-app`, module Device) đã có sẵn nút **Import**
đọc đúng file YAML theo schema mục 3:
- API: `GET /api/v1/device-field-rules/export` (xuất), `POST /api/v1/device-field-rules/import`
  (nạp) — bên `enc-ship-api`.
- Khi import: với mỗi dòng, tra thiết bị theo `device_name`+`device_type` trong danh sách thiết
  bị đã có sẵn trên tàu (phải tạo Device trước ở màn Device — simulator không tự tạo được thiết
  bị mới bên ENC). Không khớp được thiết bị nào → dòng đó bị bỏ qua, báo lại số lượng.
- Dòng khớp được: tạo mới hoặc cập nhật đúng `DeviceFieldRule` (khoá theo
  `sentence_type`+`field_index` trong phạm vi thiết bị đó).
- Sau khi import, rule EXTRA xuất hiện ngay trong danh sách field của đúng sentence/thiết bị đó
  trên màn Cấu hình bản tin — không cần thao tác thêm.

## 5. Tiêu chí nghiệm thu

1. Tạo 1 thiết bị "GPS Test" (device_type=GPS) bên ENC (màn Device) trước.
2. Trong simulator: đặt tên generator/kết nối GPS là "GPS Test", thêm 1 rule EXTRA trên sentence
   `GGA`, field_index bất kỳ (VD 15), field_name `battery_voltage`, data_type `NUMBER`, giá trị
   phát cố định (VD `12.6`).
3. Xuất YAML từ simulator.
4. Vào màn "Cấu hình bản tin" bên ENC, chọn Import, nạp đúng file vừa xuất — xác nhận hệ thống
   báo "tạo mới: 1".
5. Mở đúng thiết bị "GPS Test" + sentence GGA trên màn Cấu hình bản tin — thấy field
   `battery_voltage` xuất hiện trong danh sách "Field đã thêm (EXTRA)".
6. Bật simulator gửi (Connect → Start) tới `enc-sensor-gateway` — quay lại màn Cấu hình bản tin,
   cột "Giá trị đang chạy thật" của field `battery_voltage` phải hiện đúng `12.6`.
7. Lặp lại bước 2–6 với `data_type=NUMBER` phát giá trị tăng dần mỗi tick — xác nhận giá trị
   live cập nhật theo đúng nhịp.
