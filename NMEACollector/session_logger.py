"""Write NMEA sentences to a timestamped .bin log file."""

import os
from datetime import datetime


class SessionLogger:
    def __init__(self, output_dir: str, prefix: str = 'session',
                 existing_path: str | None = None):
        """
        Nếu existing_path được cung cấp, mở file đó để ghi tiếp (append).
        Ngược lại tạo file mới với timestamp.
        """
        if existing_path:
            self._path = existing_path
            self._file = open(self._path, 'a', encoding='utf-8')
            # Đếm số dòng đã có
            with open(self._path, 'r', encoding='utf-8', errors='replace') as f:
                self._count = sum(1 for _ in f)
        else:
            os.makedirs(output_dir, exist_ok=True)
            ts = datetime.now().strftime('%Y%m%d_%H%M%S')
            self._path = os.path.join(output_dir, f'{prefix}_{ts}.bin')
            self._file = open(self._path, 'w', encoding='utf-8')
            self._count = 0
        self._started = datetime.now()

    @property
    def path(self) -> str:
        return self._path

    @property
    def count(self) -> int:
        return self._count

    @property
    def duration_s(self) -> float:
        return (datetime.now() - self._started).total_seconds()

    def write(self, sentence: str, type_tag: str) -> None:
        ts = datetime.now().isoformat(timespec='milliseconds')
        self._file.write(f'{ts}: [{type_tag}] {sentence}\n')
        self._file.flush()
        self._count += 1

    def close(self) -> None:
        if self._file and not self._file.closed:
            self._file.close()

    @property
    def is_open(self) -> bool:
        return self._file and not self._file.closed
