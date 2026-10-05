"""Minimal single-stroke vector font for engraving labels.

Laser software handles SVG <text> inconsistently, so labels are emitted as
plain polylines. Glyphs live on a 4 (wide) x 6 (tall) grid; unknown
characters render as blanks.
"""

from __future__ import annotations

from shapely.geometry import LineString

G = {
    "0": [[(0.6, 0), (3.4, 0), (3.4, 6), (0.6, 6), (0.6, 0)]],  # narrower than O
    "1": [[(1, 5), (2, 6), (2, 0)], [(1, 0), (3, 0)]],
    "2": [[(0, 6), (4, 6), (4, 3), (0, 3), (0, 0), (4, 0)]],
    "3": [[(0, 6), (4, 6), (4, 0), (0, 0)], [(1, 3), (4, 3)]],
    "4": [[(0, 6), (0, 3), (4, 3)], [(3, 6), (3, 0)]],
    "5": [[(4, 6), (0, 6), (0, 3), (4, 3), (4, 0), (0, 0)]],
    "6": [[(4, 6), (0, 6), (0, 0), (4, 0), (4, 3), (0, 3)]],
    "7": [[(0, 6), (4, 6), (1, 0)]],
    "8": [[(0, 0), (4, 0), (4, 6), (0, 6), (0, 0)], [(0, 3), (4, 3)]],
    "9": [[(4, 3), (0, 3), (0, 6), (4, 6), (4, 0), (0, 0)]],
    "A": [[(0, 0), (0, 4), (2, 6), (4, 4), (4, 0)], [(0, 3), (4, 3)]],
    "B": [[(0, 0), (0, 6), (3, 6), (4, 5), (4, 4), (3, 3), (0, 3)], [(3, 3), (4, 2), (4, 1), (3, 0), (0, 0)]],
    "C": [[(4, 6), (0, 6), (0, 0), (4, 0)]],
    "D": [[(0, 0), (0, 6), (2, 6), (4, 4), (4, 2), (2, 0), (0, 0)]],
    "E": [[(4, 6), (0, 6), (0, 0), (4, 0)], [(0, 3), (3, 3)]],
    "F": [[(4, 6), (0, 6), (0, 0)], [(0, 3), (3, 3)]],
    "G": [[(4, 6), (0, 6), (0, 0), (4, 0), (4, 3), (2, 3)]],
    "H": [[(0, 0), (0, 6)], [(4, 0), (4, 6)], [(0, 3), (4, 3)]],
    "I": [[(1, 6), (3, 6)], [(2, 6), (2, 0)], [(1, 0), (3, 0)]],
    "J": [[(4, 6), (4, 0), (0, 0), (0, 2)]],
    "K": [[(0, 0), (0, 6)], [(4, 6), (0, 3), (4, 0)]],
    "L": [[(0, 6), (0, 0), (4, 0)]],
    "M": [[(0, 0), (0, 6), (2, 3), (4, 6), (4, 0)]],
    "N": [[(0, 0), (0, 6), (4, 0), (4, 6)]],
    "O": [[(0, 0), (4, 0), (4, 6), (0, 6), (0, 0)]],
    "P": [[(0, 0), (0, 6), (4, 6), (4, 3), (0, 3)]],
    "Q": [[(0, 0), (4, 0), (4, 6), (0, 6), (0, 0)], [(2, 2), (4, -1)]],
    "R": [[(0, 0), (0, 6), (4, 6), (4, 3), (0, 3), (4, 0)]],
    "S": [[(4, 6), (0, 6), (0, 3), (4, 3), (4, 0), (0, 0)]],
    "T": [[(0, 6), (4, 6)], [(2, 6), (2, 0)]],
    "U": [[(0, 6), (0, 0), (4, 0), (4, 6)]],
    "V": [[(0, 6), (2, 0), (4, 6)]],
    "W": [[(0, 6), (1, 0), (2, 3), (3, 0), (4, 6)]],
    "X": [[(0, 0), (4, 6)], [(0, 6), (4, 0)]],
    "Y": [[(0, 6), (2, 3), (4, 6)], [(2, 3), (2, 0)]],
    "Z": [[(0, 6), (4, 6), (0, 0), (4, 0)]],
    "-": [[(1, 3), (3, 3)]],
    ".": [[(2, 0), (2, 0.6)]],
    "/": [[(0, 0), (4, 6)]],
    "+": [[(0, 3), (4, 3)], [(2, 1), (2, 5)]],
    " ": [],
}

ADVANCE = 6.0  # grid units per character (4 glyph + 2 spacing)


def text_lines(text: str, height: float, cx: float = 0.0, cy: float = 0.0, angle: float = 0.0) -> list[LineString]:
    """Polylines for `text`, cap-height `height` mm, centred on (cx, cy)."""
    import math

    s = height / 6.0
    text = text.upper()
    width = (len(text) * ADVANCE - 2) * s
    ox, oy = -width / 2.0, -height / 2.0
    ca, sa = math.cos(math.radians(angle)), math.sin(math.radians(angle))
    out: list[LineString] = []
    for i, ch in enumerate(text):
        for stroke in G.get(ch, []):
            pts = []
            for gx, gy in stroke:
                x = ox + (i * ADVANCE + gx) * s
                y = oy + gy * s
                pts.append((cx + x * ca - y * sa, cy + x * sa + y * ca))
            if len(pts) == 2 and pts[0] == pts[1]:
                pts[1] = (pts[1][0] + 1e-3, pts[1][1])
            out.append(LineString(pts))
    return out


def text_width(text: str, height: float) -> float:
    return (len(text) * ADVANCE - 2) * height / 6.0
