"""Turn Parts into cut-ready shapes and nest them onto sheets.

`fabricate` applies kerf compensation and adds label strokes.
`nest` does a simple shelf packing (rotate each part to its minimum-area
bounding rectangle, sort by height, fill rows). Good enough for small
puzzles; swap in a smarter nester later without touching generators.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from shapely import affinity
from shapely.geometry import LineString, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polylabel

from . import font
from .design import Part
from .geometry import as_polygons, kerf_offset, largest


@dataclass
class FabPart:
    name: str
    cut: BaseGeometry                    # kerf-compensated outline
    engrave: list[LineString]
    group: str
    copy: int = 0


@dataclass
class Placed:
    part: FabPart
    cut: BaseGeometry                    # in sheet coordinates
    engrave: list[LineString]


@dataclass
class Sheet:
    index: int
    width: float
    height: float
    items: list[Placed] = field(default_factory=list)

    def used_area(self) -> float:
        return sum(p.cut.area for p in self.items)


def label_lines(outline: BaseGeometry, text: str, max_height: float = 3.0) -> list[LineString]:
    """Place `text` inside the largest polygon of `outline`, shrinking to fit."""
    poly = largest(outline)
    if poly.is_empty:
        return []
    try:
        c = polylabel(poly, tolerance=0.2)
    except Exception:  # pragma: no cover
        c = poly.representative_point()
    for h in (max_height, 2.5, 2.0, 1.6, 1.2):
        w = font.text_width(text, h)
        for angle in (0, 90):
            bw, bh = (w, h) if angle == 0 else (h, w)
            bb = box(c.x - bw / 2 - 0.4, c.y - bh / 2 - 0.4, c.x + bw / 2 + 0.4, c.y + bh / 2 + 0.4)
            if poly.contains(bb):
                return font.text_lines(text, h, c.x, c.y, angle)
    return []


def fabricate(part: Part, kerf: float, labels: bool) -> list[FabPart]:
    engrave = list(part.engrave)
    if labels and part.label:
        engrave += label_lines(part.outline, part.label)
    cut = kerf_offset(part.outline, kerf)
    return [FabPart(part.name, cut, engrave, part.group, copy=i) for i in range(part.quantity)]


def _orient(fp: FabPart) -> tuple[float, BaseGeometry, list[LineString]]:
    """Rotate so the min-area rectangle is axis aligned, long side horizontal."""
    mrr = fp.cut.minimum_rotated_rectangle
    angle = 0.0
    coords = list(mrr.exterior.coords) if hasattr(mrr, "exterior") else []
    if len(coords) >= 4:
        (x0, y0), (x1, y1), (x2, y2) = coords[0], coords[1], coords[2]
        e1 = math.hypot(x1 - x0, y1 - y0)
        e2 = math.hypot(x2 - x1, y2 - y1)
        if e1 >= e2:
            angle = -math.degrees(math.atan2(y1 - y0, x1 - x0))
        else:
            angle = -math.degrees(math.atan2(y2 - y1, x2 - x1))
    cut = affinity.rotate(fp.cut, angle, origin=(0, 0))
    eng = [affinity.rotate(l, angle, origin=(0, 0)) for l in fp.engrave]
    minx, miny, _, _ = cut.bounds
    cut = affinity.translate(cut, -minx, -miny)
    eng = [affinity.translate(l, -minx, -miny) for l in eng]
    return angle, cut, eng


def nest(fparts: list[FabPart], width: float, height: float, spacing: float, margin: float = 5.0):
    """Shelf-pack parts onto as many sheets as needed. Returns (sheets, warnings)."""
    warnings: list[str] = []
    oriented = []
    for fp in fparts:
        _, cut, eng = _orient(fp)
        _, _, w, h = cut.bounds
        if (w > width - 2 * margin or h > height - 2 * margin) and (h <= width - 2 * margin and w <= height - 2 * margin):
            cut = affinity.rotate(cut, 90, origin=(0, 0))
            eng = [affinity.rotate(l, 90, origin=(0, 0)) for l in eng]
            minx, miny, _, _ = cut.bounds
            cut = affinity.translate(cut, -minx, -miny)
            eng = [affinity.translate(l, -minx, -miny) for l in eng]
            _, _, w, h = cut.bounds
        if w > width - 2 * margin or h > height - 2 * margin:
            warnings.append(f"{fp.name} ({w:.0f}x{h:.0f} mm) does not fit on a {width:.0f}x{height:.0f} sheet")
        oriented.append((fp, cut, eng, w, h))
    oriented.sort(key=lambda t: (-t[4], -t[3]))

    sheets: list[Sheet] = []
    cur: Sheet | None = None
    x = y = shelf_h = 0.0
    for fp, cut, eng, w, h in oriented:
        if cur is None:
            cur = Sheet(len(sheets), width, height)
            sheets.append(cur)
            x, y, shelf_h = margin, margin, 0.0
        if x + w > width - margin and x > margin:          # next shelf
            x, y = margin, y + shelf_h + spacing
            shelf_h = 0.0
        if y + h > height - margin and y > margin:         # next sheet
            cur = Sheet(len(sheets), width, height)
            sheets.append(cur)
            x, y, shelf_h = margin, margin, 0.0
        yy = height - y - h  # fill from the top-left corner (sheet y axis points up)
        cur.items.append(Placed(fp, affinity.translate(cut, x, yy), [affinity.translate(l, x, yy) for l in eng]))
        x += w + spacing
        shelf_h = max(shelf_h, h)
    return sheets, warnings


def total_cut_length(sheets: list[Sheet]) -> float:
    total = 0.0
    for s in sheets:
        for it in s.items:
            for p in as_polygons(it.cut):
                total += p.length
    return total
