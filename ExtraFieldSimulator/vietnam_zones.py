"""Vùng biển/cảng/sông Việt Nam dùng để sinh toạ độ ngẫu nhiên luôn nằm trên
mặt nước (own-ship start, radar target quanh tàu mình, tàu AIS ngẫu nhiên) —
dùng chung giữa GPS/Radar/AIS tab nên tách riêng module này.
"""

from generators import _bearing_range, _latlon_from_bearing_range, _move


def _sample_zone_point(zone: tuple) -> tuple:
    """Sinh 1 điểm (lat, lon) ngẫu nhiên trong 1 vùng nước.

    zone = (name, kind, lat1, lon1, lat2, lon2, size, zone_type, weight)
    - kind='circle': điểm ngẫu nhiên trong bán kính `size` NM quanh (lat1, lon1)
      — dùng cho biển/vịnh mở, đủ rộng nên full-circle vẫn an toàn.
    - kind='corridor': điểm dọc theo đoạn thẳng xấp xỉ luồng/sông từ
      (lat1, lon1) đến (lat2, lon2), lệch vuông góc tối đa `size` NM — tránh
      full-circle rơi lên bờ như cách sinh cũ, vì sông/kênh thường hẹp.
    """
    import random
    _, kind, lat1, lon1, lat2, lon2, size, _z_type, _w = zone
    if kind == 'circle':
        bearing = random.uniform(0, 360)
        range_nm = random.uniform(0, size)
        return _latlon_from_bearing_range(lat1, lon1, bearing, range_nm)

    axis_brg, length_nm = _bearing_range(lat1, lon1, lat2, lon2)
    dist_along = random.uniform(0, length_nm)
    lat_c, lon_c = _move(lat1, lon1, axis_brg, dist_along, 1.0)
    perp_offset = random.uniform(-size, size)
    perp_brg = (axis_brg + 90.0) % 360
    return _move(lat_c, lon_c, perp_brg, perp_offset, 1.0)


