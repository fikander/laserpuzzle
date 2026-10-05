"""Data model produced by generators.

A `Design` is a list of flat `Part`s (plus optional non-cut `Hardware` like
dowels, axles, magnets, balls). Each Part carries:

* `outline`  - nominal 2D shape in the part's local XY plane (mm), shapely
               Polygon/MultiPolygon. Holes are cut-outs. NO kerf applied:
               kerf is a fabrication concern handled at export.
* `engrave`  - list of 2D LineStrings to engrave/score (local coords).
* `transform`- 4x4 matrix mapping local (x, y, z) to the assembled world
               position. The part occupies local z in [0, thickness].
* `explode`  - world-space offset direction used by the "exploded" preview.

World convention: millimetres, Z up, model standing on z=0.
"""

from __future__ import annotations

from dataclasses import dataclass, field
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


@dataclass
class Design:
    parts: list[Part] = field(default_factory=list)
    hardware: list[Hardware] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)      # assembly instructions, tips
    source_mesh: Any = None                             # trimesh.Trimesh in world coords (for ghost preview)
    stats: dict[str, Any] = field(default_factory=dict)

    def warn(self, msg: str) -> None:
        self.warnings.append(msg)

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
