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
           Each gets a slot to the middle of the overlap from opposite ends,
           once per separate overlap span.
finger_joint
           Two plates meet along an edge (box corner, any angle) or one plate's
           edge meets the other's face (T joint): the shared volume is split
           into alternating fingers.
pin_joint  A round pin (dowel, rod, bolt) through a stack of plates: holes with
           per-part fit, the pin as Hardware, optional spacer washers. Pair it
           with a `design.Pivot` to let the parts turn.
living_hinge
           Rows of staggered slits (open cut lines in `Part.cuts`) that make a
           region of the plate bendable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from shapely.geometry import LineString, MultiPoint, Point, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.ops import unary_union

from .design import Hardware, Part, plane_transform
from .geometry import BIG, as_lines, as_polygons, clean

EPS = 1e-6


@dataclass
class Joint:
    """What a joint did: cut-outs per part (local coords) and any problems."""

    kind: str
    added: dict[str, list[Polygon]] = field(default_factory=dict)    # part name -> material added (tabs)
    removed: dict[str, list[Polygon]] = field(default_factory=dict)  # part name -> material removed (slots)
    warnings: list[str] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)          # new parts the caller adds to the Design (washers)
    hardware: list[Hardware] = field(default_factory=list)   # new hardware the caller adds (pins)
    info: dict = field(default_factory=dict)                 # joint-specific numbers (finger count, bend length, ...)


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
    spans = _intervals(geom, gl, hl)
    return (spans[0][0], spans[-1][1]) if spans else None


def _intervals(geom: BaseGeometry, gl: np.ndarray, hl: float) -> list[tuple[float, float]]:
    """Merged, sorted ranges of the linear function gl.xy + hl over each polygon of `geom`."""
    raw = []
    for p in as_polygons(geom):
        vals = [float(gl @ np.asarray(c) + hl) for c in p.exterior.coords]
        raw.append((min(vals), max(vals)))
    raw.sort()
    out: list[list[float]] = []
    for a, b in raw:
        if out and a <= out[-1][1] + EPS:
            out[-1][1] = max(out[-1][1], b)
        else:
            out.append([a, b])
    return [(a, b) for a, b in out]


def cross_lap(a: Part, b: Part, clearance: float = 0.0, a_from: str = "low", spans: str = "auto") -> Joint:
    """Interlock two perpendicular plates that pass through each other.

    Along their line of intersection, `a` is slotted from the `a_from` end
    ("low"/"high" along d = n_a x n_b) to the middle of the overlap and `b`
    from the other end; slot width = other plate's thickness + clearance.

    spans  Where the plates overlap in several separate places (a slice through two
           legs): "each" joins every span on its own (each slot starts at the edge of that
           plate's own material run and stops at the middle of its span); "combined" treats
           everything as one span (one slot to the overall middle), which cuts away whole
           spans on one plate; "auto" (default) uses "each" unless "combined" leaves fewer
           pieces. With a single span all three are the same.
    """
    if spans not in ("auto", "each", "combined"):
        raise ValueError("spans must be 'auto', 'each' or 'combined'")
    if a_from not in ("low", "high"):
        raise ValueError("a_from must be 'low' or 'high'")
    na, nb = _normal(a), _normal(b)
    if abs(float(na @ nb)) > 1e-6:
        raise ValueError(f"cross_lap {a.name}/{b.name}: plates must be perpendicular")
    if spans == "auto":
        pieces = {}
        for mode in ("each", "combined"):
            sa, sb, _ = _cross_lap_slots(a, b, clearance, a_from, mode)
            pieces[mode] = len(as_polygons(clean(a.outline.difference(sa)))) + \
                len(as_polygons(clean(b.outline.difference(sb))))
        spans = "combined" if pieces["combined"] < pieces["each"] else "each"
    slot_a, slot_b, overlaps = _cross_lap_slots(a, b, clearance, a_from, spans)
    j = Joint("cross_lap")
    for lo, hi in overlaps:
        if hi - lo < 2 * max(a.thickness, b.thickness):
            j.warnings.append(f"{a.name}/{b.name}: overlap is only {hi - lo:.1f} mm - weak joint.")
    a.outline = clean(a.outline.difference(slot_a))
    b.outline = clean(b.outline.difference(slot_b))
    for p in (a, b):
        if len(as_polygons(p.outline)) > 1:
            j.warnings.append(f"{p.name}: cross-lap slot splits the part in pieces.")
    j.removed = {a.name: as_polygons(slot_a), b.name: as_polygons(slot_b)}
    j.info = {"spans": [(round(lo, 3), round(hi, 3)) for lo, hi in overlaps], "mode": spans}
    return j


