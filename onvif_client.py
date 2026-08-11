"""Client ONVIF tối giản — hỏi camera xem nó có những luồng nào rồi lấy URL RTSP của từng luồng.

VÌ SAO CẦN, dù tool chỉ ghi hình bằng ffmpeg: camera một mắt thì đường dẫn RTSP đoán được theo
hãng (Hikvision `/Streaming/Channels/102`, Dahua `&subtype=1`). Camera ĐA CẢM BIẾN thì không —
FLIR M364C và các camera nhiệt/hồng ngoại phát mỗi cảm biến một profile riêng, và URL của luồng
hồng ngoại chỉ camera mới biết. Phải hỏi bằng ONVIF, kèm ĐÚNG profile token, mới ra.

Chỉ làm hai việc: GetProfiles (có những luồng nào) và GetStreamUri (URL RTSP của một luồng).
Không PTZ, không cấu hình — ghi hình cần đúng chừng đó.

Đây là SOAP trên HTTP, không phải RTSP/RTP, nên không phạm nguyên tắc "không tự viết giao thức
video bằng Python": phần video vẫn do ffmpeg lo. Toàn bộ dùng thư viện chuẩn, không thêm gói.

Chạy thử bằng dòng lệnh:
    python camera.py onvif http://192.168.1.10/onvif/device_service --user admin --password ***
"""

import base64
import hashlib
import re
import secrets
import socket
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timezone

ONVIF_TIMEOUT = 10.0

# Token mặc định của phần lớn camera khi không khai riêng — giống OnvifTarget bên ENC.
DEFAULT_PROFILE_TOKEN = "Profile_1"

_NS_DEVICE = "http://www.onvif.org/ver10/device/wsdl"
_NS_MEDIA = "http://www.onvif.org/ver10/media/wsdl"
_NS_SCHEMA = "http://www.onvif.org/ver10/schema"


@dataclass
class OnvifProfile:
    """Một luồng camera công bố qua ONVIF."""

    token: str = ""
    name: str = ""          # "mainStream", "Thermal", "IR"... — chỗ nhận ra luồng hồng ngoại
    encoding: str = ""      # H264 / H265 / JPEG
    width: int = 0
    height: int = 0
    fps: int = 0
    stream_uri: str = ""

    def label(self) -> str:
        parts = [self.token]
        if self.name and self.name != self.token:
            parts.append(self.name)
        spec = []
        if self.encoding:
            spec.append(self.encoding)
        if self.width and self.height:
            spec.append(f"{self.width}x{self.height}")
        if self.fps:
            spec.append(f"{self.fps} fps")
        if spec:
            parts.append(" ".join(spec))
        return "  —  ".join(parts)


# ---------------------------------------------------------------------------
# SOAP
# ---------------------------------------------------------------------------

def _security_header(username: str, password: str) -> str:
    """WS-Security UsernameToken (PasswordDigest) chuẩn ONVIF; rỗng nếu không khai user.

    Digest = Base64(SHA1(nonce + created + password)). Mật khẩu KHÔNG đi trên đường truyền.

    `Created` phải gần giờ camera: đa số camera từ chối chênh quá 5 phút, và chúng trả về đúng
    "401 Unauthorized" y như khi sai mật khẩu — nên `_fault_hint` có nhắc chuyện lệch giờ.
    """
    if not username:
        return ""
    nonce = secrets.token_bytes(16)
    created = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    sha1 = hashlib.sha1()
    sha1.update(nonce)
    sha1.update(created.encode("utf-8"))
    sha1.update((password or "").encode("utf-8"))
    digest = base64.b64encode(sha1.digest()).decode()
    return (
        '  <s:Header>\n'
        '    <wsse:Security s:mustUnderstand="1"'
        ' xmlns:wsse="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-secext-1.0.xsd"'
        ' xmlns:wsu="http://docs.oasis-open.org/wss/2004/01/oasis-200401-wss-wssecurity-utility-1.0.xsd">\n'
        '      <wsse:UsernameToken>\n'
        f'        <wsse:Username>{_esc(username)}</wsse:Username>\n'
        '        <wsse:Password Type="http://docs.oasis-open.org/wss/2004/01/'
        f'oasis-200401-wss-username-token-profile-1.0#PasswordDigest">{digest}</wsse:Password>\n'
        '        <wsse:Nonce EncodingType="http://docs.oasis-open.org/wss/2004/01/'
        f'oasis-200401-wss-soap-message-security-1.0#Base64Binary">{base64.b64encode(nonce).decode()}</wsse:Nonce>\n'
        f'        <wsu:Created>{created}</wsu:Created>\n'
        '      </wsse:UsernameToken>\n'
        '    </wsse:Security>\n'
        '  </s:Header>\n'
    )


