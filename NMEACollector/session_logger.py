"""Ghi bản tin NMEA vào file .bin có đánh dấu thời gian, hỗ trợ xoay file theo ngày."""

import os
from datetime import datetime


class SessionLogger:
    def __init__(self, output_dir: str, prefix: str = "session",
                 existing_path: str | None = None,
                 daily_rotate: bool = False):
        self._output_dir  = output_dir
        self._prefix      = prefix
        self._daily_rotate = daily_rotate
        self._count       = 0
        self._started     = datetime.now()

        if existing_path:
            self._path = existing_path
            self._file = open(self._path, "a", encoding="utf-8")
            try:
                with open(self._path, "r", encoding="utf-8", errors="replace") as f:
                    self._count = sum(1 for _ in f)
            except Exception:
                pass
        else:
            self._path = self._make_path()
            os.makedirs(output_dir, exist_ok=True)
            self._file = open(self._path, "w", encoding="utf-8")

    # ── helpers ──────────────────────────────────────────────────────────────

    def _make_path(self) -> str:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        return os.path.join(self._output_dir, f"{self._prefix}_{ts}.bin")

    def _rotate(self) -> None:
        """Đóng file hiện tại, mở file mới cho ngày mới."""
        if self._file and not self._file.closed:
            self._file.close()
        self._path    = self._make_path()
        self._started = datetime.now()
        self._count   = 0
        os.makedirs(self._output_dir, exist_ok=True)
        self._file = open(self._path, "w", encoding="utf-8")

    # ── public API ────────────────────────────────────────────────────────────

    @property
    def path(self) -> str:
        return self._path

    @property
    def count(self) -> int:
        return self._count

    @property
    def duration_s(self) -> float:
        return (datetime.now() - self._started).total_seconds()

    @property
    def is_open(self) -> bool:
        return bool(self._file and not self._file.closed)

    def write(self, sentence: str, type_tag: str) -> None:
        now = datetime.now()
        # Xoay file khi sang ngày mới
        if self._daily_rotate and now.date() != self._started.date():
            self._rotate()
        # Tạo file mới nếu file bị xóa từ bên ngoài
        elif not os.path.exists(self._path):
            self._rotate()
        ts = now.isoformat(timespec="milliseconds")
        self._file.write(f"{ts}: [{type_tag}] {sentence}\n")
        self._file.flush()
        self._count += 1

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()