class ZoneHelperMixin:
    _CLASS_A_TYPES = {52, 60, 61, 62, 63, 64, 65, 66, 67, 68, 69,
                      70, 71, 72, 73, 74, 75, 76, 77, 78, 79,
                      80, 81, 82, 83, 84, 85, 86, 87, 88, 89}

    # Vùng biển/cảng/sông Việt Nam — dùng để sinh toạ độ luôn nằm trên mặt
    # nước (không rơi lên đất liền).
    # (tên, kind, lat1, lon1, lat2, lon2, size, loại_vùng, trọng_số)
    #   kind='circle'   : vùng biển/vịnh mở — tròn bán kính `size` NM quanh
    #                     (lat1, lon1); đủ rộng nên full-circle vẫn an toàn.
    #   kind='corridor' : luồng/sông hẹp — dải NM `size` (nửa bề rộng) dọc
    #                     theo đoạn thẳng xấp xỉ lòng sông/luồng từ
    #                     (lat1, lon1) đến (lat2, lon2); tránh full-circle
    #                     rơi lên bờ như cách sinh cũ.
    # loại_vùng: 'port' | 'sea' | 'river' — quyết định loại tàu/tốc độ điển hình.
    _VIETNAM_ZONES = [
        # ── Biển / vịnh mở (circle) ──────────────────────────────────────
        ('Vịnh Bắc Bộ',              'circle', 19.700, 107.500, None, None, 45.0, 'sea', 9),
        ('Ven biển Trung Bộ',        'circle', 15.300, 109.800, None, None, 45.0, 'sea', 8),
        ('Ven biển Nam Trung Bộ',    'circle', 12.300, 110.300, None, None, 45.0, 'sea', 8),
        ('Biển Đông (Nam)',          'circle',  9.500, 110.500, None, None, 55.0, 'sea', 7),
        ('Vịnh Thái Lan',            'circle',  9.300, 103.800, None, None, 35.0, 'sea', 6),
        ('Quần đảo Trường Sa',       'circle',  9.000, 113.000, None, None, 45.0, 'sea', 3),
        ('Vịnh Đà Nẵng (ngoài khơi)','circle', 16.150, 108.260, None, None,  1.5, 'sea', 5),
        ('Vịnh Nha Trang (ngoài khơi)','circle',12.190, 109.260, None, None,  1.8, 'sea', 5),
        ('Vịnh Quy Nhơn (ngoài khơi)','circle', 13.740, 109.300, None, None,  1.5, 'sea', 4),
        ('Vũng neo Vũng Tàu',        'circle', 10.300, 107.200, None, None,  3.0, 'sea', 9),
        ('Cửa Mekong (ngoài khơi)',  'circle',  9.450, 106.750, None, None,  4.0, 'sea', 5),
        ('Vịnh Hạ Long (mở)',        'circle', 20.900, 107.150, None, None,  3.0, 'sea', 6),
        # ── Luồng cảng / sông hẹp (corridor) ─────────────────────────────
        ('Sông Sài Gòn (nội đô)',    'corridor', 10.7820, 106.7040, 10.7550, 106.7430, 0.25, 'river', 6),
        ('Sông Sài Gòn (Cát Lái)',   'corridor', 10.7550, 106.7430, 10.7150, 106.7900, 0.35, 'port', 10),
        ('Luồng Cái Mép - Thị Vải',  'corridor', 10.5800, 107.0150, 10.4300, 107.0300, 0.60, 'port', 10),
        ('Sông Hậu (Cần Thơ)',       'corridor', 10.0700, 105.7300,  9.9600, 105.8500, 0.50, 'river', 6),
        ('Sông Tiền (Mỹ Tho)',       'corridor', 10.3600, 106.3400, 10.2000, 106.5600, 0.40, 'river', 5),
        ('Luồng Hải Phòng (Bạch Đằng)','corridor', 20.8700, 106.8000, 20.7500, 106.9600, 0.60, 'port', 10),
        ('Sông Cấm (Hải Phòng)',     'corridor', 20.9000, 106.6500, 20.8500, 106.7500, 0.35, 'river', 5),
    ]

    # Tàu phù hợp theo loại vùng
    _ZONE_SHIP_TYPES = {
        'port':  [52, 60, 70, 71, 72, 73, 74, 80, 81, 82, 83, 90],
        'sea':   [70, 71, 72, 73, 74, 80, 81, 82, 83, 84],
        'river': [30, 36, 37, 52, 90],
    }

    def _random_own_ship_start(self) -> tuple:
        """Chọn vị trí xuất phát ngẫu nhiên cho tàu mình — tàu cảnh sát biển
        tuần tra: chủ yếu ở ngoài khơi (sea), thỉnh thoảng ở cảng biển/luồng
        nước sâu (port). Không dùng vùng 'river' (sông nội địa hẹp — Sài Gòn
        nội đô, Cần Thơ, Mỹ Tho, sông Cấm): vừa không hợp lý cho tàu tuần tra
        biển, vừa dễ rơi lên bờ vì corridor chỉ xấp xỉ 1 đoạn thẳng trong khi
        các sông này uốn khúc nhiều."""
        import random
        sea_zones = [z for z in self._VIETNAM_ZONES if z[7] == 'sea']
        port_zones = [z for z in self._VIETNAM_ZONES if z[7] == 'port']
        zones = sea_zones if random.random() < 0.8 else port_zones
        weights = [z[8] for z in zones]
        zone = random.choices(zones, weights=weights, k=1)[0]
        lat, lon = _sample_zone_point(zone)
        return round(lat, 6), round(lon, 6)

    def _nearest_water_zone(self, lat: float, lon: float):
        """Trả về zone (trong _VIETNAM_ZONES) có điểm tham chiếu gần
        (lat, lon) nhất — dùng để sinh mục tiêu Radar/AIS "quanh tàu mình"
        bám theo đúng vùng nước tàu mình đang ở, tránh rơi lên bờ."""
        best, best_d = None, float('inf')
        for zone in self._VIETNAM_ZONES:
            _, kind, lat1, lon1, lat2, lon2, *_rest = zone
            if kind == 'circle':
                ref_lat, ref_lon = lat1, lon1
            else:
                ref_lat, ref_lon = (lat1 + lat2) / 2.0, (lon1 + lon2) / 2.0
            _, d = _bearing_range(lat, lon, ref_lat, ref_lon)
            if d < best_d:
                best_d, best = d, zone
        return best

    def _sample_near_own_ship(self, own_lat: float, own_lon: float, range_nm: float) -> tuple:
        """Sinh 1 điểm cách tàu mình khoảng `range_nm` NM, bám theo vùng
        nước (biển mở / luồng / sông) gần tàu mình nhất — mục tiêu Radar/AIS
        "quanh tàu mình" luôn nằm trên mặt nước thay vì rơi lên bờ."""
        import random
        zone = self._nearest_water_zone(own_lat, own_lon)
        if zone is None or zone[1] == 'circle':
            bearing = random.uniform(0, 360)
            return _latlon_from_bearing_range(own_lat, own_lon, bearing, range_nm)

        # corridor: rải trong 1 dải hình chữ nhật quanh VỊ TRÍ TÀU MÌNH, dọc
        # theo trục sông/luồng (không phải từ đầu đoạn zone — trước đây tính
        # từ đầu đoạn rồi clamp vào [0, length_nm] khiến hầu hết mục tiêu bị
        # dồn về đúng 1 điểm đầu/cuối đoạn). Thành phần dọc trục lấy ngẫu
        # nhiên trong [-range_nm, range_nm] thay vì cố định đúng range_nm —
        # nếu không, mọi mục tiêu chỉ rơi vào đúng 2 tia (trước/sau tàu
        # mình), nhìn như nằm thẳng hàng trên 1 đường thẳng.
        _, _kind, lat1, lon1, lat2, lon2, half_width, _z_type, _w = zone
        axis_brg, _length_nm = _bearing_range(lat1, lon1, lat2, lon2)
        along = random.uniform(-range_nm, range_nm)
        perp = random.uniform(-half_width, half_width)
        lat_c, lon_c = _move(own_lat, own_lon, axis_brg, along, 1.0)
        perp_brg = (axis_brg + 90.0) % 360
        return _move(lat_c, lon_c, perp_brg, perp, 1.0)

    def _random_vietnam_vessel(self) -> dict:
        """Tạo một tàu tại vị trí thực tế ở vùng biển Việt Nam."""
        import random
        zones = self._VIETNAM_ZONES
        weights = [z[8] for z in zones]
        zone = random.choices(zones, weights=weights, k=1)[0]
        z_type = zone[7]
        lat, lon = _sample_zone_point(zone)

        ship_type = random.choice(self._ZONE_SHIP_TYPES[z_type])
        ais_class = 'A' if ship_type in self._CLASS_A_TYPES else 'B'

        if z_type == 'port':
            speed = round(random.uniform(0.0, 0.3), 1)
            nav_status = random.choice([1, 1, 5])   # chủ yếu neo/cập bến
            heading = 511
        elif z_type == 'sea':
            speed = round(random.uniform(8.0, 18.0), 1)
            nav_status = 0
            heading = random.randint(0, 359)
        else:  # river
            speed = round(random.uniform(2.0, 8.0), 1)
            nav_status = 0
            heading = random.randint(0, 359)

        cog = round(random.uniform(0, 360), 1)

        # MMSI: cảng/sông → Việt Nam (574); biển → đa quốc gia
        if z_type == 'sea':
            mid_pool = [574, 574, 574, 413, 431, 440, 563, 533, 338]
            mid = random.choice(mid_pool)
        else:
            mid = 574

        return {
            'lat': round(lat, 6), 'lon': round(lon, 6),
            'speed': speed, 'cog': cog, 'heading': heading,
            'nav_status': nav_status, 'ship_type': ship_type,
            'ais_class': ais_class, 'mid': mid, 'zone_type': z_type,
        }
