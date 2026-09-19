# Kiến trúc & luồng xây dựng — Maritime Signal Simulator

> Tài liệu này mô tả cấu trúc code hiện tại của **Maritime Signal Simulator**
> (`main.py` ở thư mục gốc repo) — công cụ tạo và phát bản tin NMEA giả lập.
> Không bao gồm NMEA Collector / NMEA Replay (xem `README.md` cho tài liệu
> người dùng của cả 3 tool).

## 1. Sơ đồ module

```
main.py                 (~2500 dòng) — cửa sổ chính, toàn bộ UI (PyQt6) + điều phối
 ├─ generators.py        (906 dòng) — sinh câu NMEA: GPS / Radar / AIS
 ├─ transmitters.py       (203 dòng) — gửi câu NMEA ra ngoài: TCP / Serial / UDP
 ├─ gpx_parser.py                    — đọc waypoint từ file .gpx cho route AIS
 ├─ utils.py                         — checksum NMEA, format lat/lon
 ├─ ssh_settings.py                  — lưu/tải cấu hình SSH Tunnel (~/.maritime_simulator.json)
 └─ ssh_tunnel.py                    — SSH local port-forward (paramiko), fetch pod IP qua kubectl
```

Không có package ngoài nào chứa logic domain — `main.py` vừa là UI vừa là
lớp điều phối (không tách riêng controller/service).

## 2. Luồng dữ liệu khi phát tín hiệu

```
┌─────────────────────────────────────────────────────────────────┐
│  MainWindow (main.py)                                            │
│                                                                    │
│  GPSGenerator ──┐                                                 │
│  RadarTTMGenerator ──┼──►  TransmitterThread (QThread)            │
│  AISGenerator ──┘           │  vòng lặp: generate_all() → send()  │
│                              │  mỗi <interval_ms>                 │
│                              ▼                                    │
│                        <Transmitter>.send(sentence)                │
│                     (TCP Client / TCP Server / Serial / SSH)      │
└─────────────────────────────────────────────────────────────────┘
```

- **Generator** (`generators.py`) giữ *state mô phỏng* (vị trí, tốc độ,
  hướng…) và mỗi lần gọi `generate_all()` sẽ:
  1. Tính thời gian trôi qua từ lần gọi trước (`time.monotonic()`).
  2. Cập nhật vị trí theo tốc độ/hướng (di chuyển rhumb-line, hàm `_move`).
  3. Build danh sách câu NMEA đã bật (theo các flag `send_rmc`, `send_zda`,
     `send_vdo`, …) và trả về `list[str]`.
- **`TransmitterThread`** (`transmitters.py`) là `QThread` chạy nền: mỗi tick
  gọi `generate_all()` trên từng generator đang bật (checkbox GPS/Radar/AIS
  trên UI), gộp thành một danh sách message, gửi tuần tự qua transmitter, và
  phát tín hiệu Qt `message_sent` để UI ghi log — tách khỏi main thread nên
  UI không bị đứng khi gửi.
- **Transmitter** là 1 trong 4 lớp, chọn qua nhóm radio button "Connection":
  - `TCPTransmitter` — client, tự kết nối tới `host:port`.
  - `TCPServerTransmitter` — server, `listen()` + accept nền, broadcast tới
    mọi client đang kết nối.
  - `SerialTransmitter` — mở cổng COM (pyserial).
  - `UDPTransmitter` — gửi datagram UDP tới `host:port` (có cờ broadcast).
  - **SSH Tunnel** không phải transmitter riêng: nó mở `SSHTunnel` (paramiko,
    port-forward cục bộ) rồi tạo một `TCPTransmitter("127.0.0.1", local_port)`
    y hệt chế độ TCP Client, chỉ khác chỗ traffic đi qua tunnel trước khi tới
    `enc-sensor-gateway`.

## 3. Vòng đời Connect → Start → Stop → Disconnect

```
[Connect]  →  tạo transmitter theo mode đang chọn (_on_connect)
              → nếu mode SSH: mở SSHTunnel trước, transmitter trỏ vào 127.0.0.1:<local_port>
[Start]    →  tạo TransmitterThread(transmitter, gps?, radar?, ais?, interval_ms)
              → thread.start(); UI nhận message_sent → ghi log màu theo loại bản tin
[Stop]     →  thread.stop() (đặt cờ + thread.wait(3000)), transmitter vẫn mở
[Disconnect] → transmitter.close(); nếu có SSHTunnel thì tunnel.close()
```

Nút Start chỉ bật khi đã Connect thành công; đổi interval qua slider
(100–5000 ms) áp dụng ngay cho thread đang chạy (`set_interval`).

## 4. Cấu trúc UI (`MainWindow._build_*`)

- **Panel Connection** (trái): 4 radio button (TCP Client / TCP Server /
  Serial / SSH Tunnel) + sub-panel tương ứng ẩn/hiện theo `_on_mode_changed`.
