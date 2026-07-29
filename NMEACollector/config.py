"""Lưu / tải cấu hình NMEACollector từ file JSON."""

import json
import os

_DEFAULT_PATH = os.path.expanduser("~/.nmea_collector.json")

DEFAULT_CONFIG = {
    "output_folder": os.path.expanduser("~/Documents/NMEA_Logs"),
    "daily_rotate": True,
    "auto_connect": False,
    "connections": []
}

DEFAULT_CONNECTION = {
    "mode": "TCP Client",
    "host": "192.168.1.1",
    "port": 10110,
    "prefix": "session"
}


def load(path: str = _DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        # Merge missing keys with defaults
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(DEFAULT_CONFIG)


def save(cfg: dict, path: str = _DEFAULT_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
