"""Joint library: functions that modify two placed Parts so they interlock.

Every joint works from the parts' 3D transforms, so callers only position the
plates where they belong in the finished object and say which edge/plate
meets which. Outlines are changed in place (nominal geometry, no kerf);
`v.clearance` is the caller's to pass in.

At clearance 0 every joint here produces zero 3D overlap - `validate.collisions`
must stay empty.

tab_slot   An edge of one plate butts against the face of another. The edge
           grows tabs that pass through the face plate; the face plate gets
           matching slots. Works for any angle between the plates as long as
           the edge is not parallel to the face.
cross_lap  Two perpendicular plates cross each other (egg-crate / half-lap).
           Each gets a slot to the middle of the overlap from opposite ends.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import MultiPoint, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .design import Part
from .geometry import BIG, as_polygons, clean

EPS = 1e-6


@dataclass
class Joint:
    """What a joint did: cut-outs per part (local coords) and any problems."""

    kind: str
    added: dict[str, list[Polygon]] = field(default_factory=dict)    # part name -> material added (tabs)
    removed: dict[str, list[Polygon]] = field(default_factory=dict)  # part name -> material removed (slots)
    warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------- transforms
def _apply(m: np.ndarray, pts) -> np.ndarray:
    p = np.atleast_2d(np.asarray(pts, float))
    return p @ m[:3, :3].T + m[:3, 3]


def to_world(part: Part, pts) -> np.ndarray:
    """Part-local (x, y, z) points -> world."""
    return _apply(part.transform, pts)


def to_local(part: Part, pts) -> np.ndarray:
    """World points -> part-local (x, y, z)."""
    return _apply(np.linalg.inv(part.transform), pts)


def _normal(part: Part) -> np.ndarray:
    n = part.transform[:3, 2]
    return n / np.linalg.norm(n)


# ------------------------------------------------------------------- tab_slot
def tab_positions(length: float, n: int, width: float, margin: float) -> list[tuple[float, float]]:
    """Evenly spaced (start, end) intervals of `n` tabs along an edge of `length`."""
    usable = length - 2 * margin
    if n < 1 or usable <= 0:
        return []
    out = []
    for i in range(n):
        c = margin + usable * (i + 0.5) / n
        out.append((c - width / 2, c + width / 2))
    return out


def _box_slab_projection(corners: np.ndarray, t: float) -> Polygon:
    """Project the part of a box (8 corners, local coords of a plate) lying inside z in [0, t] onto XY.

    Corners are ordered as produced by `_tab_box`: index bits (i_along, i_out, i_z).
    """
    pts = [c[:2] for c in corners if -EPS <= c[2] <= t + EPS]
    for i in range(8):
        for bit in (1, 2, 4):
            j = i | bit
            if j == i:
                continue
            a, b = corners[i], corners[j]
            dz = b[2] - a[2]
            if abs(dz) < EPS:
                continue
            for z in (0.0, t):
                s = (z - a[2]) / dz
                if 0 < s < 1:
                    pts.append((a + s * (b - a))[:2])
    if len(pts) < 3:
        return Polygon()
    hull = MultiPoint([tuple(p) for p in pts]).convex_hull
    return hull if isinstance(hull, Polygon) else Polygon()


def tab_slot(
    edge_part: Part,
    face_part: Part,
    edge: tuple[tuple[float, float], tuple[float, float]],
    clearance: float = 0.0,
    n_tabs: int | None = None,
    tab_width: float | None = None,
    margin: float | None = None,
    protrude: float = 0.0,
    min_bridge: float | None = None,
) -> Joint:
    """Join `edge_part`'s straight edge to the face of `face_part` with tabs and slots.

    edge        Two points (local XY of `edge_part`) on the edge that touches the face.
                The tabs grow outward, away from the part's material.
    clearance   Added to the slot size in both directions (negative = press fit).
    n_tabs      Number of tabs; default from edge length (about one per 2.5 tab widths).
    tab_width   Default 3 x edge_part thickness.
    margin      Plain edge left at each end; default = face thickness.
    protrude    Extra tab length sticking out beyond the far face (0 = flush).
    min_bridge  Material the face plate should keep around each slot (default half its thickness);
                a warning is raised if a slot gets closer to the face outline.
    """
    te, tf = edge_part.thickness, face_part.thickness
    tab_width = 3 * te if tab_width is None else tab_width
    margin = tf if margin is None else margin
    min_bridge = tf / 2 if min_bridge is None else min_bridge
    j = Joint("tab_slot")

    p0, p1 = np.asarray(edge[0], float), np.asarray(edge[1], float)
    L = float(np.linalg.norm(p1 - p0))
    if L < EPS:
        raise ValueError(f"tab_slot {edge_part.name}: edge has zero length")
    along = (p1 - p0) / L
    out = np.array([along[1], -along[0]])           # right-hand normal; flip to point away from material
    mid = (p0 + p1) / 2
    probe = min(0.5, L / 4)
    if edge_part.outline.contains(Point(*(mid + out * probe))):
        out = -out
    if not edge_part.outline.buffer(1e-3).contains(Point(*(mid - out * probe))):
        j.warnings.append(f"{edge_part.name}: joint edge to {face_part.name} is not on the part's outline.")

    # How far the tab must reach: from the edge, through the whole face plate.
    o_world = to_world(edge_part, [[*out, 0.0]])[0] - to_world(edge_part, [[0.0, 0.0, 0.0]])[0]
    cos = float(np.dot(o_world, _normal(face_part)))
    if abs(cos) < 1e-3:
        raise ValueError(f"tab_slot {edge_part.name}->{face_part.name}: edge is parallel to the face")
    z_edge = float(to_local(face_part, to_world(edge_part, [[*mid, te / 2]]))[0][2])
    near, far = (0.0, tf) if cos > 0 else (tf, 0.0)
    gap = (near - z_edge) / cos
    depth = (far - z_edge) / cos + protrude
    if abs(gap) > 0.01:
        j.warnings.append(f"{edge_part.name}: edge is {gap:+.2f} mm from {face_part.name}'s face (should touch).")
    if depth <= EPS:
        raise ValueError(f"tab_slot {edge_part.name}->{face_part.name}: face plate is behind the edge")

    if n_tabs is None:
        n_tabs = max(1, round((L - 2 * margin) / (2.5 * tab_width)))
    spans = tab_positions(L, n_tabs, tab_width, margin)
    if not spans:
        j.warnings.append(f"{edge_part.name}: edge to {face_part.name} is too short for tabs ({L:.1f} mm).")
        return j

    tabs, slots = [], []
    face_outline = face_part.outline
    for a, b in spans:
        # Tab in edge-part local XY; starts 0.5 mm inside so the union is clean.
        q = [p0 + along * a - out * 0.5, p0 + along * b - out * 0.5,
             p0 + along * b + out * depth, p0 + along * a + out * depth]
        tabs.append(Polygon([tuple(x) for x in q]))
        # Slot = shadow of the tab solid inside the face slab, in face-local XY.
        corners = []
        for i in range(8):
            s = b if i & 1 else a
            o = depth if i & 2 else 0.0
            z = te if i & 4 else 0.0
            xy = p0 + along * s + out * o
            corners.append([xy[0], xy[1], z])
        loc = to_local(face_part, to_world(edge_part, corners))
        slot = _box_slab_projection(loc, tf)
        if slot.is_empty:
            j.warnings.append(f"{edge_part.name}: a tab misses {face_part.name}.")
            continue
        if clearance:
            slot = slot.buffer(clearance / 2, join_style="mitre", mitre_limit=3.0)
        if not face_outline.buffer(1e-6).contains(slot.buffer(min_bridge, join_style="mitre")):
            j.warnings.append(
                f"{face_part.name}: slot for {edge_part.name} is closer than {min_bridge:.1f} mm to the edge - weak.")
        slots.append(slot)

    edge_part.outline = clean(unary_union([edge_part.outline, *tabs]))
    if slots:
        for s in slots:
            face_part.outline = face_part.outline.difference(s)
        face_part.outline = clean(face_part.outline)
    if len(as_polygons(face_part.outline)) > 1:
        j.warnings.append(f"{face_part.name}: slots for {edge_part.name} split the part in pieces.")
    j.added[edge_part.name] = tabs
    j.removed[face_part.name] = slots
    return j


# ------------------------------------------------------------------ cross_lap
def _linear_in_local(part: Part, f) -> tuple[np.ndarray, float]:
    """Express a world-linear function f(p) (given as (g, h) with f = g.p + h) in the part's mid-plane XY."""
    g, h = f
    m = part.transform
    z = part.thickness / 2
    gl = np.array([g @ m[:3, 0], g @ m[:3, 1]])
    hl = float(g @ (m[:3, 3] + m[:3, 2] * z) + h)
    return gl, hl


