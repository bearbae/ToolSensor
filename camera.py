"""Camera RTSP — kiểm tra kết nối, ghi phân đoạn và phát lại, bằng cách BỌC ffmpeg/go2rtc.

Không có một dòng RTSP/RTP nào tự viết bằng Python: mọi thứ đụng tới giao thức đều giao cho
ffmpeg (tìm trong PATH) hoặc go2rtc (binary rời, người dùng chỉ đường dẫn). Việc của module này
chỉ là dựng lệnh, canh tiến trình con, ghi manifest và giữ dung lượng trong hạn mức.

Module KHÔNG phụ thuộc PyQt — chạy thẳng bằng dòng lệnh, vì lỗi khó nằm ở phần chạy dài ngày
(mất kết nối lúc 3 giờ sáng, đĩa đầy sau ba tuần) chứ không nằm ở giao diện:

    python camera.py tools
    python camera.py probe rtsp://admin:123@192.168.1.10:554/cam/realmonitor?channel=1&subtype=1
    python camera.py record <URL> --dir D:/rec --name cam1 --mode sample --on 5 --every 30
    python camera.py replay D:/rec/cam1/2026-08-11/seg_20260811_101500.mp4 --go2rtc D:/bin/go2rtc.exe
    python camera.py manifest D:/rec/cam1
"""

import argparse
import errno
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

# ---------------------------------------------------------------------------
# Hằng số
# ---------------------------------------------------------------------------

IS_WINDOWS = sys.platform.startswith("win")
CREATE_NO_WINDOW = 0x08000000  # Windows: tiến trình con không nháy cửa sổ console đen

GB = 1024 ** 3

SEGMENT_SECONDS = 300          # 5 phút/đoạn — mất tối đa 5 phút hình nếu đoạn cuối hỏng
QUOTA_CHECK_SECONDS = 300      # bằng segment_time: file chỉ sinh thêm mỗi chừng đó
# Nhịp ĐO dung lượng, tách khỏi nhịp XÉT ngưỡng ở trên. Xét ngưỡng thưa là đúng (dữ liệu chỉ
# nhích lên mỗi khi đoạn đóng), nhưng đo cũng thưa theo thì giao diện đứng hình 5 phút và người
# vận hành tưởng tool chết. Quét thư mục vài nghìn file chỉ tốn vài mili-giây.
MEASURE_SECONDS = 30.0
SCAN_INTERVAL = 3.0            # nhịp quét đoạn đã đóng để ghi vào manifest
BACKOFF_START = 5.0            # nối lại lần đầu sau 5s
BACKOFF_MAX = 60.0             # rồi gấp đôi dần, chạm 60s thì giữ nguyên (thử mãi, không bỏ cuộc)
HEALTHY_SECONDS = 120.0        # tiến trình sống quá lâu này coi như khoẻ → reset backoff
# ffmpeg còn sống mà không ghi thêm byte nào quá lâu này thì coi như đã hỏng.
#
# Không phải phòng xa: đã bắt được tại chỗ. Camera rớt giữa chừng, ffmpeg nối lại vào một cổng
# không ai nghe rồi TREO IM 35 giây — không lỗi, không thoát, không file. Chỉ nhìn "tiến trình
# còn sống" thì tool báo "Đang ghi" suốt đêm trong khi manifest trống trơn. Luồng đang chạy thì
# giây nào cũng có byte mới, nên 60 giây đứng yên là hỏng chắc chắn.
STALL_SECONDS = 60.0

# Chế độ vòng tròn KHÔNG bao giờ xoá xuống dưới ngần này phút gần nhất.
#
# Vòng tròn sinh ra để "luôn giữ hình mới nhất". Nhưng ổ có thể đầy vì thứ khác — database, log
# cảm biến, phần mềm hải đồ. Lúc đó xoá bản ghi camera bao nhiêu cũng không cứu được, mà cứ xoá
# thì đến sáng chẳng còn gì để xem. Chạm mức này thì dừng ghi và báo động, vì vấn đề không nằm
# ở camera nữa.
RING_KEEP_MINUTES = 30.0
SHUTDOWN_GRACE = 5.0           # chờ ffmpeg tự đóng file sau khi gửi 'q'
SNAPSHOT_TIMEOUT = 20.0
PROBE_TIMEOUT = 20.0

MODE_SAMPLE = "sample"
MODE_SESSION = "session"
MODE_CONTINUOUS = "continuous"

MODE_LABELS = {
    MODE_SAMPLE: "Lấy mẫu",
    MODE_SESSION: "Theo phiên",
    MODE_CONTINUOUS: "Liên tục",
}

# Bitrate ước lượng theo độ phân giải, để BÁO TRƯỚC mức tiêu thụ chứ không phải để đo.
# Mốc lấy từ thực tế: 1080p ghi -c copy ~21 GB/ngày ≈ 2 Mbps; luồng phụ (subtype=1) nhẹ ~4 lần.
_BITRATE_MBPS = ((1080, 2.0), (720, 1.0), (0, 0.5))

_DAY_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_SEG_RE = re.compile(r"^seg_(\d{8})_(\d{6})\.mp4$")

