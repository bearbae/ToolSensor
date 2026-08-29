"""Lưu / tải cấu hình SSH Tunnel của Maritime Simulator từ file JSON — cùng
quy ước với NMEACollector (xem NMEACollector/config.py, ~/.nmea_collector.json)."""

import json
import os

_DEFAULT_PATH = os.path.expanduser("~/.maritime_simulator.json")

DEFAULT_CONFIG = {
    "ssh_host": "171.244.197.133",
    "ssh_port": 2222,
    "ssh_user": "root",
    "ssh_password": "",
    "ssh_remember_password": True,
    "ssh_namespace": "enc-ship",
    "ssh_label_selector": "app=enc-sensor-gateway",
    "ssh_pod_ip": "",
    "ssh_remote_port": 5001,
    "ssh_local_port": 5001,
}


def load(path: str = _DEFAULT_PATH) -> dict:
    if not os.path.exists(path):
        return dict(DEFAULT_CONFIG)
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
        for k, v in DEFAULT_CONFIG.items():
            data.setdefault(k, v)
        return data
    except Exception:
        return dict(DEFAULT_CONFIG)


def save(cfg: dict, path: str = _DEFAULT_PATH) -> None:
    with open(path, "w", encoding="utf-8") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)