def _esc(text: str) -> str:
    """Thoát ký tự XML — tên tài khoản có thể chứa & hoặc <."""
    return (text.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
                .replace('"', "&quot;"))


def _envelope(body: str, username: str, password: str) -> bytes:
    return (
        '<?xml version="1.0" encoding="UTF-8"?>\n'
        '<s:Envelope xmlns:s="http://www.w3.org/2003/05/soap-envelope">\n'
        f'{_security_header(username, password)}'
        f'  <s:Body>\n{body}\n  </s:Body>\n'
        '</s:Envelope>\n'
    ).encode("utf-8")


def _opener(url: str, username: str, password: str):
    """Kèm sẵn xác thực Ở TẦNG HTTP.

    Một số camera tắt WS-UsernameToken và đòi HTTP Digest/Basic thay thế. Gắn cả hai handler thì
    gặp camera nào cũng qua được, không phải đoán trước nó thuộc loại nào.
    """
    if not username:
        return urllib.request.build_opener()
    mgr = urllib.request.HTTPPasswordMgrWithDefaultRealm()
    mgr.add_password(None, url, username, password or "")
    return urllib.request.build_opener(
        urllib.request.HTTPDigestAuthHandler(mgr),
        urllib.request.HTTPBasicAuthHandler(mgr),
    )


def _post(url: str, body: str, username: str, password: str,
          timeout: float = ONVIF_TIMEOUT) -> tuple:
    """Gửi một lệnh SOAP. Trả về (nội dung trả lời, lỗi) — đúng một trong hai rỗng."""
    req = urllib.request.Request(
        url, data=_envelope(body, username, password),
        headers={"Content-Type": "application/soap+xml; charset=utf-8"},
    )
    try:
        with _opener(url, username, password).open(req, timeout=timeout) as resp:
            return resp.read().decode("utf-8", "replace"), ""
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = _fault_text(exc.read().decode("utf-8", "replace"))
        except Exception:
            pass
        if exc.code == 401:
            return "", ("Camera từ chối xác thực (401). Kiểm tra user/mật khẩu, và kiểm tra "
                        "GIỜ của camera — lệch quá 5 phút là ONVIF cũng trả 401.")
        return "", f"HTTP {exc.code} {exc.reason}" + (f" — {detail}" if detail else "")
    except urllib.error.URLError as exc:
        return "", f"Không tới được camera: {exc.reason}"
    except socket.timeout:
        return "", f"Camera không trả lời trong {timeout:.0f}s"
    except Exception as exc:  # noqa: BLE001
        return "", f"Lỗi gọi ONVIF: {exc}"


def _local(tag: str) -> str:
    """Bỏ namespace khỏi tên thẻ — mỗi hãng đặt prefix một kiểu (trt:, tds:, ns1:...)."""
    return tag.rsplit("}", 1)[-1]


def _find_all(root, name: str) -> list:
    return [el for el in root.iter() if _local(el.tag) == name]


def _first_text(root, name: str, default: str = "") -> str:
    for el in root.iter():
        if _local(el.tag) == name and el.text:
            return el.text.strip()
    return default


def _fault_text(xml_text: str) -> str:
    """Rút lý do từ SOAP Fault — nếu không phải Fault thì trả rỗng."""
    m = re.search(r"<(?:\w+:)?(?:Text|faultstring|Value)[^>]*>([^<]+)<", xml_text or "")
    if m and re.search(r"<(?:\w+:)?Fault[\s>]", xml_text or ""):
        return m.group(1).strip()
    return ""


# ---------------------------------------------------------------------------
# Các lệnh dùng tới
# ---------------------------------------------------------------------------