# ffmpeg chết vì ĐẦY ĐĨA khác hẳn chết vì MẤT KẾT NỐI: đầy đĩa thì nối lại bao nhiêu lần cũng
# chết tiếp, phải dừng hẳn và báo động; mất kết nối thì cứ kiên nhẫn thử lại.
_DISK_FULL_RE = re.compile(
    r"no space left|not enough space|disk full|errno 28|failure writing|i/o error|"
    r"error writing trailer|unable to write",
    re.IGNORECASE,
)
_AUTH_RE = re.compile(r"401 unauthorized|403 forbidden|authorization failed", re.IGNORECASE)
_CONN_RE = re.compile(
    r"connection refused|connection reset|timed out|timeout|no route to host|"
    r"network is unreachable|end of file|immediate exit|404 not found|server returned",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Tiện ích chung
# ---------------------------------------------------------------------------

def _utc_now() -> datetime:
    """Giờ UTC. Tàu qua nhiều múi giờ — dùng giờ máy thì mốc thời gian có lúc nhảy lùi."""
    return datetime.now(timezone.utc)


def _stamp(dt: datetime) -> str:
    """ISO-8601 kèm hậu tố Z, đủ để công cụ phân tích nào cũng đọc được."""
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def human_bytes(n: float) -> str:
    if n >= GB:
        return f"{n / GB:.2f} GB"
    if n >= 1024 * 1024:
        return f"{n / 1024 / 1024:.0f} MB"
    return f"{n / 1024:.0f} KB"


def human_secs(sec: float) -> str:
    sec = max(0, int(sec))
    h, rem = divmod(sec, 3600)
    m, s = divmod(rem, 60)
    if h:
        return f"{h}h{m:02d}m"
    if m:
        return f"{m}m{s:02d}s"
    return f"{s}s"


def mask_url(text: str) -> str:
    """Che mật khẩu trong rtsp://user:pass@host.

    Nhận cả một dòng log chứ không riêng URL: ffmpeg/ffprobe in NGUYÊN URL đầu vào vào thông
    báo lỗi, nên mọi đường chữ ra khỏi module (giao diện, file log, manifest) đều phải đi qua
    đây. Log của tàu còn được gom lại gửi về bờ.
    """
    return re.sub(r"(rtsp://[^:/@\s]+:)[^@\s]*(@)", r"\1***\2", text or "")


def with_credentials(url: str, username: str = "", password: str = "") -> str:
    """rtsp://host/path + admin/123 → rtsp://admin:123@host/path.

    Đa số camera IP bắt xác thực ngay ở tầng RTSP; ffmpeg không lấy credential từ đâu khác nên
    URL trần bị trả 401 và tiến trình chết ngay từ giây đầu.

    Mã hoá phần trăm là BẮT BUỘC: mật khẩu camera hay có @ : / # — để nguyên thì dấu @ trong
    mật khẩu cắt URL sai chỗ và ffmpeg đi tìm một máy chủ không tồn tại.

    Giữ nguyên nếu người dùng đã tự nhét credential vào URL, hoặc không khai username.
    """
    url = (url or "").strip()
    if not username or not url.lower().startswith("rtsp://"):
        return url
    rest = url[len("rtsp://"):]
    # Chỉ xét phần trước dấu / đầu tiên: chuỗi truy vấn có thể chứa @ mà không phải credential.
    if "@" in rest.split("/", 1)[0]:
        return url
    cred = quote(username, safe="")
    if password:
        cred += ":" + quote(password, safe="")
    return f"rtsp://{cred}@{rest}"


def safe_name(name: str) -> str:
    """Tên camera dùng làm tên thư mục — chặn ký tự làm vỡ đường dẫn."""
    cleaned = re.sub(r"[^\w.\-]+", "_", (name or "").strip())
    return cleaned or "cam"


def lan_ip() -> str:
    """IP LAN thật của máy.

    Client đọc luồng replay là MÁY KHÁC, đưa cho họ 127.0.0.1 thì vô dụng. Mở một UDP socket
    tới 8.8.8.8 rồi hỏi hệ điều hành đã chọn card mạng nào — UDP không hề gửi gói nào ra ngoài
    nên không cần Internet, chỉ cần bảng định tuyến.
    """
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        return "127.0.0.1"
    finally:
        sock.close()


def port_in_use(port: int, timeout: float = 0.4) -> bool:
    """Cổng này đã có ai phục vụ chưa — thử NỐI VÀO, không thử bind.

    Thử bind vô dụng trên Windows: đã đo trên chính máy này, một tiến trình đang Listen trên
    "::" mà mình vẫn bind được cả "0.0.0.0" lẫn "::" cùng số cổng. Kết quả là hai server cùng
    một cổng, client vào lúc trúng cái này lúc trúng cái kia — kiểu lỗi mò cả buổi không ra.

    CHỈ gọi TRƯỚC khi chạy replay. Gọi sau khi đã chạy là tự nối vào chính mình và chiếm mất
    suất người xem duy nhất của ffmpeg `-listen 1`.
    """
    for host in ("127.0.0.1", "::1"):
        try:
            with socket.create_connection((host, port), timeout=timeout):
                return True
        except OSError:
            continue
    return False


def can_reach(url: str, timeout: float = 3.0) -> bool:
    """Có mở được kết nối TCP tới camera không.

    Hỏi trước khi gọi ffmpeg, vì ffmpeg gặp cổng chết thì TREO chứ không báo lỗi — đã đo: nối
    vào một cổng không ai nghe, nó nằm im 35 giây không nói gì. Trong ca mạng chập chờn, mỗi
    lần nối lại trúng lúc camera chưa kịp lên là mất trắng 60 giây chờ watchdog. Một cú TCP
    connect tốn vài mili-giây và cho câu trả lời dứt khoát.
    """
    m = re.match(r"rtsp://(?:[^@/]*@)?([^/:?]+)(?::(\d+))?", (url or "").strip(), re.IGNORECASE)
    if not m:
        return True  # không phân tích được địa chỉ thì đừng chặn, cứ để ffmpeg thử
    host, port = m.group(1), int(m.group(2) or 554)
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def find_free_port(start: int, limit: int = 60) -> int:
    """Cổng rảnh đầu tiên tính từ `start`. Trả 0 nếu dò hết `limit` cổng vẫn không thấy.

    Máy trên tàu thường đã có sẵn go2rtc/đầu ghi/phần mềm hải đồ giữ đúng mấy cổng quen thuộc
    (8554 RTSP, 8555 WebRTC...). Bắt người vận hành tự đoán cổng nào rảnh là bắt họ làm việc của
    máy tính.
    """
    for port in range(max(1, start), min(start + limit, 65536)):
        if not port_in_use(port, timeout=0.2):
            return port
    return 0


def _exe(name: str) -> str:
    return f"{name}.exe" if IS_WINDOWS else name


def search_dirs() -> list:
    """Các thư mục tự dò binary, ngoài PATH: cạnh mã nguồn và cạnh file exe đã đóng gói."""
    dirs = [Path(__file__).resolve().parent]
    if getattr(sys, "frozen", False):  # bản PyInstaller
        dirs.append(Path(sys.executable).resolve().parent)
    return dirs


def find_tool(name: str, hint: str = "") -> str:
    """Trả về đường dẫn tới binary, chuỗi rỗng nếu không thấy.

    Thứ tự: đường dẫn người dùng khai → thư mục cạnh app → PATH.
    """
    if hint:
        p = Path(hint)
        if p.is_file():
            return str(p)
    for d in search_dirs():
        p = d / _exe(name)
        if p.is_file():
            return str(p)
    return shutil.which(name) or ""


def where_looked(name: str) -> str:
    """Mô tả CHỖ ĐÃ TÌM để báo lỗi cho ra hồn — thiếu binary mà im lặng là mò cả buổi."""
    dirs = ", ".join(str(d) for d in search_dirs())
    return f"{_exe(name)} — đã tìm trong: {dirs} và PATH của hệ thống"


def check_tools(go2rtc_hint: str = "") -> dict:
    """{tên: đường dẫn hoặc chuỗi rỗng} cho ffmpeg / ffprobe / go2rtc."""
    return {
        "ffmpeg": find_tool("ffmpeg"),
        "ffprobe": find_tool("ffprobe"),
        "go2rtc": find_tool("go2rtc", go2rtc_hint),
    }


def _spawn_kwargs() -> dict:
    """Cờ spawn dùng chung cho mọi tiến trình con."""
    return {"creationflags": CREATE_NO_WINDOW} if IS_WINDOWS else {}


def _child_env() -> dict:
    """Ép tiến trình con dùng giờ UTC.

    `-strftime 1` của ffmpeg gọi localtime, tức là theo GIỜ MÁY. Đặt TZ=UTC0 để tên file luôn
    là giờ UTC — nếu không, tàu đổi múi giờ giữa chuyến là tên file nhảy lùi và thứ tự đoạn ghi
    loạn hết. `_read_segment` vẫn kiểm tra chéo phòng khi bản ffmpeg nào đó không nghe TZ.
    """
    env = os.environ.copy()
    env["TZ"] = "UTC0"
    return env


def kill_tree(proc: subprocess.Popen) -> bool:
    """Giết CẢ CÂY tiến trình con. Trả về True nếu chắc chắn nó đã chết.

    go2rtc tự spawn ffmpeg con; giết mỗi go2rtc thì ffmpeg mồ côi vẫn giữ cổng và lần replay
    sau không bind được nữa. Windows không có process group kiểu POSIX nên phải nhờ taskkill /T.

    Thử HAI lượt và KIỂM TRA LẠI: đã gặp trường hợp gọi giết xong mà tiến trình vẫn sống — nó
    ôm cổng mãi, lần phát sau báo "cổng đang bận" mà nhìn quanh chẳng thấy ai chiếm. Thà tốn
    thêm vài giây còn hơn để lại tiến trình mồ côi.
    """
    if proc is None or proc.poll() is not None:
        return True
    for _ in range(2):
        if IS_WINDOWS:
            try:
                subprocess.run(
                    ["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    timeout=10, **_spawn_kwargs(),
                )
            except Exception:
                pass
        try:
            proc.kill()
        except Exception:
            pass
        try:
            proc.wait(timeout=5)
            return True
        except Exception:
            pass
        if proc.poll() is not None:
            return True
    return proc.poll() is not None


def _shutdown_ffmpeg(proc: subprocess.Popen) -> None:
    """Dừng ffmpeg TỬ TẾ để nó kịp đóng file, chỉ giết khi nó không chịu thoát.

    Windows không có SIGINT để xin tiến trình con dừng êm. Cách chuẩn với ffmpeg là gửi ký tự
    'q' vào stdin — đúng phím người dùng gõ khi chạy tay. Phải ĐÓNG stdin sau khi gửi, không thì
    nó còn nằm chờ đọc tiếp và không bao giờ thoát.
    """
    if proc is None or proc.poll() is not None:
        return
    try:
        if proc.stdin:
            proc.stdin.write(b"q\n")
            proc.stdin.flush()
            proc.stdin.close()
    except Exception:
        pass
    try:
        proc.wait(timeout=SHUTDOWN_GRACE)
        return  # thoát êm — file đã đóng đủ
    except subprocess.TimeoutExpired:
        pass
    kill_tree(proc)


def estimate_gb_per_day(height: int, on_minutes: float = 0.0, every_minutes: float = 0.0) -> float:
    """Ước tính dung lượng/ngày theo độ phân giải và tỉ lệ thời gian ghi.

    Chỉ để CẢNH BÁO TRƯỚC khi bật ghi. Số thật do `CameraRecorder` đo từ dung lượng thư mục.
    """
    mbps = _BITRATE_MBPS[-1][1]
    for h, rate in _BITRATE_MBPS:
        if height >= h:
            mbps = rate
            break
    duty = 1.0
    if every_minutes > 0 and 0 < on_minutes < every_minutes:
        duty = on_minutes / every_minutes
    return mbps * 1_000_000 / 8 * 86400 * duty / GB


# ---------------------------------------------------------------------------
# 1. KẾT NỐI — probe bằng ffprobe
# ---------------------------------------------------------------------------

_RE_VIDEO = re.compile(r"Stream #\d+:\d+.*?:\s*Video:\s*([\w.\-]+)(.*)$")
_RE_AUDIO = re.compile(r"Stream #\d+:\d+.*?:\s*Audio:\s*([\w.\-]+)")
_RE_SIZE = re.compile(r"\b(\d{2,5})x(\d{2,5})\b")
_RE_FPS = re.compile(r"([\d.]+)\s*fps")


@dataclass
class ProbeResult:
    ok: bool = False
    codec: str = ""
    width: int = 0
    height: int = 0
    fps: float = 0.0
    audio: str = ""
    stream_line: str = ""   # nguyên dòng "Stream #0:0: Video: ..." để hiện lên GUI
    error: str = ""

    def summary(self) -> str:
        if not self.ok:
            return self.error or "Không đọc được thông tin luồng"
        parts = [self.codec or "?"]
        if self.width and self.height:
            parts.append(f"{self.width}x{self.height}")
        if self.fps:
            parts.append(f"{self.fps:g} fps")
        if self.audio:
            parts.append(f"tiếng: {self.audio}")
        return "  •  ".join(parts)


def probe(url: str, ffprobe: str = "", timeout: float = PROBE_TIMEOUT,
          username: str = "", password: str = "") -> ProbeResult:
    """Hỏi camera xem nó phát cái gì.

    ffprobe in thông tin luồng ra STDERR (stdout dành cho dữ liệu), nên đọc stderr là đúng.
    Dùng RTSP over TCP cho khớp với lúc ghi: UDP có thể qua được trong khi TCP bị chặn, probe
    thành công mà ghi lại hỏng thì càng khó hiểu.
    """
    tool = find_tool("ffprobe", ffprobe)
    if not tool:
        return ProbeResult(error=f"Không tìm thấy {where_looked('ffprobe')}")
    if not (url or "").strip():
        return ProbeResult(error="Chưa nhập URL RTSP")

    cmd = [tool, "-hide_banner", "-rtsp_transport", "tcp", "-i",
           with_credentials(url, username, password)]
    try:
        cp = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=timeout, env=_child_env(), **_spawn_kwargs(),
        )
    except subprocess.TimeoutExpired:
        return ProbeResult(error=f"Không kết nối được trong {timeout:.0f}s "
                                 f"(sai URL, sai cổng, hoặc camera chặn RTSP over TCP)")
    except OSError as exc:
        return ProbeResult(error=f"Không chạy được ffprobe: {exc}")

    # Che NGAY sau khi đọc: ffprobe nhắc lại nguyên URL đầu vào trong mọi dòng lỗi, mà cả
    # `error` lẫn `stream_line` đều được hiện lên giao diện và ghi vào file log.
    text = mask_url(cp.stderr.decode("utf-8", "replace"))
    res = ProbeResult()
    for line in text.splitlines():
        m = _RE_VIDEO.search(line)
        if m and not res.codec:
            res.codec = m.group(1)
            res.stream_line = line.strip()
            rest = m.group(2)
            size = _RE_SIZE.search(rest)
            if size:
                res.width, res.height = int(size.group(1)), int(size.group(2))
            fps = _RE_FPS.search(rest)
            if fps:
                res.fps = float(fps.group(1))
            continue
        a = _RE_AUDIO.search(line)
        if a and not res.audio:
            res.audio = a.group(1)

    if res.codec:
        res.ok = True
        return res

    # Không có dòng Video nào → lấy vài dòng cuối của ffprobe làm lý do, đừng nuốt lỗi.
    tail = [ln.strip() for ln in text.strip().splitlines() if ln.strip()][-3:]
    res.error = " | ".join(tail) or "ffprobe không trả về thông tin luồng nào"
    return res


def snapshot(url: str, out_path: Path, ffmpeg: str = "", timeout: float = SNAPSHOT_TIMEOUT,
             username: str = "", password: str = "") -> str:
    """Lấy MỘT khung hình ra jpg.

    Thay cho việc nhúng player vào app: nhìn thấy hình là đủ chứng minh "đã kết nối được thiết
    bị", mà không phải nuôi một bộ giải mã trong tiến trình GUI. Ghi ra file tạm rồi mới đổi tên
    (os.replace là thao tác nguyên tử) để GUI không bao giờ đọc phải file đang viết dở.

    Trả về chuỗi lỗi, rỗng là thành công.
    """
    tool = find_tool("ffmpeg", ffmpeg)
    if not tool:
        return f"Không tìm thấy {where_looked('ffmpeg')}"
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".tmp.jpg")
    cmd = [
        tool, "-hide_banner", "-v", "error",
        "-rtsp_transport", "tcp",
        "-i", with_credentials(url, username, password),
        "-frames:v", "1",
        "-q:v", "5",
        "-y", str(tmp),
    ]
    try:
        cp = subprocess.run(
            cmd, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE,
            timeout=timeout, env=_child_env(), **_spawn_kwargs(),
        )
    except subprocess.TimeoutExpired:
        tmp.unlink(missing_ok=True)
        return f"Chụp ảnh quá {timeout:.0f}s không xong"
    except OSError as exc:
        return f"Không chạy được ffmpeg: {exc}"

    if cp.returncode != 0 or not tmp.exists() or tmp.stat().st_size == 0:
        tmp.unlink(missing_ok=True)
        err = mask_url(cp.stderr.decode("utf-8", "replace")).strip().splitlines()
        return err[-1] if err else f"ffmpeg thoát mã {cp.returncode}"
    try:
        os.replace(tmp, out_path)
    except OSError as exc:
        # Windows từ chối thay file đang bị mở (giao diện vừa đọc ảnh, antivirus đang quét...).
        # Không sao, tấm sau đè lên — miễn là đừng ném ngoại lệ ra làm chết luồng chụp ảnh.
        return f"Không thay được ảnh cũ: {exc}"
    return ""


