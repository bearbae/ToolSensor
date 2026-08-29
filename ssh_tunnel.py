"""SSH local port-forward tunnel, for reaching an enc-sensor-gateway pod that
has no direct route from outside the ship LAN (see
enc-docs/Ket-Noi-Tool-Test-Sensor-Gateway.md for the manual procedure this
automates). Implemented directly on top of paramiko's Transport channel
forwarding rather than the (unmaintained) sshtunnel package, which still
references paramiko.DSSKey — removed in paramiko 5.x."""

import select
import socket
import threading

import paramiko


class _ForwardServer(threading.Thread):
    """Listens on a local TCP port; forwards each connection through the SSH
    transport to (remote_host, remote_port)."""

    def __init__(
        self,
        transport: paramiko.Transport,
        local_port: int,
        remote_host: str,
        remote_port: int,
    ):
        super().__init__(daemon=True)
        self._transport = transport
        self._remote_host = remote_host
        self._remote_port = remote_port
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self._sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self._sock.bind(("127.0.0.1", local_port))
        self._sock.listen(5)
        self._sock.settimeout(0.5)
        self.local_port = self._sock.getsockname()[1]
        self._running = True

    def run(self) -> None:
        while self._running:
            try:
                client_sock, _addr = self._sock.accept()
            except socket.timeout:
                continue
            except OSError:
                break
            threading.Thread(
                target=self._handle_client, args=(client_sock,), daemon=True
            ).start()

    def _handle_client(self, client_sock: socket.socket) -> None:
        try:
            channel = self._transport.open_channel(
                "direct-tcpip",
                (self._remote_host, self._remote_port),
                client_sock.getpeername(),
            )
        except Exception:
            channel = None
        if channel is None:
            client_sock.close()
            return

        try:
            while True:
                r, _w, _x = select.select([client_sock, channel], [], [])
                if client_sock in r:
                    data = client_sock.recv(4096)
                    if not data:
                        break
                    channel.send(data)
                if channel in r:
                    data = channel.recv(4096)
                    if not data:
                        break
                    client_sock.send(data)
        except Exception:
            pass
        finally:
            channel.close()
            client_sock.close()

    def stop(self) -> None:
        self._running = False
        try:
            self._sock.close()
        except Exception:
            pass


class SSHTunnel:
    """Opens 127.0.0.1:<local_port> -> <remote_host>:<remote_port> through an SSH server."""

    def __init__(
        self,
        ssh_host: str,
        ssh_port: int,
        ssh_username: str,
        ssh_password: str,
        remote_host: str,
        remote_port: int,
        local_port: int,
    ):
        self._client = paramiko.SSHClient()
        self._client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        self._client.connect(
            ssh_host,
            port=ssh_port,
            username=ssh_username,
            password=ssh_password,
            timeout=10,
        )
        transport = self._client.get_transport()
        self._forwarder = _ForwardServer(transport, local_port, remote_host, remote_port)
        self._forwarder.start()

    @property
    def local_port(self) -> int:
        return self._forwarder.local_port

    def close(self) -> None:
        try:
            self._forwarder.stop()
        except Exception:
            pass
        try:
            self._client.close()
        except Exception:
            pass


def fetch_pod_ip(
    ssh_host: str,
    ssh_port: int,
    ssh_username: str,
    ssh_password: str,
    namespace: str,
    label_selector: str,
    timeout: float = 8.0,
) -> str:
    """Run `kubectl get pod -o jsonpath=...` over SSH and return the pod IP.

    Raises RuntimeError with a human-readable message on failure.
    """
    client = paramiko.SSHClient()
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(
            ssh_host,
            port=ssh_port,
            username=ssh_username,
            password=ssh_password,
            timeout=timeout,
        )
        cmd = (
            f"kubectl -n {namespace} get pod -l {label_selector} "
            "-o jsonpath='{.items[0].status.podIP}'"
        )
        _stdin, stdout, stderr = client.exec_command(cmd, timeout=timeout)
        pod_ip = stdout.read().decode().strip()
        err = stderr.read().decode().strip()
        if not pod_ip:
            raise RuntimeError(err or "Không lấy được Pod IP (kết quả rỗng — pod có đang chạy không?)")
        return pod_ip
    finally:
        client.close()
