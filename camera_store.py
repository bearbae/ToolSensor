"""Lưu và nạp lại hồ sơ camera, để khỏi phải gõ lại URL/tài khoản/hạn mức mỗi lần mở app.

Ghi ra một file JSON trong thư mục dữ liệu của người dùng (AppData trên Windows), KHÔNG ghi
cạnh mã nguồn: bản đóng gói thường nằm trong Program Files, chỗ đó không ghi được.

MẬT KHẨU KHÔNG BAO GIỜ nằm dạng chữ thường trong file. Windows có sẵn DPAPI — mã hoá bằng danh
tính của chính tài khoản đang đăng nhập, nên file có bị chép sang máy khác cũng không giải ra
được. Máy không có DPAPI thì THÀ KHÔNG LƯU mật khẩu còn hơn lưu trần: người dùng gõ lại một ô,
đổi lấy việc mật khẩu camera không nằm chình ình trong một file JSON ai đọc cũng được.
"""

import base64
import ctypes
import ctypes.wintypes
import json
import os
import sys
from pathlib import Path

from camera import MODE_SAMPLE, RecordConfig

STORE_VERSION = 1
IS_WINDOWS = sys.platform.startswith("win")


def store_path() -> Path:
    """Đường dẫn file cấu hình."""
    if IS_WINDOWS:
        base = Path(os.getenv("APPDATA") or Path.home())
    else:
        base = Path(os.getenv("XDG_CONFIG_HOME") or (Path.home() / ".config"))
    return base / "MaritimeSignalSimulator" / "cameras.json"


# ---------------------------------------------------------------------------
# Mã hoá mật khẩu bằng DPAPI (chỉ Windows)
# ---------------------------------------------------------------------------

class _Blob(ctypes.Structure):
    _fields_ = [("cbData", ctypes.wintypes.DWORD),
                ("pbData", ctypes.POINTER(ctypes.c_char))]


def _blob_bytes(blob: _Blob) -> bytes:
    return ctypes.string_at(blob.pbData, blob.cbData)


