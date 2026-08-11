"""Tab Camera cho giao diện — danh sách camera, ghi hình, ảnh chụp và replay.

Chỉ là lớp vỏ: mọi việc thật (chạy ffmpeg, canh hạn mức, ghi manifest) nằm ở `camera.py` và
chạy được độc lập bằng dòng lệnh. Ở đây chỉ có dựng widget, đẩy log lên màn hình và hỏi trạng
thái theo nhịp.

Bộ ghi chạy trên thread thường (không phải QThread) nên callback của nó KHÔNG được đụng vào
widget. Mọi thứ đi qua `_Bridge` — pyqtSignal tự xếp hàng về luồng giao diện.
"""

import os
import subprocess
import time
from dataclasses import replace
from pathlib import Path

from PyQt6.QtCore import Qt, QObject, QThread, QTimer, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QPixmap
from PyQt6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QScrollArea,
    QMenu,
    QSpinBox,
    QSplitter,
    QToolButton,
    QVBoxLayout,
    QWidget,
)

import camera
import camera_store
import onvif_client
from camera import (
    MODE_CONTINUOUS,
    MODE_SAMPLE,
    MODE_SESSION,
    CameraRecorder,
    ProbeResult,
    RecordConfig,
    ReplaySession,
    human_bytes,
)

_LOG_BG = "#1e1e1e"
_COL_INFO = "#90a4ae"
_COL_OK = "#00e676"
_COL_WARN = "#ffee58"
_COL_ERROR = "#ef5350"
_COL_FFMPEG = "#78909c"

# Ô log chỉ giữ chừng này dòng — bản đầy đủ nằm ở <thư mục camera>/log/<ngày>.log
_MAX_LOG_LINES = 2000


def _btn_qss(normal: str, hover: str, pressed: str, text: str = "white") -> str:
    """Giống hệt hàm cùng tên trong main.py — chép lại để module này không phụ thuộc ngược."""
    return (
        f"QPushButton {{ background-color:{normal}; color:{text}; font-weight:bold;"
        f" border:none; border-radius:4px; padding:5px 12px; }}"
        f"QPushButton:hover {{ background-color:{hover}; }}"
        f"QPushButton:pressed {{ background-color:{pressed}; }}"
        f"QPushButton:disabled {{ background-color:#4a4a4a; color:#888888; }}"
    )


class _Bridge(QObject):
    """Cầu nối luồng nền → giao diện."""

    log = pyqtSignal(str, str, str)  # tên camera, mức, nội dung


class _OnvifThread(QThread):
    """Hỏi ONVIF ở luồng riêng — camera trên tàu qua switch chậm, chờ tới 10s là thường."""

    done = pyqtSignal(str, object, str)  # tên camera, danh sách profile, lỗi

    def __init__(self, name: str, url: str, user: str, password: str) -> None:
        super().__init__()
        self._name = name
        self._url = url
        self._user = user
        self._pass = password

    def run(self) -> None:
        profiles, err = onvif_client.get_profiles(self._url, self._user, self._pass)
        self.done.emit(self._name, profiles, err)


class _ProbeThread(QThread):
    """Kiểm tra kết nối ở luồng riêng — probe có thể treo tới 20 giây, không thể chạy trên GUI."""

    done = pyqtSignal(str, object)

    def __init__(self, name: str, url: str, snap_path: Path) -> None:
        super().__init__()
        self._name = name
        self._url = url  # đã kèm credential (RecordConfig.effective_url)
        self._snap = snap_path

    def run(self) -> None:
        res = camera.probe(self._url)
        # Kết nối được thì chụp luôn một khung: thấy hình là bằng chứng gọn nhất cho việc
        # "đã tới được thiết bị", khỏi phải bật ghi mới biết.
        if res.ok:
            camera.snapshot(self._url, self._snap)
        self.done.emit(self._name, res)


class _Session:
    """Một dòng trong danh sách: cấu hình + bộ ghi + kết quả kiểm tra gần nhất."""

    def __init__(self, cfg: RecordConfig) -> None:
        self.cfg = cfg
        self.rec: CameraRecorder | None = None
        self.probe: ProbeResult | None = None
        self.probe_thread: _ProbeThread | None = None
        self.onvif_thread: _OnvifThread | None = None
        self.profiles: list = []
        self.snap_mtime = 0.0

    @property
    def recording(self) -> bool:
        return bool(self.rec and self.rec.is_running())