- **QTabWidget** chính, mỗi tab tương ứng một generator:
  - **GPS** — vị trí/tốc độ/hướng tàu chủ + 8 loại câu bật/tắt độc lập
    (RMC, ZDA, HDT, HDM, HDG, ROT, THS, RMB) + panel VDO (AIVDO — tàu chủ tự
    phát AIS Class A/B).
  - **Radar (TTM)** — danh sách target (bearing/range hoặc lat/lon quy đổi
    qua lại), OSD/RSD tùy chọn, nút Generate để tạo ngẫu nhiên hàng loạt.
  - **AIS (VDM)** — danh sách tàu mô phỏng, hỗ trợ nạp route từ file GPX
    (`gpx_parser.parse_gpx`) kèm lịch tốc độ theo waypoint (`_speed_schedule`).
  - **VDO (Own Ship)** — cấu hình chi tiết bản tin AIVDO của tàu chủ.
  - **Fusion Test** — kịch bản kết hợp thủ công/tự động giữa Radar + AIS để
    kiểm thử thuật toán fusion phía nhận (không phát ra ngoài, chỉ hiển thị).
- **Log console** (phải) — `QTextEdit` mã màu theo loại bản tin
  (`_COL_GPS/_COL_RADAR/_COL_AIS`), đếm số message đã gửi mỗi 500 ms qua
  `_gps_display_timer`.

Toàn bộ widget được nối sự kiện (`toggled`/`valueChanged`/…) trực tiếp vào
thuộc tính của generator bằng lambda `setattr(...)` trong một khối
"Signal/Slot wiring" tập trung — không có data-binding framework, thay đổi
trên UI phản ánh ngay vào generator vì object được share (không copy) giữa
UI thread và `TransmitterThread`.

## 5. Kết nối SSH Tunnel (tới `enc-sensor-gateway` khi không cùng LAN)

Chi tiết nghiệp vụ đã có trong `README.md`; về code:

1. `ssh_settings.load()` đọc `~/.maritime_simulator.json`, điền sẵn form SSH
   khi mở app (`_load_ssh_settings`).
2. Nút **"Lấy Pod IP"** chạy `ssh_tunnel.fetch_pod_ip()` — SSH vào server,
   chạy `kubectl get pod -o jsonpath=...` lấy IP pod hiện tại (đổi mỗi lần
   pod restart).
3. **Connect** (mode SSH) → `SSHTunnel(...)`: dùng `paramiko.SSHClient` +
   `Transport.open_channel("direct-tcpip", ...)` tự cài forward server nội bộ
   (`_ForwardServer`, thread riêng) — không dùng package `sshtunnel` vì nó
   phụ thuộc `paramiko.DSSKey` đã bị xóa ở paramiko 5.x.
4. Cấu hình được lưu lại (trừ password nếu bỏ "Nhớ mật khẩu") sau khi kết nối
   thành công (`_save_ssh_settings`).

## 6. Đóng gói (PyInstaller)

Mỗi lần build ra `.exe` mới lại thêm một file `.spec` mới trong repo (lịch sử
đặt tên theo version: `MaritimeV8.spec` … `MaritimeV13...spec`,
`maritimeSimulatorV2.spec`, `maritimeSimulatorSSH.spec` — bản mới nhất có
tích hợp SSH Tunnel). Cấu trúc `.spec` giống nhau, chỉ khác `name=`:

```python
a = Analysis(['main.py'], pathex=['..'], ...)
pyz = PYZ(a.pure)
exe = EXE(pyz, ..., name='maritimeSimulatorSSH', console=False,
          upx=True, icon=['icon.ico'])
```

Build one-file, windowed (không console), icon `icon.ico` (tạo bằng
`_make_icon.py`). Lệnh build:

```powershell
pyinstaller maritimeSimulatorSSH.spec
```

Output nằm ở `build/<name>/` (file trung gian) và `dist/<name>.exe` (file
chạy cuối). Các `.spec`/`build`/`dist` cũ (V6–V13) là artefact của các lần
build trước, chưa được dọn khỏi repo.

## 7. Ghi chú về trạng thái hiện tại (chưa hoàn thiện)

- `transmitters.py` đã có sẵn `UDPTransmitter` và `generators.py` đã có sẵn
  builder cho câu `VBW` (Dual Ground/Water Speed) trong `GPSGenerator`, nhưng
  **UI chưa nối vào** (chưa có radio button "UDP" trong Connection panel,
  chưa có checkbox "VBW" trong GPS Settings) — phần backend sẵn sàng, phần
  wiring UI còn dang dở.
- Không có file cấu hình lưu lại toàn bộ session (GPS/Radar/AIS đã nhập) như
  NMEACollector có `config.py` — riêng phần SSH Tunnel là ngoại lệ, có lưu
  vào `~/.maritime_simulator.json`.
