"""Data model produced by generators.

A `Design` is a list of flat `Part`s (plus optional non-cut `Hardware` like
dowels, axles, magnets, balls). Each Part carries:

* `outline`  - nominal 2D shape in the part's local XY plane (mm), shapely
               Polygon/MultiPolygon. Holes are cut-outs. NO kerf applied:
               kerf is a fabrication concern handled at export.
* `engrave`  - list of 2D LineStrings to engrave/score (local coords).
* `cuts`     - open 2D LineStrings cut through the part without removing
               material (living-hinge slits). Cut colour, no kerf offset.
* `transform`- 4x4 matrix mapping local (x, y, z) to the assembled world
               position. The part occupies local z in [0, thickness].
* `explode`  - world-space offset direction used by the "exploded" preview.

World convention: millimetres, Z up, model standing on z=0.

Moving assemblies (pin joints, turntables, gears, cams and followers) describe
their axes and guides as `Pivot`s. The Design is built in its rest pose (every
pivot at 0); `Design.posed(angles)` moves the parts, and
`validate.motion_collisions` sweeps each pivot through its range.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from typing import Any

import numpy as np
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry

from .geometry import as_polygons


def plane_transform(origin, x_axis, y_axis, thickness: float = 0.0, centered: bool = False) -> np.ndarray:
    """4x4 transform for a sheet lying in the plane spanned by x_axis, y_axis.

    Local z (sheet thickness direction) = x_axis × y_axis.
    If `centered`, the sheet is centred on the plane (local z=t/2 lands on
    `origin`); otherwise its bottom face (local z=0) is on the plane.
    """
    x = np.asarray(x_axis, float)
    x = x / np.linalg.norm(x)
    y = np.asarray(y_axis, float)
    y = y / np.linalg.norm(y)
    z = np.cross(x, y)
    o = np.asarray(origin, float)
    if centered:
        o = o - z * thickness / 2.0
    m = np.eye(4)
    m[:3, 0], m[:3, 1], m[:3, 2], m[:3, 3] = x, y, z, o
    return m


def horizontal(z: float) -> np.ndarray:
    """Sheet lying flat, bottom face at height z (local xy == world xy)."""
    return plane_transform((0, 0, z), (1, 0, 0), (0, 1, 0))


def vertical_xz(y: float, thickness: float) -> np.ndarray:
    """Upright sheet in the world XZ plane, centred on world y (local x->X, local y->Z)."""
    return plane_transform((0, y, 0), (1, 0, 0), (0, 0, 1), thickness, centered=True)


def vertical_yz(x: float, thickness: float) -> np.ndarray:
    """Upright sheet in the world YZ plane, centred on world x (local x->Y, local y->Z)."""
    return plane_transform((x, 0, 0), (0, 1, 0), (0, 0, 1), thickness, centered=True)


@dataclass
class Part:
    name: str
    outline: BaseGeometry
    thickness: float
    transform: np.ndarray = field(default_factory=lambda: np.eye(4))
    engrave: list[LineString] = field(default_factory=list)
    cuts: list[LineString] = field(default_factory=list)   # open cut lines inside the outline (no material removed)
    label: str | None = None           # short text engraved on the part (e.g. "L03")
    group: str = "part"                # used for colouring / BOM grouping
    explode: tuple[float, float, float] = (0.0, 0.0, 0.0)
    quantity: int = 1                  # identical copies to cut (same placement preview shows 1)
    meta: dict[str, Any] = field(default_factory=dict)

    @property
    def polygons(self) -> list[Polygon]:
        return as_polygons(self.outline)

    def area(self) -> float:
        return float(self.outline.area)


@dataclass
class Hardware:
    """Non-cut items shown in preview and listed in the BOM."""

    name: str
    kind: str                          # "cylinder" | "sphere" | "box"
    size: dict[str, float]             # cylinder: radius, height; sphere: radius; box: x, y, z
    transform: np.ndarray = field(default_factory=lambda: np.eye(4))  # cylinder axis = local z, base at 0
    quantity: int = 1
    note: str = ""


def rotation_about(origin, axis, angle_deg: float) -> np.ndarray:
    """4x4 rotation by `angle_deg` (right-hand rule) about the world line through `origin` along `axis`."""
    k = np.asarray(axis, float)
    k = k / np.linalg.norm(k)
    a = np.radians(angle_deg)
    kx = np.array([[0, -k[2], k[1]], [k[2], 0, -k[0]], [-k[1], k[0], 0]])
    r = np.eye(3) + np.sin(a) * kx + (1 - np.cos(a)) * kx @ kx
    o = np.asarray(origin, float)
    m = np.eye(4)
    m[:3, :3] = r
    m[:3, 3] = o - r @ o
    return m


def translation_along(axis, distance: float) -> np.ndarray:
    """4x4 move by `distance` along the world direction `axis`."""
    k = np.asarray(axis, float)
    m = np.eye(4)
    m[:3, 3] = k / np.linalg.norm(k) * distance
    return m


@dataclass
class Pivot:
    """A joint parts move on: a rotation axis (pin joint, turntable, gear shaft) or a straight
    guide (`kind="slide"`: cam follower, push rod). Its value is an angle in degrees for "turn",
    a distance in mm along `axis` for "slide".

    origin, axis  World point and direction of the axis in the rest pose.
    kind          "turn" (default) or "slide".
    parts         Names of the parts that move with it. Parts of child pivots
                  follow automatically; don't list them here.
    hardware      Names of hardware items (pins, axles) that move with it.
    range         (min, max) value the mechanism allows; swept by `validate.motion_collisions`.
                  The rest pose (0) should be inside it.
    parent        Pivot this one rides on (boom -> stick -> bucket): its axis moves with the parent.
    driver        Another pivot that moves this one; driven pivots are not swept on their own.
                  (pivot name, ratio): value = ratio x driver's value (gears).
                  (pivot name, table): a cam. `table` is [(driver angle, value), ...] over one
                  turn, angles rising within [0, 360); the value is interpolated linearly
                  between the points and repeats every 360 deg of the driver (`cam_value`).
    """

    name: str
    origin: tuple[float, float, float]
    axis: tuple[float, float, float]
    parts: list[str] = field(default_factory=list)
    hardware: list[str] = field(default_factory=list)
    range: tuple[float, float] = (-180.0, 180.0)
    parent: str | None = None
    driver: tuple[str, float | list[tuple[float, float]]] | None = None
    kind: str = "turn"


PIVOT_KINDS = ("turn", "slide")


def is_cam(driver) -> bool:
    """True for a (pivot, table) driver, False for a (pivot, ratio) one."""
    return driver is not None and not isinstance(driver[1], (int, float, np.number))


def cam_value(table, angle: float) -> float:
    """Value of a cam table (see `Pivot.driver`) at the driver's `angle` (deg, any turn)."""
    t = np.asarray(table, float)
    return float(np.interp(angle % 360.0, t[:, 0], t[:, 1], period=360.0))


