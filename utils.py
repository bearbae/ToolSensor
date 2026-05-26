"""Utility functions for NMEA sentence formatting and checksum calculation."""


def nmea_checksum(sentence: str) -> str:
    """XOR all characters in sentence (between $ or ! and *) and return 2-char hex."""
    checksum = 0
    for char in sentence:
        checksum ^= ord(char)
    return f"{checksum:02X}"


def format_nmea_lat(lat: float) -> tuple:
    """Convert decimal degrees latitude to NMEA format (DDMM.MMMM, N/S)."""
    direction = 'N' if lat >= 0 else 'S'
    lat = abs(lat)
    degrees = int(lat)
    minutes = (lat - degrees) * 60.0
    return f"{degrees:02d}{minutes:07.4f}", direction


def format_nmea_lon(lon: float) -> tuple:
    """Convert decimal degrees longitude to NMEA format (DDDMM.MMMM, E/W)."""
    direction = 'E' if lon >= 0 else 'W'
    lon = abs(lon)
    degrees = int(lon)
    minutes = (lon - degrees) * 60.0
    return f"{degrees:03d}{minutes:07.4f}", direction
