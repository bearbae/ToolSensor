"""Hằng số style và helper dùng chung giữa main.py và các mixin ui_*.py.

Tách riêng để tránh import vòng: các mixin (ui_connection.py, ui_gps_tab.py,
...) được main.py import vào, nên không thể import ngược lại từ main.py.
"""

# ---------------------------------------------------------------------------
# Colour scheme for the dark log console
# ---------------------------------------------------------------------------
_LOG_BG = "#1e1e1e"
_COL_GPS = "#00e676"
_COL_RADAR = "#ffee58"
_COL_AIS = "#40c4ff"
_COL_INFO = "#90a4ae"
_COL_ERROR = "#ef5350"


def _btn_qss(normal: str, hover: str, pressed: str,
             text: str = "white") -> str:
    """Return a full QPushButton stylesheet with hover and pressed states."""
    return (
        f"QPushButton {{"
        f"  background-color:{normal}; color:{text};"
        f"  font-weight:bold; border:none; border-radius:4px;"
        f"  padding:5px 12px;"
        f"}}"
        f"QPushButton:hover {{"
        f"  background-color:{hover};"
        f"}}"
        f"QPushButton:pressed {{"
        f"  background-color:{pressed};"
        f"}}"
        f"QPushButton:disabled {{"
        f"  background-color:#4a4a4a; color:#888888;"
        f"}}"
    )


# Global stylesheet for plain (unstyled) buttons – adds visible hover/press
_APP_QSS = """
QPushButton {
    border: 1px solid #767676;
    border-radius: 4px;
    padding: 4px 10px;
    min-height: 24px;
}
QPushButton:hover {
    background-color: #d0e8ff;
    border-color: #0d6efd;
}
QPushButton:pressed {
    background-color: #a8cff8;
    border-color: #0a58ca;
}
QPushButton:disabled {
    color: #a0a0a0;
    border-color: #c0c0c0;
}
"""


def _parse_speed_schedule(text: str) -> list:
    """Parse '0:20, 5:8, 12:20' → [(0, 20.0), ...] sorted ascending by waypoint index."""
    result = []
    for part in text.split(','):
        part = part.strip()
        if ':' not in part:
            continue
        wp_str, spd_str = part.split(':', 1)
        try:
            wp = int(wp_str.strip())
            spd = float(spd_str.strip())
            if wp >= 0 and spd >= 0:
                result.append((wp, spd))
        except ValueError:
            continue
    result.sort(key=lambda x: x[0])
    return result
