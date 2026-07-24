"""Replay engine — sends parsed log records through a transmitter with original timing."""

import time
import threading

from PyQt6.QtCore import QThread, pyqtSignal


class ReplayThread(QThread):
    """Worker thread that replays log records respecting original inter-message delays."""

    sentence_sent = pyqtSignal(str, str)   # (sentence, type_tag)
    progress      = pyqtSignal(int, int)   # (current_index, total)
    finished      = pyqtSignal()
    error         = pyqtSignal(str)

    def __init__(self, records: list, transmitter, speed: float = 1.0):
        super().__init__()
        self._records     = records      # list of (datetime, type_tag, sentence)
        self._transmitter = transmitter
        self._speed       = speed
        self._running     = False
        self._pause_evt   = threading.Event()
        self._pause_evt.set()           # not paused initially

    # ── Public controls ────────────────────────────────────────────────────

    def set_speed(self, speed: float) -> None:
        self._speed = max(0.1, speed)

    def pause(self) -> None:
        self._pause_evt.clear()

    def resume(self) -> None:
        self._pause_evt.set()

    def stop(self) -> None:
        self._running = False
        self._pause_evt.set()   # unblock any waiting sleep

    # ── Thread body ────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        total    = len(self._records)
        prev_ts  = None

        for idx, (ts, type_tag, sentence) in enumerate(self._records):
            if not self._running:
                break

            # Wait if paused
            self._pause_evt.wait()
            if not self._running:
                break

            # Reproduce original inter-message delay, scaled by speed
            if prev_ts is not None:
                delay_s = (ts - prev_ts).total_seconds() / self._speed
                if delay_s > 0:
                    deadline = time.monotonic() + delay_s
                    while time.monotonic() < deadline:
                        if not self._running:
                            break
                        self._pause_evt.wait()
                        remaining = deadline - time.monotonic()
                        if remaining > 0:
                            time.sleep(min(0.02, remaining))

            if not self._running:
                break

            try:
                self._transmitter.send(sentence + '\r\n')
            except Exception as exc:
                self.error.emit(str(exc))
                break

            self.sentence_sent.emit(sentence, type_tag)
            self.progress.emit(idx + 1, total)
            prev_ts = ts

        self.finished.emit()