def _cross_lap_slots(a: Part, b: Part, clearance: float, a_from: str, spans: str):
    """Slots (local XY of a and of b) and overlap spans of a cross_lap in mode "each"/"combined"."""
    na, nb = _normal(a), _normal(b)
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
    runs_a = _intervals(a.outline.intersection(strip_a), ua, uha)
    runs_b = _intervals(b.outline.intersection(strip_b), ub, uhb)
    if not runs_a or not runs_b:
        raise ValueError(f"cross_lap {a.name}/{b.name}: plates do not cross")
    if spans == "combined":
        runs_a = [(runs_a[0][0], runs_a[-1][1])]
        runs_b = [(runs_b[0][0], runs_b[-1][1])]
    overlaps = []                                    # (lo, hi, run of a, run of b)
    for ra in runs_a:
        for rb in runs_b:
            lo, hi = max(ra[0], rb[0]), min(ra[1], rb[1])
            if hi - lo > EPS:
                overlaps.append((lo, hi, ra, rb))
    if not overlaps:
        raise ValueError(f"cross_lap {a.name}/{b.name}: plates do not overlap")

    c2 = clearance / 2
    cut_a, cut_b = [], []
    for lo, hi, ra, rb in overlaps:
        mid = (lo + hi) / 2
        # A slot reaches from the plate's own edge (end of its material run) to the middle.
        if spans == "combined":
            ra_lo = ra_hi = rb_lo = rb_hi = None
        else:
            ra_lo, ra_hi, rb_lo, rb_hi = ra[0] - 1.0, ra[1] + 1.0, rb[0] - 1.0, rb[1] + 1.0
        if a_from == "low":
            cut_a.append(_halfplane(ga, ha, -wa, wa).intersection(_halfplane(ua, uha, ra_lo, mid + c2)))
            cut_b.append(_halfplane(gb, hb, -wb, wb).intersection(_halfplane(ub, uhb, mid - c2, rb_hi)))
        else:
            cut_a.append(_halfplane(ga, ha, -wa, wa).intersection(_halfplane(ua, uha, mid - c2, ra_hi)))
            cut_b.append(_halfplane(gb, hb, -wb, wb).intersection(_halfplane(ub, uhb, rb_lo, mid + c2)))
    slot_a = unary_union(cut_a).intersection(a.outline.envelope.buffer(1.0))
    slot_b = unary_union(cut_b).intersection(b.outline.envelope.buffer(1.0))
    return slot_a, slot_b, [(lo, hi) for lo, hi, _, _ in overlaps]


# --------------------------------------------------------------- finger_joint
def _slab_shadow(a: Part, b: Part) -> BaseGeometry:
    """Strip of a's local XY where b's slab passes through a's slab (projected along a's normal)."""
    nb = _normal(b)
    m = a.transform
    g = np.array([nb @ m[:3, 0], nb @ m[:3, 1]])
    h0 = float(nb @ m[:3, 3] - nb @ b.transform[:3, 3])      # b's slab: 0 <= nb.p - nb.ob <= tb
    k = float(nb @ m[:3, 2]) * a.thickness                    # change across a's thickness
    return _halfplane(g, h0, -max(0.0, k), b.thickness - min(0.0, k))


def finger_count(length: float, finger: float) -> int:
    """Odd number of fingers closest to length / finger (at least 1)."""
    return max(1, 2 * int(round((length / finger - 1) / 2)) + 1)


