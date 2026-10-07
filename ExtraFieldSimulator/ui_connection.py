"""Connection panel — TCP Client/Server, UDP, Serial, SSH Tunnel."""

from PyQt6.QtCore import Qt
from PyQt6.QtWidgets import (
    QButtonGroup,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QRadioButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

import ssh_settings
from ssh_tunnel import SSHTunnel, fetch_pod_ip
from transmitters import (
    SerialTransmitter,
    TCPServerTransmitter,
    TCPTransmitter,
    UDPTransmitter,
    list_serial_ports,
)
from ui_common import _btn_qss


class ConnectionPanelMixin:
    def _build_connection_panel(self) -> QGroupBox:
        group = QGroupBox("Connection")
        layout = QVBoxLayout(group)

        # Mode radio buttons
        mode_row = QHBoxLayout()
        self._rb_tcp = QRadioButton("TCP Client")
        self._rb_tcp_server = QRadioButton("TCP Server")
        self._rb_udp = QRadioButton("UDP")
        self._rb_serial = QRadioButton("Serial Port")
        self._rb_ssh = QRadioButton("SSH Tunnel")
        self._rb_tcp.setChecked(True)
        self._mode_grp = QButtonGroup(self)
        self._mode_grp.addButton(self._rb_tcp)
        self._mode_grp.addButton(self._rb_tcp_server)
        self._mode_grp.addButton(self._rb_udp)
        self._mode_grp.addButton(self._rb_serial)
        self._mode_grp.addButton(self._rb_ssh)
        mode_row.addWidget(self._rb_tcp)
        mode_row.addWidget(self._rb_tcp_server)
        mode_row.addWidget(self._rb_udp)
        mode_row.addWidget(self._rb_serial)
        mode_row.addWidget(self._rb_ssh)
        layout.addLayout(mode_row)

        # TCP Client sub-panel
        self._tcp_widget = QWidget()
        tcp_form = QFormLayout(self._tcp_widget)
        tcp_form.setContentsMargins(0, 0, 0, 0)
        self._tcp_host = QLineEdit("127.0.0.1")
        self._tcp_port = QSpinBox()
        self._tcp_port.setRange(1, 65535)
        self._tcp_port.setValue(10110)
        tcp_form.addRow("Host:", self._tcp_host)
        tcp_form.addRow("Port:", self._tcp_port)
        layout.addWidget(self._tcp_widget)

        # TCP Server sub-panel
        self._tcp_server_widget = QWidget()
        srv_form = QFormLayout(self._tcp_server_widget)
        srv_form.setContentsMargins(0, 0, 0, 0)
        self._srv_host = QLineEdit("0.0.0.0")
        self._srv_port = QSpinBox()
        self._srv_port.setRange(1, 65535)
        self._srv_port.setValue(10110)
        self._lbl_clients = QLabel("0 clients connected")
        self._lbl_clients.setStyleSheet("color: #0d6efd; font-weight: bold;")
        srv_form.addRow("Bind IP:", self._srv_host)
        srv_form.addRow("Port:", self._srv_port)
        srv_form.addRow("", self._lbl_clients)
        self._tcp_server_widget.setVisible(False)
        layout.addWidget(self._tcp_server_widget)

        # UDP sub-panel
        self._udp_widget = QWidget()
        udp_form = QFormLayout(self._udp_widget)
        udp_form.setContentsMargins(0, 0, 0, 0)
        self._udp_host = QLineEdit("127.0.0.1")
        self._udp_host.setToolTip("Nhập 255.255.255.255 để broadcast toàn mạng LAN")
        self._udp_port = QSpinBox()
        self._udp_port.setRange(1, 65535)
        self._udp_port.setValue(10110)
        self._udp_broadcast = QCheckBox("Broadcast (bật SO_BROADCAST)")
        udp_form.addRow("Host:", self._udp_host)
        udp_form.addRow("Port:", self._udp_port)
        udp_form.addRow("", self._udp_broadcast)
        self._udp_widget.setVisible(False)
        layout.addWidget(self._udp_widget)

        # Serial sub-panel
        self._serial_widget = QWidget()
        serial_form = QFormLayout(self._serial_widget)
        serial_form.setContentsMargins(0, 0, 0, 0)

        port_row = QHBoxLayout()
        self._serial_port = QComboBox()
        self._btn_refresh = QPushButton("Refresh")
        self._btn_refresh.setFixedWidth(68)
        port_row.addWidget(self._serial_port, stretch=1)
        port_row.addWidget(self._btn_refresh)

        self._serial_baud = QComboBox()
        self._serial_baud.addItems(["4800", "9600", "19200", "38400", "115200"])

        self._serial_parity = QComboBox()
        self._serial_parity.addItems(["None (N)", "Even (E)", "Odd (O)"])

        self._serial_bits = QComboBox()
        self._serial_bits.addItems(["8", "7"])

        serial_form.addRow("Port:", port_row)
        serial_form.addRow("Baudrate:", self._serial_baud)
        serial_form.addRow("Parity:", self._serial_parity)
        serial_form.addRow("Data bits:", self._serial_bits)

        self._serial_widget.setVisible(False)
        layout.addWidget(self._serial_widget)

        # SSH Tunnel sub-panel — kết nối tới enc-sensor-gateway khi máy
        # không có đường mạng trực tiếp tới server (xem
        # enc-docs/Ket-Noi-Tool-Test-Sensor-Gateway.md). Tự mở SSH local
        # port-forward rồi kết nối TCP Client vào 127.0.0.1:<local_port>.
        self._ssh_widget = QWidget()
        ssh_form = QFormLayout(self._ssh_widget)
        ssh_form.setContentsMargins(0, 0, 0, 0)

        self._ssh_host = QLineEdit()
        self._ssh_host.setPlaceholderText("vd: 171.244.197.133")
        self._ssh_port = QSpinBox()
        self._ssh_port.setRange(1, 65535)
        self._ssh_port.setValue(2222)
        self._ssh_user = QLineEdit("root")

        pass_row = QHBoxLayout()
        self._ssh_pass = QLineEdit()
        self._ssh_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._ssh_remember_pass = QCheckBox("Nhớ mật khẩu")
        self._ssh_remember_pass.setToolTip(
            "Lưu mật khẩu vào ~/.maritime_simulator.json để lần sau tự điền sẵn"
        )
        pass_row.addWidget(self._ssh_pass, stretch=1)
        pass_row.addWidget(self._ssh_remember_pass)

        self._ssh_namespace = QLineEdit("enc-ship")
        self._ssh_label_selector = QLineEdit("app=enc-sensor-gateway")

        pod_row = QHBoxLayout()
        self._ssh_pod_ip = QLineEdit()
        self._ssh_pod_ip.setPlaceholderText("vd: 10.42.0.96")
        self._btn_ssh_fetch_pod_ip = QPushButton("Lấy Pod IP")
        self._btn_ssh_fetch_pod_ip.setToolTip(
            "Chạy 'kubectl get pod' qua SSH để lấy IP hiện tại của pod\n"
            "(đổi mỗi lần pod restart)"
        )
        pod_row.addWidget(self._ssh_pod_ip, stretch=1)
        pod_row.addWidget(self._btn_ssh_fetch_pod_ip)

        self._ssh_remote_port = QSpinBox()
        self._ssh_remote_port.setRange(1, 65535)
        self._ssh_remote_port.setValue(5001)
        self._ssh_remote_port.setToolTip("Cổng thiết bị — lấy từ cột config của bảng device")

        self._ssh_local_port = QSpinBox()
        self._ssh_local_port.setRange(1, 65535)
        self._ssh_local_port.setValue(5001)
        self._ssh_local_port.setToolTip("Cổng local trên máy bạn, tool sẽ kết nối TCP Client vào 127.0.0.1:<cổng này>")

        ssh_form.addRow("SSH Host:", self._ssh_host)
        ssh_form.addRow("SSH Port:", self._ssh_port)
        ssh_form.addRow("Username:", self._ssh_user)
        ssh_form.addRow("Password:", pass_row)
        ssh_form.addRow("k8s Namespace:", self._ssh_namespace)
        ssh_form.addRow("Pod Selector:", self._ssh_label_selector)
        ssh_form.addRow("Pod IP:", pod_row)
        ssh_form.addRow("Cổng thiết bị:", self._ssh_remote_port)
        ssh_form.addRow("Cổng local:", self._ssh_local_port)

        self._ssh_widget.setVisible(False)
        layout.addWidget(self._ssh_widget)
        self._load_ssh_settings()

        # Connect / Disconnect
        conn_row = QHBoxLayout()
        self._btn_connect = QPushButton("Connect")
        self._btn_connect.setStyleSheet(
            _btn_qss("#28a745", "#218838", "#1a6b2a")
        )
        self._btn_disconnect = QPushButton("Disconnect")
        self._btn_disconnect.setStyleSheet(
            _btn_qss("#dc3545", "#c82333", "#a71d2a")
        )
        self._btn_disconnect.setEnabled(False)
        conn_row.addWidget(self._btn_connect)
        conn_row.addWidget(self._btn_disconnect)
        layout.addLayout(conn_row)

        self._refresh_ports()
        return group

    def _on_mode_changed(self) -> None:
        self._tcp_widget.setVisible(self._rb_tcp.isChecked())
        self._tcp_server_widget.setVisible(self._rb_tcp_server.isChecked())
        self._udp_widget.setVisible(self._rb_udp.isChecked())
        self._serial_widget.setVisible(self._rb_serial.isChecked())
        self._ssh_widget.setVisible(self._rb_ssh.isChecked())

    def _refresh_ports(self) -> None:
        self._serial_port.clear()
        ports = list_serial_ports()
        if ports:
            self._serial_port.addItems(ports)
        else:
            self._serial_port.addItem("(no ports found)")

    # Connection ----------------------------------------------------------

    def _on_connect(self) -> None:
        try:
            if self._rb_tcp.isChecked():
                host = self._tcp_host.text().strip()
                port = self._tcp_port.value()
                self._transmitter = TCPTransmitter(host, port)
                label = f"TCP Client  {host}:{port}"
            elif self._rb_tcp_server.isChecked():
                host = self._srv_host.text().strip()
                port = self._srv_port.value()
                self._transmitter = TCPServerTransmitter(host, port)
                label = f"TCP Server  {host}:{port}"
            elif self._rb_udp.isChecked():
                host = self._udp_host.text().strip()
                port = self._udp_port.value()
                self._transmitter = UDPTransmitter(host, port, broadcast=self._udp_broadcast.isChecked())
                label = f"UDP  {host}:{port}"
            elif self._rb_ssh.isChecked():
                ssh_host = self._ssh_host.text().strip()
                pod_ip = self._ssh_pod_ip.text().strip()
                if not ssh_host or not pod_ip:
                    raise ValueError("Cần nhập SSH Host và Pod IP trước khi kết nối")
                local_port = self._ssh_local_port.value()
                tunnel = SSHTunnel(
                    ssh_host=ssh_host,
                    ssh_port=self._ssh_port.value(),
                    ssh_username=self._ssh_user.text().strip(),
                    ssh_password=self._ssh_pass.text(),
                    remote_host=pod_ip,
                    remote_port=self._ssh_remote_port.value(),
                    local_port=local_port,
                )
                try:
                    self._transmitter = TCPTransmitter("127.0.0.1", tunnel.local_port)
                except Exception:
                    tunnel.close()
                    raise
                self._ssh_tunnel = tunnel
                label = f"SSH Tunnel  127.0.0.1:{tunnel.local_port}  →  {pod_ip}:{self._ssh_remote_port.value()}"
                self._save_ssh_settings()
            else:
                port_name = self._serial_port.currentText()
                baud = int(self._serial_baud.currentText())
                parity_map = {"None (N)": "N", "Even (E)": "E", "Odd (O)": "O"}
                parity = parity_map.get(self._serial_parity.currentText(), "N")
                bits = int(self._serial_bits.currentText())
                self._transmitter = SerialTransmitter(port_name, baud, parity, bits)
                label = f"Serial  {port_name} @ {baud}"

            self._btn_connect.setEnabled(False)
            self._btn_disconnect.setEnabled(True)
            self._btn_start.setEnabled(True)
            self.statusBar().showMessage(f"Connected — {label}")
            self._log_info(f"Connected: {label}")

        except Exception as exc:
            QMessageBox.critical(self, "Connection Error", str(exc))

    def _on_disconnect(self) -> None:
        self._on_stop()
        if self._transmitter:
            self._transmitter.close()
            self._transmitter = None
        if self._ssh_tunnel:
            self._ssh_tunnel.close()
            self._ssh_tunnel = None
        self._btn_connect.setEnabled(True)
        self._btn_disconnect.setEnabled(False)
        self._btn_start.setEnabled(False)
        self.statusBar().showMessage("Disconnected")
        self._log_info("Disconnected")

    def _load_ssh_settings(self) -> None:
        """Điền sẵn panel SSH Tunnel từ ~/.maritime_simulator.json (nếu có),
        hoặc giá trị mặc định (SSH Host = 171.244.197.133) nếu chưa từng lưu."""
        cfg = ssh_settings.load()
        self._ssh_host.setText(cfg["ssh_host"])
        self._ssh_port.setValue(cfg["ssh_port"])
        self._ssh_user.setText(cfg["ssh_user"])
        self._ssh_namespace.setText(cfg["ssh_namespace"])
        self._ssh_label_selector.setText(cfg["ssh_label_selector"])
        self._ssh_pod_ip.setText(cfg["ssh_pod_ip"])
        self._ssh_remote_port.setValue(cfg["ssh_remote_port"])
        self._ssh_local_port.setValue(cfg["ssh_local_port"])
        self._ssh_remember_pass.setChecked(cfg["ssh_remember_password"])
        if cfg["ssh_remember_password"]:
            self._ssh_pass.setText(cfg["ssh_password"])

    def _save_ssh_settings(self) -> None:
        """Lưu panel SSH Tunnel vào ~/.maritime_simulator.json sau khi kết
        nối thành công lần đầu — mật khẩu chỉ lưu nếu tick 'Nhớ mật khẩu'."""
        remember = self._ssh_remember_pass.isChecked()
        cfg = {
            "ssh_host": self._ssh_host.text().strip(),
            "ssh_port": self._ssh_port.value(),
            "ssh_user": self._ssh_user.text().strip(),
            "ssh_password": self._ssh_pass.text() if remember else "",
            "ssh_remember_password": remember,
            "ssh_namespace": self._ssh_namespace.text().strip(),
            "ssh_label_selector": self._ssh_label_selector.text().strip(),
            "ssh_pod_ip": self._ssh_pod_ip.text().strip(),
            "ssh_remote_port": self._ssh_remote_port.value(),
            "ssh_local_port": self._ssh_local_port.value(),
        }
        try:
            ssh_settings.save(cfg)
        except Exception:
            pass

    def _on_ssh_fetch_pod_ip(self) -> None:
        ssh_host = self._ssh_host.text().strip()
        if not ssh_host:
            QMessageBox.warning(self, "Thiếu thông tin", "Nhập SSH Host trước")
            return
        self.setCursor(Qt.CursorShape.WaitCursor)
        self._btn_ssh_fetch_pod_ip.setEnabled(False)
        try:
            pod_ip = fetch_pod_ip(
                ssh_host=ssh_host,
                ssh_port=self._ssh_port.value(),
                ssh_username=self._ssh_user.text().strip(),
                ssh_password=self._ssh_pass.text(),
                namespace=self._ssh_namespace.text().strip(),
                label_selector=self._ssh_label_selector.text().strip(),
            )
            self._ssh_pod_ip.setText(pod_ip)
            self._log_info(f"Đã lấy Pod IP: {pod_ip}")
        except Exception as exc:
            QMessageBox.critical(self, "Lấy Pod IP thất bại", str(exc))
        finally:
            self._btn_ssh_fetch_pod_ip.setEnabled(True)
            self.unsetCursor()
