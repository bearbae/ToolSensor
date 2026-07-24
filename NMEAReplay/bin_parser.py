"""Parser for .bin log files captured from real maritime equipment.

Line format:
    2026-07-19T14:21:14.564: [TYPE] NMEA_SENTENCE
"""

import re
from datetime import datetime

_LINE_RE = re.compile(r'^(\d{4}-\d{2}-\d{2}T[\d:.]+):\s+\[(\w+)\]\s+(.+)$')


def parse_log_file(filepath: str) -> list[tuple]:
    """Parse a single .bin log file.

    Returns a list of (datetime, type_tag, sentence) tuples.
    Lines tagged [UNKNOWN] or lines that fail to parse are skipped.
    """
    records = []
    with open(filepath, 'r', encoding='utf-8', errors='replace') as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            m = _LINE_RE.match(line)
            if not m:
                continue
            ts_str, type_tag, sentence = m.groups()
            if type_tag == 'UNKNOWN':
                continue
            try:
                ts = datetime.fromisoformat(ts_str)
            except ValueError:
                continue
            records.append((ts, type_tag, sentence.strip()))
    return records


def merge_logs(*record_lists) -> list[tuple]:
    """Merge multiple parsed record lists and sort by timestamp."""
    merged = []
    for records in record_lists:
        merged.extend(records)
    merged.sort(key=lambda r: r[0])
    return merged


def count_by_type(records: list[tuple]) -> dict[str, int]:
    """Return a dict mapping type_tag → count."""
    counts: dict[str, int] = {}
    for _, tag, _ in records:
        counts[tag] = counts.get(tag, 0) + 1
    return counts