class CameraTab(QWidget):
    """Tab Camera: nhiều camera song song, mỗi dòng một phiên ghi độc lập."""

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self._sessions: dict = {}
        self._order: list = []
        self._loading = False
        self._replay: ReplaySession | None = None
        self._snap_pix: QPixmap | None = None
        self._default_root = str(Path.home() / "camera_recordings")

        self._bridge = _Bridge()
        self._bridge.log.connect(self._on_log)

        self._build_ui()
        self._check_tools()
        self._load_profiles()

        # Một nhịp duy nhất cho mọi thứ đọc-để-hiện: trạng thái, dung lượng, ảnh chụp.
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._refresh)
        self._timer.start()

    # ------------------------------------------------------------------
    # Dựng giao diện
    # ------------------------------------------------------------------

    @staticmethod
    def _form() -> QFormLayout:
        """QFormLayout chịu được cửa sổ hẹp.

        Mặc định Qt giữ nhãn và ô nhập trên cùng một hàng bằng mọi giá; hẹp quá thì nó bóp các
        hàng xuống dưới mức tối thiểu và chúng chồng lên nhau — đúng cảnh đã gặp. WrapLongRows
        cho phép nhãn tự xuống dòng nằm trên ô nhập khi không đủ bề ngang.
        """
        form = QFormLayout()
        form.setRowWrapPolicy(QFormLayout.RowWrapPolicy.WrapLongRows)
        form.setFieldGrowthPolicy(QFormLayout.FieldGrowthPolicy.ExpandingFieldsGrow)
        form.setLabelAlignment(Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter)
        return form

    def _build_ui(self) -> None:
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self._lbl_tools = QLabel()
        self._lbl_tools.setWordWrap(True)
        root.addWidget(self._lbl_tools)

        # Cột trái đặt trong vùng cuộn: cấu hình camera nhiều mục, cửa sổ thấp thì cuộn xuống
        # xem tiếp, chứ không được bóp các hàng cho chúng đè lên nhau.
        left_scroll = QScrollArea()
        left_scroll.setWidget(self._build_left())
        left_scroll.setWidgetResizable(True)
        left_scroll.setFrameShape(left_scroll.Shape.NoFrame)
        left_scroll.setMinimumWidth(340)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        splitter.addWidget(left_scroll)
        splitter.addWidget(self._build_right())
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setSizes([430, 830])
        # Hệ số giãn 1: thiếu nó thì splitter chỉ cao bằng sizeHint, kéo cửa sổ cao lên vẫn bỏ
        # trống cả trăm pixel phía dưới còn cột trái thì vẫn bắt cuộn.
        root.addWidget(splitter, 1)

    def _build_left(self) -> QWidget:
        panel = QWidget()
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(0, 0, 0, 0)

        # --- Danh sách camera ---------------------------------------------
        list_grp = QGroupBox("Camera đã lưu — bấm một dòng để nạp lại toàn bộ cấu hình của nó")
        list_vl = QVBoxLayout(list_grp)
        self._cam_list = QListWidget()
        self._cam_list.setMaximumHeight(96)
        self._cam_list.currentRowChanged.connect(self._on_select)
        list_vl.addWidget(self._cam_list)
        row = QHBoxLayout()
        self._btn_add = QPushButton("Thêm")
        self._btn_dup = QPushButton("Nhân bản")
        self._btn_dup.setToolTip("Chép cấu hình camera đang chọn — thêm camera cùng loại chỉ cần "
                                 "sửa mỗi địa chỉ IP")
        self._btn_del = QPushButton("Xoá")
        self._btn_save = QPushButton("Lưu")
        self._btn_save.setToolTip("Ghi cấu hình mọi camera ra đĩa để lần sau mở app có sẵn")
        self._btn_add.clicked.connect(lambda: self._add_camera())
        self._btn_dup.clicked.connect(self._duplicate_camera)
        self._btn_del.clicked.connect(self._remove_camera)
        self._btn_save.clicked.connect(self._on_save_profiles)
        for b in (self._btn_add, self._btn_dup, self._btn_del, self._btn_save):
            row.addWidget(b)

        # Xuất/nạp file rời nằm sau nút "⋯": mỗi chuyến mới dùng một lần, không đáng chiếm
        # nguyên một hàng trong cột vốn đã phải cuộn.
        self._btn_more = QToolButton()
        self._btn_more.setText("⋯")
        self._btn_more.setToolTip("Xuất / nạp cấu hình ra file JSON")
        self._btn_more.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu = QMenu(self._btn_more)
        menu.addAction("Xuất ra file...", self._on_export)
        menu.addAction("Nạp từ file...", self._on_import)
        self._btn_more.setMenu(menu)
        row.addWidget(self._btn_more)
        list_vl.addLayout(row)

        self._lbl_store = QLabel()
        self._lbl_store.setWordWrap(True)
        self._lbl_store.setStyleSheet(f"color:{_COL_INFO}; font-style:italic;")
        list_vl.addWidget(self._lbl_store)
        layout.addWidget(list_grp)

        # --- Cấu hình -----------------------------------------------------
        cfg_grp = QGroupBox("Cấu hình camera")
        cfg_vl = QVBoxLayout(cfg_grp)
        form = self._form()

        self._ed_name = QLineEdit()
        self._ed_url = QLineEdit()
        self._ed_url.setPlaceholderText("rtsp://admin:matkhau@192.168.1.10:554/...")

        url_row = QHBoxLayout()
        url_row.addWidget(self._ed_url, stretch=1)
        self._btn_probe = QPushButton("Kiểm tra")
        self._btn_probe.setFixedWidth(84)
        self._btn_probe.clicked.connect(self._on_probe)
        url_row.addWidget(self._btn_probe)

        # Tách riêng user/mật khẩu thay vì bắt gõ vào URL: mật khẩu camera hay có @ : / — ghép
        # tay là URL vỡ. camera.with_credentials tự mã hoá rồi mới ghép.
        cred_row = QHBoxLayout()
        self._ed_user = QLineEdit()
        self._ed_user.setPlaceholderText("admin")
        self._ed_pass = QLineEdit()
        self._ed_pass.setEchoMode(QLineEdit.EchoMode.Password)
        self._ed_pass.setPlaceholderText("mật khẩu")
        self._btn_show_pass = QPushButton("Hiện")
        self._btn_show_pass.setFixedWidth(52)
        self._btn_show_pass.setCheckable(True)
        self._btn_show_pass.toggled.connect(
            lambda on: self._ed_pass.setEchoMode(
                QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        cred_row.addWidget(self._ed_user, stretch=1)
        cred_row.addWidget(self._ed_pass, stretch=1)
        cred_row.addWidget(self._btn_show_pass)

        # --- ONVIF: dò luồng cho camera đa cảm biến ------------------------
        # Camera một mắt thì gõ thẳng URL RTSP là xong. Camera nhiệt/hồng ngoại (FLIR...) phát
        # mỗi cảm biến một profile và URL của luồng hồng ngoại KHÔNG đoán được — phải hỏi camera
        # bằng đúng profile token. Hàng này để trống nếu không cần.
        onvif_row = QHBoxLayout()
        self._ed_onvif = QLineEdit()
        self._ed_onvif.setPlaceholderText("http://192.168.1.10/onvif/device_service  (tuỳ chọn)")
        self._btn_onvif = QPushButton("Lấy profile")
        self._btn_onvif.setFixedWidth(96)
        self._btn_onvif.setToolTip("Hỏi camera xem nó có những luồng nào (mắt thường / hồng ngoại...)")
        self._btn_onvif.clicked.connect(self._on_fetch_profiles)
        onvif_row.addWidget(self._ed_onvif, stretch=1)
        onvif_row.addWidget(self._btn_onvif)

        prof_row = QHBoxLayout()
        self._cb_profile = QComboBox()
        self._cb_profile.setEditable(True)  # gõ tay được: nhiều nơi đã biết sẵn token cần dùng
        self._cb_profile.setPlaceholderText("Profile_1 / MP2 ...")
        self._cb_profile.currentIndexChanged.connect(self._on_profile_picked)
        self._btn_stream = QPushButton("Lấy URL")
        self._btn_stream.setFixedWidth(96)
        self._btn_stream.setToolTip("Lấy URL RTSP của token đang chọn và điền vào ô URL phía trên")
        self._btn_stream.clicked.connect(self._on_fetch_stream_uri)
        prof_row.addWidget(self._cb_profile, stretch=1)
        prof_row.addWidget(self._btn_stream)

        dir_row = QHBoxLayout()
        self._ed_dir = QLineEdit()
        self._btn_dir = QPushButton("Chọn")
        self._btn_dir.setFixedWidth(60)
        self._btn_dir.clicked.connect(self._on_pick_dir)
        dir_row.addWidget(self._ed_dir, stretch=1)
        dir_row.addWidget(self._btn_dir)

        form.addRow("Tên:", self._ed_name)
        form.addRow("URL RTSP:", url_row)
        form.addRow("User / Mật khẩu:", cred_row)
        form.addRow("ONVIF URL:", onvif_row)
        form.addRow("Profile token:", prof_row)
        form.addRow("Thư mục lưu:", dir_row)
        cfg_vl.addLayout(form)

        # Lời khuyên quan trọng nhất giữ trên màn hình (một dòng); phần dài để trong tooltip của
        # đúng ô liên quan — người dùng rê chuột vào ô nào thì cần hướng dẫn cho ô đó.
        hint = QLabel("Nên dùng LUỒNG PHỤ của camera — nhẹ hơn ~4 lần (rê chuột vào ô URL)")
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#0d6efd; font-style:italic;")
        cfg_vl.addWidget(hint)

        self._ed_url.setToolTip(
            "URL RTSP của luồng cần ghi.\n\n"
            "Luồng phụ nhẹ hơn khoảng 4 lần, đủ dùng cho việc thu mẫu phân tích:\n"
            "  Hikvision : rtsp://<ip>:554/Streaming/Channels/102\n"
            "  Dahua     : rtsp://<ip>:554/cam/realmonitor?channel=1&subtype=1\n\n"
            "Camera nhiều mắt (nhiệt/hồng ngoại) thì đừng đoán đường dẫn — khai ONVIF URL bên "
            "dưới rồi bấm 'Lấy profile', chọn đúng luồng là ô này tự điền.")
        self._ed_user.setToolTip("Bỏ trống nếu URL đã có sẵn dạng rtsp://user:mật_khẩu@...")
        self._ed_pass.setToolTip("Ký tự đặc biệt (@ : / #) cứ gõ bình thường, tool tự mã hoá "
                                 "khi ghép vào URL.")

        self._lbl_probe = QLabel("Chưa kiểm tra")
        self._lbl_probe.setWordWrap(True)
        self._lbl_probe.setStyleSheet(f"color:{_COL_INFO};")
        cfg_vl.addWidget(self._lbl_probe)

        # --- Chế độ ghi ---------------------------------------------------
        mode_grp = QGroupBox("Chế độ ghi")
        mode_vl = QVBoxLayout(mode_grp)
        self._cb_mode = QComboBox()
        self._cb_mode.addItem("Lấy mẫu — ghi M phút mỗi N phút  (mặc định)", MODE_SAMPLE)
        self._cb_mode.addItem("Theo phiên — chỉ ghi khi bấm", MODE_SESSION)
        self._cb_mode.addItem("Liên tục — ghi suốt, TỐN ĐĨA", MODE_CONTINUOUS)
        self._cb_mode.currentIndexChanged.connect(self._on_mode_changed)
        mode_vl.addWidget(self._cb_mode)

        self._sample_row = QWidget()
        srow = QHBoxLayout(self._sample_row)
        srow.setContentsMargins(0, 0, 0, 0)
        self._sp_on = QDoubleSpinBox()
        self._sp_on.setRange(0.2, 1440)
        self._sp_on.setDecimals(1)
        self._sp_on.setSuffix(" phút ghi")
        self._sp_every = QDoubleSpinBox()
        self._sp_every.setRange(0.5, 1440)
        self._sp_every.setDecimals(1)
        self._sp_every.setSuffix(" phút/chu kỳ")
        srow.addWidget(self._sp_on)
        srow.addWidget(QLabel("mỗi"))
        srow.addWidget(self._sp_every)
        mode_vl.addWidget(self._sample_row)

        self._lbl_estimate = QLabel()
        self._lbl_estimate.setWordWrap(True)
        self._lbl_estimate.setStyleSheet("font-weight:bold;")
        mode_vl.addWidget(self._lbl_estimate)
        cfg_vl.addWidget(mode_grp)

        # --- Hạn mức ------------------------------------------------------
        lim_grp = QGroupBox("Giới hạn dung lượng")
        lim_form = self._form()
        lim_grp.setLayout(lim_form)
        self._sp_quota = QDoubleSpinBox()
        self._sp_quota.setRange(0.5, 100000)
        self._sp_quota.setDecimals(1)
        self._sp_quota.setSuffix(" GB")
        self._sp_quota.setToolTip("Hạn mức riêng của camera này")
        self._sp_free = QDoubleSpinBox()
        self._sp_free.setRange(0.5, 100000)
        self._sp_free.setDecimals(1)
        self._sp_free.setSuffix(" GB")
        self._sp_free.setToolTip("Chừa lại cho gateway / log cảm biến / database dùng chung ổ")
        self._sp_seg = QSpinBox()
        self._sp_seg.setRange(10, 3600)
        self._sp_seg.setSuffix(" giây/đoạn")
        self._sp_snap = QSpinBox()
        self._sp_snap.setRange(0, 3600)
        self._sp_snap.setSuffix(" giây (0 = tắt)")
        self._chk_ring = QCheckBox("Vòng tròn: xoá đoạn cũ nhất để ghi tiếp")
        self._chk_ring.setToolTip(
            "TẮT  : chạm hạn mức thì DỪNG và báo động, không xoá gì (mặc định)\n"
            "BẬT  : xoá đoạn cũ nhất để ghi mãi, luôn giữ hình mới nhất.\n"
            "       Áp dụng cho cả hạn mức camera lẫn sàn trống của ổ,\n"
            f"       nhưng luôn chừa lại {camera.RING_KEEP_MINUTES:.0f} phút gần nhất — xoá tới\n"
            "       mức đó mà ổ vẫn đầy thì lỗi không nằm ở camera.")
        self._chk_auto = QCheckBox("Tự bắt đầu ghi ngay khi mở app")
        self._chk_auto.setToolTip(
            "Cho tàu mất điện xong tự thu tiếp mà không cần ai bấm nút.\n"
            "Nhớ bật thêm: cho app chạy cùng Windows (Win+R → shell:startup → tạo lối tắt).")
        lim_form.addRow("Hạn mức camera:", self._sp_quota)
        lim_form.addRow("Sàn trống của ổ:", self._sp_free)
        lim_form.addRow("Độ dài đoạn:", self._sp_seg)
        lim_form.addRow("Chụp ảnh mỗi:", self._sp_snap)
        lim_form.addRow("", self._chk_ring)
        lim_form.addRow("", self._chk_auto)
        cfg_vl.addWidget(lim_grp)
        layout.addWidget(cfg_grp)

        # --- Nút ghi ------------------------------------------------------
        btn_row = QHBoxLayout()
        self._btn_rec = QPushButton("Bắt đầu ghi")
        self._btn_rec.setStyleSheet(_btn_qss("#28a745", "#218838", "#1a6b2a"))
        self._btn_stop = QPushButton("Dừng ghi")
        self._btn_stop.setStyleSheet(_btn_qss("#dc3545", "#c82333", "#a71d2a"))
        self._btn_stop.setEnabled(False)
        self._btn_rec.clicked.connect(self._on_record)
        self._btn_stop.clicked.connect(self._on_stop)
        btn_row.addWidget(self._btn_rec)
        btn_row.addWidget(self._btn_stop)
        layout.addLayout(btn_row)
        layout.addStretch()

        # Mọi ô nhập đều ghi thẳng vào cấu hình của camera đang chọn.
        for w in (self._ed_name, self._ed_url, self._ed_dir, self._ed_user, self._ed_pass,
                  self._ed_onvif):
            w.textChanged.connect(self._apply_form)
        self._cb_profile.currentTextChanged.connect(self._apply_form)
        for w in (self._sp_on, self._sp_every, self._sp_quota, self._sp_free):
            w.valueChanged.connect(self._apply_form)
        for w in (self._sp_seg, self._sp_snap):
            w.valueChanged.connect(self._apply_form)
        self._chk_ring.toggled.connect(self._apply_form)
        self._chk_auto.toggled.connect(self._apply_form)

        self._config_widgets = [
            self._ed_name, self._ed_url, self._ed_user, self._ed_pass, self._btn_show_pass,
            self._ed_onvif, self._btn_onvif, self._cb_profile, self._btn_stream,
            self._ed_dir, self._btn_dir, self._cb_mode,
            self._sp_on, self._sp_every, self._sp_quota, self._sp_free, self._sp_seg,
            self._sp_snap, self._chk_ring, self._chk_auto,
        ]
        return panel

    def _build_right(self) -> QWidget:
        # Ba khối xếp dọc trong một splitter: hình+dung lượng / replay / nhật ký. Dùng splitter
        # thay vì layout cứng để người dùng tự chia lại khi màn hình bé — muốn xem log dài thì
        # kéo khối trên nhỏ lại, không phải chịu một tỉ lệ do mình áp đặt.
        outer = QSplitter(Qt.Orientation.Vertical)

        top_widget = QWidget()
        top = QHBoxLayout(top_widget)
        top.setContentsMargins(0, 0, 0, 0)

        # --- Ảnh chụp -----------------------------------------------------
        # Cố tình KHÔNG nhúng player video: tốn công, dễ vỡ, và không giúp gì cho việc ghi.
        # Một khung hình mỗi 10–30 giây đã đủ chứng minh "đã kết nối được thiết bị".
        snap_grp = QGroupBox("Hình ảnh  (khung chụp định kỳ, không phải video)")
        snap_vl = QVBoxLayout(snap_grp)
        self._lbl_snap = QLabel("Chưa có ảnh")
        # Nhỏ vừa đủ để cửa sổ hẹp vẫn xếp được; ảnh tự co giãn theo ô (xem resizeEvent).
        self._lbl_snap.setMinimumSize(200, 140)
        self._lbl_snap.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._lbl_snap.setStyleSheet("background:#101010; color:#607d8b; border:1px solid #333;")
        self._lbl_snap_time = QLabel("")
        self._lbl_snap_time.setWordWrap(True)
        self._lbl_snap_time.setStyleSheet(f"color:{_COL_INFO};")
        self._lbl_snap_time.setToolTip(
            "Giờ máy để đối chiếu với dấu giờ camera tự in lên hình.\n"
            "Giờ UTC (Z) khớp tên file bản ghi và mốc thời gian trong manifest.")
        snap_vl.addWidget(self._lbl_snap, stretch=1)
        snap_vl.addWidget(self._lbl_snap_time)
        top.addWidget(snap_grp, stretch=1)

        # --- Dung lượng ---------------------------------------------------
        stat_grp = QGroupBox("Trạng thái & dung lượng")
        stat_vl = QVBoxLayout(stat_grp)
        self._lbl_state = QLabel("Đã dừng")
        self._lbl_state.setStyleSheet("font-weight:bold; font-size:14px;")
        self._lbl_alarm = QLabel()
        self._lbl_alarm.setWordWrap(True)
        self._lbl_alarm.setVisible(False)
        self._lbl_alarm.setStyleSheet(
            "background:#5c1a1a; color:#ffcdd2; font-weight:bold; padding:6px; border-radius:4px;")
        self._bar_quota = QProgressBar()
        self._bar_quota.setRange(0, 100)
        self._bar_quota.setFormat("%p% hạn mức")
        self._lbl_used = QLabel("—")
        self._lbl_free = QLabel("—")
        self._lbl_rate = QLabel("—")
        self._lbl_segs = QLabel("—")
        for lbl in (self._lbl_used, self._lbl_free, self._lbl_rate, self._lbl_segs):
            lbl.setWordWrap(True)
        stat_vl.addWidget(self._lbl_state)
        stat_vl.addWidget(self._lbl_alarm)
        stat_vl.addWidget(self._bar_quota)
        stat_vl.addWidget(self._lbl_used)
        stat_vl.addWidget(self._lbl_free)
        stat_vl.addWidget(self._lbl_rate)
        stat_vl.addWidget(self._lbl_segs)
        self._btn_open_dir = QPushButton("Mở thư mục bản ghi")
        self._btn_open_dir.clicked.connect(self._on_open_dir)
        stat_vl.addWidget(self._btn_open_dir)
        stat_vl.addStretch()
        stat_grp.setMinimumWidth(240)
        top.addWidget(stat_grp, stretch=1)
        outer.addWidget(top_widget)

        # --- Replay -------------------------------------------------------
        outer.addWidget(self._build_replay())

        # --- Nhật ký ------------------------------------------------------
        log_grp = QGroupBox("Nhật ký camera  (mốc thời gian theo giờ UTC, khớp tên file bản ghi)")
        log_vl = QVBoxLayout(log_grp)
        self._log = QPlainTextEdit()
        self._log.setReadOnly(True)
        self._log.setFont(QFont("Consolas", 9))
        self._log.setStyleSheet(f"background-color:{_LOG_BG}; color:#ffffff; border:none;")
        # Giữ 2000 dòng gần nhất; log đầy đủ nằm trong file theo ngày.
        self._log.document().setMaximumBlockCount(_MAX_LOG_LINES)
        self._log.setMinimumHeight(90)
        log_vl.addWidget(self._log)
        bar = QHBoxLayout()
        btn_clear = QPushButton("Xoá")
        btn_clear.clicked.connect(self._log.clear)
        self._chk_ffmpeg = QCheckBox("Hiện dòng của ffmpeg")
        self._chk_ffmpeg.setChecked(True)
        self._chk_autoscroll = QCheckBox("Tự cuộn")
        self._chk_autoscroll.setChecked(True)
        bar.addWidget(btn_clear)
        bar.addWidget(self._chk_ffmpeg)
        bar.addWidget(self._chk_autoscroll)
        bar.addStretch()
        self._lbl_logfile = QLabel("")
        self._lbl_logfile.setStyleSheet(f"color:{_COL_INFO};")
        bar.addWidget(self._lbl_logfile)
        log_vl.addLayout(bar)
        outer.addWidget(log_grp)

        # Chỗ dôi ra khi kéo to cửa sổ dồn cho nhật ký; hình và replay giữ nguyên tầm.
        outer.setStretchFactor(0, 3)
        outer.setStretchFactor(1, 0)
        outer.setStretchFactor(2, 2)
        outer.setSizes([300, 150, 260])
        return outer

    def _build_replay(self) -> QGroupBox:
        grp = QGroupBox("Replay — phát lặp một file đã ghi thành luồng RTSP")
        vl = QVBoxLayout(grp)
        form = self._form()  # nhãn tự xuống dòng khi cửa sổ hẹp

        file_row = QHBoxLayout()
        self._ed_file = QLineEdit()
        self._ed_file.setPlaceholderText("Chọn một file .mp4 đã ghi")
        self._ed_file.setMinimumWidth(120)
        btn_file = QPushButton("Chọn file")
        btn_file.clicked.connect(self._on_pick_file)
        file_row.addWidget(self._ed_file, stretch=1)
        file_row.addWidget(btn_file)
        form.addRow("File:", file_row)

        g2_row = QHBoxLayout()
        self._sp_port = QSpinBox()
        self._sp_port.setRange(1, 65535)
        self._sp_port.setValue(8554)
        self._sp_port.setMaximumWidth(90)
        self._ed_go2rtc = QLineEdit(camera.find_tool("go2rtc"))
        self._ed_go2rtc.setPlaceholderText("Đường dẫn go2rtc (bỏ trống = chỉ ffmpeg, 1 client)")
        self._ed_go2rtc.setMinimumWidth(120)
        btn_g2 = QPushButton("Chọn")
        btn_g2.clicked.connect(self._on_pick_go2rtc)
        g2_row.addWidget(self._sp_port)
        g2_row.addWidget(self._ed_go2rtc, stretch=1)
        g2_row.addWidget(btn_g2)
        form.addRow("Cổng / go2rtc:", g2_row)
        vl.addLayout(form)

        row3 = QHBoxLayout()
        self._btn_replay = QPushButton("Phát")
        self._btn_replay.setStyleSheet(_btn_qss("#0d6efd", "#0b5ed7", "#0a58ca"))
        self._btn_replay_stop = QPushButton("Dừng phát")
        self._btn_replay_stop.setEnabled(False)
        self._btn_replay.clicked.connect(self._on_replay)
        self._btn_replay_stop.clicked.connect(self._on_replay_stop)
        # IP LAN THẬT, không phải localhost: máy xem luồng là máy khác.
        self._ed_replay_url = QLineEdit()
        self._ed_replay_url.setReadOnly(True)
        self._ed_replay_url.setPlaceholderText("URL cho VLC sẽ hiện ở đây")
        self._ed_replay_url.setMinimumWidth(120)
        btn_copy = QPushButton("Copy")
        btn_copy.clicked.connect(self._on_copy_url)
        row3.addWidget(self._btn_replay)
        row3.addWidget(self._btn_replay_stop)
        row3.addWidget(self._ed_replay_url, stretch=1)
        row3.addWidget(btn_copy)
        vl.addLayout(row3)

        # App KHÔNG nhúng player (xem chú thích khung Hình ảnh), nên phải nói thẳng phải mở
        # bằng gì — không thì bấm Phát xong ngồi chờ mãi không thấy hình đâu.
        self._lbl_replay_hint = QLabel("Bấm Phát rồi mở URL bằng VLC (Ctrl+N) — app này không "
                                       "hiện video, chỉ hiện ảnh chụp định kỳ.")
        self._lbl_replay_hint.setWordWrap(True)
        self._lbl_replay_hint.setStyleSheet(f"color:{_COL_INFO}; font-style:italic;")
        vl.addWidget(self._lbl_replay_hint)
        return grp

    # ------------------------------------------------------------------
    # Công cụ ngoài
    # ------------------------------------------------------------------

    def _check_tools(self) -> None:
        """Thiếu binary thì nói rõ THIẾU CÁI GÌ và ĐÃ TÌM Ở ĐÂU, ngay lúc mở tab."""
        tools = camera.check_tools(self._ed_go2rtc.text())
        missing = [n for n in ("ffmpeg", "ffprobe") if not tools[n]]
        if missing:
            detail = "  |  ".join(camera.where_looked(n) for n in missing)
            self._lbl_tools.setText(f"THIẾU {', '.join(missing)} — tab Camera không chạy được.\n{detail}")
            self._lbl_tools.setStyleSheet(
                "background:#5c1a1a; color:#ffcdd2; font-weight:bold; padding:6px; border-radius:4px;")
        else:
            g2 = tools["go2rtc"] or "chưa có (replay sẽ dùng ffmpeg, chỉ 1 client xem được)"
            self._lbl_tools.setText(f"ffmpeg: {tools['ffmpeg']}      go2rtc: {g2}")
            self._lbl_tools.setStyleSheet(f"color:{_COL_INFO};")

    # ------------------------------------------------------------------
    # Danh sách camera
    # ------------------------------------------------------------------

    # --- Lưu / nạp hồ sơ camera ------------------------------------------

    def _load_profiles(self) -> None:
        """Nạp cấu hình lần trước. Chưa có gì thì tạo một camera trống như cũ."""
        configs, extras, err = camera_store.load()
        if err:
            self._bridge.log.emit("cấu hình", "warn", err)
        for cfg in configs:
            name = camera.safe_name(cfg.name)
            if name in self._sessions:
                continue
            cfg.name = name
            self._sessions[name] = _Session(cfg)
            self._order.append(name)
            self._cam_list.addItem(name)
        if extras.get("go2rtc"):
            self._ed_go2rtc.setText(str(extras["go2rtc"]))
        try:
            self._sp_port.setValue(int(extras.get("replay_port", 8554)))
        except (TypeError, ValueError):
            pass
        if not self._order:
            self._add_camera()
            self._show_store_hint("Chưa lưu hồ sơ nào")
            return
        self._cam_list.setCurrentRow(0)
        self._default_root = str(self._sessions[self._order[0]].cfg.root)
        self._autostart_cameras()
        missing = [c.name for c in configs if c.username and not c.password]
        hint = f"Đã nạp {len(configs)} camera từ hồ sơ đã lưu"
        if missing:
            # Nói rõ vì sao ô mật khẩu trống, đừng để người dùng tưởng mất cấu hình.
            hint += f" — phải nhập lại mật khẩu cho: {', '.join(missing)}"
        self._show_store_hint(hint)

    def _autostart_cameras(self) -> None:
        """Bật ghi cho camera đã đánh dấu tự chạy.

        Đây là mắt xích để tàu mất điện xong tự thu tiếp: Windows lên → app lên (lối tắt trong
        shell:startup) → camera này tự ghi. Không có nó thì phải có người ra bấm nút, mà 3 giờ
        sáng thì không có ai.
        """
        started = []
        for name in self._order:
            sess = self._sessions.get(name)
            if not sess or not sess.cfg.autostart or not sess.cfg.url or sess.recording:
                continue
            if not camera.find_tool("ffmpeg"):
                self._bridge.log.emit(name, "error",
                                      f"Không tự ghi được — {camera.where_looked('ffmpeg')}")
                break
            sess.rec = CameraRecorder(
                sess.cfg, on_log=lambda lv, tx, n=name: self._bridge.log.emit(n, lv, tx))
            sess.rec.start()
            started.append(name)
        if started:
            self._bridge.log.emit("cấu hình", "ok",
                                  f"Tự bắt đầu ghi: {', '.join(started)}")
        self._refresh()

    def _on_save_profiles(self) -> None:
        configs = [self._sessions[n].cfg for n in self._order]
        extras = {"go2rtc": self._ed_go2rtc.text().strip(), "replay_port": self._sp_port.value()}
        err = camera_store.save(configs, extras)
        if err:
            self._bridge.log.emit("cấu hình", "error", err)
            QMessageBox.warning(self, "Không lưu được", err)
            return
        note = ("" if camera_store.can_store_password()
                else "  (máy này không mã hoá được nên KHÔNG lưu mật khẩu)")
        self._show_store_hint(f"Đã lưu {len(configs)} camera{note}")
        self._bridge.log.emit("cấu hình", "ok",
                              f"Đã lưu {len(configs)} camera vào {camera_store.store_path()}")

    def _on_export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Xuất cấu hình camera ra file", str(Path.home() / "camera_profiles.json"),
            "JSON (*.json)")
        if not path:
            return
        configs = [self._sessions[n].cfg for n in self._order]
        err = camera_store.save(configs, {"go2rtc": self._ed_go2rtc.text().strip(),
                                          "replay_port": self._sp_port.value()},
                                path=Path(path))
        if err:
            QMessageBox.warning(self, "Không xuất được", err)
            return
        self._bridge.log.emit("cấu hình", "ok", f"Đã xuất {len(configs)} camera ra {path}")
        # Nói trước để khỏi tưởng file hỏng: DPAPI khoá theo tài khoản Windows của máy này.
        QMessageBox.information(
            self, "Đã xuất",
            f"Đã ghi {len(configs)} camera ra:\n{path}\n\n"
            f"Lưu ý: mật khẩu trong file chỉ giải được trên chính máy và tài khoản Windows này. "
            f"Mang sang máy khác thì mọi thứ khác vẫn nạp được, riêng mật khẩu phải nhập lại.")

    def _on_import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Nạp cấu hình camera từ file",
                                              str(Path.home()), "JSON (*.json)")
        if not path:
            return
        configs, extras, err = camera_store.load(Path(path))
        if err:
            QMessageBox.warning(self, "Không nạp được", err)
            return
        if not configs:
            QMessageBox.information(self, "File trống", "File này không có camera nào.")
            return
        # THÊM vào chứ không đè: nạp nhầm file mà mất sạch cấu hình đang có thì quá đắt.
        added = 0
        for cfg in configs:
            name = camera.safe_name(cfg.name)
            while name in self._sessions:
                name = f"{name}_2"
            cfg.name = name
            self._sessions[name] = _Session(cfg)
            self._order.append(name)
            self._cam_list.addItem(name)
            added += 1
        if extras.get("go2rtc") and not self._ed_go2rtc.text().strip():
            self._ed_go2rtc.setText(str(extras["go2rtc"]))
        self._cam_list.setCurrentRow(len(self._order) - 1)
        self._show_store_hint(f"Đã nạp thêm {added} camera từ {Path(path).name}")
        self._bridge.log.emit("cấu hình", "ok", f"Đã nạp thêm {added} camera từ {path}")

    def _show_store_hint(self, text: str) -> None:
        # Chỉ một dòng trạng thái; đường dẫn dài để trong tooltip cho khỏi ăn hai hàng.
        self._lbl_store.setText(text)
        self._lbl_store.setToolTip(f"Hồ sơ lưu tại:\n{camera_store.store_path()}")

    def _add_camera(self) -> None:
        idx = 1
        while f"cam{idx}" in self._sessions:
            idx += 1
        name = f"cam{idx}"
        cfg = RecordConfig(name=name, root=Path(self._default_root))
        self._sessions[name] = _Session(cfg)
        self._order.append(name)
        self._cam_list.addItem(name)
        self._cam_list.setCurrentRow(len(self._order) - 1)

    def _duplicate_camera(self) -> None:
        """Chép camera đang chọn. Đội camera trên tàu thường cùng hãng, cùng tài khoản, cùng
        chính sách ghi — chỉ khác mỗi địa chỉ."""
        sess = self._current()
        if not sess:
            return
        cfg = replace(sess.cfg)  # dataclass: bản sao nông là đủ, mọi trường đều là giá trị
        idx = 2
        while camera.safe_name(f"{sess.cfg.name}_{idx}") in self._sessions:
            idx += 1
        cfg.name = camera.safe_name(f"{sess.cfg.name}_{idx}")
        self._sessions[cfg.name] = _Session(cfg)
        self._order.append(cfg.name)
        self._cam_list.addItem(cfg.name)
        self._cam_list.setCurrentRow(len(self._order) - 1)
        self._bridge.log.emit(cfg.name, "info", f"Nhân bản từ {sess.cfg.name} — sửa lại URL/IP "
                                                f"rồi bấm Lưu")

    def _remove_camera(self) -> None:
        sess = self._current()
        if not sess:
            return
        if sess.recording:
            answer = QMessageBox.question(
                self, "Đang ghi",
                f"{sess.cfg.name} đang ghi. Dừng và xoá khỏi danh sách?")
            if answer != QMessageBox.StandardButton.Yes:
                return
            sess.rec.stop()
        name = sess.cfg.name
        row = self._order.index(name)
        self._order.pop(row)
        self._sessions.pop(name, None)
        self._cam_list.takeItem(row)
        if not self._order:
            self._add_camera()

    def _current(self) -> _Session | None:
        row = self._cam_list.currentRow()
        if row < 0 or row >= len(self._order):
            return None
        return self._sessions.get(self._order[row])

    def _on_select(self, row: int) -> None:
        sess = self._current()
        if not sess:
            return
        cfg = sess.cfg
        self._loading = True
        self._ed_name.setText(cfg.name)
        self._ed_url.setText(cfg.url)
        self._ed_user.setText(cfg.username)
        self._ed_pass.setText(cfg.password)
        self._ed_onvif.setText(cfg.onvif_url)
        self._cb_profile.clear()
        for p in sess.profiles:
            self._cb_profile.addItem(p.label(), p.token)
        self._cb_profile.setCurrentText(cfg.profile_token)
        self._ed_dir.setText(str(cfg.root))
        self._cb_mode.setCurrentIndex(max(0, self._cb_mode.findData(cfg.mode)))
        self._sp_on.setValue(cfg.on_minutes)
        self._sp_every.setValue(cfg.every_minutes)
        self._sp_quota.setValue(cfg.quota_gb)
        self._sp_free.setValue(cfg.min_free_gb)
        self._sp_seg.setValue(cfg.segment_seconds)
        self._sp_snap.setValue(cfg.snapshot_seconds)
        self._chk_ring.setChecked(cfg.ring)
        self._chk_auto.setChecked(cfg.autostart)
        self._loading = False
        self._lbl_probe.setText(sess.probe.summary() if sess.probe else "Chưa kiểm tra")
        self._lbl_snap.setText("Chưa có ảnh")
        self._lbl_snap.setPixmap(QPixmap())
        sess.snap_mtime = 0.0
        self._sample_row.setVisible(cfg.mode == MODE_SAMPLE)
        self._update_estimate()
        self._refresh()

    def _apply_form(self) -> None:
        """Ghi giá trị trên form vào cấu hình camera đang chọn."""
        if self._loading:
            return
        sess = self._current()
        if not sess or sess.recording:
            return
        cfg = sess.cfg
        old = cfg.name
        new = camera.safe_name(self._ed_name.text())
        if new != old and new not in self._sessions:
            self._sessions.pop(old, None)
            self._sessions[new] = sess
            self._order[self._order.index(old)] = new
            cfg.name = new
        cfg.url = self._ed_url.text().strip()
        cfg.username = self._ed_user.text().strip()
        cfg.password = self._ed_pass.text()  # KHÔNG strip: mật khẩu có thể có khoảng trắng
        cfg.onvif_url = self._ed_onvif.text().strip()
        token = self._cb_profile.currentData() or self._cb_profile.currentText().strip()
        cfg.profile_token = token.split("  —  ")[0].strip() if token else ""
        cfg.root = Path(self._ed_dir.text().strip() or self._default_root)
        self._default_root = str(cfg.root)
        cfg.mode = self._cb_mode.currentData()
        cfg.on_minutes = self._sp_on.value()
        cfg.every_minutes = self._sp_every.value()
        cfg.quota_gb = self._sp_quota.value()
        cfg.min_free_gb = self._sp_free.value()
        cfg.segment_seconds = self._sp_seg.value()
        cfg.snapshot_seconds = self._sp_snap.value()
        cfg.ring = self._chk_ring.isChecked()
        cfg.autostart = self._chk_auto.isChecked()
        self._update_estimate()

    def _on_mode_changed(self) -> None:
        mode = self._cb_mode.currentData()
        self._sample_row.setVisible(mode == MODE_SAMPLE)
        sess = self._current()
        # Ghi liên tục phải CẢNH BÁO TRƯỚC mức tiêu thụ — camera tốn gấp cả nghìn lần cảm biến
        # text, mà máy này còn chạy gateway, log cảm biến thô và database.
        if mode == MODE_CONTINUOUS and not self._loading and sess:
            height = sess.probe.height if sess.probe and sess.probe.height else 1080
            gb = camera.estimate_gb_per_day(height)
            answer = QMessageBox.warning(
                self, "Ghi liên tục — kiểm tra dung lượng",
                f"Ghi LIÊN TỤC ở mức {height}p tốn khoảng {gb:.0f} GB/ngày "
                f"({gb * 30:.0f} GB cho chuyến một tháng).\n\n"
                f"Chế độ lấy mẫu 5 phút mỗi 30 phút chỉ tốn ~{gb / 6:.1f} GB/ngày, "
                f"còn dùng thêm luồng phụ của camera thì xuống ~{gb / 24:.1f} GB/ngày.\n\n"
                f"Vẫn ghi liên tục?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.No)
            if answer != QMessageBox.StandardButton.Yes:
                self._cb_mode.setCurrentIndex(self._cb_mode.findData(MODE_SAMPLE))
                return
        self._apply_form()

    def _update_estimate(self) -> None:
        sess = self._current()
        if not sess:
            return
        cfg = sess.cfg
        height = sess.probe.height if sess.probe and sess.probe.height else 1080
        known = "đã đo" if (sess.probe and sess.probe.height) else "giả định 1080p, chưa kiểm tra"
        if cfg.mode == MODE_SAMPLE:
            gb = camera.estimate_gb_per_day(height, cfg.on_minutes, cfg.every_minutes)
        else:
            gb = camera.estimate_gb_per_day(height)
        days = cfg.quota_gb / gb if gb > 0 else 0
        self._lbl_estimate.setText(
            f"Ước tính ~{gb:.1f} GB/ngày ({gb * 30:.0f} GB/tháng) — {known}. "
            f"Hạn mức {cfg.quota_gb:g} GB đủ khoảng {days:.0f} ngày.")

    # ------------------------------------------------------------------
    # Hành động
    # ------------------------------------------------------------------

    def _on_pick_dir(self) -> None:
        path = QFileDialog.getExistingDirectory(self, "Chọn thư mục lưu bản ghi",
                                                self._ed_dir.text() or self._default_root)
        if path:
            self._ed_dir.setText(path)

    def _on_pick_file(self) -> None:
        sess = self._current()
        start = str(sess.cfg.cam_dir) if sess else self._default_root
        path, _ = QFileDialog.getOpenFileName(self, "Chọn đoạn video để phát lại", start,
                                              "Video (*.mp4);;Tất cả (*)")
        if path:
            self._ed_file.setText(path)

    def _on_pick_go2rtc(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Chọn binary go2rtc", "",
                                              "Chương trình (*.exe);;Tất cả (*)")
        if path:
            self._ed_go2rtc.setText(path)
            self._check_tools()

    def _on_open_dir(self) -> None:
        sess = self._current()
        if not sess:
            return
        # Tạo trước nếu chưa có: mở đường dẫn không tồn tại thì Explorer báo lỗi khó hiểu, còn
        # thư mục rỗng thì thấy ngay là "chưa ghi được gì".
        sess.cfg.cam_dir.mkdir(parents=True, exist_ok=True)
        try:
            os.startfile(str(sess.cfg.cam_dir))  # type: ignore[attr-defined]
        except AttributeError:
            subprocess.Popen(["xdg-open", str(sess.cfg.cam_dir)])
        except OSError as exc:
            QMessageBox.warning(self, "Không mở được thư mục", str(exc))

    def _on_probe(self) -> None:
        sess = self._current()
        if not sess:
            return
        if not sess.cfg.url:
            QMessageBox.warning(self, "Thiếu URL", "Nhập URL RTSP của camera trước đã.")
            return
        if sess.probe_thread and sess.probe_thread.isRunning():
            return
        self._lbl_probe.setText("Đang kiểm tra...")
        self._btn_probe.setEnabled(False)
        sess.cfg.cam_dir.mkdir(parents=True, exist_ok=True)
        th = _ProbeThread(sess.cfg.name, sess.cfg.effective_url, sess.cfg.snapshot_path)
        th.done.connect(self._on_probe_done)
        sess.probe_thread = th
        th.start()

    @pyqtSlot(str, object)
    def _on_probe_done(self, name: str, res: ProbeResult) -> None:
        self._btn_probe.setEnabled(True)
        sess = self._sessions.get(name)
        if not sess:
            return
        sess.probe = res
        if res.ok:
            self._bridge.log.emit(name, "ok", f"Kiểm tra OK — {res.summary()}")
            self._bridge.log.emit(name, "info", res.stream_line)
        else:
            self._bridge.log.emit(name, "error", f"Kiểm tra thất bại — {res.error}")
        if self._current() is sess:
            self._lbl_probe.setText(res.summary())
            self._lbl_probe.setStyleSheet(f"color:{_COL_OK if res.ok else _COL_ERROR};")
            self._update_estimate()

    def _on_fetch_profiles(self) -> None:
        sess = self._current()
        if not sess:
            return
        if not sess.cfg.onvif_url:
            QMessageBox.warning(self, "Thiếu ONVIF URL",
                                "Nhập địa chỉ ONVIF của camera, thường là\n"
                                "http://<ip>/onvif/device_service\n\n"
                                "Camera một mắt thì không cần — gõ thẳng URL RTSP là đủ.")
            return
        if sess.onvif_thread and sess.onvif_thread.isRunning():
            return
        self._btn_onvif.setEnabled(False)
        self._btn_onvif.setText("Đang hỏi...")
        self._bridge.log.emit(sess.cfg.name, "info",
                              f"Hỏi ONVIF {sess.cfg.onvif_url} xem có những luồng nào")
        th = _OnvifThread(sess.cfg.name, sess.cfg.onvif_url,
                          sess.cfg.username, sess.cfg.password)
        th.done.connect(self._on_profiles_done)
        sess.onvif_thread = th
        th.start()

    @pyqtSlot(str, object, str)
    def _on_profiles_done(self, name: str, profiles: list, err: str) -> None:
        self._btn_onvif.setEnabled(True)
        self._btn_onvif.setText("Lấy profile")
        sess = self._sessions.get(name)
        if not sess:
            return
        if err:
            self._bridge.log.emit(name, "error", f"ONVIF lỗi — {err}")
            QMessageBox.warning(self, "Không hỏi được ONVIF", err)
            return
        sess.profiles = profiles
        self._bridge.log.emit(name, "ok", f"Camera có {len(profiles)} luồng:")
        for p in profiles:
            self._bridge.log.emit(name, "info", f"    {p.label()}  →  {p.stream_uri or '?'}")
        if self._current() is not sess:
            return
        self._loading = True
        self._cb_profile.clear()
        for p in profiles:
            self._cb_profile.addItem(p.label(), p.token)
        self._loading = False
        # Tự chọn profile đầu tiên để điền sẵn URL; camera nhiệt thì người dùng đổi sang luồng
        # hồng ngoại bằng một cú bấm, thấy rõ tên luồng trong danh sách.
        if profiles:
            self._cb_profile.setCurrentIndex(0)
            self._on_profile_picked(0)

    def _on_profile_picked(self, index: int) -> None:
        if self._loading or index < 0:
            return
        sess = self._current()
        if not sess or index >= len(sess.profiles):
            return
        p = sess.profiles[index]
        sess.cfg.profile_token = p.token
        sess.cfg.profile_name = p.name
        if p.stream_uri:
            self._loading = True
            self._ed_url.setText(p.stream_uri)
            self._loading = False
            sess.cfg.url = p.stream_uri
            self._bridge.log.emit(sess.cfg.name, "ok",
                                  f"Đã chọn luồng {p.name or p.token} → {p.stream_uri}")

    def _on_fetch_stream_uri(self) -> None:
        """Lấy URL cho token GÕ TAY — dùng khi đã biết sẵn token, khỏi dò cả danh sách."""
        sess = self._current()
        if not sess:
            return
        token = self._cb_profile.currentText().strip()
        # Người dùng có thể đang chọn một dòng trong danh sách (nhãn dài) thay vì gõ token.
        data = self._cb_profile.currentData()
        if data:
            token = data
        elif "  —  " in token:
            token = token.split("  —  ")[0].strip()
        if not token:
            QMessageBox.warning(self, "Thiếu token", "Nhập profile token hoặc bấm 'Lấy profile'.")
            return
        if not sess.cfg.onvif_url:
            QMessageBox.warning(self, "Thiếu ONVIF URL", "Nhập địa chỉ ONVIF của camera trước.")
            return
        self._btn_stream.setEnabled(False)
        QApplication.processEvents()
        uri, err = onvif_client.get_stream_uri(
            sess.cfg.onvif_url, token, sess.cfg.username, sess.cfg.password)
        self._btn_stream.setEnabled(True)
        if err:
            self._bridge.log.emit(sess.cfg.name, "error", f"ONVIF lỗi — {err}")
            QMessageBox.warning(self, "Không lấy được URL luồng", err)
            return
        sess.cfg.profile_token = token
        self._ed_url.setText(uri)
        self._bridge.log.emit(sess.cfg.name, "ok", f"Token {token} → {uri}")

    def _on_record(self) -> None:
        sess = self._current()
        if not sess or sess.recording:
            return
        if not sess.cfg.url:
            QMessageBox.warning(self, "Thiếu URL", "Nhập URL RTSP của camera trước đã.")
            return
        if not camera.find_tool("ffmpeg"):
            QMessageBox.critical(self, "Thiếu ffmpeg", camera.where_looked("ffmpeg"))
            return
        name = sess.cfg.name
        sess.rec = CameraRecorder(
            sess.cfg, on_log=lambda lv, tx, n=name: self._bridge.log.emit(n, lv, tx))
        sess.rec.start()
        self._refresh()

    def _on_stop(self) -> None:
        sess = self._current()
        if not sess or not sess.recording:
            return
        self._btn_stop.setEnabled(False)
        self._btn_stop.setText("Đang dừng...")
        QApplication.processEvents()
        sess.rec.stop()  # gửi 'q' cho ffmpeg rồi chờ nó đóng file, tối đa vài giây
        self._btn_stop.setText("Dừng ghi")
        self._refresh()

    def _on_replay(self) -> None:
        path = self._ed_file.text().strip()
        if not path:
            QMessageBox.warning(self, "Chưa chọn file", "Chọn một đoạn .mp4 đã ghi.")
            return
        self._on_replay_stop()

        # Kiểm cổng TRƯỚC và tự đề xuất cổng rảnh: cổng quen thuộc trên máy có hệ thống camera
        # gần như luôn bận sẵn, để người dùng bấm - lỗi - đổi số - bấm lại là hành họ.
        port = self._sp_port.value()
        if camera.port_in_use(port):
            free = camera.find_free_port(port + 1)
            if not free:
                QMessageBox.warning(self, "Không còn cổng rảnh",
                                    f"Cổng {port} đang bận và không tìm được cổng rảnh nào gần đó.")
                return
            answer = QMessageBox.question(
                self, "Cổng đang bận",
                f"Cổng {port} đang bị chương trình khác giữ (thường là go2rtc, đầu ghi hoặc phần "
                f"mềm hải đồ đang chạy).\n\nDùng cổng {free} thay thế?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
                QMessageBox.StandardButton.Yes)
            if answer != QMessageBox.StandardButton.Yes:
                return
            self._sp_port.setValue(free)

        sess = self._current()
        name = camera.safe_name(sess.cfg.name if sess else "cam1")
        self._replay = ReplaySession(
            Path(path), port=self._sp_port.value(), name=name,
            go2rtc=self._ed_go2rtc.text().strip(),
            on_log=lambda lv, tx: self._bridge.log.emit("replay", lv, tx))
        err = self._replay.start()
        if err:
            self._replay = None
            self._bridge.log.emit("replay", "error", err)
            QMessageBox.critical(self, "Không phát được", err)
            return
        self._ed_replay_url.setText(self._replay.url)
        self._btn_replay_stop.setEnabled(True)
        khach = ("nhiều máy xem cùng lúc được" if self._replay.backend == "go2rtc"
                 else "CHỈ một máy xem cùng lúc (không có go2rtc)")
        self._lbl_replay_hint.setText(
            f"ĐANG PHÁT qua {self._replay.backend} — {khach}. Mở VLC → Ctrl+N → dán URL bên trên. "
            f"Cửa sổ app này không hiện video.")
        self._lbl_replay_hint.setStyleSheet(f"color:{_COL_OK}; font-weight:bold;")

    def _on_replay_stop(self) -> None:
        if self._replay:
            self._replay.stop()
            self._replay = None
        self._ed_replay_url.clear()
        self._btn_replay_stop.setEnabled(False)
        self._lbl_replay_hint.setText("Bấm Phát rồi mở URL bằng VLC (Ctrl+N) — app này không "
                                      "hiện video, chỉ hiện ảnh chụp định kỳ.")
        self._lbl_replay_hint.setStyleSheet(f"color:{_COL_INFO}; font-style:italic;")

    def _on_copy_url(self) -> None:
        url = self._ed_replay_url.text()
        if url:
            QApplication.clipboard().setText(url)
            self._bridge.log.emit("replay", "info", f"Đã copy: {url}")

    # ------------------------------------------------------------------
    # Nhật ký & làm mới
    # ------------------------------------------------------------------

    @pyqtSlot(str, str, str)
    def _on_log(self, cam: str, level: str, text: str) -> None:
        if level == "ffmpeg" and not self._chk_ffmpeg.isChecked():
            return
        colour = {
            "ok": _COL_OK, "warn": _COL_WARN, "error": _COL_ERROR, "ffmpeg": _COL_FFMPEG,
        }.get(level, _COL_INFO)
        # Giờ UTC, kèm chữ Z cho khỏi nhầm: tên file bản ghi và manifest đều theo UTC, log hiện
        # giờ máy thì lúc đối chiếu sự cố với bản ghi sẽ lệch đúng bằng múi giờ tàu đang chạy.
        ts = time.strftime("%H:%M:%SZ", time.gmtime())
        self._log.appendHtml(
            f'<span style="color:{_COL_INFO};">[{ts}]</span> '
            f'<span style="color:#ffffff;">[{cam}]</span> '
            f'<span style="color:{colour};">{text}</span>'
        )
        if self._chk_autoscroll.isChecked():
            sb = self._log.verticalScrollBar()
            sb.setValue(sb.maximum())

    def _refresh(self) -> None:
        """Nhịp 1 giây: cập nhật danh sách, thống kê và ảnh chụp của camera đang chọn."""
        for row, name in enumerate(self._order):
            sess = self._sessions.get(name)
            if not sess:
                continue
            item = self._cam_list.item(row)
            if item is None:
                continue
            mark = "● ghi" if sess.recording and sess.rec.stats().recording else (
                "◐ chờ" if sess.recording else "○ dừng")
            item.setText(f"{mark}   {name}")

        sess = self._current()
        if not sess:
            return
        recording = sess.recording
        self._btn_rec.setEnabled(not recording)
        self._btn_stop.setEnabled(recording)
        for w in self._config_widgets:
            w.setEnabled(not recording)

        if sess.rec:
            s = sess.rec.stats()
            self._lbl_state.setText(s.state)
            self._lbl_alarm.setVisible(bool(s.alarm))
            self._lbl_alarm.setText(f"BÁO ĐỘNG: {s.alarm} — đã dừng ghi, KHÔNG tự xoá gì cả."
                                    if s.alarm else "")
            pct = int(s.used_bytes / s.quota_bytes * 100) if s.quota_bytes else 0
            self._bar_quota.setValue(min(100, pct))
            self._lbl_used.setText(
                f"Đã dùng: {human_bytes(s.used_bytes)} / {sess.cfg.quota_gb:g} GB")
            self._lbl_free.setText(
                f"Ổ đĩa còn trống: {human_bytes(s.free_bytes)}  "
                f"(sàn {sess.cfg.min_free_gb:g} GB)")
            rate = f"{s.gb_per_day:.2f} GB/ngày (đo thật)" if s.gb_per_day > 0 else "đang đo..."
            left = f"còn ghi được ~{s.days_left:.1f} ngày" if s.days_left >= 0 else "chưa đủ dữ liệu"
            self._lbl_rate.setText(f"Tốc độ: {rate} — {left}")
            segs = f"Đã ghi {s.segments} đoạn, {s.gaps} khoảng đứt"
            if s.reconnects:
                # Số này leo nhanh = đường tới camera phập phù, không phải tool hỏng.
                segs += f", đã nối lại {s.reconnects} lần"
            if s.open_segment:
                # Nói rõ đang có file dở: đoạn chỉ vào manifest lúc đóng, mà đoạn mặc định dài 5
                # phút — không nói thì 5 phút đầu nhìn như tool không ghi được gì.
                segs += (f"\nĐang ghi dở: {s.open_segment} ({human_bytes(s.open_bytes)}) — "
                         f"được tính khi đoạn đóng")
            elif s.last_segment:
                segs += f" — mới nhất: {s.last_segment}"
            self._lbl_segs.setText(segs)
            self._lbl_logfile.setText(f"log đầy đủ: {sess.cfg.cam_dir / 'log'}")
        else:
            self._lbl_state.setText("Đã dừng")
            self._lbl_alarm.setVisible(False)

        self._update_snapshot(sess)

    def _update_snapshot(self, sess: _Session) -> None:
        path = sess.cfg.snapshot_path
        try:
            mtime = path.stat().st_mtime
        except OSError:
            return
        if mtime <= sess.snap_mtime:
            return
        pix = QPixmap(str(path))
        if pix.isNull():
            return  # ảnh đang được ghi dở — nhịp sau lấy lại
        sess.snap_mtime = mtime
        self._snap_pix = pix  # giữ bản gốc để còn vẽ lại khi đổi cỡ cửa sổ
        self._draw_snapshot()
        # Hiện CẢ HAI giờ. Camera tự đóng dấu giờ máy nó lên khung hình, mà bản ghi và manifest
        # lại theo UTC — chỉ ghi một trong hai thì luôn có người phải nhẩm trừ trong đầu, và
        # nhẩm sai đúng vào lúc đang dò một sự cố.
        # Gọn để không bị cắt ở cửa sổ hẹp; giải thích dài nằm ở tooltip.
        self._lbl_snap_time.setText(
            f"Chụp {time.strftime('%H:%M:%S', time.localtime(mtime))} giờ máy"
            f"  •  {time.strftime('%H:%M:%SZ', time.gmtime(mtime))}"
            f"  •  {sess.cfg.name}")

    def _draw_snapshot(self) -> None:
        """Vẽ ảnh vừa khít ô hiện tại, giữ tỉ lệ."""
        if self._snap_pix is None or self._snap_pix.isNull():
            return
        self._lbl_snap.setPixmap(self._snap_pix.scaled(
            self._lbl_snap.size(), Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, event) -> None:
        # Kéo cửa sổ mà không vẽ lại thì ảnh giữ nguyên cỡ cũ, để lại viền đen hoặc bị cắt cho
        # tới tấm chụp kế tiếp (có thể 30 giây sau).
        super().resizeEvent(event)
        self._draw_snapshot()

    # ------------------------------------------------------------------
    # Thoát
    # ------------------------------------------------------------------

    def shutdown(self) -> None:
        """Dừng mọi thứ lúc đóng app — không để lại ffmpeg hay go2rtc mồ côi giữ cổng."""
        self._timer.stop()
        # Tự lưu lúc thoát: người vận hành chỉnh xong rồi tắt app, quên bấm Lưu là mất hết.
        try:
            camera_store.save([self._sessions[n].cfg for n in self._order],
                              {"go2rtc": self._ed_go2rtc.text().strip(),
                               "replay_port": self._sp_port.value()})
        except Exception:
            pass  # không lưu được cũng không được cản việc đóng app
        for sess in list(self._sessions.values()):
            for th in (sess.probe_thread, sess.onvif_thread):
                if th and th.isRunning():
                    th.wait(2000)
            if sess.rec:
                sess.rec.stop()
        if self._replay:
            self._replay.stop()
            self._replay = None
