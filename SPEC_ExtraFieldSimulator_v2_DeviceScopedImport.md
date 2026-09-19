# Spec bổ sung — Import theo thiết bị chọn tay (không cần khớp tên)

> Phụ lục cho `SPEC_ExtraFieldSimulator.md` (đọc file đó trước). Ghi lại thay đổi vừa làm ở phía
> ENC (`enc-ship-api`/`enc-ship-app`, 2026-09-15) và phần **nên** sửa lại ở simulator cho khớp —
> không có thay đổi bắt buộc nào ở simulator để không bị hỏng, phần dưới đây thuần là dọn UX.

## 1. Vấn đề của cách cũ

Cách import cũ (mục 3-4 của spec gốc) khớp thiết bị bằng `device_name + device_type` ghi trong
file — người dùng simulator phải gõ đúng tuyệt đối tên thiết bị đã tạo sẵn bên ENC. Gõ sai (rất dễ
xảy ra, không có validate) khiến cả dòng bị **âm thầm** bỏ qua bên ENC (`skipped_no_device`),
không có cảnh báo rõ ràng ngay lúc import.

Trong `extra_fields.py` hiện tại, khi người dùng simulator không điền "Tên thiết bị", giá trị
export ra rơi về `device_names.get(r.device_type, r.device_type)` — tức là dùng luôn
`device_type` (`"GPS"`, `"AIS"`...) làm tên, gần như chắc chắn KHÔNG khớp tên thiết bị thật nào
bên ENC → import theo cách cũ sẽ luôn bị bỏ qua nếu người dùng quên điền tên.

## 2. Cách mới ở phía ENC — không cần tên thiết bị nữa

Thêm 1 nút import **mới** ngay trên từng thiết bị ở màn Device (danh sách thiết bị) bên ENC. Luồng
dùng:

1. Xuất file YAML từ simulator như bình thường (không đổi gì ở bước này).
2. Bên ENC, mở màn **Device**, bấm icon import (📥) trên đúng card của thiết bị muốn nạp cấu hình
   vào.
3. Chọn file YAML vừa xuất — ENC áp **toàn bộ** rule hợp lệ trong file cho đúng thiết bị đó, **bỏ
   qua hoàn toàn** `device_name`/`device_type` ghi trong file để xác định thiết bị (thiết bị đích
   đã cố định là thiết bị vừa bấm).
4. ENC vẫn tự chặn: `sentence_type` trong file phải tương thích với `device_type` thật của thiết
   bị đích (vd rule `VDM`/`VDO` chỉ nạp được vào thiết bị AIS, rule `TTM` chỉ nạp được vào RADAR —
   nạp sai loại bị đếm riêng, không tạo/update, không báo lỗi dừng cả file).

File thay đổi phía ENC (tham khảo, không cần đọc để sửa simulator):
`enc-ship-api/.../dto/response/DeviceFieldRuleConfigExportDTO.java`,
`enc-ship-api/.../service/DeviceFieldRuleTransferService.java`,
`enc-ship-app/src/views/Device/components/DeviceFieldRuleImportModal.tsx`.

## 3. Ảnh hưởng tới schema YAML — KHÔNG đổi

Schema file export (mục 3 spec gốc) **giữ nguyên 100%**. `device_name`/`device_type` vẫn có thể
có mặt trong file như cũ — không gây lỗi gì, chỉ đơn giản là **không còn được đọc** khi import qua
nút mới ở màn Device. Cách import cũ (khớp theo tên, gọi thẳng `POST /api/v1/device-field-rules/import`
không kèm `device_id`) vẫn hoạt động y hệt trước — dùng khi cần nạp 1 file cho nhiều thiết bị khác
nhau cùng lúc (file có nhiều `device_name` khác nhau).

→ **Simulator không bắt buộc phải sửa gì để không bị hỏng.**

## 4. Đề xuất dọn UX ở simulator (không bắt buộc, nên làm)

Vì cách import mới không cần tên thiết bị đúng nữa, phần "Tên thiết bị" ở simulator
(`main.py`, panel liên quan tới `extra_fields.py`) từ **bắt buộc phải đúng** trở thành **chỉ còn
cần thiết nếu người dùng chủ động chọn dùng cách import cũ (khớp theo tên)**. Gợi ý:

1. **Đổi label/placeholder ô "Tên thiết bị"** — từ ngụ ý bắt buộc sang rõ ràng optional, vd:
   `"Tên thiết bị (tuỳ chọn — chỉ cần nếu Import bên ENC theo tên; có thể bỏ trống nếu dùng nút
   Import trên màn Device)"`.
2. **`extra_fields.export_yaml`** — không cần đổi code (fallback `device_names.get(r.device_type,
   r.device_type)` đã an toàn, không crash), chỉ cần cập nhật docstring/comment ở đầu hàm để phản
   ánh đúng: giá trị `device_name` giờ chỉ là "gợi ý", không còn là khoá bắt buộc phải khớp.
3. Nếu `main.py` có bất kỳ validate/cảnh báo nào ép người dùng phải điền tên thiết bị trước khi
   cho xuất file — nới lỏng thành cảnh báo mềm (tooltip/hint), không chặn export nữa.
4. Không cần đổi gì ở `apply_extra_fields`/`import_yaml` (round-trip nội bộ của simulator, không
   liên quan tới cách ENC đọc file).

## 5. Tiêu chí nghiệm thu bổ sung (cho cách import mới)

1. Tạo 1 thiết bị `device_type=AIS` bên ENC (màn Device) — **không cần đặt tên theo quy ước gì
   đặc biệt**.
2. Trong simulator: cấu hình rule EXTRA cho sentence `VDM`, **để trống ô "Tên thiết bị"** (hoặc
   điền tên bất kỳ, không cần khớp).
3. Xuất YAML.
4. Bên ENC, màn Device → bấm icon import trên đúng thiết bị AIS vừa tạo → chọn file → xác nhận kết
   quả báo `tạo mới: 1`, `bỏ qua (sai loại bản tin): 0`.
5. Thử thêm 1 rule `TTM` (Radar) trong cùng file, import lại vào đúng thiết bị AIS đó → xác nhận
   dòng `TTM` bị đếm vào `bỏ qua (sai loại bản tin)`, không tạo rule nào cho AIS.
6. Mở màn "Cấu hình bản tin" bên ENC đúng thiết bị AIS, sentence VDM — thấy field EXTRA vừa nạp.