def protect(text: str) -> str:
    """Mã hoá chuỗi, trả về base64. Chuỗi rỗng nếu không mã hoá được (thì đừng lưu gì cả)."""
    if not text or not IS_WINDOWS:
        return ""
    try:
        raw = text.encode("utf-8")
        src = _Blob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw),
                                          ctypes.POINTER(ctypes.c_char)))
        out = _Blob()
        ok = ctypes.windll.crypt32.CryptProtectData(
            ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return ""
        try:
            return base64.b64encode(_blob_bytes(out)).decode()
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
    except Exception:
        return ""


def unprotect(blob_b64: str) -> str:
    """Giải mã chuỗi đã protect(). Rỗng nếu không giải được (đổi máy, đổi tài khoản Windows)."""
    if not blob_b64 or not IS_WINDOWS:
        return ""
    try:
        raw = base64.b64decode(blob_b64)
        src = _Blob(len(raw), ctypes.cast(ctypes.create_string_buffer(raw),
                                          ctypes.POINTER(ctypes.c_char)))
        out = _Blob()
        ok = ctypes.windll.crypt32.CryptUnprotectData(
            ctypes.byref(src), None, None, None, None, 0, ctypes.byref(out))
        if not ok:
            return ""
        try:
            return _blob_bytes(out).decode("utf-8", "replace")
        finally:
            ctypes.windll.kernel32.LocalFree(out.pbData)
    except Exception:
        return ""


def can_store_password() -> bool:
    """Máy này có chỗ cất mật khẩu tử tế không."""
    return IS_WINDOWS and bool(protect("kiem tra"))


# ---------------------------------------------------------------------------
# Đọc / ghi
# ---------------------------------------------------------------------------

def _to_dict(cfg: RecordConfig, keep_password: bool) -> dict:
    data = {
        "name": cfg.name,
        "url": cfg.url,
        "username": cfg.username,
        "onvif_url": cfg.onvif_url,
        "profile_token": cfg.profile_token,
        "profile_name": cfg.profile_name,
        "root": str(cfg.root),
        "mode": cfg.mode,
        "on_minutes": cfg.on_minutes,
        "every_minutes": cfg.every_minutes,
        "segment_seconds": cfg.segment_seconds,
        "quota_gb": cfg.quota_gb,
        "min_free_gb": cfg.min_free_gb,
        "ring": cfg.ring,
        "snapshot_seconds": cfg.snapshot_seconds,
        "autostart": cfg.autostart,
    }
    if keep_password and cfg.password:
        blob = protect(cfg.password)
        if blob:
            data["password_dpapi"] = blob  # chỉ có dạng đã mã hoá, không bao giờ có chữ thường
    return data


def _from_dict(data: dict) -> RecordConfig:
    cfg = RecordConfig()
    for key in ("name", "url", "username", "onvif_url", "profile_token", "profile_name", "mode"):
        if isinstance(data.get(key), str):
            setattr(cfg, key, data[key])
    if data.get("root"):
        cfg.root = Path(str(data["root"]))
    for key in ("on_minutes", "every_minutes", "quota_gb", "min_free_gb"):
        try:
            setattr(cfg, key, float(data[key]))
        except (KeyError, TypeError, ValueError):
            pass
    for key in ("segment_seconds", "snapshot_seconds"):
        try:
            setattr(cfg, key, int(data[key]))
        except (KeyError, TypeError, ValueError):
            pass
    cfg.ring = bool(data.get("ring", False))
    cfg.autostart = bool(data.get("autostart", False))
    if cfg.mode not in ("sample", "session", "continuous"):
        cfg.mode = MODE_SAMPLE
    cfg.password = unprotect(data.get("password_dpapi", ""))
    return cfg


def save(configs: list, extras: dict | None = None, keep_password: bool = True,
         path: Path | None = None) -> str:
    """Ghi danh sách camera. Trả về chuỗi lỗi, rỗng là xong.

    `path` bỏ trống thì ghi vào chỗ mặc định; truyền vào để xuất ra file mang đi máy khác.
    """
    path = Path(path) if path else store_path()
    payload = {
        "version": STORE_VERSION,
        "_ghi_chu": "Mật khẩu (nếu có) được mã hoá bằng DPAPI của Windows, gắn với tài khoản "
                    "đăng nhập trên chính máy này. Chép file sang máy khác sẽ không giải ra được.",
        "cameras": [_to_dict(c, keep_password) for c in configs],
        "extras": extras or {},
    }
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        # Ghi ra file tạm rồi đổi tên: mất điện giữa chừng thì vẫn còn nguyên bản cũ, thay vì
        # để lại một file JSON cụt không nạp được.
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)
        return ""
    except OSError as exc:
        return f"Không ghi được {path}: {exc}"


def load(path: Path | None = None) -> tuple:
    """Trả về (danh sách RecordConfig, extras, lỗi). Chưa có file thì trả danh sách rỗng.

    `path` bỏ trống thì đọc chỗ mặc định; truyền vào để nạp một file mang từ nơi khác tới.
    """
    path = Path(path) if path else store_path()
    if not path.is_file():
        return [], {}, ""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as exc:
        return [], {}, f"Không đọc được {path}: {exc}"
    if not isinstance(payload, dict):
        return [], {}, f"{path} sai định dạng"
    configs = []
    for item in payload.get("cameras", []):
        if isinstance(item, dict):
            try:
                configs.append(_from_dict(item))
            except Exception as exc:  # noqa: BLE001 — một dòng hỏng không được làm hỏng cả file
                return configs, payload.get("extras", {}), f"Bỏ qua một camera lỗi: {exc}"
    extras = payload.get("extras", {})
    return configs, extras if isinstance(extras, dict) else {}, ""
