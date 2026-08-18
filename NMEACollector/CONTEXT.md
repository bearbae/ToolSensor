# NMEACollector — Tài liệu ngữ cảnh dự án

## Tổng quan

**NMEACollector** là tool thu thập và ghi log bản tin NMEA từ các thiết bị hàng hải thật trên tàu (radar, AIS, GPS, gyro). Hỗ trợ tối đa 25 kết nối đồng thời (TCP Client / TCP Server / Serial), mỗi kết nối lưu vào file riêng.

Tool được build bằng **PyQt6 + Python**, đóng gói bằng **PyInstaller**.

---

## Cấu trúc file

```
NMEACollector/
├── main.py           # UI chính (PyQt6), quản lý kết nối, config
├── receiver.py       # Thread nhận data TCP/Serial
├── session_logger.py # Ghi log ra file .bin
├── classifier.py     # Phân loại câu NMEA theo tag
├── config.py         # Load/save cấu hình JSON
├── startup.py        # Tự khởi động cùng hệ thống (Windows Registry / Linux .desktop)
└── _make_icon.py     # Tạo icon
```

Thư mục cha (`d:\Meta\ToolSensor\`) chứa `transmitters.py` — dùng hàm `list_serial_ports()`.

---

## Môi trường thực tế

- Tool được dùng **trên tàu biển**, chạy liên tục 24/7
- Nhận data từ: Radar (RATTM), AIS (AIVDM) baud 38400, GPS (GPRMC), Gyro
- Tổng tốc độ data: ~70-100 msg/giây
- Chạy trên cả **Windows** và **Ubuntu Linux**
- Build cho Linux bằng Docker: `docker run --rm -v "path:/src" ubuntu:22.04 bash -c "apt update && apt install -y python3 python3-pip libgl1-mesa-glx libglib2.0-0 && pip3 install pyinstaller pyserial PyQt6 && cd /src/NMEACollector && pyinstaller --onefile --name NMEACollector --paths '..' main.py"`

---

## Các tính năng chính

### 1. Kết nối (receiver.py)
- **TCP Client**: kết nối đến thiết bị phát, tự retry mỗi 5 giây khi mất kết nối
- **TCP Server**: lắng nghe, nhận nhiều client (tối đa 20 client đồng thời)
- **Serial**: kết nối cổng COM/ttyUSB, tự retry khi thiết bị bị rút

### 2. Ghi log (session_logger.py)
- File log dạng: `prefix_YYYYMMDD_HHMMSS.bin`
- Mỗi dòng: `2024-08-12T14:23:45.123: [RMC] $GPRMC,...`
- Xoay file tự động khi sang ngày mới (nếu bật)
- Tạo file mới nếu file bị xóa trong khi đang ghi
- Giới hạn dung lượng thư mục log (nếu user cấu hình)
- Luôn giữ tối thiểu **5GB trống** trên ổ đĩa (xóa file cũ nhất nếu thiếu)

### 3. Cấu hình (config.py)
- Lưu tại: `~/.nmea_collector.json` (ẩn, cả Windows lẫn Linux)
- Fields: `output_folder`, `daily_rotate`, `auto_connect`, `max_folder_gb`, `connections`

### 4. Tự khởi động (startup.py)
- **Windows**: ghi vào Registry `HKCU\Software\Microsoft\Windows\CurrentVersion\Run`
- **Linux**: tạo `~/.config/autostart/nmea-collector.desktop`
- Không cần quyền Admin/root

### 5. Console log (main.py)
- Hiển thị bản tin NMEA realtime với màu sắc theo loại (AIS=xanh, Radar=vàng, GPS=xanh lá)
- Tối đa 200 dòng, trim xuống 100 khi vượt ngưỡng
- **Throttle**: buffer lại, flush ra console mỗi 500ms (không update mỗi câu)

---

## Tất cả thay đổi đã thực hiện (theo thứ tự)

### startup.py — Thêm hỗ trợ Linux autostart
**Trước:** Chỉ hỗ trợ Windows Registry, trên Linux là no-op.  
**Sau:** Tách thành 2 impl riêng — Windows dùng Registry, Linux tạo file `.desktop` trong `~/.config/autostart/`.

```python
# Linux impl
_DESKTOP_FILE = os.path.expanduser("~/.config/autostart/nmea-collector.desktop")

def _linux_enable():
    os.makedirs(_DESKTOP_DIR, exist_ok=True)
    content = _DESKTOP_TEMPLATE.format(exec_path=_exe_path().replace('"', ""))
    with open(_DESKTOP_FILE, "w", encoding="utf-8") as f:
        f.write(content)
```

### main.py — Label tự khởi động
**Trước:** `"Tự khởi động cùng Windows"`  
**Sau:** `"Tự khởi động cùng hệ thống"` + tooltip thay đổi theo OS

### session_logger.py — Tạo file mới khi file bị xóa
```python
def write(self, sentence, type_tag):
    ...
    elif not os.path.exists(self._path):
        self._rotate()   # tạo file mới nếu bị xóa từ bên ngoài
```

### config.py — Thêm field max_folder_gb
```python
DEFAULT_CONFIG = {
    ...
    "max_folder_gb": None,   # None = không giới hạn
    ...
}
```

### session_logger.py — Giới hạn dung lượng thư mục + bảo vệ ổ đĩa
Thêm `_enforce_size_limit()` với 2 điều kiện:
1. Thư mục log vượt ngưỡng `max_folder_gb` → xóa file cũ nhất
2. Ổ đĩa còn dưới **5GB** → xóa file cũ nhất (luôn hoạt động dù có hay không có giới hạn)

```python
import shutil
_MIN_FREE_BYTES = 5 * 1024 ** 3   # 5GB

def _enforce_size_limit(self):
    # Điều kiện 1: vượt giới hạn thư mục
    if self._max_bytes:
        # xóa file cũ cho đến khi dưới ngưỡng
        ...
    # Điều kiện 2: ổ đĩa gần đầy (luôn kiểm tra)
    free = shutil.disk_usage(self._output_dir).free
    while free < _MIN_FREE_BYTES:
        # xóa file cũ nhất
        ...
```

### main.py — Tăng giới hạn kết nối từ 5 lên 25
```python
MAX_CONNECTIONS = 25
```

### receiver.py — Fix memory leak: TCP buffer không giới hạn
**Nguyên nhân crash:** Nếu data không có `\n`, buffer tích lũy vô hạn → sau 2 ngày lên GB → OOM killer kill app.
```python
def _split_lines(self, buf, chunk):
    buf += chunk
    while '\n' in buf:
        line, buf = buf.split('\n', 1)
        self._emit(line)
    if len(buf) > 8192:   # xóa buffer nếu quá lớn
        buf = ''
    return buf
```

### receiver.py — Fix memory leak: Serial buffer không giới hạn
```python
if len(raw_buf) > 8192:
    raw_buf = b''
```

### main.py — Fix memory leak: Thread không được wait() khi disconnect
**Nguyên nhân:** `disconnect()` chỉ set `_running=False` rồi bỏ reference, thread vẫn đang chạy.
```python
def disconnect(self):
    if self._receiver:
        self._receiver.stop()
        self._receiver.wait(3000)   # chờ tối đa 3s để thread kết thúc sạch
        self._receiver = None
```

### main.py — Fix: Ghi file không bắt exception
```python
try:
    self._logger.write(sentence, tag)
except OSError as exc:
    self._lbl_status.setText(f"Lỗi ghi file: {exc}")
```

### receiver.py — Fix: TCP Server thread tích lũy
Giới hạn 20 client đồng thời, dọn dẹp thread chết trước khi tạo mới:
```python
_MAX_SERVER_CLIENTS = 20
client_threads = [t for t in client_threads if t.is_alive()]
if len(client_threads) >= self._MAX_SERVER_CLIENTS:
    conn.close()
    continue
```

### main.py — Fix memory leak: QTextEdit undo stack
```python
self._log.setUndoRedoEnabled(False)
```

### main.py — Giảm giới hạn console từ 3000 xuống 200 dòng
```python
_MAX_LOG_LINES = 200
_TRIM_TO_LINES = 100
```

### main.py — Throttle console update (tránh nghẹt main thread)
Thay vì append mỗi câu NMEA ngay lập tức, buffer lại và flush mỗi 500ms:
```python
self._console_buf: list[str] = []

def _on_sentence(self, sentence, tag, label):
    # chỉ append vào buffer, KHÔNG update console ngay
    self._console_buf.append(html_line)
    if len(self._console_buf) > 500:
        self._console_buf = self._console_buf[-200:]   # giới hạn buffer

def _flush_console(self):
    # gọi từ timer 500ms
    for line in self._console_buf:
        self._log.append(line)
    self._console_buf.clear()
    # trim nếu vượt 200 dòng
    ...
```

### receiver.py — Fix: Không tự reconnect sau khi mất mạng lâu
**Nguyên nhân:** Khi rút cáp, `recv()` timeout 1s rồi `continue` mãi, không bao giờ thoát ra để retry.  
**Fix:** Kết hợp TCP Keepalive + no-data timeout 30 giây:

```python
_NO_DATA_TIMEOUT = 30

def _apply_keepalive(self, sock):
    sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
    if hasattr(socket, 'TCP_KEEPIDLE'):   # Linux
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)

