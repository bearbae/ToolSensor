"""NMEA sentence generators for GPS (RMC), Radar (TTM), and AIS (VDM) messages.

All generators simulate movement: positions are updated each call based on
elapsed time, speed, and course using great-circle (rhumb-line approximation)
calculations.
"""

import datetime
import math
import time

from utils import nmea_checksum, format_nmea_lat, format_nmea_lon

# Earth radius in nautical miles
_R_NM = 3440.065

# AIS 6-bit ASCII lookup: space=32, @=0, A-Z=1-26, 0-9=48-57
_AIS_CHAR_MAP = {' ': 32, '@': 0}
_AIS_CHAR_MAP.update({chr(i): i - ord('A') + 1 for i in range(ord('A'), ord('Z') + 1)})
_AIS_CHAR_MAP.update({chr(i): i - ord('0') + 48 for i in range(ord('0'), ord('9') + 1)})


def _encode_ais_text(text: str, length: int) -> list:
    """Encode text to AIS 6-bit ASCII bits, padded/truncated to `length` chars."""
    text = text.upper().ljust(length, '@')[:length]
    bits = []
    for c in text:
        val = _AIS_CHAR_MAP.get(c, 32)
        for i in range(5, -1, -1):
            bits.append((val >> i) & 1)
    return bits


def _move(lat: float, lon: float, course_deg: float, speed_kn: float,
          dt_hours: float) -> tuple:
    """Return new (lat, lon) after moving at given speed/course for dt_hours."""
    dist_nm = speed_kn * dt_hours
    if dist_nm == 0.0:
        return lat, lon
    d = dist_nm / _R_NM
    lat1 = math.radians(lat)
    lon1 = math.radians(lon)
    brg = math.radians(course_deg)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d)
        + math.cos(lat1) * math.sin(d) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