# ---------------------------------------------------------------------------
# 2. GHI — cấu hình, thống kê, bộ ghi
# ---------------------------------------------------------------------------

@dataclass
class RecordConfig:
    """Cấu hình một camera. Mặc định KHÔNG ghi liên tục — xem chú thích `mode`."""

    name: str = "cam1"
    url: str = ""
    # Khai riêng thay vì bắt người dùng tự ghép vào URL: mật khẩu camera hay có ký tự đặc biệt,
    # ghép tay là URL vỡ. Chỉ nằm trong bộ nhớ — tool không lưu cấu hình ra đĩa.
    username: str = ""
    password: str = ""

    # Chỉ để HỎI camera lấy URL RTSP (xem onvif_client.py) — lúc ghi thì ffmpeg chỉ dùng `url`.
    # Ghi lại vào manifest vì với camera đa cảm biến, "đoạn này quay bằng mắt thường hay mắt
    # nhiệt" là thông tin không suy ra được từ file video.
    onvif_url: str = ""
    profile_token: str = ""
    profile_name: str = ""

    root: Path = field(default_factory=lambda: Path.home() / "camera_recordings")

    # Camera tốn gấp cả nghìn lần cảm biến text (1080p ~21 GB/ngày), mà mục đích là thu MẪU để
    # phân tích chứ không phải bằng chứng liên tục → mặc định lấy mẫu 5 phút mỗi 30 phút.
    #
    # SESSION và CONTINUOUS chạy giống hệt nhau (ghi tới khi bấm dừng); khác nhau ở CHỦ ĐÍCH,
    # và chủ đích đó được ghi vào manifest để lúc phân tích biết quãng này là người vận hành chủ
    # động bật hay là chế độ ghi suốt. Giao diện cũng chỉ cảnh báo dung lượng với CONTINUOUS.
    mode: str = MODE_SAMPLE
    on_minutes: float = 5.0
    every_minutes: float = 30.0

    segment_seconds: int = SEGMENT_SECONDS

    # HAI TẦNG GIỚI HẠN, cái nào chạm trước thì dừng. Tầng hai bảo vệ gateway/DB dùng chung ổ.
    quota_gb: float = 50.0
    min_free_gb: float = 20.0
    ring: bool = False  # "vòng tròn": xoá đoạn cũ nhất ghi tiếp. MẶC ĐỊNH TẮT — xoá dữ liệu
                        # phải là quyết định của người vận hành, không phải mặc định của tool.

    snapshot_seconds: int = 30  # 0 = tắt ảnh chụp định kỳ
    # Tự ghi ngay khi mở app. Cùng với việc cho app chạy lúc Windows khởi động, đây là cách duy
    # nhất để tàu MẤT ĐIỆN xong tự thu tiếp mà không cần ai ra bấm nút.
    autostart: bool = False
    ffmpeg: str = ""

    @property
    def effective_url(self) -> str:
        """URL thật đưa cho ffmpeg — đã kèm credential. Đừng đem đi log, dùng `url` cho việc đó."""
        return with_credentials(self.url, self.username, self.password)

    @property
    def cam_dir(self) -> Path:
        return Path(self.root) / safe_name(self.name)

    @property
    def manifest_path(self) -> Path:
        return self.cam_dir / "manifest.jsonl"

    @property
    def snapshot_path(self) -> Path:
        return self.cam_dir / "snapshot.jpg"

    def mode_text(self) -> str:
        if self.mode == MODE_SAMPLE:
            return f"Lấy mẫu {self.on_minutes:g} phút mỗi {self.every_minutes:g} phút"
        return MODE_LABELS.get(self.mode, self.mode)


@dataclass
class RecorderStats:
    """Ảnh chụp trạng thái cho GUI đọc (GUI hỏi theo nhịp, không cần signal riêng)."""

    name: str = ""
    running: bool = False
    recording: bool = False
    state: str = "Đã dừng"
    alarm: str = ""
    used_bytes: int = 0
    quota_bytes: int = 0
    free_bytes: int = 0
    min_free_bytes: int = 0
    segments: int = 0
    gaps: int = 0
    reconnects: int = 0   # số lần phải nối lại — đường truyền phập phù thì số này leo nhanh
    gb_per_day: float = 0.0
    days_left: float = -1.0   # -1 = chưa đo đủ để nói
    last_segment: str = ""
    open_segment: str = ""    # đoạn đang ghi dở — chưa vào manifest vì chưa đóng
    open_bytes: int = 0