def finger_joint(a: Part, b: Part, clearance: float = 0.0, n: int | None = None,
                 finger: float | None = None, a_ends: bool = True) -> Joint:
    """Join two non-parallel plates whose solids overlap along a line with alternating fingers.

    Draw both plates to their full outer size so they overlap where they meet (box corner:
    both reach the outside corner; T joint: the edge plate reaches through the face plate).
    The overlap is split along the line where the plates meet into `n` (odd) equal segments;
    each plate keeps every other one. Works at any angle; the result has zero 3D overlap.

    n          Number of fingers + gaps (odd). Default from `finger`.
    finger     Target finger width; default 2 x the thicker plate.
    a_ends     `a` keeps the two end segments (the corners); otherwise `b` does.
    clearance  Each finger's gap is widened by this along the joint (negative = press fit).
    """
    j = Joint("finger_joint")
    na, nb = _normal(a), _normal(b)
    d = np.cross(na, nb)
    if np.linalg.norm(d) < 1e-6:
        raise ValueError(f"finger_joint {a.name}/{b.name}: plates are parallel")
    d /= np.linalg.norm(d)
    strip_a, strip_b = _slab_shadow(a, b), _slab_shadow(b, a)
    ua, uha = _linear_in_local(a, (d, 0.0))
    ub, uhb = _linear_in_local(b, (d, 0.0))
    ia = _interval(a.outline.intersection(strip_a), ua, uha)
    ib = _interval(b.outline.intersection(strip_b), ub, uhb)
    if ia is None or ib is None:
        raise ValueError(f"finger_joint {a.name}/{b.name}: plates do not meet")
    lo, hi = max(ia[0], ib[0]), min(ia[1], ib[1])
    L = hi - lo
    if L < EPS:
        raise ValueError(f"finger_joint {a.name}/{b.name}: plates do not overlap")
    finger = 2 * max(a.thickness, b.thickness) if finger is None else finger
    n = finger_count(L, finger) if n is None else n
    if n < 1 or n % 2 == 0:
        raise ValueError("finger_joint: n must be odd and >= 1")
    if n < 3:
        j.warnings.append(f"{a.name}/{b.name}: joint is only {L:.1f} mm long - no room for fingers.")

    c2 = clearance / 2
    keep_a = [k for k in range(n) if (k % 2 == 0) == a_ends]
    keep_b = [k for k in range(n) if k not in keep_a]

    def segments(ks, u, uh):
        return unary_union([_halfplane(u, uh, lo + L * k / n - c2, lo + L * (k + 1) / n + c2) for k in ks])

    cut_a = strip_a.intersection(segments(keep_b, ua, uha)) if keep_b else Polygon()
    cut_b = strip_b.intersection(segments(keep_a, ub, uhb)) if keep_a else Polygon()
    a.outline = clean(a.outline.difference(cut_a))
    b.outline = clean(b.outline.difference(cut_b))
    for p in (a, b):
        if len(as_polygons(p.outline)) > 1:
            j.warnings.append(f"{p.name}: finger joint splits the part in pieces.")
    j.removed = {a.name: as_polygons(cut_a), b.name: as_polygons(cut_b)}
    j.info = {"fingers": n, "length": round(L, 3), "finger_width": round(L / n, 3)}
    return j


