"""Writers for cut files.

Colour / layer convention. Laser software maps colours to operations, and
shops publish their own colour rules, so both colours are parameters
(`cut_color`, `engrave_color`). Defaults are the common choice:
  * CUT     - red   (#ff0000), hairline stroke
  * ENGRAVE - blue  (#0000ff), hairline stroke (score/line engrave)
DXF keeps the CUT / ENGRAVE layer names and sets their colour (true colour,
plus the matching AutoCAD index colour when there is one).
SVG units are millimetres (width="600mm" + viewBox in mm).
SVG y axis points down, so y is flipped on export (y -> H - y). That keeps
parts looking as they do from above (+Z) in local coordinates, so engraved
text reads correctly and engravings land on the part's top face.
"""

from __future__ import annotations

import io
from xml.sax.saxutils import escape

import ezdxf

from .geometry import as_lines, as_polygons
from .layout import Sheet

CUT_COLOR = "#ff0000"
ENGRAVE_COLOR = "#0000ff"
STROKE = 0.1

# AutoCAD index colours with an exact RGB; anything else falls back to 7 (white/black) + true colour.
_ACI = {(255, 0, 0): 1, (255, 255, 0): 2, (0, 255, 0): 3, (0, 255, 255): 4, (0, 0, 255): 5, (255, 0, 255): 6}


def _rgb(color: str) -> tuple[int, int, int]:
    h = color.lstrip("#")
    return int(h[0:2], 16), int(h[2:4], 16), int(h[4:6], 16)


def _ring_d(coords, H: float) -> str:
    pts = list(coords)
    if not pts:
        return ""
    s = f"M{pts[0][0]:.3f},{H - pts[0][1]:.3f}"
    s += "".join(f"L{x:.3f},{H - y:.3f}" for x, y in pts[1:])
    return s + "Z"


def _line_d(coords, H: float) -> str:
    pts = list(coords)
    s = f"M{pts[0][0]:.3f},{H - pts[0][1]:.3f}"
    return s + "".join(f"L{x:.3f},{H - y:.3f}" for x, y in pts[1:])


def sheet_svg(sheet: Sheet, show_sheet: bool = False,
              cut_color: str = CUT_COLOR, engrave_color: str = ENGRAVE_COLOR) -> str:
    W, H = sheet.width, sheet.height
    out = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" height="{H}mm" viewBox="0 0 {W} {H}">',
    ]
    if show_sheet:
        out.append(f'<rect class="sheet" x="0" y="0" width="{W}" height="{H}" fill="none" stroke="#999" stroke-width="0.3" stroke-dasharray="4 2"/>')
    out.append(f'<g id="engrave" fill="none" stroke="{escape(engrave_color)}" stroke-width="{STROKE}">')
    for it in sheet.items:
        for l in it.engrave:
            out.append(f'<path d="{_line_d(l.coords, H)}"/>')
    out.append("</g>")
    out.append(f'<g id="cut" fill="none" stroke="{escape(cut_color)}" stroke-width="{STROKE}">')
    for it in sheet.items:
        # holes first so inner features are cut before the part drops out
        ds = []
        for p in as_polygons(it.cut):
            ds += [_ring_d(i.coords, H) for i in p.interiors]
        for p in as_polygons(it.cut):
            ds.append(_ring_d(p.exterior.coords, H))
        title = escape(it.part.name)
        out.append(f'<path data-part="{title}" d="{" ".join(ds)}"><title>{title}</title></path>')
    out.append("</g>")
    out.append("</svg>")
    return "\n".join(out)


def sheet_dxf(sheet: Sheet, cut_color: str = CUT_COLOR, engrave_color: str = ENGRAVE_COLOR) -> bytes:
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for name, color in (("CUT", cut_color), ("ENGRAVE", engrave_color)):
        rgb = _rgb(color)
        doc.layers.add(name, color=_ACI.get(rgb, 7), true_color=ezdxf.colors.rgb2int(rgb))
    msp = doc.modelspace()
    for it in sheet.items:
        for l in it.engrave:
            msp.add_lwpolyline(list(l.coords), dxfattribs={"layer": "ENGRAVE"})
        for p in as_polygons(it.cut):
            for ring in list(p.interiors) + [p.exterior]:
                msp.add_lwpolyline(list(ring.coords)[:-1], close=True, dxfattribs={"layer": "CUT"})
    buf = io.StringIO()
    doc.write(buf)
    return buf.getvalue().encode("utf-8")
