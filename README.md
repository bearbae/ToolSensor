# Maritime NMEA Toolkit

Bộ 3 công cụ hỗ trợ thu thập, mô phỏng và phát lại dữ liệu NMEA từ thiết bị hàng hải.

---

## Tổng quan

| Tool                          | File exe                | Mục đích                                                   |
| ----------------------------- | ----------------------- | ---------------------------------------------------------- |
| **Maritime Signal Simulator** | `MaritimeSimulator.exe` | Tạo và phát bản tin NMEA giả lập (GPS, Radar, AIS)         |
| **NMEA Collector**            | `NMEACollector.exe`     | Thu thập và ghi log bản tin NMEA từ thiết bị thật trên tàu |
| **NMEA Replay**               | `NMEAReplay.exe`        | Phát lại file log `.bin` đã thu về                         |

---

## 1. Maritime Signal Simulator

> Công cụ tạo bản tin NMEA giả lập để kiểm thử hệ thống nhận dữ liệu hàng hải.

### Tính năng

- Phát đồng thời GPS, Radar (RATTM) và AIS (AIVDM)
- Cấu hình chu kỳ phát từ 100 ms đến 5.000 ms
- Kết nối qua **TCP Client**, **TCP Server** hoặc **Cổng Serial**
- Nhật ký bản tin mã màu theo loại tín hiệu

### Kết nối

1. Chọn chế độ kết nối: **TCP Client** / **TCP Server** / **Serial Port**
2. Nhập địa chỉ Host + Port (TCP) hoặc chọn cổng COM + Baudrate (Serial)
3. Nhấn **Connect** → kết nối thành công thì nút **Start** sẽ sáng lên
4. Nhấn **▶ Start** để bắt đầu phát, **■ Stop** để dừng

### Cài đặt GPS

| Trường                | Mô tả                               |
| --------------------- | ----------------------------------- |
| Latitude / Longitude  | Vị trí xuất phát của tàu chủ        |
| Speed                 | Tốc độ (knot)                       |
| Course (True)         | Hướng đi thật (độ)                  |
| Heading (True/Mag)    | Hướng mũi tàu thật / từ (độ)        |
| Deviation / Variation | Độ lệch la bàn và từ thiên          |
| Rate of Turn          | Tốc độ quay (độ/phút, dương = phải) |

**Loại bản tin GPS có thể bật riêng:** RMC, ZDA, HDT, HDM, HDG, ROT, THS, RMB

> **RMB Waypoint:** Bật checkbox RMB để cấu hình điểm đến (Origin WP, Dest WP, Lat/Lon đích, Cross-Track Error).

### Cài đặt Radar (RATTM)

| Trường    | Mô tả                               |
| --------- | ----------------------------------- |
| Target ID | Số hiệu mục tiêu (1–99)             |
| Bearing   | Góc phương vị từ tàu chủ (độ)       |
| Range     | Khoảng cách (hải lý)                |
| Speed     | Tốc độ mục tiêu (knot)              |
| Course    | Hướng đi mục tiêu (độ)              |
| Name      | Tên mục tiêu (tuỳ chọn)             |
| Status    | T = Tracking / L = Lost / Q = Query |

**Chuyển đổi tọa độ:**

- **Own-ship:** Nhập lat/lon tàu chủ (hoặc bấm **← GPS** để kéo từ giá trị GPS đang cấu hình)
- **Brg+Rng → Lat/Lon:** Hiển thị tọa độ thực của mục tiêu tính từ Bearing+Range
- **Lat/Lon → Brg+Rng:** Nhập tọa độ đích, bấm **Fill** để điền tự động Bearing và Range vào form

> Dùng nút **Add / Update** để thêm mục tiêu vào danh sách, **Remove** để xoá.  
> Nút **Generate** tự tạo ngẫu nhiên nhiều mục tiêu cùng lúc.

### Cài đặt AIS (AIVDM)

| Trường               | Mô tả                       |
| -------------------- | --------------------------- |
| MMSI                 | Số định danh tàu (9 chữ số) |
| Ship Name            | Tên tàu (tối đa 20 ký tự)   |
| Latitude / Longitude | Vị trí tàu AIS              |
| Speed                | Tốc độ (knot)               |
| Course               | Hướng đi (độ)               |
| Ship Type            | Loại tàu theo mã ITU        |

---

## 2. NMEA Collector

> Công cụ thu thập liên tục bản tin NMEA từ thiết bị thật trên tàu, chạy ổn định ngày đêm trong nhiều tuần.

### Tính năng

- Kết nối tối đa **5 cổng đồng thời** (TCP Client / TCP Server / Serial)
- Mỗi kết nối lưu vào **file `.bin` riêng**
- **Tự xoay file** vào lúc 0h00 mỗi ngày (tạo file mới theo ngày)
- **Tự kết nối lại** khi mất tín hiệu (TCP/Serial đều retry sau 5 giây)
- **Lưu/tải cấu hình** tự động (`~/.nmea_collector.json`)
- **Tự khởi động cùng Windows** (đăng ký Registry HKCU, không cần quyền Admin)
- **Chạy ngầm** — bấm X để thu vào system tray, double-click icon để mở lại
- Nhật ký NMEA theo thời gian thực, mã màu theo loại bản tin

### Giao diện

```
┌─────────────────────────────────────────────────────────┐
│  Cài đặt chung        │  Nhật ký NMEA                   │
│  ├─ Thư mục lưu log   │  (bản tin theo thời gian thực)  │
│  ├─ Xoay file hàng ngày                                 │
│  ├─ Tự kết nối        │                                 │
│  └─ Tự khởi động      │                                 │
│                        │                                 │
│  Các kết nối (1–5)    │                                 │
│  ├─ Kết nối #1        │                                 │
│  ├─ Kết nối #2        │                                 │
│  └─ ...               │                                 │
│                        │                                 │
│  Thống kê             │                                 │
└─────────────────────────────────────────────────────────┘
```

