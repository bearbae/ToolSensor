"""TCP and Serial transmitters, plus a QThread-based sender."""

import socket
import threading
import time

import serial
import serial.tools.list_ports
from PyQt6.QtCore import QThread, pyqtSignal

from generators import GPSGenerator, RadarTTMGenerator, AISGenerator


def list_serial_ports() -> list:
    """Return a sorted list of available COM port device names."""
    return sorted(p.device for p in serial.tools.list_ports.comports())


class TCPTransmitter:
    """Connects as a TCP client and sends NMEA sentences."""

    def __init__(self, host: str, port: int):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.settimeout(5.0)
        self._sock.connect((host, port))

    def send(self, data: str) -> None:
        self._sock.sendall((data + '\r\n').encode('ascii'))

    def close(self) -> None:
        try:
            self._sock.close()
        except Exception:
            pass


class TCPServerTransmitter:
    """Listens as a TCP server; broadcasts NMEA sentences to all connected clients."""

    def __init__(self, host: str, port: int):
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind((host, port))
        self._sock.listen(10)
        self._sock.settimeout(0.5)
        self._clients: list = []
        self._lock = threading.Lock()
        self._running = True
        self._accept_thread = threading.Thread(target=self._accept_loop, daemon=True)
        self._accept_thread.start()

    def _accept_loop(self) -> None:
        while self._running:
            try:
                conn, _ = self._sock.accept()
                conn.settimeout(2.0)
                with self._lock:
                    self._clients.append(conn)
            except socket.timeout:
                continue
            except Exception:
                break

    def send(self, data: str) -> None:
        dead = []
        with self._lock:
            for client in self._clients:
                try:
                    client.sendall((data + '\r\n').encode('ascii'))
                except Exception:
                    dead.append(client)
            for d in dead:
                self._clients.remove(d)

    def client_count(self) -> int:
        with self._lock:
            return len(self._clients)

    def close(self) -> None:
        self._running = False
        with self._lock:
            for client in self._clients:
                try:
                    client.close()
                except Exception:
                    pass
            self._clients.clear()
        try:
            self._sock.close()
        except Exception:
            pass


class SerialTransmitter:
    """Opens a serial port and sends NMEA sentences."""

    def __init__(
        self,
        port: str,
        baudrate: int = 4800,
        parity: str = 'N',
        bytesize: int = 8,
        stopbits: float = 1,
    ):
        self._ser = serial.Serial(
            port=port,
            baudrate=baudrate,
            parity=parity,
            bytesize=bytesize,
            stopbits=stopbits,
            timeout=1,
        )

    def send(self, data: str) -> None:
        self._ser.write((data + '\r\n').encode('ascii'))

    def close(self) -> None:
        try:
            self._ser.close()
        except Exception:
            pass


class TransmitterThread(QThread):
    """Background thread that periodically generates and sends NMEA sentences."""

    message_sent = pyqtSignal(str)
    error_occurred = pyqtSignal(str)

    def __init__(
        self,
        transmitter,
        gps_gen: GPSGenerator | None,
        radar_gen: RadarTTMGenerator | None,
        ais_gen: AISGenerator | None,
        interval_ms: int = 1000,
    ):
        super().__init__()
        self._transmitter = transmitter
        self._gps_gen = gps_gen
        self._radar_gen = radar_gen
        self._ais_gen = ais_gen
        self._interval_ms = interval_ms
        self._running = False

    def set_interval(self, ms: int) -> None:
        self._interval_ms = ms

    def run(self) -> None:
        self._running = True
        while self._running:
            try:
                messages: list[str] = []
                if self._gps_gen:
                    messages.extend(self._gps_gen.generate_all())
                if self._radar_gen:
                    # Sync own-ship position so bearing/range stay correct
                    if self._gps_gen:
                        self._radar_gen.own_lat = self._gps_gen.lat
                        self._radar_gen.own_lon = self._gps_gen.lon
                    messages.extend(self._radar_gen.generate_all())
                if self._ais_gen:
                    messages.extend(self._ais_gen.generate_all())

                for msg in messages:
                    if not self._running:
                        break
                    self._transmitter.send(msg)
                    self.message_sent.emit(msg)

            except Exception as exc:
                self.error_occurred.emit(str(exc))
                self._running = False
                break

            # Sleep in 50 ms ticks so stop() is responsive
            elapsed = 0
            while elapsed < self._interval_ms and self._running:
                time.sleep(0.05)
                elapsed += 50

    def stop(self) -> None:
        self._running = False
        self.wait(3000)
