# Hướng dẫn sử dụng — Extra Field Simulator

**Extra Field Simulator** là công cụ phát bản tin NMEA giả lập của GPS, Radar và AIS. Công cụ có
thể **chèn thêm field EXTRA** (field nằm ngoài chuẩn NMEA) vào bản tin để test tính năng **"Cấu
hình bản tin"** của hệ thống ENC.

Công cụ dùng để:
- Phát dữ liệu GPS, Radar (TTM/OSD/RSD) và AIS (VDM/VDO) tới gateway qua TCP, UDP, cổng COM hoặc
  SSH Tunnel.
- Tạo nhanh danh sách target Radar, tàu AIS và kịch bản test fusion.
- Cấu hình field EXTRA, xuất file YAML và nạp file đó vào ENC.

---

## Mục lục

1. [Tổng quan màn hình](#1-tổng-quan-màn-hình)
2. [Thao tác nhanh](#2-thao-tác-nhanh)
3. [Panel Connection — kết nối](#3-panel-connection--kết-nối)
4. [Panel Generator — nguồn phát và GPS](#4-panel-generator--nguồn-phát-và-gps)
5. [Tab Radar (TTM)](#5-tab-radar-ttm)
6. [Tab AIS (VDM)](#6-tab-ais-vdm)
7. [Tab VDO (Own Ship)](#7-tab-vdo-own-ship)
8. [Tab Fusion Test](#8-tab-fusion-test)
9. [Tab EXTRA Field](#9-tab-extra-field)
10. [NMEA Log Console và thanh trạng thái](#10-nmea-log-console-và-thanh-trạng-thái)
11. [Nạp cấu hình vào ENC](#11-nạp-cấu-hình-vào-enc)
12. [Kịch bản test mẫu](#12-kịch-bản-test-mẫu)
13. [Lỗi thường gặp](#13-lỗi-thường-gặp)

---

## 1. Tổng quan màn hình

```
┌──────────────────────────────┬──────────────────────────────────────────────────┐
│ CONNECTION                   │ TARGET CONTROL                                   │
│  ○TCP Client ○TCP Server     │ [Radar (TTM)][AIS (VDM)][VDO][Fusion][EXTRA Field]│
│  ○UDP ○Serial ○SSH Tunnel    │                                                  │
│  ...tham số kết nối...       │   ...nội dung tab đang chọn...                   │
│  [Connect]  [Disconnect]     │                                                  │
├──────────────────────────────┤                                                  │
│ GENERATOR                    ├──────────────────────────────────────────────────┤
│  ☑GPS ☐Radar ☐AIS            │ NMEA LOG CONSOLE                                 │
│  Interval ────●──── 1000 ms  │  [12:00:01.123] $GPRMC,....*hh                   │
│  GPS Settings                │  [12:00:01.124] $GPGGA,....,12.6*hh              │
│   ☑RMC ☑ZDA ☐HDT ...         │                                                  │
│   Lat/Lon/Speed/Course...    │  [Clear] ☑Auto-scroll          120 messages sent │
│  [▶ Start]  [■ Stop]         │                                                  │
└──────────────────────────────┴──────────────────────────────────────────────────┘
 Thanh trạng thái: Disconnected / Connected — ... / Transmitting — interval 1000 ms
```

- **Bên trái** (cuộn được): cài đặt kết nối và nguồn phát.
- **Bên phải, phía trên**: 5 tab cấu hình target và field EXTRA.
- **Bên phải, phía dưới**: log các bản tin đã gửi.
- Có thể kéo thanh chia ở giữa để đổi độ rộng hai bên.

---

## 2. Thao tác nhanh

1. **Connection**: chọn kiểu kết nối, nhập tham số, bấm **Connect**.
2. **Generator**: tick nguồn cần phát (GPS / Radar / AIS) và chọn các sentence GPS.
3. Nếu phát Radar hoặc AIS: vào tab **Radar** hoặc **AIS** để thêm target (bấm **Generate** để
   sinh nhanh).
4. Vào tab **EXTRA Field** để thêm rule field EXTRA.
5. Bấm **▶ Start**. Xem bản tin trong **NMEA Log Console**.
6. Bấm **■ Stop** để dừng, **Disconnect** để ngắt kết nối.

> Mọi thay đổi ở GPS Settings, danh sách target và rule EXTRA đều có tác dụng **ngay khi đang
> phát**, không cần Stop rồi Start lại.

---

## 3. Panel Connection — kết nối

Chọn một trong 5 chế độ. Phần tham số bên dưới đổi theo chế độ đang chọn.

### 3.1. TCP Client

Tool chủ động kết nối tới một địa chỉ đang lắng nghe TCP (thường là gateway).

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| Host | `127.0.0.1` | IP hoặc hostname của đích |
| Port | `10110` | Cổng TCP của đích |

### 3.2. TCP Server

Tool mở cổng và chờ phía nhận kết nối vào. Bản tin được gửi cho **mọi client** đang kết nối.

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| Bind IP | `0.0.0.0` | IP lắng nghe (`0.0.0.0` là mọi card mạng) |
| Port | `10110` | Cổng lắng nghe |
| *N clients connected* | — | Số client đang kết nối, cập nhật trong lúc phát |

### 3.3. UDP

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| Host | `127.0.0.1` | IP đích. Nhập `255.255.255.255` để broadcast toàn mạng LAN |
| Port | `10110` | Cổng UDP đích |
| Broadcast | tắt | Bắt buộc tick khi gửi tới địa chỉ broadcast |

### 3.4. Serial Port

| Trường | Ý nghĩa |
|---|---|
| Port | Cổng COM. Bấm **Refresh** để quét lại khi vừa cắm thiết bị |
| Baudrate | 4800 / 9600 / 19200 / 38400 / 115200 |
| Parity | None / Even / Odd |
| Data bits | 8 / 7 |

### 3.5. SSH Tunnel

Dùng khi máy của bạn **không kết nối trực tiếp** được tới gateway chạy trên k8s. Tool mở SSH
port-forward rồi kết nối TCP vào `127.0.0.1:<Cổng local>`.

| Trường | Mặc định | Ý nghĩa |
|---|---|---|
| SSH Host | — | IP máy chủ SSH |
| SSH Port | `2222` | Cổng SSH |
| Username | `root` | Tài khoản SSH |
| Password | — | Mật khẩu SSH. Tick **Nhớ mật khẩu** để lưu cho lần sau |
| k8s Namespace | `enc-ship` | Namespace của gateway |
| Pod Selector | `app=enc-sensor-gateway` | Label để tìm pod gateway |
| Pod IP | — | IP của pod gateway. Bấm **Lấy Pod IP** để tool tự lấy |
| Cổng thiết bị | `5001` | Cổng của thiết bị trên gateway (xem cột config trong bảng device bên ENC) |
| Cổng local | `5001` | Cổng mở trên máy bạn, thường để trùng Cổng thiết bị |

Các bước:
1. Nhập SSH Host, Port, Username, Password.
2. Bấm **Lấy Pod IP**. Pod IP đổi mỗi khi pod restart, nên hãy lấy lại nếu đang dùng được mà
   đột nhiên không kết nối được.
3. Nhập **Cổng thiết bị** đúng với thiết bị cần test bên ENC.
4. Bấm **Connect**.

Sau lần kết nối thành công, thông tin SSH được lưu và tự điền lại ở lần mở sau. Mật khẩu chỉ
được lưu khi có tick **Nhớ mật khẩu**.

### 3.6. Connect / Disconnect

- **Connect** (xanh lá): mở kết nối. Thành công thì nút **Start** sáng lên và thanh trạng thái
  hiện `Connected — ...`. Lỗi thì tool hiện hộp thoại *Connection Error* kèm lý do.
- **Disconnect** (đỏ): dừng phát (nếu đang phát) rồi đóng kết nối.
- Khi đóng cửa sổ, tool tự Disconnect.

---

## 4. Panel Generator — nguồn phát và GPS

### 4.1. Chọn nguồn phát

| Checkbox | Phát gì |
|---|---|
| **GPS** | Các sentence GPS đang tick trong *GPS Settings*, cùng AIVDO nếu bật ở tab VDO |
| **Radar** | `RATTM` cho từng target ở tab Radar, cùng OSD/RSD nếu bật |
| **AIS** | `AIVDM` cho từng tàu ở tab AIS |

Có thể tick cùng lúc nhiều nguồn. Các checkbox này chỉ được đọc **lúc bấm Start**, nên muốn đổi
nguồn thì Stop rồi Start lại.

### 4.2. Interval

Thanh kéo từ **100 đến 5000 ms**: chu kỳ phát. Mỗi chu kỳ (một tick) tool phát một lượt toàn bộ
sentence đang bật. Giá trị này cũng chỉ được đọc lúc bấm Start.

### 4.3. GPS Settings — chọn sentence

Tick các sentence cần phát (mặc định bật RMC và ZDA):

| Sentence | Nội dung |
|---|---|
| RMC | Vị trí, tốc độ, hướng đi, ngày giờ |
| ZDA | Ngày giờ UTC |
| HDT | Hướng mũi tàu (thật) |
| HDM | Hướng mũi tàu (từ) |
| HDG | Hướng từ kèm độ lệch (deviation / variation) |
| ROT | Tốc độ quay trở |
| THS | Hướng mũi tàu thật kèm trạng thái |
| RMB | Thông tin dẫn đường tới waypoint (bật RMB thì hiện nhóm *RMB Waypoint*) |
| VBW | Tốc độ nước / đáy |
| GGA | Vị trí kèm chất lượng GPS |
| VTG | Hướng đi và tốc độ so với đáy |

### 4.4. GPS Settings — thông số tàu mình

| Trường | Ý nghĩa |
|---|---|
| Latitude / Longitude | Vị trí tàu mình. Khi mở tool, vị trí được chọn ngẫu nhiên quanh các cảng/sông Việt Nam. Trong lúc phát, hai ô này tự cập nhật theo vị trí tàu đang di chuyển |
| Speed | Tốc độ (kn). Tàu di chuyển theo Speed và Course |
| Course (True) | Hướng đi (°) |
| Heading (True) / (Mag) | Hướng mũi tàu thật / từ, dùng cho HDT, HDM, THS |
| Deviation / Variation | Độ lệch và hướng E/W, dùng cho HDG |
| Rate of Turn | °/phút. Dương là quay phải, âm là quay trái, dùng cho ROT |

### 4.5. RMB Waypoint (khi tick RMB)

| Trường | Ý nghĩa |
|---|---|
| Origin WP / Dest WP | Tên waypoint xuất phát / đích (tối đa 10 ký tự) |
| Dest Lat / Dest Lon | Toạ độ waypoint đích |
| Cross-Track Error | Độ lệch tuyến (NM) |
| Steer | Hướng bẻ lái: L (trái) / R (phải) |

### 4.6. Start / Stop

- **▶ Start**: bắt đầu phát. Chỉ bấm được sau khi đã Connect.
- **■ Stop**: dừng phát, vẫn giữ kết nối.

---

## 5. Tab Radar (TTM)

Quản lý danh sách **target radar**. Mỗi target được phát thành một câu `$RATTM` ở mỗi tick.

### 5.1. Form target

| Trường | Ý nghĩa |
|---|---|
| Target ID | 1–99. Mỗi target có một ID riêng |
| Bearing | Phương vị từ tàu mình tới target (°) |
| Range | Khoảng cách từ tàu mình (NM) |
| Speed / Course | Tốc độ (kn) và hướng đi (°) của target |
| Name | Tên target (không bắt buộc) |
| Status | T (Tracking), L (Lost), Q (Query) |

Nút:
- **Add / Update**: thêm target mới. Nếu đã có target cùng Target ID thì target đó được cập nhật.
- **Remove**: xoá target đang chọn trong danh sách.
- **Bấm vào một dòng** trong danh sách: nạp target đó lên form để sửa.

Target di chuyển theo Speed/Course, nên Bearing và Range trong danh sách thay đổi dần trong lúc
phát.

### 5.2. Chuyển đổi toạ độ

Nhóm công cụ phụ để quy đổi giữa Bearing/Range và Lat/Lon:

| Dòng | Cách dùng |
|---|---|
| **Own-ship** | Vị trí tàu mình làm gốc tính. Nhập tay hoặc bấm **← GPS** để lấy vị trí GPS hiện tại |
| **Brg+Rng →** | Tự tính Lat/Lon của target từ Bearing + Range trên form. Bấm **Copy** để chép `lat, lon` vào clipboard |
| **Lat/Lon →** | Nhập Lat/Lon của target rồi bấm **Fill**: tool tính Bearing + Range và điền vào form |

Ví dụ: muốn đặt target radar đúng vị trí một điểm trên bản đồ thì bấm **← GPS**, nhập Lat/Lon điểm
đó vào dòng *Lat/Lon →*, bấm **Fill**, rồi bấm **Add / Update**.

### 5.3. Auto generate

- Nhập số lượng target rồi bấm **Generate**: tool sinh target ngẫu nhiên cách tàu mình 0.5–15 NM,
  với ID nối tiếp các ID đang có và tên dạng `TGT01`, `TGT02`, …
- **Clear All**: xoá toàn bộ target radar.

### 5.4. OSD và RSD

| Checkbox | Phát | Thông số |
|---|---|---|
| **OSD (Own Ship Data)** | `$RAOSD` | **Set**: hướng dòng chảy (°). **Drift**: tốc độ dòng chảy (kn). Heading, Course và Speed tự lấy từ GPS |
| **RSD (Radar System Data)** | `$RARSD` | VRM 1/2 (NM), EBL 1/2 (°), Range Scale (NM), Display Rotation (North-up / Head-up / Course-up) |

OSD và RSD chỉ được phát khi đã tick nguồn **Radar** ở panel Generator.

---

## 6. Tab AIS (VDM)

Quản lý danh sách **tàu AIS**. Mỗi tàu phát `!AIVDM` ở mỗi tick:
- **Class A**: Type 1 (vị trí) mỗi tick, và Type 5 (thông tin tĩnh, gồm 2 câu) định kỳ.
- **Class B**: Type 18 (vị trí) mỗi tick, và Type 24 (thông tin tĩnh) định kỳ.

### 6.1. Form tàu

| Trường | Ý nghĩa |
|---|---|
| MMSI | Mã tàu 9 chữ số, dùng làm khoá (thêm tàu cùng MMSI sẽ cập nhật tàu cũ) |
| AIS Class | Class A hoặc Class B |
| IMO Number | Số IMO. `0` là không có. Chỉ dùng cho Class A |
| Ship Name | Tên tàu (tối đa 20 ký tự) |
| Call Sign | Hô hiệu (tối đa 7 ký tự) |
| Ship Type | Loại tàu. Ví dụ: 30 tàu cá, 52 tàu kéo, 60–69 tàu khách, 70–79 tàu hàng, 80–89 tàu dầu |
| Destination | Cảng đến (tối đa 20 ký tự) |
| ETA | Tick **Enable** để nhập thời gian dự kiến đến (tháng/ngày giờ:phút) |
| Latitude / Longitude | Vị trí tàu |
| SOG / COG | Tốc độ (kn) và hướng đi so với đáy (°) |
| Heading | Hướng mũi tàu. `511` là không có |
| Nav Status | Trạng thái hành trình: đang chạy máy, thả neo, cập cầu, … |
| Rate of Turn | °/phút, chỉ dùng cho Class A |

Nút và thao tác trên danh sách giống tab Radar: **Add / Update**, **Remove**, bấm vào dòng để sửa.

Mỗi dòng trong danh sách hiển thị: MMSI, tên, class, route GPX (nếu có), vị trí, SOG, COG. Vị trí
được cập nhật liên tục trong lúc phát.

### 6.2. GPX Route — cho tàu chạy theo lộ trình

1. Chọn tàu trong danh sách, hoặc điền form cho tàu mới.
2. Bấm **Tải GPX** và chọn file `.gpx`. File cần có ít nhất 2 điểm.
3. Tick **Lặp lại route** nếu muốn tàu quay lại điểm đầu khi đi hết route.
4. Bấm **Add / Update** để gán route cho tàu. Tàu bắt đầu từ điểm đầu tiên của route.

Nhãn bên phải hiển thị tiến độ, ví dụ `Waypoint 3/10` hoặc `Đã đến điểm cuối (10/10)`. Nút **✕**
bỏ route của tàu đang chọn.

**Biến thiên tốc độ**: tick để đặt tốc độ theo từng đoạn của route. Nhập theo dạng
`waypoint:tốc_độ`, cách nhau bằng dấu phẩy. Ví dụ:

```
0:20, 5:8, 12:20
```

Nghĩa là chạy 20 kn từ waypoint 0, giảm còn 8 kn từ waypoint 5, lên lại 20 kn từ waypoint 12. Nhãn
*Tốc độ hiện tại* hiển thị tốc độ đang áp dụng. Bấm **Add / Update** để lưu lịch tốc độ.

### 6.3. Auto generate

- Nhập số tàu và chọn vùng rồi bấm **Generate**:
  - **Xung quanh tàu mình**: tàu cách tàu mình 0.3–40 NM. Tàu gần thường là tàu nhỏ, tàu xa là tàu
    lớn.
  - **Vùng biển Việt Nam**: tàu rải khắp vùng biển Việt Nam.
- **Clear All**: xoá toàn bộ tàu AIS và route.

---

## 7. Tab VDO (Own Ship)

Phát bản tin `!AIVDO`, tức bản tin AIS của **chính tàu mình**.

1. Tick **Enable AIVDO**.
2. Điền thông tin tàu mình: MMSI, AIS Class, IMO, Ship Name, Call Sign, Ship Type, Destination,
   ETA, Nav Status. Các trường có ý nghĩa giống tab AIS.

Vị trí, tốc độ, hướng đi và heading **tự lấy từ GPS Settings**. AIVDO được phát cùng nguồn GPS, nên
cần tick **GPS** ở panel Generator.

---

## 8. Tab Fusion Test

Tạo kịch bản test **ghép (fusion) giữa Radar và AIS**, gồm:
- **Cặp Fused**: một target radar và một tàu AIS ở **cùng vị trí, cùng tốc độ, cùng hướng**.
- **Radar-only**: target chỉ có trên radar.
- **AIS-only**: tàu chỉ có trên AIS.

Tab có 2 tab con.

### 8.1. Tab con "Thủ công"

Tạo một cặp Fused:

| Trường | Ý nghĩa |
|---|---|
| Target ID (Radar) | ID target radar |
| Bearing / Range | Vị trí so với tàu mình |
| Speed / Course | Dùng chung cho cả target radar và tàu AIS |
| Tên tàu | Dùng chung cho cả hai. Để trống thì tool đặt `FUS<ID>` |
| MMSI | Bắt buộc, đúng 9 chữ số |
| Ship Type / AIS Class / Nav Status | Thông tin cho tàu AIS |

Bấm **Thêm cặp Fused**: tool thêm target vào tab Radar và tàu vào tab AIS. Vị trí tàu AIS được
tính từ Bearing/Range so với vị trí GPS hiện tại. Nếu đã có cặp trùng Target ID hoặc MMSI thì cặp
cũ bị thay thế.

### 8.2. Tab con "Auto Generate"

| Trường | Ý nghĩa |
|---|---|
| Fused (Radar + AIS) | Số cặp ghép |
| Radar-only | Số target chỉ có radar |
| AIS-only | Số tàu chỉ có AIS |
| AIS-only vị trí | Xung quanh tàu mình, hoặc vùng biển Việt Nam |
| MMSI Country | Mã quốc gia trong MMSI. *Mix* là ngẫu nhiên nhiều nước |

- **Generate Fusion Scenario**: **xoá toàn bộ** target radar và tàu AIS hiện có, rồi sinh kịch bản
  mới.
- **Clear All**: xoá toàn bộ target radar và tàu AIS.

### 8.3. Danh sách kịch bản

Mỗi dòng có một nhãn:
- `[FUSED] Radar=01 ↔ MMSI=574123456 ...`: cặp ghép.
- `[RADAR] ID=04 ...`: chỉ có radar.
- `[AIS  ] MMSI=... ...`: chỉ có AIS.
- `[MISSING: ...]`: một phía của cặp đã bị xoá ở tab Radar hoặc AIS.

> Để phát kịch bản fusion, cần tick cả **Radar** và **AIS** ở panel Generator.

---

## 9. Tab EXTRA Field

Đây là tab chính của công cụ: cấu hình các **field EXTRA** được chèn vào bản tin trước khi gửi.

### 9.1. Form rule

| Trường | Ý nghĩa |
|---|---|
| **Sentence Type** | Bản tin cần chèn field. Loại thiết bị hiện trong ngoặc, ví dụ `GGA (GPS)`, `TTM (RADAR)`, `VDM (AIS)`. **Bắt buộc chọn**: mặc định là *— Chọn sentence —* |
| **Target ID / MMSI** | Chỉ hiện khi chọn `TTM` hoặc `VDM`. Để trống thì rule áp dụng cho mọi target. Xem mục 9.5 |
| **Field Index** | Vị trí chèn, **đếm từ 0**, tính trên các field **sau** tên bản tin (`$GPGGA` không tính) |
| **Field Name** | Tên field, đặt tuỳ ý. Đây là tên sẽ hiển thị bên ENC, ví dụ `battery_voltage` |
| **Action** | **EXTRA**: chèn field vào bản tin. **DISABLE**: không đổi bản tin gửi đi, chỉ ghi vào file YAML để ENC bỏ field đó |
| **Data Type** | STRING, NUMBER hoặc BOOLEAN |
| **Giá trị phát** | Cách sinh giá trị (mục 9.2) |

Khi chọn Action = DISABLE, ô Data Type và Giá trị phát bị khoá vì không cần dùng.

### 9.2. Giá trị phát

Ô nhập bên dưới form thay đổi theo Data Type và chế độ:

| Data Type | Chế độ | Ô nhập | Giá trị gửi đi |
|---|---|---|---|
| STRING | Cố định | Giá trị (text) | Đúng text đã nhập. Dấu `,` tự đổi thành khoảng trắng để không làm hỏng câu NMEA |
| NUMBER | Cố định | Giá trị | Ví dụ `12.6` |
| NUMBER | Ngẫu nhiên trong khoảng | Từ / Đến | Số ngẫu nhiên trong khoảng, đổi ở mỗi câu |
| NUMBER | Tăng dần mỗi tick | Bắt đầu / Bước tăng mỗi tick | `Bắt đầu`, `Bắt đầu + Bước`, `Bắt đầu + 2×Bước`, … |
| BOOLEAN | Cố định | Checkbox *TRUE* | `1` nếu tick, `0` nếu không |
| BOOLEAN | Ngẫu nhiên | — | `1` hoặc `0` ngẫu nhiên |

> **Lưu ý:** giá trị được tính lại **mỗi khi có một câu được gửi**. Với `TTM`/`VDM`, nếu có 5
> target thì mỗi tick gửi 5 câu, nên giá trị *Tăng dần* nhảy 5 bước mỗi tick. Muốn từng target
> tăng đều từng bước thì tạo rule riêng cho từng Target ID / MMSI.
>
> Bộ đếm *Tăng dần* quay về giá trị *Bắt đầu* mỗi khi bạn bấm Add / Update lại rule đó hoặc Import
> YAML.

### 9.3. Nút và danh sách rule

| Nút / thao tác | Tác dụng |
|---|---|
| **Add / Update** | Lưu rule. Nếu đã có rule cùng Sentence Type, Field Index và Target ID/MMSI thì rule cũ bị thay thế |
| **Remove** | Xoá rule đang chọn |
| Bấm vào một dòng | Nạp rule đó lên form để sửa, sửa xong bấm Add / Update |
| **Export YAML** | Xuất rule ra file YAML (mục 11) |
| **Import YAML** | Nạp rule từ file YAML. Toàn bộ rule đang có bị **thay thế**, không gộp thêm |

Danh sách rule được sắp theo loại thiết bị, sentence, field index. Ví dụ:

```
[GPS] GGA #15  battery_voltage  (NUMBER, fixed)
[RADAR] TTM #12  [target=3]  risk_level  (NUMBER, increment)
[AIS] VDM #6  DISABLE
```

Mỗi lần lưu rule, NMEA Log Console ghi một dòng `[INFO] Đã lưu rule ...`.

### 9.4. Field được chèn vào câu như thế nào

- **Field Index nằm trong** số field chuẩn của câu: field EXTRA được **chèn xen** vào vị trí đó,
  các field chuẩn phía sau lùi lại một vị trí (không bị ghi đè).
- **Field Index lớn hơn** số field chuẩn: tool thêm các field rỗng cho đủ vị trí rồi đặt giá trị.
- Checksum `*hh` cuối câu luôn được tính lại.

Ví dụ: câu GGA chuẩn có 14 field (index 0–13). Rule `GGA`, Field Index `15`, giá trị `12.6`:

```
$GPGGA,...,0.0,M,,*hh          ← câu gốc (field 12, 13 rỗng)
$GPGGA,...,0.0,M,,,,12.6*hh    ← sau khi chèn (field 14 rỗng, field 15 = 12.6)
```

Muốn field EXTRA nằm ngay sau field cuối cùng mà không có field rỗng xen giữa thì đặt Field Index
bằng đúng số field chuẩn của câu (với GGA là `14`).

> ⚠️ **Với AIS (VDM/VDO):** câu AIS chỉ có 6 field ở phần vỏ: `tổng số câu, số thứ tự câu, mã
> chuỗi, kênh, payload, fill bits` (index 0–5). Không chèn được vào bên trong payload. Hãy dùng
> **Field Index từ 6 trở lên**. Nếu chèn vào index 0–5, các field vỏ bị đẩy lệch và phía nhận sẽ
> giải mã sai.

### 9.5. Rule mặc định và rule riêng theo target (TTM, VDM)

Radar có nhiều target và AIS có nhiều tàu phát cùng lúc, nên rule cho `TTM` và `VDM` có 2 loại:

- **Rule mặc định**: ô Target ID / MMSI để trống. Áp dụng cho mọi target.
- **Rule riêng**: có điền Target ID (với TTM) hoặc MMSI (với VDM). Chỉ áp dụng cho target đó, và
  **thay thế** rule mặc định ở cùng Field Index. Các target khác vẫn dùng rule mặc định.

Ví dụ: sentence `TTM`, Field Index `12` (ngay sau field cuối của câu TTM chuẩn), có 3 target
radar:

| Rule đã tạo | Target 1 | Target 2 | Target 3 |
|---|---|---|---|
| Chỉ có rule mặc định = `0` | `0` | `0` | `0` |
| Thêm rule riêng cho target `3` = `99` | `0` | `0` | `99` |
| Chỉ có rule riêng cho target `3` | (không chèn) | (không chèn) | `99` |

Target ID xem ở cột đầu danh sách tab Radar. MMSI xem ở cột đầu danh sách tab AIS.

> Với tàu AIS Class A, thông tin tĩnh (Type 5) gửi thành 2 câu. Rule riêng theo MMSI chỉ áp dụng
> cho câu thứ nhất; câu thứ hai chỉ nhận rule mặc định.

### 9.6. Kiểm tra kết quả

Sau khi Start, xem **NMEA Log Console**. Log hiển thị **đúng câu đã gửi**, tức là đã chèn field
EXTRA và tính lại checksum. Hãy đối chiếu vị trí field trong log với Field Index đã cấu hình trước
khi kiểm tra bên ENC.

---

## 10. NMEA Log Console và thanh trạng thái

### 10.1. Log Console

- Mỗi dòng có dạng `[giờ:phút:giây.mili] <bản tin>`.
- Màu chữ:
  - `GPRMC`: màu GPS.
  - `RATTM`, `RAOSD`, `RARSD`: màu Radar.
  - `AIVDM`, `AIVDO`: màu AIS.
  - Các sentence GPS khác: màu trắng.
  - Dòng `[INFO]`: thông báo của tool (kết nối, lưu rule, export, …).
  - Dòng `[ERROR]`: lỗi khi gửi.
- **Clear**: xoá log.
- **Auto-scroll**: tự cuộn xuống dòng mới nhất. Bỏ tick để dừng cuộn khi cần đọc kỹ.
- *N messages sent*: số bản tin đã gửi kể từ lần Start gần nhất.

### 10.2. Thanh trạng thái (đáy cửa sổ)

| Hiển thị | Ý nghĩa |
|---|---|
| `Disconnected` | Chưa kết nối |
| `Connected — <kiểu> <địa chỉ>` | Đã kết nối, chưa phát |
| `Transmitting — interval N ms` | Đang phát |
| `Connected (stopped)` | Đã Stop, vẫn giữ kết nối |

Nếu lỗi trong lúc phát (ví dụ mất kết nối), tool hiện hộp thoại *Transmission Error*, ghi log
`[ERROR]` và tự Stop.

---

## 11. Nạp cấu hình vào ENC

### 11.1. Export YAML

Ở tab **EXTRA Field**, bấm **Export YAML** và chọn nơi lưu (tên mặc định
`device_field_rules.yaml`). Nội dung file có dạng:

```yaml
device_field_rules:
- device_name: GPS
  device_type: GPS
  sentence_type: GGA
  field_index: 15
  action: EXTRA
  field_name: battery_voltage
  data_type: NUMBER
  value_mode: fixed
  fixed_value: '12.6'
  range_min: 0.0
  range_max: 0.0
  step: 1.0
```

- ENC chỉ đọc 7 dòng đầu (từ `device_name` tới `data_type`). Các dòng còn lại để tool Import lại
  đúng cách sinh giá trị.
- `device_name` được ghi bằng loại thiết bị (`GPS`, `RADAR`, `AIS`).
- ENC chỉ phân biệt rule theo **sentence + field index**, không theo target. Vì vậy các rule cùng
  sentence và field index nhưng khác Target ID / MMSI được **gộp thành 1 dòng** khi export (ưu tiên
  rule mặc định). Log sẽ ghi rõ, ví dụ `Đã export 1 dòng ... (gộp từ 3 rule nội bộ theo target)`.
- Vì vậy file YAML **không lưu được** rule riêng theo target. Import lại file đó vào tool sẽ không
  có lại các rule riêng.

### 11.2. Import vào ENC theo thiết bị (khuyên dùng)

1. Bên ENC, tạo thiết bị ở màn **Device** với đúng loại (GPS / RADAR / AIS). Tên đặt tuỳ ý.
2. Ở màn **Device**, bấm icon import (📥) trên card của thiết bị đó rồi chọn file YAML vừa export.
3. ENC áp các rule trong file cho thiết bị đó.
   - Rule có sentence không đúng loại thiết bị (ví dụ `TTM` nạp vào thiết bị AIS) được đếm vào
     *bỏ qua (sai loại bản tin)* và không được tạo.

### 11.3. Import vào ENC theo tên (cách cũ)

Ở màn **Cấu hình bản tin**, bấm Import. ENC tìm thiết bị theo `device_name` + `device_type` trong
file. Vì tool ghi `device_name` là `GPS` / `RADAR` / `AIS`, bạn phải **sửa `device_name` trong file**
cho trùng tên thiết bị bên ENC. Nếu tên không khớp, dòng đó bị bỏ qua.

---

## 12. Kịch bản test mẫu

**Mục tiêu:** ENC đọc được field `battery_voltage` = `12.6` trong bản tin GGA.

1. **ENC**: tạo thiết bị GPS, ví dụ "GPS Test", và cấu hình kết nối tới gateway.
2. **Connection**: chọn SSH Tunnel (hoặc TCP Client nếu có mạng trực tiếp), nhập **Cổng thiết bị**
   của "GPS Test", bấm **Connect**.
3. **Generator**: tick **GPS**, tick **GGA** trong GPS Settings.
4. **Tab EXTRA Field**: Sentence `GGA (GPS)`, Field Index `15`, Field Name `battery_voltage`,
   Action `EXTRA`, Data Type `NUMBER`, Giá trị phát *Cố định* `12.6`. Bấm **Add / Update**.
5. Bấm **Export YAML**.
6. **ENC**: màn Device → icon import trên "GPS Test" → chọn file vừa xuất. Kết quả báo *tạo mới: 1*.
7. Bấm **▶ Start**. Log hiện câu `$GPGGA,...,12.6*hh`.
8. **ENC**: mở màn **Cấu hình bản tin** của "GPS Test", sentence GGA. Field `battery_voltage` có
   *Giá trị đang chạy thật* = `12.6`.
9. Đổi giá trị phát sang *Tăng dần mỗi tick* (Bắt đầu `0`, Bước `1`), bấm **Add / Update**. Giá trị
   bên ENC tăng 1 theo mỗi chu kỳ Interval.

**Biến thể cho Radar:** tick **Radar**, bấm **Generate** ở tab Radar để có vài target, rồi tạo rule
`TTM` với Field Index `12`. Thêm một rule riêng cho Target ID `1` với giá trị khác, và kiểm tra ENC
thấy target 1 có giá trị khác các target còn lại.

---

## 13. Lỗi thường gặp

| Hiện tượng | Nguyên nhân và cách xử lý |
|---|---|
| Nút **Start** bị mờ | Chưa Connect |
| Bấm Add / Update báo *Thiếu Sentence Type* | Chưa chọn sentence trong ô Sentence Type |
| Log không có field EXTRA | Sentence đó không được phát: chưa tick nguồn (GPS/Radar/AIS), chưa tick sentence trong GPS Settings, hoặc tab Radar/AIS chưa có target |
| Đã tick thêm Radar/AIS nhưng không thấy phát | Checkbox nguồn chỉ được đọc khi bấm Start: hãy Stop rồi Start lại |
| Rule riêng theo target không có tác dụng | Sai Target ID hoặc MMSI. Kiểm tra lại danh sách ở tab Radar/AIS |
| Giá trị *Tăng dần* của TTM/VDM nhảy nhiều bước mỗi tick | Mỗi target là một câu. Xem lưu ý ở mục 9.2 |
| ENC giải mã sai câu AIS | Field Index của VDM/VDO nằm trong 0–5. Dùng từ 6 trở lên |
| Rule DISABLE không làm thay đổi log | Đúng thiết kế: DISABLE chỉ là chỉ thị cho ENC, bản tin vẫn gửi đủ field |
| ENC báo bỏ qua dòng khi import | Import theo tên mà `device_name` không khớp (nên dùng import theo thiết bị, mục 11.2), hoặc sentence không đúng loại thiết bị |
| Import YAML vào tool mất các rule riêng theo target | File YAML không lưu rule riêng theo target. Xem mục 11.1 |
| SSH Tunnel không kết nối được | Pod đã restart nên IP đổi: bấm **Lấy Pod IP** lại. Kiểm tra Cổng thiết bị và mật khẩu |
| Hộp thoại *Transmission Error* khi đang phát | Mất kết nối tới đích. Tool đã tự Stop; kiểm tra mạng rồi Connect lại |
| Lỗi GPX *quá ít điểm* | File GPX phải có ít nhất 2 điểm |
