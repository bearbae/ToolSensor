"""Receive NMEA sentences from Serial port or TCP (client/server)."""

import socket
import threading
import time

from PyQt6.QtCore import QThread, pyqtSignal

from classifier import classify


class ReceiverThread(QThread):
    sentence_received = pyqtSignal(str, str)   # (sentence, type_tag)
    status_changed    = pyqtSignal(str)
    error             = pyqtSignal(str)

    def __init__(self, mode: str, **kwargs):
        """
        mode: 'serial' | 'tcp_client' | 'tcp_server'
        kwargs for serial:     port, baud
        kwargs for tcp_client: host, port
        kwargs for tcp_server: host, port
        """
        super().__init__()
        self._mode    = mode
        self._kwargs  = kwargs
        self._running = False

    def stop(self) -> None:
        self._running = False

    # ── dispatch ────────────────────────────────────────────────────────────

    def run(self) -> None:
        self._running = True
        try:
            if self._mode == 'serial':
                self._run_serial()
            elif self._mode == 'tcp_client':
                self._run_tcp_client()   # tự xử lý retry bên trong
            elif self._mode == 'tcp_server':
                self._run_tcp_server()
        except Exception as exc:
            if self._running:            # chỉ báo lỗi khi không phải do stop()
                self.error.emit(str(exc))

    # ── helpers ─────────────────────────────────────────────────────────────

    def _emit(self, line: str) -> None:
        line = line.strip()
        if line and line[0] in ('$', '!'):
            tag = classify(line)
            self.sentence_received.emit(line, tag)

    def _split_lines(self, buf: str, chunk: str):
        buf += chunk
        while '\n' in buf:
            line, buf = buf.split('\n', 1)
            self._emit(line)
        # Xóa buffer nếu quá lớn mà không có newline (tránh memory leak)
        if len(buf) > 8192:
            buf = ''
        return buf

    # ── serial (có tự động kết nối lại) ────────────────────────────────────

    def _run_serial(self) -> None:
        import serial
        port = self._kwargs['port']
        baud = self._kwargs.get('baud', 4800)

        while self._running:
            try:
                self.status_changed.emit(f"Đang mở cổng {port}…")
                with serial.Serial(port, baud, timeout=1) as ser:
                    self.status_changed.emit(f"Serial {port} @ {baud} baud")
                    raw_buf = b''
                    while self._running:
                        try:
                            data = ser.read(256)
                            if data:
                                raw_buf += data
                                while b'\n' in raw_buf:
                                    line_b, raw_buf = raw_buf.split(b'\n', 1)
                                    self._emit(line_b.decode('ascii', errors='replace'))
                                if len(raw_buf) > 8192:
                                    raw_buf = b''
                        except serial.SerialException as exc:
                            self.status_changed.emit(
                                f"Lỗi Serial: {exc}, thử lại sau {self._RETRY_DELAY}s…"
                            )
                            break
            except Exception as exc:
                if not self._running:
                    break
                self.status_changed.emit(
                    f"Không mở được {port}: {exc}, thử lại sau {self._RETRY_DELAY}s…"
                )

            for _ in range(self._RETRY_DELAY * 2):
                if not self._running:
                    return
                time.sleep(0.5)

    # ── TCP client (có tự động kết nối lại) ────────────────────────────────

    _RETRY_DELAY = 5   # giây chờ giữa các lần thử lại

    _NO_DATA_TIMEOUT = 30   # giây không nhận data → coi như mất kết nối

    def _apply_keepalive(self, sock: socket.socket) -> None:
        """Bật TCP keepalive để OS phát hiện kết nối chết."""
        try:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            if hasattr(socket, 'TCP_KEEPIDLE'):    # Linux
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPIDLE, 10)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPINTVL, 5)
                sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_KEEPCNT, 3)
        except Exception:
            pass

    def _run_tcp_client(self) -> None:
        host = self._kwargs['host']
        port = self._kwargs['port']

        while self._running:
            try:
                self.status_changed.emit(f"Đang kết nối {host}:{port}…")
                with socket.create_connection((host, port), timeout=5) as sock:
                    self._apply_keepalive(sock)
                    sock.settimeout(1.0)
                    self.status_changed.emit(f"Đã kết nối {host}:{port}")
                    buf = ''
                    last_data = time.time()
                    while self._running:
                        try:
                            data = sock.recv(4096).decode('ascii', errors='replace')
                            if not data:
                                self.status_changed.emit("Bên phát ngắt kết nối, đang thử lại…")
                                break
                            last_data = time.time()
                            buf = self._split_lines(buf, data)
                        except socket.timeout:
                            if time.time() - last_data > self._NO_DATA_TIMEOUT:
                                self.status_changed.emit("Không nhận được data, đang thử kết nối lại…")
                                break
                            continue
            except OSError as exc:
                if not self._running:
                    break
                self.status_changed.emit(
                    f"Kết nối thất bại ({exc.strerror}), thử lại sau {self._RETRY_DELAY}s…"
                )

            # Chờ trước khi thử lại — kiểm tra _running mỗi 0.5s
            for _ in range(self._RETRY_DELAY * 2):
                if not self._running:
                    return
                time.sleep(0.5)

    # ── TCP server ──────────────────────────────────────────────────────────

    _MAX_SERVER_CLIENTS = 20

    def _run_tcp_server(self) -> None:
        host = self._kwargs.get('host', '0.0.0.0')
        port = self._kwargs['port']
        client_threads: list[threading.Thread] = []
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(10)
            srv.settimeout(1.0)
            self.status_changed.emit(f"TCP Server listening on {host}:{port}")
            while self._running:
                try:
                    conn, addr = srv.accept()
                    # Dọn dẹp thread đã xong trước khi tạo mới
                    client_threads = [t for t in client_threads if t.is_alive()]
                    if len(client_threads) >= self._MAX_SERVER_CLIENTS:
                        conn.close()
                        continue
                    self.status_changed.emit(f"Client connected: {addr[0]}:{addr[1]}")
                    t = threading.Thread(
                        target=self._handle_client, args=(conn,), daemon=True
                    )
                    t.start()
                    client_threads.append(t)
                except socket.timeout:
                    continue

    def _handle_client(self, conn: socket.socket) -> None:
        conn.settimeout(1.0)
        buf = ''
        with conn:
            while self._running:
                try:
                    data = conn.recv(4096).decode('ascii', errors='replace')
                    if not data:
                        break
                    buf = self._split_lines(buf, data)
                except socket.timeout:
                    continue