# Trong _run_tcp_client:
last_data = time.time()
except socket.timeout:
    if time.time() - last_data > self._NO_DATA_TIMEOUT:
        break   # thoát ra retry
    continue
```

### main.py — Thêm crash log
```python
def _setup_crash_log():
    log_path = os.path.expanduser("~/nmea_collector_crash.log")
    def _handle_exception(exc_type, exc_value, exc_tb):
        with open(log_path, "a", encoding="utf-8") as f:
            f.write(f"CRASH: {datetime.now().isoformat()}\n")
            f.write(''.join(traceback.format_exception(...)))
    sys.excepthook = _handle_exception
```
File crash log: `~/nmea_collector_crash.log` (append, không ghi đè)

---

## Tóm tắt các bug đã fix

| # | Vấn đề | File | Trạng thái |
|---|--------|------|------------|
| 1 | TCP buffer tích lũy không giới hạn → OOM | receiver.py | ✅ Fixed |
| 2 | Serial buffer tích lũy không giới hạn → OOM | receiver.py | ✅ Fixed |
| 3 | Thread không wait() khi disconnect → tích lũy | main.py | ✅ Fixed |
| 4 | Ghi file không bắt OSError → crash signal | main.py | ✅ Fixed |
| 5 | TCP Server tạo thread vô hạn | receiver.py | ✅ Fixed |
| 6 | QTextEdit undo stack tích lũy | main.py | ✅ Fixed |
| 7 | Console update 100 lần/giây → nghẹt main thread | main.py | ✅ Fixed |
| 8 | Console buffer không giới hạn | main.py | ✅ Fixed |
| 9 | Mất mạng lâu không tự reconnect | receiver.py | ✅ Fixed |
| 10 | File bị xóa ngoài không tạo lại | session_logger.py | ✅ Fixed |
| 11 | Giới hạn thư mục không tính dung lượng thực tế ổ đĩa | session_logger.py | ✅ Fixed |

---

## Lưu ý khi sửa code

- `receiver.py` chạy trong **QThread** riêng — không được gọi UI trực tiếp, chỉ emit signal
- `_on_sentence` trong `ConnectionRow` chạy trên **main thread** (slot từ signal cross-thread)
- File log được ghi trong **main thread** (tại `ConnectionRow._on_sentence`)
- Console được flush trong **main thread** (tại `MainWindow._tick` mỗi 500ms)
- `_enforce_size_limit()` gọi mỗi lần `write()` — nên giữ nhẹ, đã có `try/except` bao toàn bộ
- Không bao giờ xóa `self._path` (file đang ghi) trong `_enforce_size_limit()`