# ------------------------------------------------------------------ pin_joint
def _frame_along(axis: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Two unit vectors x, y with x x y = axis."""
    ref = np.array([1.0, 0, 0]) if abs(axis[0]) < 0.9 else np.array([0, 1.0, 0])
    x = np.cross(ref, axis)
    x /= np.linalg.norm(x)
    return x, np.cross(axis, x)


def pin_joint(
    parts: list[Part],
    origin,
    axis,
    diameter: float,
    fit: float = 0.15,
    fits: dict[str, float] | None = None,
    extra: float = 0.0,
    min_bridge: float | None = None,
    washer_thickness: float | None = None,
    washer_od: float | None = None,
    name: str = "Pin",
) -> Joint:
    """Run a round pin of `diameter` through `parts` along the world line `origin` + s * `axis`.

    Each part gets a hole of diameter + fit (`fits[part name]` overrides `fit`: a negative
    press fit for parts glued/clamped to the pin, the running fit for parts that turn on it).
    The axis must be perpendicular to every plate. The pin (Hardware "cylinder") spans the
    stack plus `extra` at each end; add `j.hardware` to the design.

    washer_thickness  Fill each gap between neighbouring plates with ring washers of this
                      thickness (outer diameter `washer_od`, default pin + 4 x thickness), cut
                      from that material; add `j.parts` to the design. Gaps that are not a
                      multiple of it are warned about.
    To let parts turn, declare a `design.Pivot(origin=origin, axis=axis, ...)`.
    """
    j = Joint("pin_joint")
    fits = fits or {}
    ax = np.asarray(axis, float)
    ax /= np.linalg.norm(ax)
    o = np.asarray(origin, float)
    if not parts:
        raise ValueError("pin_joint: no parts")
    slabs = []                                       # (s_in, s_out, part)
    for p in parts:
        if abs(float(_normal(p) @ ax)) < 0.999:
            raise ValueError(f"pin_joint {name}: axis is not perpendicular to {p.name}")
        lo = to_local(p, [o])[0]
        ld = np.linalg.inv(p.transform)[:3, :3] @ ax
        s0, s1 = sorted(((0.0 - lo[2]) / ld[2], (p.thickness - lo[2]) / ld[2]))
        c = lo + ld * (s0 + s1) / 2
        hole = Point(c[0], c[1]).buffer((diameter + fits.get(p.name, fit)) / 2, quad_segs=16)
        bridge = p.thickness / 2 if min_bridge is None else min_bridge
        if not p.outline.contains(Point(c[0], c[1])):
            j.warnings.append(f"{name}: misses {p.name}.")
        elif not p.outline.buffer(1e-6).contains(hole.buffer(bridge)):
            j.warnings.append(f"{p.name}: hole for {name} is closer than {bridge:.1f} mm to the edge - weak.")
        p.outline = clean(p.outline.difference(hole))
        j.removed[p.name] = [hole]
        slabs.append((s0, s1, p))
    slabs.sort(key=lambda t: t[0])

    x, y = _frame_along(ax)
    s_lo, s_hi = slabs[0][0] - extra, max(s1 for _, s1, _ in slabs) + extra
    length = s_hi - s_lo
    j.hardware.append(Hardware(name, "cylinder", {"radius": diameter / 2, "height": round(length, 3)},
                               plane_transform(o + ax * s_lo, x, y), note=f"Ø{diameter:g} x {length:.0f} mm"))
    gaps = []
    for (_, prev_out, prev), (nxt_in, _, nxt) in zip(slabs, slabs[1:]):
        gap = nxt_in - prev_out
        if gap < -EPS:
            j.warnings.append(f"{name}: {prev.name} and {nxt.name} overlap along the pin.")
            continue
        gaps.append((prev.name, nxt.name, round(gap, 3)))
        if not washer_thickness or gap < EPS:
            continue
        count = int(np.floor(gap / washer_thickness + 1e-6))
        left = gap - count * washer_thickness
        if left > 0.5:
            j.warnings.append(f"{name}: {left:.1f} mm play between {prev.name} and {nxt.name}.")
        od = diameter + 4 * washer_thickness if washer_od is None else washer_od
        ring = Point(0, 0).buffer(od / 2, quad_segs=16).difference(
            Point(0, 0).buffer((diameter + fit) / 2, quad_segs=16))
        for i in range(count):
            j.parts.append(Part(f"{name} washer {len(j.parts) + 1}", ring, washer_thickness,
                                plane_transform(o + ax * (prev_out + i * washer_thickness), x, y), group="washer"))
    j.info = {"span": (round(s_lo, 3), round(s_hi, 3)), "gaps": gaps}
    return j


# --------------------------------------------------------------- living_hinge
def hinge_length(angle_deg: float, inner_radius: float, thickness: float) -> float:
    """Length of plate a living hinge needs to bend by `angle_deg` around `inner_radius` (neutral axis)."""
    return float(np.radians(angle_deg) * (inner_radius + thickness / 2))


def living_hinge(
    part: Part,
    region: BaseGeometry | None = None,
    angle: float = 90.0,
    slit: float | None = None,
    bridge: float | None = None,
    pitch: float | None = None,
    margin: float = 0.0,
) -> Joint:
    """Make `region` of `part` bendable with rows of staggered slits (straight lattice hinge).

    region  Area to make flexible (local XY); default the whole part.
    angle   Direction of the slits in local XY, degrees from +x. The plate bends about this
            direction (slits along y -> the hinge rolls up around y).
    slit    Slit length (default 8 x thickness); bridge = material between slits in a row
            (default = thickness); pitch = distance between rows (default 0.6 x thickness).
            Closer rows and longer slits bend tighter but are weaker.
    margin  Keep slits this far from the part's outline (0 = slits run out of the edge).
    Slits are open cut lines added to `part.cuts`; no material is removed. Use
    `hinge_length` to size the region for a bend.
    """
    j = Joint("living_hinge")
    t = part.thickness
    slit = 8 * t if slit is None else slit
    bridge = t if bridge is None else bridge
    pitch = 0.6 * t if pitch is None else pitch
    if min(slit, bridge, pitch) <= 0:
        raise ValueError("living_hinge: slit, bridge and pitch must be > 0")
    area = part.outline if region is None else part.outline.intersection(region)
    if margin > 0:
        area = area.intersection(part.outline.buffer(-margin, join_style="mitre"))
    if area.is_empty:
        raise ValueError(f"living_hinge {part.name}: region does not overlap the part")
    a = np.radians(angle)
    u = np.array([np.cos(a), np.sin(a)])            # along the slits
    v = np.array([-u[1], u[0]])                      # across the rows (bending direction)
    pts = np.array([c for p in as_polygons(area) for c in p.exterior.coords])
    us, vs = pts @ u, pts @ v
    period = slit + bridge
    lines: list[LineString] = []
    rows = 0
    vrow = vs.min() + pitch / 2
    while vrow < vs.max():
        start = us.min() - period + (period / 2 if rows % 2 else 0.0)
        k = start
        while k < us.max() + period:
            seg = LineString([tuple(u * k + v * vrow), tuple(u * (k + slit) + v * vrow)])
            lines += [l for l in as_lines(area.intersection(seg)) if l.length >= min(bridge, slit) - EPS]
            k += period
        rows += 1
        vrow += pitch
    part.cuts = list(part.cuts) + lines
    if pitch < 0.3 * t:
        j.warnings.append(f"{part.name}: hinge rows {pitch:.1f} mm apart are thinner than 0.3 x thickness - fragile.")
    j.info = {"rows": rows, "slits": len(lines), "bend_length": round(float(vs.max() - vs.min()), 3)}
    return j