def driven_value(driver, value: float) -> float:
    """A driven pivot's value when its driver is at `value`."""
    return cam_value(driver[1], value) if is_cam(driver) else float(driver[1]) * value


def table_problem(table) -> str | None:
    """What is wrong with a cam table (None if nothing)."""
    try:
        t = np.asarray(table, float)
    except (TypeError, ValueError):
        return "cam table is not a list of (angle, value) pairs"
    if t.ndim != 2 or t.shape[1] != 2 or len(t) < 2:
        return "cam table needs at least two (angle, value) pairs"
    if not np.all(np.isfinite(t)):
        return "cam table has values that aren't numbers"
    if t[0, 0] < 0 or t[-1, 0] >= 360 or np.any(np.diff(t[:, 0]) <= 0):
        return "cam table angles must rise within [0, 360)"
    return None


@dataclass
class Design:
    parts: list[Part] = field(default_factory=list)
    hardware: list[Hardware] = field(default_factory=list)
    pivots: list[Pivot] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # assembly instructions, tips
    source_mesh: Any = None                             # trimesh.Trimesh in world coords (for ghost preview)
    stats: dict[str, Any] = field(default_factory=dict)
    meta: dict[str, Any] = field(default_factory=dict)   # machine-readable extras for code, not shown to users

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

    # ------------------------------------------------------------ motion
    def pivot_problems(self) -> list[str]:
        """Inconsistent pivot declarations (unknown names, cycles, part on two pivots)."""
        out = []
        names = {p.name for p in self.parts}
        hw = {h.name for h in self.hardware}
        piv = {p.name: p for p in self.pivots}
        owner: dict[str, str] = {}
        if len(piv) != len(self.pivots):
            out.append("Two pivots have the same name.")
        for p in self.pivots:
            for n in p.parts:
                if n not in names:
                    out.append(f"Pivot {p.name}: no part named {n}.")
                elif n in owner:
                    out.append(f"Part {n} is on two pivots ({owner[n]}, {p.name}).")
                owner.setdefault(n, p.name)
            out += [f"Pivot {p.name}: no hardware named {n}." for n in p.hardware if n not in hw]
            if p.kind not in PIVOT_KINDS:
                out.append(f"Pivot {p.name}: unknown kind {p.kind!r}.")
            if is_cam(p.driver) and (problem := table_problem(p.driver[1])):
                out.append(f"Pivot {p.name}: {problem}.")
            for ref in (p.parent, p.driver[0] if p.driver else None):
                if ref is not None and ref not in piv:
                    out.append(f"Pivot {p.name}: no pivot named {ref}.")
            if not p.range[0] <= 0 <= p.range[1]:
                out.append(f"Pivot {p.name}: rest pose 0 is outside its range {p.range}.")
        for p in self.pivots:                       # parent / driver chains must end
            seen, cur = set(), p
            while cur is not None and cur.name not in seen:
                seen.add(cur.name)
                nxt = cur.parent or (cur.driver[0] if cur.driver else None)
                cur = piv.get(nxt) if nxt else None
            if cur is not None:
                out.append(f"Pivot {p.name}: parent/driver chain loops.")
                break
        return out

    def pivot_angles(self, angles: dict[str, float]) -> dict[str, float]:
        """Every pivot's value (deg, or mm for a slide): given ones, driven ones from their drivers,
        the rest 0."""
        piv = {p.name: p for p in self.pivots}
        out: dict[str, float] = {}

        def angle(name: str, depth: int = 0) -> float:
            if name not in out:
                p = piv[name]
                if p.driver and depth < len(piv):
                    out[name] = driven_value(p.driver, angle(p.driver[0], depth + 1))
                else:
                    out[name] = float(angles.get(name, 0.0))
            return out[name]

        for n in piv:
            angle(n)
        return out

    def motions(self, angles: dict[str, float]) -> dict[str, np.ndarray]:
        """World motion (4x4, applied on top of the rest-pose transform) of every pivot."""
        piv = {p.name: p for p in self.pivots}
        ang = self.pivot_angles(angles)
        out: dict[str, np.ndarray] = {}

        def motion(name: str, depth: int = 0) -> np.ndarray:
            if name not in out:
                p = piv[name]
                own = (translation_along(p.axis, ang[name]) if p.kind == "slide"
                       else rotation_about(p.origin, p.axis, ang[name]))
                parent = p.parent if p.parent in piv and depth < len(piv) else None
                out[name] = motion(parent, depth + 1) @ own if parent else own
            return out[name]

        for n in piv:
            motion(n)
        return out

    def posed(self, angles: dict[str, float]) -> "Design":
        """Copy with parts and hardware moved to the pose `angles` (pivot name -> degrees)."""
        mot = self.motions(angles)
        part_m = {n: mot[p.name] for p in self.pivots for n in p.parts}
        hw_m = {n: mot[p.name] for p in self.pivots for n in p.hardware}
        d = replace(self)
        d.parts = [replace(p, transform=part_m[p.name] @ p.transform) if p.name in part_m else p for p in self.parts]
        d.hardware = [replace(h, transform=hw_m[h.name] @ h.transform) if h.name in hw_m else h
                      for h in self.hardware]
        return d

    def bom(self) -> list[dict]:
        rows: dict[str, dict] = {}
        for p in self.parts:
            r = rows.setdefault(p.group, {"item": p.group, "kind": "cut", "count": 0, "thickness": p.thickness})
            r["count"] += p.quantity
        out = list(rows.values())
        hw: dict[tuple, dict] = {}                 # identical items placed several times -> one row
        for h in self.hardware:
            key = (h.name, h.kind, tuple(sorted(h.size.items())), h.note)
            r = hw.setdefault(key, {"item": h.name, "kind": h.kind, "count": 0, "size": h.size, "note": h.note})
            r["count"] += h.quantity
        return out + list(hw.values())


def multipolygon(geom: BaseGeometry) -> MultiPolygon:
    return MultiPolygon(as_polygons(geom))