### Thêm kết nối

1. Nhấn **+ Thêm kết nối**
2. Chọn chế độ: **TCP Client** / **TCP Server** / **Cổng Serial**
3. Điền tham số kết nối:
   - TCP Client: Host, Port
   - TCP Server: Port lắng nghe
   - Serial: Cổng COM, Baudrate
4. Đặt **Tiền tố file** để dễ nhận biết (vd: `gps`, `radar`, `ais`)
5. Nhấn **Kết nối** trên card hoặc **Kết nối tất cả** trên thanh toolbar

### Cài đặt chung

| Tùy chọn                      | Mô tả                                                       |
| ----------------------------- | ----------------------------------------------------------- |
| Thư mục lưu log               | Nơi lưu các file `.bin` (mặc định: `~/Documents/NMEA_Logs`) |
| Tự tạo file khi sang ngày mới | Đóng file cũ và mở file mới lúc 0h00                        |
| Tự động kết nối khi khởi động | Tự kết nối tất cả cổng ngay khi mở tool                     |
| Tự khởi động cùng Windows     | Đăng ký vào Windows Registry                                |

### Lưu cấu hình

- Nhấn **Lưu cấu hình** để ghi cấu hình hiện tại vào `C:\Users\<tên>\\.nmea_collector.json`
- Cấu hình được tải tự động mỗi lần mở tool

### Quy tắc đặt tên file

```
<tiền_tố>_YYYYMMDD_HHMMSS.bin
```

Ví dụ: `gps_20260730_083000.bin`

Khi kết nối lại cùng session (chưa sang ngày), tool **ghi nối tiếp vào file cũ** thay vì tạo file mới.

### Chạy ngầm (System Tray)

- Bấm **X** (nút đóng cửa sổ) → tool thu vào system tray, **không dừng thu dữ liệu**
- **Double-click** icon radar dưới thanh taskbar để mở lại cửa sổ
- **Chuột phải** vào icon → **Thoát** để đóng hẳn tool

### Mã màu nhật ký

| Màu        | Loại bản tin               |
| ---------- | -------------------------- |
| Xanh lá    | GPS (RMC, GGA, HDT, ...)   |
| Vàng       | Radar (TTM, OSD, RSD, ...) |
| Xanh dương | AIS (VDM, VDO)             |
| Trắng      | Khác                       |

---

## 3. NMEA Replay

> Công cụ phát lại file log `.bin` đã thu về để kiểm thử hoặc trình diễn offline.

### Tính năng

- Load tối đa 3 file: **GPS**, **AIS**, **Radar** (`.bin` từ NMEA Collector)
- Phát qua **TCP Client**, **TCP Server** hoặc **Serial Port**
- Điều khiển: **Play / Pause / Stop**
- Điều chỉnh tốc độ phát: **0.1x đến 10x** so với tốc độ thu gốc
- Thanh tiến trình hiển thị vị trí hiện tại trong file
- Nhật ký bản tin mã màu theo thời gian thực

### Hướng dẫn sử dụng

**Bước 1 — Kết nối đầu ra:**

1. Chọn chế độ: TCP Client / TCP Server / Serial Port
2. Nhập thông số (Host+Port hoặc cổng COM)
3. Nhấn **Connect**

**Bước 2 — Load file:**

1. Nhấn nút **`...`** bên cạnh GPS / AIS / Radar để chọn file `.bin`
2. Có thể load 1, 2 hoặc cả 3 loại cùng lúc
3. Nhấn **Load Files** — tool hiển thị tổng số bản tin đã đọc được

**Bước 3 — Phát lại:**

- **▶ Play** — bắt đầu phát
- **⏸ Pause** — tạm dừng (giữ nguyên vị trí)
- **■ Stop** — dừng và quay về đầu file
- Kéo thanh **Speed** để điều chỉnh tốc độ (1x = tốc độ gốc)

---

## Định dạng file `.bin`

File `.bin` do NMEA Collector tạo ra là file văn bản thuần tuý, mỗi dòng là một bản tin NMEA kèm timestamp:

```
2026-07-30T08:30:00.123|$GPRMC,083000.00,A,1046.6140,N,10642.0416,E,5.0,45.0,300726,,,A*XX
2026-07-30T08:30:01.124|$RATTM,01,2.5,45.0,T,3.2,90.0,T,0.0,,T,,M,0*XX
```

NMEA Replay đọc timestamp này để phát lại đúng khoảng cách thời gian giữa các bản tin.

---

## Luồng hoạt động điển hình

```
[Thiết bị thật trên tàu]
        │  TCP / Serial
        ▼
[NMEA Collector]  ──→  gps_20260730.bin
                  ──→  radar_20260730.bin
                  ──→  ais_20260730.bin
        │
        │ (chuyển file về văn phòng)
        ▼
[NMEA Replay]  ──→  [Hệ thống kiểm thử / Phần mềm hiển thị bản đồ]


[Maritime Signal Simulator]  ──→  [Hệ thống kiểm thử] (không cần tàu thật)
```

---

## Yêu cầu hệ thống

- Windows 10 / 11 (64-bit)
- Không cần cài thêm Python hay thư viện nào khi dùng bản `.exe`
- Quyền Administrator: **không cần** (trừ khi cổng Serial yêu cầu driver riêng)

---

## Ghi chú kỹ thuật

- File cấu hình NMEACollector: `C:\Users\<tên>\.nmea_collector.json`
- Tự khởi động Windows: Registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\NMEACollector`
- Mặc định NMEA baudrate Serial: **4800 baud** (chuẩn IEC 61162-1)
