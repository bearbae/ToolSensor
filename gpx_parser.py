"""Parse GPX files and return a list of (lat, lon) waypoints."""

import xml.etree.ElementTree as ET

_NS = {'gpx': 'http://www.topografix.com/GPX/1/1'}


def parse_gpx(path: str) -> list:
    """Return [(lat, lon), ...] from <rtept> or <trkpt> elements."""
    tree = ET.parse(path)
    root = tree.getroot()

    points = []

    # Route points (<rte><rtept>)
    for pt in root.findall('.//gpx:rtept', _NS):
        points.append((float(pt.get('lat')), float(pt.get('lon'))))

    # Track points (<trk><trkseg><trkpt>) — fallback
    if not points:
        for pt in root.findall('.//gpx:trkpt', _NS):
            points.append((float(pt.get('lat')), float(pt.get('lon'))))

    # Fallback: no namespace (some GPX exporters omit it)
    if not points:
        for pt in root.iter():
            if pt.tag.endswith(('rtept', 'trkpt')):
                try:
                    points.append((float(pt.get('lat')), float(pt.get('lon'))))
                except (TypeError, ValueError):
                    pass

    return points
