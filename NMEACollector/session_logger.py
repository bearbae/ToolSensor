"""Ghi bản tin NMEA vào file .bin có đánh dấu thời gian, hỗ trợ xoay file theo ngày."""

import os
import shutil
from datetime import datetime

_MIN_FREE_BYTES = 5 * 1024 ** 3   # luôn giữ tối thiểu 5GB trống trên ổ đĩa


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

    def _get_log_files(self) -> list[str]:
        """Danh sách file trong thư mục log, sắp xếp cũ nhất trước."""
        try:
            entries = [
                os.path.join(self._output_dir, f)
                for f in os.listdir(self._output_dir)
                if os.path.isfile(os.path.join(self._output_dir, f))
            ]
            entries.sort(key=lambda p: os.path.getmtime(p))
            return entries
        except Exception:
            return []

    def _delete_oldest(self, files: list[str]) -> None:
        """Xóa file cũ nhất (trừ file đang ghi)."""
        for path in files:
            if os.path.abspath(path) == os.path.abspath(self._path):
                continue
            try:
                os.remove(path)
            except Exception:
                pass
            break

    def _enforce_size_limit(self) -> None:
        """Xóa file log cũ nếu vượt giới hạn thư mục hoặc ổ đĩa gần đầy."""
        try:
            files = self._get_log_files()
            if not files:
                return

            # Điều kiện 1: thư mục vượt giới hạn người dùng đặt
            if self._max_bytes:
                total = sum(os.path.getsize(p) for p in files)
                while total > self._max_bytes and len(files) > 1:
                    oldest = next(
                        (p for p in files
                         if os.path.abspath(p) != os.path.abspath(self._path)),
                        None
                    )
                    if not oldest:
                        break
                    total -= os.path.getsize(oldest)
                    os.remove(oldest)
                    files.remove(oldest)

            # Điều kiện 2: ổ đĩa còn dưới 5GB (luôn kiểm tra dù có hay không có giới hạn)
            free = shutil.disk_usage(self._output_dir).free
            while free < _MIN_FREE_BYTES and len(files) > 1:
                oldest = next(
                    (p for p in files
                     if os.path.abspath(p) != os.path.abspath(self._path)),
                    None
                )
                if not oldest:
                    break
                os.remove(oldest)
                files.remove(oldest)
                free = shutil.disk_usage(self._output_dir).free

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