def media_url(onvif_url: str, username: str = "", password: str = "") -> str:
    """Tìm địa chỉ dịch vụ Media.

    ONVIF tách device_service (thông tin thiết bị) khỏi media_service (luồng video), nhưng mỗi
    hãng đặt một kiểu. Hỏi thẳng camera bằng GetCapabilities là chắc nhất; hỏng thì mới đoán
    theo quy ước, cuối cùng là dùng luôn địa chỉ người dùng khai (nhiều camera nhận tất trên
    device_service).
    """
    onvif_url = (onvif_url or "").strip()
    if not onvif_url:
        return ""
    body = (f'    <tds:GetCapabilities xmlns:tds="{_NS_DEVICE}">\n'
            f'      <tds:Category>Media</tds:Category>\n'
            f'    </tds:GetCapabilities>')
    text, err = _post(onvif_url, body, username, password)
    if not err and text:
        for media in _find_all(ET.fromstring(text), "Media"):
            addr = _first_text(media, "XAddr")
            if addr:
                return addr
    if "device_service" in onvif_url:
        return onvif_url.replace("device_service", "media_service")
    return onvif_url


def get_profiles(onvif_url: str, username: str = "", password: str = "",
                 with_uri: bool = True) -> tuple:
    """Liệt kê profile của camera. Trả về (danh sách OnvifProfile, lỗi).

    `with_uri=True` thì hỏi luôn URL RTSP của từng profile — đó mới là thứ đem đi ghi được.
    """
    murl = media_url(onvif_url, username, password)
    if not murl:
        return [], "Chưa nhập ONVIF URL"

    body = f'    <trt:GetProfiles xmlns:trt="{_NS_MEDIA}"/>'
    text, err = _post(murl, body, username, password)
    if err:
        return [], err
    fault = _fault_text(text)
    if fault:
        return [], f"Camera báo lỗi: {fault}"

    try:
        root = ET.fromstring(text)
    except ET.ParseError as exc:
        return [], f"Trả lời của camera không phải XML hợp lệ: {exc}"

    profiles = []
    for node in _find_all(root, "Profiles"):
        # token là THUỘC TÍNH của thẻ Profiles; tên hiển thị nằm ở thẻ con Name.
        token = node.attrib.get("token") or node.attrib.get("Token") or ""
        if not token:
            continue
        p = OnvifProfile(token=token, name=_first_text(node, "Name", token))
        # Tìm theo tên thẻ ở mọi độ sâu: Media1 và Media2 lồng khác nhau, cách này ăn cả hai.
        p.encoding = _first_text(node, "Encoding")
        p.width = _int(_first_text(node, "Width"))
        p.height = _int(_first_text(node, "Height"))
        p.fps = _int(_first_text(node, "FrameRateLimit"))
        profiles.append(p)

    if not profiles:
        return [], "Camera không trả về profile nào (kiểm tra lại quyền của tài khoản)"

    if with_uri:
        for p in profiles:
            p.stream_uri, _ = get_stream_uri(murl, p.token, username, password, resolved=True)
    return profiles, ""


def get_stream_uri(onvif_url: str, token: str, username: str = "", password: str = "",
                   resolved: bool = False) -> tuple:
    """Lấy URL RTSP của MỘT profile. Trả về (uri, lỗi).

    `resolved=True` nghĩa là `onvif_url` đã là địa chỉ dịch vụ Media, khỏi dò lại.
    """
    murl = onvif_url if resolved else media_url(onvif_url, username, password)
    if not murl:
        return "", "Chưa nhập ONVIF URL"
    if not token:
        return "", "Chưa có profile token"

    body = (
        f'    <trt:GetStreamUri xmlns:trt="{_NS_MEDIA}" xmlns:tt="{_NS_SCHEMA}">\n'
        f'      <trt:StreamSetup>\n'
        f'        <tt:Stream>RTP-Unicast</tt:Stream>\n'
        f'        <tt:Transport><tt:Protocol>RTSP</tt:Protocol></tt:Transport>\n'
        f'      </trt:StreamSetup>\n'
        f'      <trt:ProfileToken>{_esc(token)}</trt:ProfileToken>\n'
        f'    </trt:GetStreamUri>'
    )
    text, err = _post(murl, body, username, password)
    if err:
        return "", err
    fault = _fault_text(text)
    if fault:
        return "", f"Camera báo lỗi: {fault}"
    try:
        uri = _first_text(ET.fromstring(text), "Uri")
    except ET.ParseError as exc:
        return "", f"Trả lời của camera không phải XML hợp lệ: {exc}"
    if not uri:
        return "", "Camera không trả về URL luồng cho profile này"
    return uri, ""


def _int(text: str) -> int:
    try:
        return int(float(text))
    except (TypeError, ValueError):
        return 0
