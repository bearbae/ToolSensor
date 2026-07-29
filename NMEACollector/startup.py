"""Quản lý tự khởi động cùng Windows qua Registry (HKCU, không cần quyền admin)."""

import os
import sys

try:
    import winreg
    _WINREG_OK = True
except ImportError:
    _WINREG_OK = False   # không chạy trên Windows

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "NMEACollector"


def _exe_path() -> str:
    """Trả về đường dẫn exe (khi đóng gói) hoặc 'python script.py' (khi chạy thẳng)."""
    if getattr(sys, "frozen", False):
        # Đã đóng gói bằng PyInstaller
        return f'"{sys.executable}"'
    else:
        # Chạy từ source
        script = os.path.abspath(__file__.replace("startup.py", "main.py"))
        return f'"{sys.executable}" "{script}"'


def is_enabled() -> bool:
    """Kiểm tra tool có đang được đăng ký tự khởi động không."""
    if not _WINREG_OK:
        return False
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def enable() -> None:
    """Đăng ký tự khởi động cùng Windows."""
    if not _WINREG_OK:
        return
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _exe_path())


def disable() -> None:
    """Hủy đăng ký tự khởi động."""
    if not _WINREG_OK:
        return
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
    except (FileNotFoundError, OSError):
        pass


def set_enabled(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()