class CameraRecorder:
    """Ghi RTSP thành từng đoạn mp4, kèm manifest, hạn mức dung lượng và tự nối lại.

    Một luồng chính điều phối: canh cửa sổ lấy mẫu → chạy ffmpeg → theo dõi → nối lại. Thêm hai
    luồng phụ: một đọc stderr của ffmpeg (BẮT BUỘC, xem `_drain`), một chụp ảnh định kỳ.

    ffmpeg đọc THẲNG RTSP của camera chứ không qua go2rtc: bản ghi phải độc lập với việc xem.
    `-c copy` chép nguyên luồng đã nén, không giải mã rồi mã lại — CPU gần như bằng 0 và hình
    giữ đúng chất lượng gốc. Máy trên tàu còn chạy gateway, log cảm biến, database.
    """

    def __init__(self, cfg: RecordConfig, on_log=None) -> None:
        self.cfg = cfg
        self._on_log = on_log

        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._snap_thread: threading.Thread | None = None
        self._proc: subprocess.Popen | None = None

        self._mlock = threading.Lock()
        self._stderr_tail: deque = deque(maxlen=40)
        self._ff_progress = ""   # mốc tiến độ ffmpeg tự báo, xem _drain_progress
        self._ff_marks: dict = {}
        self._seen: set = set()

        # Khoảng ĐỨT đang mở. Thiếu thông tin này thì lúc phân tích không phân biệt được
        # "mất dữ liệu" với "vốn không ghi".
        self._gap_start: datetime | None = None
        self._gap_reasons: list = []
        self._gap_priority = 0

        self._state = "Đã dừng"
        self._alarm = ""
        self._recording = False
        self._blocked = False
        self._used = 0
        self._free = 0
        self._segments = 0
        self._gaps = 0
        self._reconnects = 0
        self._burst_had_data = False
        self._unreachable = 0
        self._last_segment = ""
        self._last_quota = 0.0
        self._last_measure = 0.0
        self._first_burst = True
        self._open_seg = ("", 0)  # (tên, kích thước) đoạn ĐANG ghi dở
        self._samples: deque = deque(maxlen=300)  # (thời điểm, dung lượng) đo tốc độ tăng thật
        self._tz_warned = False

    # --- Vòng đời --------------------------------------------------------

    def start(self) -> None:
        if self._thread and self._thread.is_alive():
            return
        self.cfg.cam_dir.mkdir(parents=True, exist_ok=True)
        self._stop.clear()
        self._first_burst = True
        self._seen = self._seen_from_manifest()
        self._thread = threading.Thread(target=self._guard, args=(self._run, "ghi hình"),
                                        name=f"rec-{self.cfg.name}", daemon=True)
        self._thread.start()
        if self.cfg.snapshot_seconds > 0:
            self._snap_thread = threading.Thread(
                target=self._guard, args=(self._snapshot_loop, "chụp ảnh"),
                name=f"snap-{self.cfg.name}", daemon=True)
            self._snap_thread.start()

    def _guard(self, func, what: str) -> None:
        """Bọc luồng nền: một lỗi không lường trước phải để lại DẤU VẾT.

        App chạy suốt chuyến đi một tháng. Luồng chết vì ngoại lệ mà không ai biết thì giao diện
        vẫn hiện trạng thái cũ, còn bản ghi thì ngừng từ lúc nào không hay.
        """
        try:
            func()
        except Exception as exc:  # noqa: BLE001 — cố tình bắt hết
            import traceback
            self._log("error", f"Luồng {what} chết vì lỗi không lường trước: {exc}")
            self._log("error", traceback.format_exc().replace("\n", " | "))
            self._set_state(f"LỖI — luồng {what} đã dừng")

    def stop(self, join: bool = True) -> None:
        self._stop.set()
        _shutdown_ffmpeg(self._proc)
        if join and self._thread:
            self._thread.join(timeout=SHUTDOWN_GRACE + 10)

    def is_running(self) -> bool:
        return bool(self._thread and self._thread.is_alive())

    def stats(self) -> RecorderStats:
        quota = int(self.cfg.quota_gb * GB)
        min_free = int(self.cfg.min_free_gb * GB)
        rate = self._rate_gb_per_day()
        headroom = min(quota - self._used, self._free - min_free)
        days = headroom / GB / rate if rate > 0.01 and headroom > 0 else -1.0
        return RecorderStats(
            name=self.cfg.name,
            running=self.is_running(),
            recording=self._recording,
            state=self._state,
            alarm=self._alarm,
            used_bytes=self._used,
            quota_bytes=quota,
            free_bytes=self._free,
            min_free_bytes=min_free,
            segments=self._segments,
            gaps=self._gaps,
            reconnects=self._reconnects,
            gb_per_day=rate,
            days_left=days,
            last_segment=self._last_segment,
            open_segment=self._open_seg[0] if self._recording else "",
            open_bytes=self._open_seg[1] if self._recording else 0,
        )

    # --- Log -------------------------------------------------------------

    def _log(self, level: str, text: str) -> None:
        """Ghi ra file xoay vòng theo ngày, đồng thời đẩy lên GUI qua callback.

        File là bản đầy đủ: ô log trên GUI chỉ giữ 2000 dòng gần nhất, mà sự cố lúc 3 giờ sáng
        thì sáng ra đã trôi khỏi ô log từ lâu.
        """
        now = _utc_now()
        # Chốt chặn DUY NHẤT cho mật khẩu: mọi dòng — kể cả stderr thô của ffmpeg, vốn nhắc lại
        # nguyên URL đầu vào — đều chui qua đây trước khi ra file log và giao diện.
        text = mask_url(text)
        line = f"[{_stamp(now)}] [{level.upper():5}] {text}"
        try:
            log_dir = self.cfg.cam_dir / "log"
            log_dir.mkdir(parents=True, exist_ok=True)
            with open(log_dir / f"{now:%Y-%m-%d}.log", "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except Exception:
            pass  # không ghi được log thì cũng không được làm sập việc ghi hình
        if self._on_log:
            try:
                self._on_log(level, text)
            except Exception:
                pass

    def _set_state(self, text: str) -> None:
        self._state = text

    # --- Manifest --------------------------------------------------------

    def _manifest_write(self, entry: dict) -> None:
        entry["cam"] = self.cfg.name
        try:
            with self._mlock:
                with open(self.cfg.manifest_path, "a", encoding="utf-8") as f:
                    f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as exc:
            self._log("error", f"Không ghi được manifest: {exc}")

    def _seen_from_manifest(self) -> set:
        """Nạp danh sách đoạn ĐÃ ghi vào manifest, và xem lần chạy trước kết thúc thế nào.

        Không phải để tránh trùng cho vui: app khởi động lại thì các file cũ vẫn nằm đó, quét
        lại sẽ nhân đôi manifest. Ngược lại, đoạn cuối của lần chạy trước bị crash chưa kịp ghi
        manifest thì lần này quét thấy và bổ sung — đúng cái ta muốn.

        Tiện thể ghi nhận phiên trước có đóng tử tế không: thiếu bản ghi "session stop" nghĩa là
        app chết đột ngột (mất điện, bị kết thúc cưỡng bức).
        """
        seen: set = set()
        self._prev_unclean = False
        self._prev_last_end = None
        path = self.cfg.manifest_path
        if not path.exists():
            return seen
        try:
            with open(path, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        obj = json.loads(line)
                    except ValueError:
                        continue
                    kind = obj.get("type")
                    if kind == "segment" and obj.get("file"):
                        seen.add(obj["file"])
                        self._prev_last_end = obj.get("end") or self._prev_last_end
                    elif kind == "gap":
                        self._prev_last_end = obj.get("end") or self._prev_last_end
                    elif kind == "session":
                        # Phiên mở mà không thấy đóng → lần chạy trước chết giữa chừng.
                        self._prev_unclean = obj.get("event") == "start"
        except Exception as exc:
            self._log("warn", f"Không đọc được manifest cũ ({exc}) — bỏ qua, ghi tiếp")
        return seen

    def _open_gap(self, reason: str, priority: int = 1) -> None:
        """Mở (hoặc bổ sung lý do cho) khoảng đứt đang chạy.

        Một khoảng đứt hay có NHIỀU lý do nối nhau: hết cửa sổ lấy mẫu → tới lượt ghi thì camera
        lại mất. Nếu chỉ giữ lý do đầu tiên, manifest sẽ ghi "ngoài cửa sổ lấy mẫu" cho cả quãng
        và giấu mất chuyện MẤT DỮ LIỆU — đúng thứ mà manifest sinh ra để phân biệt. Nên lý do
        nặng hơn (priority lớn hơn) được đẩy lên làm lý do chính, các lý do khác vẫn giữ đủ.
        """
        if self._gap_start is None:
            self._gap_start = _utc_now()
            self._gap_reasons = [reason]
            self._gap_priority = priority
            return
        if reason not in self._gap_reasons:
            self._gap_reasons.append(reason)
        if priority > self._gap_priority:
            self._gap_priority = priority
            self._gap_reasons.remove(reason)
            self._gap_reasons.insert(0, reason)

    def _close_gap(self, end: datetime) -> None:
        if self._gap_start is None:
            return
        start = self._gap_start
        reasons = self._gap_reasons or ["không rõ"]
        self._gap_start = None
        self._gap_reasons = []
        self._gap_priority = 0
        if end <= start:
            end = _utc_now()
        seconds = (end - start).total_seconds()
        if seconds < 5:
            # Vài giây bắt tay RTSP hoặc khe hở lúc đổi đoạn — không phải mất dữ liệu. Ghi vào
            # manifest chỉ tổ lấp đầy bằng nhiễu, đúng lúc cần tìm sự cố thật thì khó thấy.
            return
        self._gaps += 1
        self._manifest_write({
            "type": "gap",
            "start": _stamp(start),
            "end": _stamp(end),
            "seconds": round(seconds, 1),
            "reason": reasons[0],
            "reasons": reasons,
        })
        self._log("warn", f"Khoảng đứt {human_secs(seconds)} ({' + '.join(reasons)}) "
                          f"từ {_stamp(start)} đến {_stamp(end)}")

    # --- Quét đoạn đã đóng ----------------------------------------------

    def _segment_files(self) -> list:
        """Mọi đoạn trên đĩa, xếp theo thứ tự thời gian (tên file là mốc UTC nên sort được)."""
        files = []
        try:
            for day in sorted(p for p in self.cfg.cam_dir.iterdir()
                              if p.is_dir() and _DAY_RE.match(p.name)):
                files.extend(sorted(day.glob("seg_*.mp4")))
        except FileNotFoundError:
            pass
        return files

    def _scan_segments(self, final: bool = False) -> None:
        """Ghi vào manifest những đoạn đã ĐÓNG.

        Đoạn mới nhất là file ffmpeg đang viết dở — kích thước còn thay đổi nên chưa ghi. Khi
        tiến trình đã thoát (`final=True`) thì mọi file đều đóng, quét nốt.
        """
        files = self._segment_files()
        if not final:
            files = files[:-1]
        for path in files:
            key = self._rel(path)
            if key in self._seen:
                continue
            self._seen.add(key)
            self._read_segment(path, key)

    def _rel(self, path: Path) -> str:
        try:
            return path.relative_to(self.cfg.cam_dir).as_posix()
        except ValueError:
            return path.as_posix()

    def _read_segment(self, path: Path, key: str) -> None:
        try:
            st = path.stat()
        except OSError:
            return
        end = datetime.fromtimestamp(st.st_mtime, timezone.utc)
        start = _parse_seg_time(path.name)
        # Kiểm tra chéo: nếu TZ=UTC0 không có tác dụng với bản ffmpeg đang dùng thì tên file là
        # giờ máy và mốc thời gian sai hẳn vài tiếng. Thà suy ngược từ mtime còn hơn ghi sai.
        if start is None or abs((end - start).total_seconds()) > 6 * 3600:
            if not self._tz_warned:
                self._tz_warned = True
                self._log("warn", "Tên file không khớp giờ UTC — ffmpeg không nhận TZ. "
                                  "Mốc thời gian trong manifest suy từ thời điểm sửa file.")
            start = end - timedelta(seconds=self.cfg.segment_seconds)

        self._segments += 1
        self._last_segment = key
        self._manifest_write({
            "type": "segment",
            "file": key,
            "start": _stamp(start),
            "end": _stamp(end),
            "seconds": round(max(0.0, (end - start).total_seconds()), 1),
            "bytes": st.st_size,
        })
        self._close_gap(start)  # đoạn đầu tiên sau khi nối lại chính là lúc khoảng đứt kết thúc

    # --- Hạn mức dung lượng ---------------------------------------------

    def _dir_size(self) -> int:
        """Dung lượng thư mục camera.

        Đoạn ĐANG ghi dở gần như không được tính: Windows chỉ cập nhật kích thước trong mục thư
        mục lúc đóng file (xem `_drain_progress`). Nghĩa là con số này trễ tối đa một đoạn — vài
        chục MB với đoạn 5 phút, không đáng kể so với hạn mức tính bằng GB, và tự đúng lại mỗi
        lần đoạn được đóng. Tầng bảo vệ thứ hai (sàn dung lượng trống của ổ) thì luôn chính xác
        vì hỏi thẳng hệ điều hành.
        """
        total = 0
        for root, _dirs, names in os.walk(self.cfg.cam_dir):
            for n in names:
                try:
                    total += os.path.getsize(os.path.join(root, n))
                except OSError:
                    pass
        return total

    def _rate_gb_per_day(self) -> float:
        """Tốc độ tăng ĐO TỪ THỰC TẾ, không phải ước lượng theo bitrate."""
        if len(self._samples) < 2:
            return 0.0
        t0, u0 = self._samples[0]
        t1, u1 = self._samples[-1]
        span = t1 - t0
        if span < 600 or u1 <= u0:  # dưới 10 phút thì con số chưa có nghĩa
            return 0.0
        return (u1 - u0) / span * 86400 / GB

    def _measure(self, force: bool = False) -> None:
        """Đo dung lượng đã dùng và chỗ trống của ổ. Chỉ ĐO, không phán xét."""
        if not force and time.monotonic() - self._last_measure < MEASURE_SECONDS:
            return
        self._last_measure = time.monotonic()
        self._used = self._dir_size()
        try:
            self._free = shutil.disk_usage(self.cfg.cam_dir).free
        except OSError:
            self._free = 0
        self._samples.append((time.time(), self._used))

    def _quota_tick(self, force: bool = False) -> bool:
        """Kiểm tra hạn mức. Trả về True nghĩa là PHẢI dừng ghi.

        Nhịp bám theo ĐỘ DÀI ĐOẠN chứ không phải một con số cố định: dung lượng chỉ nhích lên
        mỗi khi có đoạn mới, nên quét dày hơn là phí; nhưng ai đó đặt đoạn 30 giây mà vẫn 5 phút
        mới kiểm tra một lần thì lúc phát hiện đã vượt hạn mức cả chục đoạn.
        """
        self._measure()  # số liệu tươi cho giao diện, không dính tới việc xét ngưỡng

        interval = max(30, min(self.cfg.segment_seconds, QUOTA_CHECK_SECONDS))
        if not force and time.monotonic() - self._last_quota < interval:
            return self._blocked
        self._last_quota = time.monotonic()
        self._measure(force=True)

        used, free = self._used, self._free
        quota = int(self.cfg.quota_gb * GB)
        min_free = int(self.cfg.min_free_gb * GB)
        over = used >= quota
        low = free <= min_free

        # Vòng tròn dọn theo CẢ HAI ngưỡng: hạn mức camera và sàn trống của ổ. Người vận hành
        # bật nó lên là muốn "ghi mãi, luôn giữ cái mới nhất" — dừng vì ổ sắp đầy thì đúng cái
        # họ không muốn. Chặn đà xoá bằng RING_KEEP_MINUTES, xem _prune.
        if (over or low) and self.cfg.ring:
            freed = self._prune(quota, min_free)
            if freed:
                used = self._used = self._dir_size()
                try:
                    free = self._free = shutil.disk_usage(self.cfg.cam_dir).free
                except OSError:
                    pass
                over, low = used >= quota, free <= min_free

        if over or low:
            reason = (f"chạm hạn mức camera ({human_bytes(used)}/{self.cfg.quota_gb:g} GB)"
                      if over else
                      f"ổ đĩa chỉ còn trống {human_bytes(free)} (sàn {self.cfg.min_free_gb:g} GB)")
            if not self._blocked:
                self._log("error", f"DỪNG GHI — {reason}. "
                                   f"Không tự xoá gì cả; dọn bớt hoặc bật chế độ vòng tròn.")
            self._alarm = reason
            self._blocked = True
        else:
            if self._blocked:
                self._log("info", f"Dung lượng đã ổn ({human_bytes(used)} dùng, "
                                  f"{human_bytes(free)} trống) — ghi tiếp")
            self._alarm = ""
            self._blocked = False
        return self._blocked

    def _prune(self, quota: int, min_free: int) -> int:
        """Chế độ vòng tròn: xoá đoạn CŨ NHẤT để luôn giữ được hình mới nhất.

        Dọn theo cả hạn mức camera lẫn sàn trống của ổ, chừa 10% để không phải xoá lại ngay ở
        lần kiểm tra kế tiếp, và không bao giờ đụng file mới nhất (ffmpeg đang viết, Windows còn
        khoá file đó).

        GIỚI HẠN CỨNG: luôn chừa lại RING_KEEP_MINUTES phút gần nhất. Xoá tới mức đó mà ổ vẫn
        không đủ chỗ nghĩa là chỗ trống bị thứ khác ăn — xoá tiếp chỉ mất nốt hình vừa quay mà
        vẫn phải dừng. Lúc đó để `_quota_tick` báo động cho người xử lý.
        """
        files = self._segment_files()[:-1]
        keep = max(2, int(RING_KEEP_MINUTES * 60 / max(1, self.cfg.segment_seconds)))
        if len(files) <= keep:
            return 0
        files = files[:-keep]  # chỉ đụng phần cũ hơn khoảng giữ lại
        freed = 0
        target_used = quota * 0.9
        target_free = min_free * 1.1
        used = self._used
        free = self._free
        for path in files:
            if used < target_used and free > target_free:
                break
            try:
                size = path.stat().st_size
                path.unlink()
            except OSError as exc:
                self._log("warn", f"Không xoá được {path.name}: {exc}")
                continue
            key = self._rel(path)
            self._seen.discard(key)
            used -= size
            free += size
            freed += size
            self._manifest_write({"type": "pruned", "file": key, "bytes": size,
                                  "at": _stamp(_utc_now())})
        if freed:
            self._log("warn", f"Vòng tròn: đã xoá {human_bytes(freed)} đoạn cũ nhất")
            for day in list(self.cfg.cam_dir.iterdir()):
                if day.is_dir() and _DAY_RE.match(day.name) and not any(day.iterdir()):
                    try:
                        day.rmdir()
                    except OSError:
                        pass
        return freed

    # --- Cửa sổ lấy mẫu --------------------------------------------------

    def _sample_window(self) -> tuple:
        """(đang trong cửa sổ ghi?, số giây còn lại của trạng thái hiện tại).

        Neo theo đồng hồ tuyệt đối chứ không theo lúc bấm nút: 5 phút mỗi 30 phút thì luôn rơi
        vào phút 00–05 và 30–35, đoán được và không lệch đi sau mỗi lần app khởi động lại.
        """
        if self.cfg.mode != MODE_SAMPLE:
            return True, 0.0
        period = max(self.cfg.every_minutes, 0.1) * 60
        on = max(self.cfg.on_minutes, 0.1) * 60
        if on >= period:
            return True, 0.0
        pos = time.time() % period
        if pos < on:
            return True, on - pos
        return False, period - pos

    # --- Vòng chạy chính -------------------------------------------------

    def _run(self) -> None:
        cfg = self.cfg
        self._log("info", f"Bắt đầu phiên — {cfg.mode_text()}, đoạn {cfg.segment_seconds}s, "
                          f"hạn mức {cfg.quota_gb:g} GB, sàn trống {cfg.min_free_gb:g} GB"
                          + (", vòng tròn BẬT" if cfg.ring else ""))
        self._log("info", f"Thư mục: {cfg.cam_dir}")
        self._manifest_write({
            "type": "session", "event": "start", "at": _stamp(_utc_now()),
            "url": mask_url(cfg.effective_url), "mode": cfg.mode,
            "on_minutes": cfg.on_minutes, "every_minutes": cfg.every_minutes,
            "segment_seconds": cfg.segment_seconds,
            "profile_token": cfg.profile_token, "profile_name": cfg.profile_name,
        })
        # Lần chạy trước chết giữa chừng → ghi thẳng khoảng đứt cho quãng máy nằm im. Không có
        # dòng này thì manifest chỉ có một chỗ trống câm lặng, và lúc phân tích không phân biệt
        # được "tàu mất điện" với "chưa từng ghi".
        if getattr(self, "_prev_unclean", False) and self._prev_last_end:
            try:
                start = datetime.strptime(self._prev_last_end, "%Y-%m-%dT%H:%M:%SZ").replace(
                    tzinfo=timezone.utc)
            except ValueError:
                start = None
            if start:
                seconds = (_utc_now() - start).total_seconds()
                if seconds >= 5:
                    self._gaps += 1
                    self._manifest_write({
                        "type": "gap", "start": _stamp(start), "end": _stamp(_utc_now()),
                        "seconds": round(seconds, 1),
                        "reason": "app dừng đột ngột (mất điện hoặc bị kết thúc)",
                        "reasons": ["app dừng đột ngột (mất điện hoặc bị kết thúc)"],
                    })
                    self._log("warn", f"Phiên trước không đóng tử tế — bù khoảng đứt "
                                      f"{human_secs(seconds)} kể từ {self._prev_last_end}")

        self._open_gap("phiên vừa bắt đầu")
        self._quota_tick(force=True)
        backoff = BACKOFF_START

        while not self._stop.is_set():
            if self._quota_tick():
                self._set_state(f"DỪNG — {self._alarm}")
                # Ghi ĐÚNG lý do vào khoảng đứt: "không có dữ liệu vì hết chỗ" khác hẳn "không
                # có dữ liệu vì ngoài giờ lấy mẫu", và người phân tích cần phân biệt được.
                self._open_gap("chạm hạn mức dung lượng", 2)
                if self._stop.wait(60):
                    break
                self._quota_tick(force=True)  # người vận hành có thể vừa dọn ổ
                continue

            on, remain = self._sample_window()
            # Lượt đầu tiên thì ghi NGAY, không chờ tới cửa sổ tròn giờ. Người vận hành bấm Ghi
            # là muốn thấy nó chạy: chờ tới 25 phút mới nhúc nhích thì ai cũng tưởng hỏng, chưa
            # kể đây là lúc cần biết ngay camera có ghi được thật hay không.
            if self._first_burst and self.cfg.mode == MODE_SAMPLE:
                on, remain = True, self.cfg.on_minutes * 60
            if not on:
                self._set_state(f"Chờ cửa sổ lấy mẫu (còn {human_secs(remain)})")
                self._stop.wait(min(remain, 5.0))  # tick 5s để GUI đếm ngược cho mượt
                continue

            deadline = time.monotonic() + remain if remain > 0 else None
            self._first_burst = False
            began = time.monotonic()
            reason = self._record_burst(deadline)
            ran = time.monotonic() - began

            if reason not in ("died", "stall", "unreachable"):
                backoff = BACKOFF_START
                continue

            if reason == "unreachable":
                # Không nối được thì đừng đếm là "mất kết nối lần N" và đừng bơm log:
                # ca này lặp lại mỗi vài giây suốt thời gian camera còn nằm im.
                self._open_gap("mất kết nối camera", 3)
                self._stop.wait(backoff)
                backoff = min(backoff * 2, BACKOFF_MAX)
                continue
            if reason == "stall":
                kind, detail = "conn", f"đứng hình quá {STALL_SECONDS:.0f}s"
            else:
                kind, detail = self._classify_death()
            if kind == "disk":
                self._alarm = "ffmpeg chết vì ĐẦY ĐĨA"
                self._blocked = True
                self._log("error", f"ffmpeg chết vì ĐẦY ĐĨA ({detail}) — dừng ghi, KHÔNG nối lại. "
                                   f"Dọn ổ rồi tool tự ghi tiếp.")
                continue
            self._reconnects += 1
            # Phân biệt MẠNG CHẬP CHỜN với CAMERA KHÔNG TỚI ĐƯỢC.
            #
            # Lượt vừa rồi có ghi được byte nào không mới là câu trả lời. Có nghĩa là camera có
            # thật, đường tới nó có thật, chỉ là phập phù — thử lại NGAY (5s) để vớt được càng
            # nhiều hình càng tốt. Chờ 60 giây trong ca này là tự nguyện mất 60 giây hình mỗi
            # lần rớt. Còn nếu không ghi được gì (sai URL, camera mất điện, đứt cáp) thì mới
            # giãn dần ra cho khỏi quần cả camera lẫn log.
            if self._burst_had_data or ran >= HEALTHY_SECONDS:
                backoff = BACKOFF_START
            self._log("warn", f"Mất kết nối lần {self._reconnects} sau {human_secs(ran)} "
                              f"({detail}) — nối lại sau {backoff:.0f}s")
            self._set_state(f"Mất kết nối — nối lại sau {backoff:.0f}s")
            self._stop.wait(backoff)
            if not self._burst_had_data:
                backoff = min(backoff * 2, BACKOFF_MAX)

        self._scan_segments(final=True)
        self._close_gap(_utc_now())
        self._manifest_write({"type": "session", "event": "stop", "at": _stamp(_utc_now()),
                              "segments": self._segments, "gaps": self._gaps})
        self._recording = False
        self._set_state("Đã dừng")
        self._log("info", f"Kết thúc phiên — {self._segments} đoạn, {self._gaps} khoảng đứt, "
                          f"{human_bytes(self._used)}")

    def _ffmpeg_cmd(self) -> list:
        cfg = self.cfg
        # Thư mục con theo NGÀY: 30 ngày × 5 phút = 8.640 file/camera, dồn một chỗ thì mỗi lần
        # liệt kê là một lần treo giao diện.
        pattern = str(cfg.cam_dir / "%Y-%m-%d" / "seg_%Y%m%d_%H%M%S.mp4")
        return [
            find_tool("ffmpeg", cfg.ffmpeg) or "ffmpeg",
            "-hide_banner", "-v", "error",
            # Bắt ffmpeg tự báo tiến độ ra stdout. Đây là NGUỒN DUY NHẤT đáng tin để biết nó có
            # đang ghi thật hay không: đã đo trên camera Hikvision, kích thước file đang ghi dở
            # đứng nguyên 28 byte suốt 60 giây (Windows chỉ cập nhật mục thư mục lúc đóng file),
            # nên nhìn file mà đoán thì cứ mỗi 60 giây lại tưởng đứt và giết nhầm ffmpeg — với
            # đoạn 5 phút thì không đoạn nào sống nổi tới lúc được đóng.
            "-progress", "pipe:1",
            "-nostats",
            # TCP cho RTSP: UDP mất gói làm hỏng khung, mà bản ghi thì không có cơ hội ghi lại.
            "-rtsp_transport", "tcp",
            # Kèm sẵn user/mật khẩu. Lưu ý: dòng lệnh của tiến trình con ai xem Task Manager
            # cũng thấy — đây là giới hạn cố hữu của cách xác thực RTSP, không né được.
            "-i", cfg.effective_url,
            # Chép nguyên luồng đã nén — không chuyển mã (xem chú thích của lớp).
            "-c", "copy",
            # BỎ TIẾNG. Không phải để tiết kiệm: rất nhiều camera IP phát tiếng G.711
            # (pcm_alaw/pcm_mulaw) mà mp4 KHÔNG chứa được, ffmpeg sẽ chết ngay giây đầu với
            # "Could not find tag for codec pcm_alaw". Giám sát cũng không cần tiếng.
            "-an",
            "-f", "segment",
            "-segment_time", str(cfg.segment_seconds),
            # Cắt tại khung khoá → mỗi file mở được độc lập, không phụ thuộc file trước.
            "-reset_timestamps", "1",
            "-strftime", "1",
            # MP4 PHÂN MẢNH — bắt buộc, không phải tuỳ chọn tối ưu. MP4 thường chỉ ghi bảng chỉ
            # mục (moov) khi ĐÓNG file, nên đoạn đang ghi dở không trình phát nào mở được
            # ("moov atom not found"). Mà đoạn dở là chuyện thường: mất kết nối, mất điện, app
            # bị giết — mỗi lần như vậy mất trắng tới 5 phút hình, đúng quãng hay cần xem nhất.
            "-segment_format", "mp4",
            "-segment_format_options",
            "movflags=+frag_keyframe+empty_moov+default_base_moof",
            pattern,
        ]

    def _ensure_day_dirs(self) -> None:
        """Tạo sẵn thư mục ngày HÔM NAY và NGÀY MAI (giờ UTC).

        ffmpeg không tự tạo thư mục cho pattern strftime; ca ghi vắt qua nửa đêm mà thiếu thư
        mục là ffmpeg chết ngay tại thời khắc đó — kiểu lỗi chỉ lộ ra sau vài ngày chạy.
        """
        now = _utc_now()
        for d in (now, now + timedelta(days=1)):
            try:
                (self.cfg.cam_dir / f"{d:%Y-%m-%d}").mkdir(parents=True, exist_ok=True)
            except OSError as exc:
                self._log("error", f"Không tạo được thư mục ngày: {exc}")

    def _record_burst(self, deadline) -> str:
        """Chạy MỘT lượt ffmpeg.

        Trả về lý do kết thúc: died (tiến trình thoát) | stall (còn sống mà không ghi gì) |
        stopped (người dùng dừng) | window (hết cửa sổ lấy mẫu) | quota (chạm hạn mức).
        """
        # Gõ cửa trước. Camera chưa lên thì quay ra ngay, khỏi tốn 60 giây chờ ffmpeg treo.
        if not can_reach(self.cfg.effective_url):
            self._burst_had_data = False
            self._unreachable += 1
            if self._unreachable in (1, 3) or self._unreachable % 20 == 0:
                self._log("warn", f"Chưa tới được camera (lần {self._unreachable}) — "
                                  f"{mask_url(self.cfg.url)}")
            self._set_state("Chưa tới được camera — đang thử lại")
            return "unreachable"
        if self._unreachable:
            self._log("info", f"Đã tới được camera trở lại sau {self._unreachable} lần thử")
            self._unreachable = 0

        self._ensure_day_dirs()
        cmd = self._ffmpeg_cmd()
        if not Path(cmd[0]).is_file() and not shutil.which(cmd[0]):
            self._log("error", f"Không tìm thấy {where_looked('ffmpeg')}")
            self._stop.wait(BACKOFF_MAX)
            return "stopped" if self._stop.is_set() else "died"

        try:
            proc = subprocess.Popen(
                cmd,
                stdin=subprocess.PIPE,      # giữ để còn gửi 'q' lúc dừng (xem _shutdown_ffmpeg)
                stdout=subprocess.PIPE,     # dòng tiến độ của -progress
                stderr=subprocess.PIPE,
                env=_child_env(),
                **_spawn_kwargs(),
            )
        except OSError as exc:
            self._log("error", f"Không chạy được ffmpeg: {exc}")
            self._stop.wait(BACKOFF_MAX)
            return "died"

        self._proc = proc
        self._stderr_tail.clear()
        self._ff_progress = ""
        threading.Thread(target=self._drain, args=(proc,),
                         name=f"ffmpeg-err-{self.cfg.name}", daemon=True).start()
        threading.Thread(target=self._drain_progress, args=(proc,),
                         name=f"ffmpeg-prog-{self.cfg.name}", daemon=True).start()
        self._recording = True
        self._set_state("Đang ghi")
        self._log("info", f"ffmpeg đã chạy (pid {proc.pid}) → {mask_url(self.cfg.url)}")

        last_scan = time.monotonic()
        last_day = _utc_now().date()
        last_progress = time.monotonic()
        progress = self._progress_key()
        self._burst_had_data = False  # lượt này có ghi được byte nào không (xem _run)
        reason = "died"
        while True:
            if self._stop.is_set():
                reason = "stopped"
                break
            if proc.poll() is not None:
                reason = "died"
                break
            if deadline is not None and time.monotonic() >= deadline:
                reason = "window"
                break
            now = time.monotonic()
            if now - last_scan >= SCAN_INTERVAL:
                last_scan = now
                self._scan_segments()
                # Watchdog: tiến trình còn sống chưa chắc là đang ghi (xem STALL_SECONDS).
                current = self._progress_key()
                if current != progress:
                    progress = current
                    last_progress = now
                    self._burst_had_data = True
                    self._set_state("Đang ghi")
                elif now - last_progress >= STALL_SECONDS:
                    reason = "stall"
                    break
                elif now - last_progress >= 15:
                    # Nói thật với người dùng trong lúc chờ watchdog: "Đang ghi" mà file không
                    # nhúc nhích thì chữ "Đang ghi" là đang nói dối.
                    self._set_state(f"Đang ghi — {now - last_progress:.0f}s chưa có dữ liệu mới")
            if self._quota_tick():
                reason = "quota"
                break
            today = _utc_now().date()
            if today != last_day:
                last_day = today
                self._ensure_day_dirs()
            time.sleep(0.5)

        if reason == "stall":
            self._log("error", f"ffmpeg còn sống nhưng {STALL_SECONDS:.0f}s không ghi thêm được "
                               f"byte nào — giết và nối lại")
            kill_tree(proc)  # đứng hình thì xin dừng êm cũng vô ích, giết thẳng
        elif reason != "died":
            _shutdown_ffmpeg(proc)  # dừng tử tế để đoạn cuối được đóng trọn vẹn
        self._proc = None
        self._recording = False
        self._scan_segments(final=True)

        # Lý do "mất dữ liệu" (priority 3) phải thắng lý do "vốn không ghi" (priority 1) khi cả
        # hai cùng rơi vào một khoảng đứt — xem _open_gap.
        gap_reason, priority = {
            "stopped": ("người vận hành dừng ghi", 1),
            "window": ("ngoài cửa sổ lấy mẫu", 1),
            "quota": ("chạm hạn mức dung lượng", 2),
            "died": ("mất kết nối camera", 3),
            "stall": ("mất kết nối camera (ffmpeg đứng hình)", 3),
        }[reason]
        self._open_gap(gap_reason, priority)
        if reason == "window":
            self._log("info", "Hết cửa sổ lấy mẫu — tạm dừng tới lượt sau")
        return reason

    def _drain_progress(self, proc: subprocess.Popen) -> None:
        """Đọc dòng `-progress` của ffmpeg, giữ lại mốc tiến độ mới nhất.

        Theo GIÁ TRỊ chứ không phải theo việc có dòng chảy về: camera đơ mà kết nối còn sống thì
        ffmpeg vẫn đều đặn in tiến độ, chỉ là con số đứng yên — đó mới đúng là "không ghi được".
        Cũng phải đọc cho hết, y như stderr: không ai đọc thì ống đầy và ffmpeg treo.
        """
        try:
            for raw in iter(proc.stdout.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line.startswith(("out_time_ms=", "out_time_us=", "total_size=")):
                    key, _, value = line.partition("=")
                    self._ff_marks[key] = value
                    self._ff_progress = "|".join(f"{k}={v}" for k, v in sorted(
                        self._ff_marks.items()))
        except Exception:
            pass
        finally:
            try:
                proc.stdout.close()
            except Exception:
                pass

    def _progress_key(self) -> tuple:
        """Dấu hiệu "đang thực sự ghi".

        Ba nguồn, đổi cái nào cũng tính là còn sống. Nguồn chính là tiến độ ffmpeg tự báo; số
        đoạn và kích thước file chỉ là chỗ dựa phòng khi bản ffmpeg nào đó không hỗ trợ
        `-progress` (kích thước file gần như vô dụng trên Windows, xem `_drain_progress`).
        """
        files = self._segment_files()
        if not files:
            self._open_seg = ("", 0)
            return (0, 0, self._ff_progress)
        try:
            size = files[-1].stat().st_size
        except OSError:
            size = -1
        # File mới nhất chính là file ffmpeg đang viết — giữ lại để giao diện nói được "đang ghi
        # dở cái này", thay vì báo 0 đoạn suốt 5 phút đầu làm người dùng tưởng hỏng.
        self._open_seg = (files[-1].name, max(0, size))
        return (len(files), size, self._ff_progress)

    def _drain(self, proc: subprocess.Popen) -> None:
        """Đọc stderr của ffmpeg trên luồng riêng.

        BẮT BUỘC phải có: không ai đọc thì đường ống đầy (~64KB) và ffmpeg TREO CỨNG — luồng
        đứng hình sau vài giờ chạy tốt, không lỗi, không thoát, không ai biết. Tiện thể giữ vài
        chục dòng cuối để nói được LÝ DO khi tiến trình chết.
        """
        try:
            for raw in iter(proc.stderr.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if not line:
                    continue
                self._stderr_tail.append(line)
                self._log("ffmpeg", line)
        except Exception:
            pass  # tiến trình đã đóng
        finally:
            try:
                proc.stderr.close()
            except Exception:
                pass

    def _classify_death(self) -> tuple:
        """Phân biệt ffmpeg chết vì ĐẦY ĐĨA với chết vì MẤT KẾT NỐI — hai cách xử lý khác nhau."""
        tail = " | ".join(self._stderr_tail) or "(ffmpeg không nói gì)"
        try:
            free = shutil.disk_usage(self.cfg.cam_dir).free
        except OSError:
            free = -1
        # Ổ gần cạn là bằng chứng mạnh hơn cả thông báo lỗi: nhiều lỗi ghi file bị ffmpeg báo
        # bằng những câu chẳng liên quan gì tới dung lượng.
        if 0 <= free < 200 * 1024 * 1024:
            return "disk", f"ổ chỉ còn {human_bytes(free)}"
        if _DISK_FULL_RE.search(tail):
            return "disk", tail[-200:]
        if _AUTH_RE.search(tail):
            return "auth", "camera từ chối xác thực — kiểm tra user/mật khẩu trong URL"
        if _CONN_RE.search(tail):
            return "conn", tail[-200:]
        return "unknown", tail[-200:]

    # --- Ảnh chụp định kỳ ------------------------------------------------

    def _snapshot_loop(self) -> None:
        """Chụp một khung mỗi N giây để GUI có hình.

        Lưu ý: đây là MỘT kết nối RTSP nữa tới camera. Vài đầu ghi giới hạn số kết nối đồng
        thời — thấy ảnh chụp lỗi liên tục trong khi bản ghi vẫn chạy thì giãn nhịp ra.
        """
        interval = max(5, self.cfg.snapshot_seconds)
        fails = 0
        delay = 3.0  # tấm đầu tiên lấy sớm để người dùng thấy hình ngay khi vừa bấm ghi
        while not self._stop.wait(delay):
            delay = interval
            err = snapshot(self.cfg.effective_url, self.cfg.snapshot_path, self.cfg.ffmpeg)
            if err:
                fails += 1
                # Camera mất cả đêm thì đừng bơm hàng nghìn dòng log giống hệt nhau.
                if fails in (1, 5) or fails % 20 == 0:
                    self._log("warn", f"Không chụp được ảnh (lần {fails}): {err}")
            elif fails:
                self._log("info", "Đã chụp lại được ảnh")
                fails = 0


def _parse_seg_time(name: str) -> datetime | None:
    m = _SEG_RE.match(name)
    if not m:
        return None
    try:
        return datetime.strptime(m.group(1) + m.group(2), "%Y%m%d%H%M%S").replace(
            tzinfo=timezone.utc)
    except ValueError:
        return None


# ---------------------------------------------------------------------------
# 3. REPLAY — dựng lại file đã ghi thành luồng RTSP
# ---------------------------------------------------------------------------

class ReplaySession:
    """Phát một file đã ghi thành luồng RTSP cho client khác đọc.

    Ưu tiên go2rtc: nó là RTSP server thật, nhiều client xem cùng lúc được. Không có go2rtc thì
    lùi về ffmpeg ở chế độ `-rtsp_flags listen` — chỉ phục vụ ĐƯỢC MỘT client, và ffmpeg tự
    thoát khi client đó rời đi nên phải có luồng canh để dựng lại.

    Tối giản có chủ đích: một file, phát lặp. Không ghép nhiều đoạn, không tua, không playlist.
    """

    def __init__(self, file: Path, port: int = 8554, name: str = "cam1",
                 go2rtc: str = "", ffmpeg: str = "", on_log=None) -> None:
        # Tuyệt đối hoá NGAY: go2rtc chạy với thư mục làm việc khác, đường dẫn tương đối vào
        # config của nó là stream chết câm (client chỉ nhận 404, không ai nói vì sao).
        self.file = Path(file).resolve()
        self.port = port
        self.name = safe_name(name)
        self.go2rtc = find_tool("go2rtc", go2rtc)
        self.ffmpeg = find_tool("ffmpeg", ffmpeg)
        self._on_log = on_log
        self._proc: subprocess.Popen | None = None
        self._cfg_path: Path | None = None
        self._stop = threading.Event()
        self._keeper: threading.Thread | None = None
        self._err_tail: deque = deque(maxlen=10)  # để nói được lý do khi tiến trình chết ngay
        self.backend = ""

    @property
    def url(self) -> str:
        """URL đưa cho người xem. LUÔN dùng IP LAN thật — máy xem là máy khác, không phải localhost.

        Giao thức tuỳ đường đang chạy: go2rtc phát RTSP thật; đường lùi bằng ffmpeg phát
        MPEG-TS trên HTTP (xem `_start_ffmpeg`), VLC mở được cả hai.
        """
        if self.backend == "ffmpeg":
            return f"http://{lan_ip()}:{self.port}/"
        return f"rtsp://{lan_ip()}:{self.port}/{self.name}"

    def _log(self, level: str, text: str) -> None:
        if self._on_log:
            try:
                self._on_log(level, text)
            except Exception:
                pass

    def start(self) -> str:
        """Chạy replay. Trả về chuỗi lỗi, rỗng là thành công."""
        if self.is_running():
            return ""
        if not self.file.is_file():
            return f"Không thấy file: {self.file}"
        # Bắt lỗi cổng NGAY, trước khi chạy gì: máy trên tàu hay đã có sẵn một go2rtc khác giữ
        # 8554. Không kiểm thì tiến trình con chết câm và giao diện vẫn báo đang phát.
        if port_in_use(self.port):
            return (f"Cổng {self.port} đang bị chương trình khác chiếm. Chọn cổng khác "
                    f"(8555, 8601...) hoặc tắt chương trình đang giữ cổng đó.")
        self._stop.clear()
        if self.go2rtc:
            err = self._start_go2rtc()
        else:
            err = self._start_ffmpeg()
            if not err:
                self._log("warn", f"Không có go2rtc ({where_looked('go2rtc')}) — phát bằng ffmpeg "
                                  f"qua HTTP, CHỈ phục vụ được MỘT client xem cùng lúc")
        if err:
            return err
        # Chạy được lệnh chưa chắc đã phục vụ được. Chờ một nhịp rồi xem tiến trình còn sống
        # không — hỏng vì cổng, vì sai đường dẫn file, vì thiếu quyền đều lộ ra ở đây. Cố tình
        # KHÔNG nối thử vào cổng: sẽ chiếm mất suất người xem duy nhất (xem port_in_use).
        if self._stop.wait(1.5):
            return "Đã huỷ"
        if self._proc is None or self._proc.poll() is not None:
            code = self._proc.returncode if self._proc else "?"
            tail = " | ".join(self._err_tail) or "(không có thông báo)"
            self.stop()
            return f"{self.backend} thoát ngay (mã {code}) — {tail}"
        self._log("info", f"Replay [{self.backend}] {self.file.name} → {self.url}")
        return ""

    def _start_go2rtc(self) -> str:
        # Nguồn kiểu `exec:` — go2rtc chạy nguyên lệnh ffmpeg này rồi nhận luồng qua {output}.
        #
        # KHÔNG dùng dạng gọn `ffmpeg:<file>#input=-re -stream_loop -1`: go2rtc không nuốt được
        # KHOẢNG TRẮNG trong tham số `input`, nó bỏ luôn stream và client chỉ nhận 404 câm
        # (log go2rtc vỏn vẹn "streams: unknown error"). Đã thử trên go2rtc 1.9.14.
        #
        # `-re` đọc file theo ĐÚNG tốc độ thời gian thực. Thiếu nó ffmpeg xả hết file trong vài
        # giây rồi kết thúc — client chỉ kịp thấy một chớp hình.
        ffmpeg = (self.ffmpeg or "ffmpeg").replace("\\", "/")
        src = (f'exec:"{ffmpeg}" -hide_banner -v error -re -stream_loop -1 '
               f'-i "{self.file.as_posix()}" -c copy -rtsp_transport tcp -f rtsp {{output}}')
        cfg = (
            "# Sinh tự động bởi ToolSensor — sửa tay ở đây sẽ bị ghi đè\n"
            "api:\n"
            '  listen: ""   # tắt API: máy có thể đang chạy go2rtc khác giữ cổng 1984\n'
            "webrtc:\n"
            '  listen: ""   # tắt WebRTC: không cần, và tránh đụng cổng 8555\n'
            "rtsp:\n"
            f'  listen: ":{self.port}"\n'
            "streams:\n"
            # Nháy ĐƠN: chuỗi exec ở trên đã chứa nháy kép quanh đường dẫn.
            f"  {self.name}: '{src}'\n"
            "log:\n"
            "  level: info\n"
        )
        self._cfg_path = Path(tempfile.gettempdir()) / f"toolsensor_replay_{self.port}.yaml"
        try:
            self._cfg_path.write_text(cfg, encoding="utf-8")
        except OSError as exc:
            return f"Không ghi được config tạm cho go2rtc: {exc}"
        try:
            self._proc = subprocess.Popen(
                [self.go2rtc, "-config", str(self._cfg_path)],
                stdin=subprocess.DEVNULL,
                # go2rtc log ra STDOUT (khác ffmpeg). Gộp cả hai vào một đường ống rồi đọc —
                # bỏ stdout đi thì stream hỏng cũng chỉ thấy client báo 404, không rõ vì sao.
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                **_spawn_kwargs(),
            )
        except OSError as exc:
            return f"Không chạy được go2rtc: {exc}"
        self.backend = "go2rtc"
        threading.Thread(target=self._drain, args=(self._proc.stdout, "go2rtc"),
                         daemon=True).start()
        time.sleep(1.0)
        if self._proc.poll() is not None:
            return f"go2rtc thoát ngay (mã {self._proc.returncode}) — cổng {self.port} bị chiếm?"
        return ""

    def _start_ffmpeg(self) -> str:
        if not self.ffmpeg:
            return f"Không tìm thấy {where_looked('ffmpeg')}"
        self.backend = "ffmpeg"
        if not self._spawn_ffmpeg():
            return "Không chạy được ffmpeg cho replay"
        # `-listen 1` phục vụ xong một người xem là ffmpeg thoát → luồng canh dựng lại, nếu không
        # thì xem xong một lần là luồng chết, phải bấm nút lại.
        self._keeper = threading.Thread(target=self._keep_alive, daemon=True)
        self._keeper.start()
        return ""

    def _spawn_ffmpeg(self) -> bool:
        """Phát qua HTTP/MPEG-TS, KHÔNG phải RTSP.

        Đề bài định dùng `-f rtsp -rtsp_flags listen` để ffmpeg tự làm RTSP server. Đã thử trên
        ffmpeg 8.1.2 với cả ba cách viết (`-rtsp_flags listen`, `+listen`, `-listen 1`): không
        cách nào mở cổng cả, nhật ký của nó ghi "Starting connection attempt to 0.0.0.0" — tức
        vẫn đang đi KẾT NỐI RA chứ không phải đứng nghe. Client vì thế chờ tới hết giờ.

        MPEG-TS trên HTTP thì ffmpeg làm server thật (`-listen 1`), đã đo là VLC/ffprobe đọc
        được. Đổi lại URL là http:// và cũng chỉ phục vụ một người xem — muốn RTSP thật và nhiều
        client thì chỉ đường dẫn go2rtc vào.
        """
        cmd = [
            self.ffmpeg, "-hide_banner", "-v", "error",
            "-re",                     # BẮT BUỘC: phát đúng tốc độ thật, thiếu là xả hết trong vài giây
            "-stream_loop", "-1",      # lặp vô hạn
            "-i", str(self.file),
            "-c", "copy",
            "-f", "mpegts",            # TS chịu được việc người xem vào giữa chừng
            "-listen", "1",
            f"http://0.0.0.0:{self.port}",
        ]
        try:
            self._proc = subprocess.Popen(
                cmd, stdin=subprocess.PIPE, stdout=subprocess.DEVNULL,
                stderr=subprocess.PIPE, **_spawn_kwargs(),
            )
        except OSError as exc:
            self._log("error", f"Không chạy được ffmpeg: {exc}")
            return False
        threading.Thread(target=self._drain, args=(self._proc.stderr, "ffmpeg"),
                         daemon=True).start()
        return True

    def _keep_alive(self) -> None:
        while not self._stop.wait(1.0):
            proc = self._proc
            if proc is not None and proc.poll() is not None:
                if self._stop.is_set():
                    break
                self._log("info", "Client đã rời — dựng lại cổng chờ replay")
                if not self._spawn_ffmpeg():
                    break

    def _drain(self, stream, tag: str) -> None:
        try:
            for raw in iter(stream.readline, b""):
                line = raw.decode("utf-8", "replace").strip()
                if line:
                    self._err_tail.append(line)
                    self._log("ffmpeg", f"[{tag}] {line}")
        except Exception:
            pass

    def is_running(self) -> bool:
        return self._proc is not None and self._proc.poll() is None

    def stop(self) -> None:
        self._stop.set()
        if self._keeper:
            self._keeper.join(timeout=3)
        # go2rtc đẻ ffmpeg con — phải giết cả cây, xem kill_tree.
        if not kill_tree(self._proc) and self._proc is not None:
            self._log("error", f"KHÔNG giết được {self.backend} (pid {self._proc.pid}) — nó vẫn "
                               f"đang giữ cổng {self.port}. Kết thúc tiến trình đó bằng tay.")
        self._proc = None
        if self._cfg_path:
            try:
                self._cfg_path.unlink(missing_ok=True)
            except OSError:
                pass
        self._log("info", "Đã dừng replay")


# ---------------------------------------------------------------------------
# Đọc manifest — dùng cho CLI lẫn GUI
# ---------------------------------------------------------------------------

def read_manifest(path) -> dict:
    """Tóm tắt manifest: bao nhiêu đoạn, bao nhiêu khoảng đứt, che phủ bao nhiêu phần trăm."""
    p = Path(path)
    if p.is_dir():
        p = p / "manifest.jsonl"
    out = {
        "path": str(p), "exists": p.is_file(), "segments": 0, "gaps": 0, "pruned": 0,
        "bytes": 0, "recorded_seconds": 0.0, "gap_seconds": 0.0, "longest_gap": 0.0,
        "longest_gap_at": "", "first": "", "last": "", "sessions": 0, "coverage": 0.0,
        "gap_reasons": {},
    }
    if not out["exists"]:
        return out
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except ValueError:
                continue
            kind = e.get("type")
            if kind == "segment":
                out["segments"] += 1
                out["bytes"] += int(e.get("bytes", 0))
                out["recorded_seconds"] += float(e.get("seconds", 0))
                if not out["first"]:
                    out["first"] = e.get("start", "")
                out["last"] = e.get("end", "")
            elif kind == "gap":
                sec = float(e.get("seconds", 0))
                out["gaps"] += 1
                out["gap_seconds"] += sec
                reason = e.get("reason", "?")
                out["gap_reasons"][reason] = out["gap_reasons"].get(reason, 0) + 1
                if sec > out["longest_gap"]:
                    out["longest_gap"] = sec
                    out["longest_gap_at"] = e.get("start", "")
            elif kind == "pruned":
                out["pruned"] += 1
            elif kind == "session":
                if e.get("event") == "start":
                    out["sessions"] += 1
    span = out["recorded_seconds"] + out["gap_seconds"]
    if span > 0:
        out["coverage"] = out["recorded_seconds"] / span * 100
    return out


# ---------------------------------------------------------------------------
# Dòng lệnh
# ---------------------------------------------------------------------------

def _print_log(level: str, text: str) -> None:
    if level == "ffmpeg":
        text = "  " + text
    print(f"[{_stamp(_utc_now())}] {level.upper():5} {text}", flush=True)


def _cmd_tools(args) -> int:
    tools = check_tools(args.go2rtc)
    missing = 0
    for name, path in tools.items():
        if path:
            print(f"  [OK]     {name:8} → {path}")
        else:
            missing += 1
            need = "tuỳ chọn, chỉ replay mới cần" if name == "go2rtc" else "BẮT BUỘC"
            print(f"  [THIẾU]  {name:8} ({need})\n           {where_looked(name)}")
    return 1 if missing and not tools["ffmpeg"] else 0


def _cmd_probe(args) -> int:
    res = probe(args.url, args.ffprobe, username=args.user, password=args.password)
    if not res.ok:
        print(f"LỖI: {res.error}")
        return 1
    print(f"  {res.summary()}")
    print(f"  {res.stream_line}")
    if res.height:
        gb = estimate_gb_per_day(res.height)
        print(f"  Ước tính nếu ghi LIÊN TỤC: ~{gb:.1f} GB/ngày ({gb * 30:.0f} GB/tháng)")
        gb5 = estimate_gb_per_day(res.height, 5, 30)
        print(f"  Ước tính nếu LẤY MẪU 5/30 phút: ~{gb5:.1f} GB/ngày ({gb5 * 30:.0f} GB/tháng)")
    return 0


def _cmd_record(args) -> int:
    cfg = RecordConfig(
        name=args.name, url=args.url, username=args.user, password=args.password,
        root=Path(args.dir), mode=args.mode,
        on_minutes=args.on, every_minutes=args.every, segment_seconds=args.segment,
        quota_gb=args.quota, min_free_gb=args.min_free, ring=args.ring,
        snapshot_seconds=args.snapshot, ffmpeg=args.ffmpeg,
    )
    rec = CameraRecorder(cfg, on_log=_print_log)
    rec.start()
    print("Đang ghi. Ctrl+C để dừng.")
    try:
        while rec.is_running():
            time.sleep(args.report)
            s = rec.stats()
            print(f"--- {s.state} | {human_bytes(s.used_bytes)}/{cfg.quota_gb:g} GB "
                  f"| trống {human_bytes(s.free_bytes)} | {s.segments} đoạn, {s.gaps} đứt "
                  f"| {s.gb_per_day:.2f} GB/ngày"
                  + (f" | còn ~{s.days_left:.1f} ngày" if s.days_left >= 0 else ""), flush=True)
    except KeyboardInterrupt:
        print("\nĐang dừng...")
    rec.stop()
    _cmd_manifest(argparse.Namespace(path=str(cfg.cam_dir)))
    return 0


def _cmd_onvif(args) -> int:
    """Hỏi camera có những luồng nào — camera nhiệt/hồng ngoại phải qua đây mới ra URL."""
    import onvif_client

    if args.token:
        uri, err = onvif_client.get_stream_uri(args.url, args.token, args.user, args.password)
        if err:
            print(f"LỖI: {err}")
            return 1
        print(f"  {args.token} → {uri}")
        return 0

    profiles, err = onvif_client.get_profiles(args.url, args.user, args.password)
    if err:
        print(f"LỖI: {err}")
        return 1
    print(f"\nCamera công bố {len(profiles)} luồng:\n")
    for p in profiles:
        print(f"  {p.label()}")
        print(f"      token : {p.token}")
        print(f"      RTSP  : {p.stream_uri or '(không lấy được)'}\n")
    print("Chép URL RTSP của luồng cần ghi rồi đưa vào lệnh record/probe.\n")
    return 0


def _cmd_replay(args) -> int:
    sess = ReplaySession(Path(args.file), port=args.port, name=args.name,
                         go2rtc=args.go2rtc, ffmpeg=args.ffmpeg, on_log=_print_log)
    err = sess.start()
    if err:
        print(f"LỖI: {err}")
        return 1
    print(f"Mở bằng VLC:  {sess.url}")
    print("Ctrl+C để dừng.")
    try:
        while sess.is_running() or sess.backend == "ffmpeg":
            time.sleep(1)
    except KeyboardInterrupt:
        pass
    sess.stop()
    return 0


def _cmd_manifest(args) -> int:
    m = read_manifest(args.path)
    if not m["exists"]:
        print(f"Không thấy manifest: {m['path']}")
        return 1
    print(f"\nManifest: {m['path']}")
    print(f"  Phiên ghi        : {m['sessions']}")
    print(f"  Đoạn             : {m['segments']}  ({human_bytes(m['bytes'])})")
    print(f"  Tổng thời lượng  : {human_secs(m['recorded_seconds'])}")
    print(f"  Khoảng đứt       : {m['gaps']}  (tổng {human_secs(m['gap_seconds'])})")
    if m["gaps"]:
        print(f"  Đứt dài nhất     : {human_secs(m['longest_gap'])} lúc {m['longest_gap_at']}")
        for reason, count in sorted(m["gap_reasons"].items(), key=lambda x: -x[1]):
            print(f"      - {reason}: {count} lần")
    if m["pruned"]:
        print(f"  Đã xoá (vòng tròn): {m['pruned']} đoạn")
    print(f"  Từ               : {m['first']}")
    print(f"  Đến              : {m['last']}")
    print(f"  Che phủ          : {m['coverage']:.1f}% thời gian phiên chạy\n")
    return 0


def main(argv=None) -> int:
    # Console Windows mặc định là cp1252, không in được tiếng Việt lẫn ký hiệu — mọi lệnh sẽ
    # chết vì UnicodeEncodeError ngay dòng in đầu tiên. Ép UTF-8 trước khi làm gì khác.
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except (AttributeError, OSError):
            pass

    ap = argparse.ArgumentParser(
        description="Camera RTSP: kiểm tra, ghi phân đoạn và phát lại (bọc ffmpeg/go2rtc)")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("tools", help="kiểm tra ffmpeg/ffprobe/go2rtc")
    p.add_argument("--go2rtc", default="", help="đường dẫn go2rtc nếu không nằm trong PATH")
    p.set_defaults(func=_cmd_tools)

    p = sub.add_parser("probe", help="kiểm tra URL RTSP, in codec/độ phân giải/fps")
    p.add_argument("url")
    p.add_argument("--user", default="", help="tài khoản camera (nếu chưa nhét vào URL)")
    p.add_argument("--password", default="", help="mật khẩu camera; ký tự đặc biệt tự mã hoá")
    p.add_argument("--ffprobe", default="")
    p.set_defaults(func=_cmd_probe)

    p = sub.add_parser("record", help="ghi luồng RTSP thành từng đoạn mp4")
    p.add_argument("url")
    p.add_argument("--user", default="", help="tài khoản camera (nếu chưa nhét vào URL)")
    p.add_argument("--password", default="", help="mật khẩu camera; ký tự đặc biệt tự mã hoá")
    p.add_argument("--dir", required=True, help="thư mục gốc chứa bản ghi")
    p.add_argument("--name", default="cam1")
    p.add_argument("--mode", default=MODE_SAMPLE,
                   choices=[MODE_SAMPLE, MODE_SESSION, MODE_CONTINUOUS])
    p.add_argument("--on", type=float, default=5.0, help="số phút ghi mỗi chu kỳ (chế độ lấy mẫu)")
    p.add_argument("--every", type=float, default=30.0, help="chu kỳ, tính bằng phút")
    p.add_argument("--segment", type=int, default=SEGMENT_SECONDS, help="độ dài mỗi đoạn (giây)")
    p.add_argument("--quota", type=float, default=50.0, help="hạn mức riêng của camera (GB)")
    p.add_argument("--min-free", type=float, default=20.0, dest="min_free",
                   help="sàn dung lượng trống của ổ (GB)")
    p.add_argument("--ring", action="store_true", help="xoá đoạn cũ nhất khi chạm hạn mức")
    p.add_argument("--snapshot", type=int, default=0, help="chụp ảnh mỗi N giây (0 = tắt)")
    p.add_argument("--report", type=float, default=60.0, help="in thống kê mỗi N giây")
    p.add_argument("--ffmpeg", default="")
    p.set_defaults(func=_cmd_record)

    p = sub.add_parser("onvif", help="hỏi camera có những luồng nào (profile token → URL RTSP)")
    p.add_argument("url", help="VD: http://192.168.1.10/onvif/device_service")
    p.add_argument("--user", default="")
    p.add_argument("--password", default="")
    p.add_argument("--token", default="", help="biết sẵn token thì chỉ lấy URL của luồng đó")
    p.set_defaults(func=_cmd_onvif)

    p = sub.add_parser("replay", help="phát lặp một file đã ghi thành luồng RTSP")
    p.add_argument("file")
    p.add_argument("--port", type=int, default=8554)
    p.add_argument("--name", default="cam1")
    p.add_argument("--go2rtc", default="")
    p.add_argument("--ffmpeg", default="")
    p.set_defaults(func=_cmd_replay)

    p = sub.add_parser("manifest", help="tóm tắt manifest (thư mục camera hoặc file .jsonl)")
    p.add_argument("path")
    p.set_defaults(func=_cmd_manifest)

    args = ap.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