def _bearing_range(own_lat: float, own_lon: float,
                   tgt_lat: float, tgt_lon: float) -> tuple:
    """Return (bearing_deg, range_nm) from own ship to target."""
    lat1 = math.radians(own_lat)
    lat2 = math.radians(tgt_lat)
    dlon = math.radians(tgt_lon - own_lon)
    dlat = lat2 - lat1
    a = math.sin(dlat / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
    range_nm = _R_NM * 2 * math.asin(math.sqrt(max(0.0, a)))
    y = math.sin(dlon) * math.cos(lat2)
    x = math.cos(lat1) * math.sin(lat2) - math.sin(lat1) * math.cos(lat2) * math.cos(dlon)
    bearing = (math.degrees(math.atan2(y, x)) + 360) % 360
    return bearing, range_nm


def _latlon_from_bearing_range(own_lat: float, own_lon: float,
                                bearing_deg: float, range_nm: float) -> tuple:
    """Return absolute (lat, lon) of a point at bearing/range from own ship."""
    d = range_nm / _R_NM
    lat1 = math.radians(own_lat)
    lon1 = math.radians(own_lon)
    brg = math.radians(bearing_deg)
    lat2 = math.asin(
        math.sin(lat1) * math.cos(d)
        + math.cos(lat1) * math.sin(d) * math.cos(brg)
    )
    lon2 = lon1 + math.atan2(
        math.sin(brg) * math.sin(d) * math.cos(lat1),
        math.cos(d) - math.sin(lat1) * math.sin(lat2),
    )
    return math.degrees(lat2), math.degrees(lon2)


# ---------------------------------------------------------------------------

class GPSGenerator:
    """Generates GPRMC sentences. Own-ship position updates each call."""

    def __init__(self):
        self.lat = 10.776900
        self.lon = 106.700900
        self.speed = 5.0      # knots
        self.course = 45.0    # degrees true
        self._last_t = time.monotonic()

    def generate(self) -> str:
        now_t = time.monotonic()
        dt = (now_t - self._last_t) / 3600.0   # hours
        self._last_t = now_t

        self.lat, self.lon = _move(self.lat, self.lon, self.course, self.speed, dt)

        now = datetime.datetime.now(datetime.timezone.utc)
        time_str = now.strftime("%H%M%S.00")
        date_str = now.strftime("%d%m%y")
        lat_str, lat_dir = format_nmea_lat(self.lat)
        lon_str, lon_dir = format_nmea_lon(self.lon)
        body = (
            f"GPRMC,{time_str},A,{lat_str},{lat_dir},"
            f"{lon_str},{lon_dir},{self.speed:.1f},{self.course:.1f},"
            f"{date_str},,,A"
        )
        return f"${body}*{nmea_checksum(body)}"

    def generate_zda(self) -> str:
        """Generate GPZDA sentence with full UTC date/time (4-digit year)."""
        now = datetime.datetime.now(datetime.timezone.utc)
        time_str = now.strftime("%H%M%S.00")
        body = (
            f"GPZDA,{time_str},"
            f"{now.day:02d},{now.month:02d},{now.year:04d},"
            f"00,00"
        )
        return f"${body}*{nmea_checksum(body)}"

    def reset_position(self, lat: float, lon: float) -> None:
        """Snap own-ship to a new position without movement history."""
        self.lat = lat
        self.lon = lon
        self._last_t = time.monotonic()


# ---------------------------------------------------------------------------

class RadarTTMGenerator:
    """Generates RATTM sentences. Target positions advance each call."""

    def __init__(self):
        # target_id -> {lat, lon, speed, course, status, name}
        self.targets: dict = {}
        self._last_t = time.monotonic()
        # Reference for own-ship position (kept in sync with GPSGenerator)
        self.own_lat = 10.776900
        self.own_lon = 106.700900

    def add_or_update_target(
        self,
        target_id: int,
        bearing: float,
        range_nm: float,
        speed: float,
        course: float,
        status: str = 'T',
        name: str = '',
    ) -> None:
        tgt_lat, tgt_lon = _latlon_from_bearing_range(
            self.own_lat, self.own_lon, bearing, range_nm
        )
        self.targets[target_id] = {
            'lat': tgt_lat,
            'lon': tgt_lon,
            'speed': speed,
            'course': course,
            'status': status,
            'name': name,
            'bearing': bearing,
            'range': range_nm,
        }

    def remove_target(self, target_id: int) -> None:
        self.targets.pop(target_id, None)

    def generate_all(self) -> list:
        now_t = time.monotonic()
        dt = (now_t - self._last_t) / 3600.0
        self._last_t = now_t

        messages = []
        for tid, t in self.targets.items():
            # Advance target position
            t['lat'], t['lon'] = _move(
                t['lat'], t['lon'], t['course'], t['speed'], dt
            )
            # Recalculate bearing and range relative to own ship
            bearing, range_nm = _bearing_range(
                self.own_lat, self.own_lon, t['lat'], t['lon']
            )
            t['bearing'] = bearing
            t['range'] = range_nm
            body = (
                f"RATTM,{int(tid):02d},{range_nm:.1f},{bearing:.1f},T,"
                f"{t['speed']:.1f},{t['course']:.1f},T,0.0,0.0,N,"
                f"{t['name']},{t['status']}"
            )
            messages.append(f"${body}*{nmea_checksum(body)}")
        return messages


# ---------------------------------------------------------------------------

class AISGenerator:
    """Generates AIVDM sentences (Type 1/5 for Class A, Type 18/24 for Class B).

    Position reports are emitted every call.
    Static data (Type 5 / Type 24) follows ITU-R M.1371-5: sent immediately on
    first appearance, then at most once every STATIC_INTERVAL seconds (360 s = 6 min).
    """

    STATIC_INTERVAL = 360.0   # seconds between static-data transmissions

    def __init__(self):
        self.vessels: dict = {}   # mmsi -> dict
        self._last_t = time.monotonic()
        self._seq_id = 0          # sequential message identifier for multi-sentence messages

    def add_or_update_vessel(
        self,
        mmsi: int,
        lat: float,
        lon: float,
        sog: float,
        cog: float,
        heading: int = 511,
        nav_status: int = 0,
        shipname: str = '',
        shiptype: int = 0,
        callsign: str = '',
        destination: str = '',
        eta: tuple = (0, 0, 24, 60),   # (month, day, hour, minute) — 0/24/60 = n/a
        imo: int = 0,                  # IMO number 1000000–9999999; 0 = not available
        ais_class: str = 'A',          # 'A' → Type 1+5;  'B' → Type 18+24A+24B
    ) -> None:
        self.vessels[mmsi] = {
            'lat': lat,
            'lon': lon,
            'sog': sog,
            'cog': cog,
            'heading': heading,
            'nav_status': nav_status,
            'shipname': shipname,
            'shiptype': shiptype,
            'callsign': callsign,
            'destination': destination,
            'eta': eta,
            'imo': imo,
            'ais_class': ais_class,
        }

    def remove_vessel(self, mmsi: int) -> None:
        self.vessels.pop(mmsi, None)

    def _build_type5_bits(self, mmsi: int, vessel: dict) -> list:
        """Build 424-bit AIS Type 5 (static & voyage data) payload."""
        bits = []

        def add_uint(value: int, n: int) -> None:
            value = int(value) & ((1 << n) - 1)
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        add_uint(5, 6)                                              # Message type
        add_uint(0, 2)                                              # Repeat
        add_uint(mmsi, 30)                                          # MMSI
        add_uint(0, 2)                                              # AIS version
        add_uint(vessel.get('imo', 0), 30)                          # IMO number
        bits.extend(_encode_ais_text(vessel.get('callsign', ''), 7))   # Call sign (42 bits)
        bits.extend(_encode_ais_text(vessel.get('shipname', ''), 20))  # Ship name (120 bits)
        add_uint(vessel.get('shiptype', 0), 8)                     # Ship & cargo type
        add_uint(0, 9)                                              # Dim to bow
        add_uint(0, 9)                                              # Dim to stern
        add_uint(0, 6)                                              # Dim to port
        add_uint(0, 6)                                              # Dim to starboard
        add_uint(0, 4)                                              # EPFS type
        eta = vessel.get('eta', (0, 0, 24, 60))
        add_uint(eta[0], 4)                                         # ETA month
        add_uint(eta[1], 5)                                         # ETA day
        add_uint(eta[2], 5)                                         # ETA hour
        add_uint(eta[3], 6)                                         # ETA minute
        add_uint(0, 8)                                              # Draught x10
        bits.extend(_encode_ais_text(vessel.get('destination', ''), 20))  # Destination
        add_uint(0, 1)                                              # DTE
        add_uint(0, 1)                                              # Spare
        return bits                                                 # 424 bits total

    def _build_type1_bits(self, mmsi: int, vessel: dict) -> list:
        bits = []

        def add_uint(value: int, n: int) -> None:
            value = int(value) & ((1 << n) - 1)
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        def add_int(value: int, n: int) -> None:
            value = int(value)
            if value < 0:
                value += (1 << n)
            value &= (1 << n) - 1
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        add_uint(1, 6)                                          # Message type
        add_uint(0, 2)                                          # Repeat
        add_uint(mmsi, 30)                                      # MMSI
        add_uint(vessel['nav_status'], 4)                       # Nav status
        add_int(-128, 8)                                        # ROT (n/a)
        add_uint(int(vessel['sog'] * 10), 10)                   # SOG ×10
        add_uint(0, 1)                                          # Pos accuracy
        add_int(round(vessel['lon'] * 600000), 28)              # Lon (1/10000 min)
        add_int(round(vessel['lat'] * 600000), 27)              # Lat (1/10000 min)
        add_uint(int(vessel['cog'] * 10), 12)                   # COG ×10
        add_uint(vessel['heading'], 9)                          # Heading
        add_uint(datetime.datetime.now(datetime.timezone.utc).second, 6)  # UTC second
        add_uint(0, 2)                                          # Maneuver
        add_uint(0, 3)                                          # Spare
        add_uint(0, 1)                                          # RAIM
        add_uint(0, 19)                                         # Radio status
        return bits                                             # 168 bits

    def _build_type18_bits(self, mmsi: int, vessel: dict) -> list:
        """Build 168-bit AIS Type 18 (Class B position report)."""
        bits = []

        def add_uint(value: int, n: int) -> None:
            value = int(value) & ((1 << n) - 1)
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        def add_int(value: int, n: int) -> None:
            value = int(value)
            if value < 0:
                value += (1 << n)
            value &= (1 << n) - 1
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        add_uint(18, 6)                                                  # Message type
        add_uint(0, 2)                                                   # Repeat
        add_uint(mmsi, 30)                                               # MMSI
        add_uint(0, 8)                                                   # Reserved
        add_uint(int(vessel['sog'] * 10), 10)                            # SOG ×10
        add_uint(0, 1)                                                   # Pos accuracy
        add_int(round(vessel['lon'] * 600000), 28)                       # Lon (1/10000 min)
        add_int(round(vessel['lat'] * 600000), 27)                       # Lat (1/10000 min)
        add_uint(int(vessel['cog'] * 10), 12)                            # COG ×10
        add_uint(vessel['heading'], 9)                                   # Heading
        add_uint(datetime.datetime.now(datetime.timezone.utc).second, 6) # UTC second
        add_uint(0, 2)                                                   # Regional reserved
        add_uint(1, 1)                                                   # CS Unit = 1 (Class B CS)
        add_uint(0, 1)                                                   # Display flag
        add_uint(1, 1)                                                   # DSC flag
        add_uint(1, 1)                                                   # Band flag
        add_uint(1, 1)                                                   # MSG22 flag
        add_uint(0, 1)                                                   # Assigned
        add_uint(0, 1)                                                   # RAIM
        add_uint(0, 20)                                                  # Radio status
        return bits                                                      # 168 bits

    def _build_type24a_bits(self, mmsi: int, vessel: dict) -> list:
        """Build 168-bit AIS Type 24 Part A (Class B static — ship name)."""
        bits = []

        def add_uint(value: int, n: int) -> None:
            value = int(value) & ((1 << n) - 1)
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        add_uint(24, 6)                                                  # Message type
        add_uint(0, 2)                                                   # Repeat
        add_uint(mmsi, 30)                                               # MMSI
        add_uint(0, 2)                                                   # Part number = 0
        bits.extend(_encode_ais_text(vessel.get('shipname', ''), 20))    # Ship name (120 bits)
        add_uint(0, 8)                                                   # Spare
        return bits                                                      # 168 bits

    def _build_type24b_bits(self, mmsi: int, vessel: dict) -> list:
        """Build 168-bit AIS Type 24 Part B (Class B static — callsign, shiptype)."""
        bits = []

        def add_uint(value: int, n: int) -> None:
            value = int(value) & ((1 << n) - 1)
            for i in range(n - 1, -1, -1):
                bits.append((value >> i) & 1)

        add_uint(24, 6)                                                  # Message type
        add_uint(0, 2)                                                   # Repeat
        add_uint(mmsi, 30)                                               # MMSI
        add_uint(1, 2)                                                   # Part number = 1
        add_uint(vessel.get('shiptype', 0), 8)                           # Ship & cargo type
        bits.extend(_encode_ais_text('', 7))                             # Vendor ID (42 bits)
        bits.extend(_encode_ais_text(vessel.get('callsign', ''), 7))     # Call sign (42 bits)
        add_uint(0, 9)                                                   # Dim to bow
        add_uint(0, 9)                                                   # Dim to stern
        add_uint(0, 6)                                                   # Dim to port
        add_uint(0, 6)                                                   # Dim to starboard
        add_uint(0, 4)                                                   # EPFS type
        add_uint(0, 2)                                                   # Spare
        return bits                                                      # 168 bits

    def _bits_to_payload(self, bits: list) -> tuple:
        fill_bits = (6 - len(bits) % 6) % 6
        while len(bits) % 6 != 0:
            bits.append(0)
        chars = []
        for i in range(0, len(bits), 6):
            val = 0
            for j in range(6):
                val = (val << 1) | bits[i + j]
            val += 48
            if val > 87:
                val += 8
            chars.append(chr(val))
        return ''.join(chars), fill_bits

    def _next_seq_id(self) -> int:
        """Return next sequential message identifier (1–9), cycling."""
        self._seq_id = (self._seq_id % 9) + 1
        return self._seq_id

    def generate_all(self) -> list:
        now_t = time.monotonic()
        dt = (now_t - self._last_t) / 3600.0
        self._last_t = now_t

        messages = []
        for mmsi, vessel in self.vessels.items():
            vessel['lat'], vessel['lon'] = _move(
                vessel['lat'], vessel['lon'],
                vessel['cog'], vessel['sog'], dt
            )

            # Determine whether static data is due this cycle.
            # _last_static_t = 0 means never sent → send immediately.
            last_static = vessel.get('_last_static_t', 0.0)
            send_static = (now_t - last_static) >= self.STATIC_INTERVAL

            if vessel.get('ais_class', 'A') == 'A':
                # Type 1 — Class A position report (every cycle)
                bits1 = self._build_type1_bits(mmsi, vessel)
                payload1, fill1 = self._bits_to_payload(bits1)
                body1 = f"AIVDM,1,1,,A,{payload1},{fill1}"
                messages.append(f"!{body1}*{nmea_checksum(body1)}")

                # Type 5 — static & voyage data (every 6 min per ITU-R M.1371-5)
                if send_static:
                    seq = self._next_seq_id()
                    bits5 = self._build_type5_bits(mmsi, vessel)
                    payload5_1, _ = self._bits_to_payload(bits5[:336])
                    payload5_2, fill5 = self._bits_to_payload(bits5[336:])
                    body5_1 = f"AIVDM,2,1,{seq},A,{payload5_1},0"
                    body5_2 = f"AIVDM,2,2,{seq},A,{payload5_2},{fill5}"
                    messages.append(f"!{body5_1}*{nmea_checksum(body5_1)}")
                    messages.append(f"!{body5_2}*{nmea_checksum(body5_2)}")
                    vessel['_last_static_t'] = now_t
            else:
                # Type 18 — Class B position report (every cycle)
                bits18 = self._build_type18_bits(mmsi, vessel)
                payload18, fill18 = self._bits_to_payload(bits18)
                body18 = f"AIVDM,1,1,,B,{payload18},{fill18}"
                messages.append(f"!{body18}*{nmea_checksum(body18)}")

                # Type 24 A + B — static data (every 6 min per ITU-R M.1371-5)
                if send_static:
                    bits24a = self._build_type24a_bits(mmsi, vessel)
                    payload24a, fill24a = self._bits_to_payload(bits24a)
                    body24a = f"AIVDM,1,1,,B,{payload24a},{fill24a}"
                    messages.append(f"!{body24a}*{nmea_checksum(body24a)}")

                    bits24b = self._build_type24b_bits(mmsi, vessel)
                    payload24b, fill24b = self._bits_to_payload(bits24b)
                    body24b = f"AIVDM,1,1,,B,{payload24b},{fill24b}"
                    messages.append(f"!{body24b}*{nmea_checksum(body24b)}")
                    vessel['_last_static_t'] = now_t

        return messages