def _halfplane(gl: np.ndarray, hl: float, lo: float | None, hi: float | None) -> BaseGeometry:
    """Region of local XY where lo <= gl.xy + hl <= hi (either bound may be None)."""
    n = np.linalg.norm(gl)
    u = gl / n
    v = np.array([-u[1], u[0]])
    a = -BIG if lo is None else (lo - hl) / n
    b = BIG if hi is None else (hi - hl) / n
    pts = [u * a - v * BIG, u * b - v * BIG, u * b + v * BIG, u * a + v * BIG]
    return Polygon([tuple(p) for p in pts])


def _interval(geom: BaseGeometry, gl: np.ndarray, hl: float) -> tuple[float, float] | None:
    polys = as_polygons(geom)
    if not polys:
        return None
    vals = [float(gl @ np.asarray(c) + hl) for p in polys for c in p.exterior.coords]
    return min(vals), max(vals)


def cross_lap(a: Part, b: Part, clearance: float = 0.0, a_from: str = "low") -> Joint:
    """Interlock two perpendicular plates that pass through each other.

    Along their line of intersection, `a` is slotted from the `a_from` end
    ("low"/"high" along d = n_a x n_b) to the middle of the overlap and `b`
    from the other end; slot width = other plate's thickness + clearance.
    """
    j = Joint("cross_lap")
    na, nb = _normal(a), _normal(b)
    if abs(float(na @ nb)) > 1e-6:
        raise ValueError(f"cross_lap {a.name}/{b.name}: plates must be perpendicular")
    d = np.cross(na, nb)
    d /= np.linalg.norm(d)

    def mid_plane(p: Part):   # signed distance to the plate's mid-plane: n.x - n.o
        n = _normal(p)
        o = p.transform[:3, 3] + n * p.thickness / 2
        return n, -float(n @ o)

    line = (d, 0.0)
    ga, ha = _linear_in_local(a, mid_plane(b))
    gb, hb = _linear_in_local(b, mid_plane(a))
    ua, uha = _linear_in_local(a, line)
    ub, uhb = _linear_in_local(b, line)
    wa = (b.thickness + clearance) / 2              # half slot width cut in a
    wb = (a.thickness + clearance) / 2
    strip_a = _halfplane(ga, ha, -b.thickness / 2, b.thickness / 2)
    strip_b = _halfplane(gb, hb, -a.thickness / 2, a.thickness / 2)
    ia = _interval(a.outline.intersection(strip_a), ua, uha)
    ib = _interval(b.outline.intersection(strip_b), ub, uhb)
    if ia is None or ib is None:
        raise ValueError(f"cross_lap {a.name}/{b.name}: plates do not cross")
    lo, hi = max(ia[0], ib[0]), min(ia[1], ib[1])
    if hi - lo < EPS:
        raise ValueError(f"cross_lap {a.name}/{b.name}: plates do not overlap")
    mid = (lo + hi) / 2
    c2 = clearance / 2
    if a_from == "low":
        slot_a = _halfplane(ga, ha, -wa, wa).intersection(_halfplane(ua, uha, None, mid + c2))
        slot_b = _halfplane(gb, hb, -wb, wb).intersection(_halfplane(ub, uhb, mid - c2, None))
    elif a_from == "high":
        slot_a = _halfplane(ga, ha, -wa, wa).intersection(_halfplane(ua, uha, mid - c2, None))
        slot_b = _halfplane(gb, hb, -wb, wb).intersection(_halfplane(ub, uhb, None, mid + c2))
    else:
        raise ValueError("a_from must be 'low' or 'high'")
    slot_a = slot_a.intersection(a.outline.envelope.buffer(1.0))
    slot_b = slot_b.intersection(b.outline.envelope.buffer(1.0))
    a.outline = clean(a.outline.difference(slot_a))
    b.outline = clean(b.outline.difference(slot_b))
    for p in (a, b):
        if len(as_polygons(p.outline)) > 1:
            j.warnings.append(f"{p.name}: cross-lap slot splits the part in pieces.")
    if hi - lo < 2 * max(a.thickness, b.thickness):
        j.warnings.append(f"{a.name}/{b.name}: overlap is only {hi - lo:.1f} mm - weak joint.")
    j.removed = {a.name: as_polygons(slot_a), b.name: as_polygons(slot_b)}
    return j
