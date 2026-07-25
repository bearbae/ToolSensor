"""Receive NMEA sentences from Serial port or TCP (client/server)."""

import socket
import threading

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
                self._run_tcp_client()
            elif self._mode == 'tcp_server':
                self._run_tcp_server()
        except Exception as exc:
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
        return buf

    # ── serial ──────────────────────────────────────────────────────────────

    def _run_serial(self) -> None:
        import serial
        port = self._kwargs['port']
        baud = self._kwargs.get('baud', 4800)
        with serial.Serial(port, baud, timeout=1) as ser:
            self.status_changed.emit(f"Serial {port} @ {baud} baud")
            raw_buf = b''
            while self._running:
                data = ser.read(256)
                if data:
                    raw_buf += data
                    while b'\n' in raw_buf:
                        line_b, raw_buf = raw_buf.split(b'\n', 1)
                        self._emit(line_b.decode('ascii', errors='replace'))

    # ── TCP client ──────────────────────────────────────────────────────────

    def _run_tcp_client(self) -> None:
        host = self._kwargs['host']
        port = self._kwargs['port']
        with socket.create_connection((host, port), timeout=5) as sock:
            sock.settimeout(1.0)
            self.status_changed.emit(f"TCP Client connected to {host}:{port}")
            buf = ''
            while self._running:
                try:
                    data = sock.recv(4096).decode('ascii', errors='replace')
                    if not data:
                        self.status_changed.emit("TCP server closed connection")
                        break
                    buf = self._split_lines(buf, data)
                except socket.timeout:
                    continue

    # ── TCP server ──────────────────────────────────────────────────────────

    def _run_tcp_server(self) -> None:
        host = self._kwargs.get('host', '0.0.0.0')
        port = self._kwargs['port']
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as srv:
            srv.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            srv.bind((host, port))
            srv.listen(10)
            srv.settimeout(1.0)
            self.status_changed.emit(f"TCP Server listening on {host}:{port}")
            while self._running:
                try:
                    conn, addr = srv.accept()
                    self.status_changed.emit(f"Client connected: {addr[0]}:{addr[1]}")
                    t = threading.Thread(
                        target=self._handle_client, args=(conn,), daemon=True
                    )
                    t.start()
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
