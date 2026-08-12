"""Ghi bản tin NMEA vào file .bin có đánh dấu thời gian, hỗ trợ xoay file theo ngày."""

import os
from datetime import datetime


class SessionLogger:
    def __init__(self, output_dir: str, prefix: str = "session",
                 existing_path: str | None = None,
                 daily_rotate: bool = False,
                 max_folder_gb: float | None = None):
        self._output_dir   = output_dir
        self._prefix       = prefix
        self._daily_rotate = daily_rotate
        self._max_bytes    = int(max_folder_gb * 1024 ** 3) if max_folder_gb else None
        self._count        = 0
        self._started      = datetime.now()

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
        """Đóng file hiện tại, mở file mới."""
        if self._file and not self._file.closed:
            self._file.close()
        self._path    = self._make_path()
        self._started = datetime.now()
        self._count   = 0
        os.makedirs(self._output_dir, exist_ok=True)
        self._file = open(self._path, "w", encoding="utf-8")

    def _enforce_size_limit(self) -> None:
        """Xóa file log cũ nhất cho đến khi thư mục dưới ngưỡng giới hạn."""
        if not self._max_bytes:
            return
        try:
            entries = [
                os.path.join(self._output_dir, f)
                for f in os.listdir(self._output_dir)
                if os.path.isfile(os.path.join(self._output_dir, f))
            ]
            # Sắp xếp theo thời gian chỉnh sửa, cũ nhất trước
            entries.sort(key=lambda p: os.path.getmtime(p))
            total = sum(os.path.getsize(p) for p in entries)
            for path in entries:
                if total <= self._max_bytes:
                    break
                # Không xóa file đang ghi
                if os.path.abspath(path) == os.path.abspath(self._path):
                    continue
                size = os.path.getsize(path)
                os.remove(path)
                total -= size
        except Exception:
            pass

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
        self._enforce_size_limit()
        ts = now.isoformat(timespec="milliseconds")
        self._file.write(f"{ts}: [{type_tag}] {sentence}\n")
        self._file.flush()
        self._count += 1

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()
