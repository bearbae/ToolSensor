"""Quản lý tự khởi động cùng hệ thống.

- Windows : ghi vào Registry HKCU (không cần quyền admin)
- Linux   : tạo file .desktop trong ~/.config/autostart/
"""

import os
import sys

# ── Windows ───────────────────────────────────────────────────────────────────
try:
    import winreg
    _WINREG_OK = True
except ImportError:
    _WINREG_OK = False

_REG_PATH = r"Software\Microsoft\Windows\CurrentVersion\Run"
_APP_NAME = "NMEACollector"

# ── Linux ─────────────────────────────────────────────────────────────────────
_DESKTOP_DIR  = os.path.expanduser("~/.config/autostart")
_DESKTOP_FILE = os.path.join(_DESKTOP_DIR, "nmea-collector.desktop")

_DESKTOP_TEMPLATE = """\
[Desktop Entry]
Type=Application
Name=NMEACollector
Exec={exec_path}
Hidden=false
NoDisplay=false
X-GNOME-Autostart-enabled=true
"""


def _exe_path() -> str:
    """Trả về lệnh thực thi (exe đóng gói hoặc 'python main.py')."""
    if getattr(sys, "frozen", False):
        return f'"{sys.executable}"'
    script = os.path.abspath(os.path.join(os.path.dirname(__file__), "main.py"))
    return f'"{sys.executable}" "{script}"'


# ── Windows impl ──────────────────────────────────────────────────────────────

def _win_is_enabled() -> bool:
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _REG_PATH) as key:
            winreg.QueryValueEx(key, _APP_NAME)
            return True
    except (FileNotFoundError, OSError):
        return False


def _win_enable() -> None:
    with winreg.OpenKey(
        winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
    ) as key:
        winreg.SetValueEx(key, _APP_NAME, 0, winreg.REG_SZ, _exe_path())


def _win_disable() -> None:
    try:
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER, _REG_PATH, 0, winreg.KEY_SET_VALUE
        ) as key:
            winreg.DeleteValue(key, _APP_NAME)
    except (FileNotFoundError, OSError):
        pass


# ── Linux impl ────────────────────────────────────────────────────────────────

def _linux_is_enabled() -> bool:
    return os.path.isfile(_DESKTOP_FILE)


def _linux_enable() -> None:
    os.makedirs(_DESKTOP_DIR, exist_ok=True)
    content = _DESKTOP_TEMPLATE.format(exec_path=_exe_path().replace('"', ""))
    with open(_DESKTOP_FILE, "w", encoding="utf-8") as f:
        f.write(content)


def _linux_disable() -> None:
    try:
        os.remove(_DESKTOP_FILE)
    except FileNotFoundError:
        pass


# ── Public API ────────────────────────────────────────────────────────────────

def is_enabled() -> bool:
    if _WINREG_OK:
        return _win_is_enabled()
    if sys.platform.startswith("linux"):
        return _linux_is_enabled()
    return False


def enable() -> None:
    if _WINREG_OK:
        _win_enable()
    elif sys.platform.startswith("linux"):
        _linux_enable()


def disable() -> None:
    if _WINREG_OK:
        _win_disable()
    elif sys.platform.startswith("linux"):
        _linux_disable()


def set_enabled(enabled: bool) -> None:
    if enabled:
        enable()
    else:
        disable()
