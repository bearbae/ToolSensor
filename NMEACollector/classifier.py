"""Classify NMEA sentence → type tag (e.g. 'RMC', 'VDM', 'TTM')."""

import re

_RE = re.compile(r'^[$!]([A-Z]{2,6}),')


def classify(sentence: str) -> str:
    """Return 3-char type tag from the sentence identifier's last 3 chars."""
    m = _RE.match(sentence.strip())
    if not m:
        return 'UNKNOWN'
    ident = m.group(1)       # e.g. 'GPRMC', 'AIVDM', 'RATTM'
    return ident[-3:]        # 'RMC', 'VDM', 'TTM'
