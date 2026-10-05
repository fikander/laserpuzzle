"""2D geometry helpers built on shapely."""

from __future__ import annotations

from functools import reduce

import numpy as np
import trimesh
from shapely import affinity
from shapely.geometry import GeometryCollection, LineString, MultiLineString, MultiPolygon, Polygon, box
from shapely.geometry.base import BaseGeometry
from shapely.ops import polygonize, unary_union

BIG = 1e5


def as_polygons(geom: BaseGeometry | None) -> list[Polygon]:
    """Flatten any geometry into a list of non-empty Polygons."""
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, Polygon):
        return [geom]
    if isinstance(geom, (MultiPolygon, GeometryCollection)):
        out: list[Polygon] = []
        for g in geom.geoms:
            out.extend(as_polygons(g))
        return out
    return []


def as_lines(geom: BaseGeometry | None) -> list[LineString]:
    if geom is None or geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [geom]
    if isinstance(geom, (MultiLineString, GeometryCollection)):
        out: list[LineString] = []
        for g in geom.geoms:
            out.extend(as_lines(g))
        return out
    if isinstance(geom, Polygon):
        return [LineString(geom.exterior.coords)] + [LineString(i.coords) for i in geom.interiors]
    if isinstance(geom, MultiPolygon):
        return [l for p in geom.geoms for l in as_lines(p)]
    return []


def clean(geom: BaseGeometry, min_area: float = 0.0, simplify: float = 0.0) -> BaseGeometry:
    """Fix invalid geometry, drop tiny islands, optionally simplify."""
    if geom.is_empty:
        return geom
    g = geom.buffer(0)
    if simplify > 0:
        g = g.simplify(simplify, preserve_topology=True)
    polys = [p for p in as_polygons(g) if p.area >= min_area]
    if not polys:
        return Polygon()
    return unary_union(polys)


def largest(geom: BaseGeometry) -> Polygon:
    polys = as_polygons(geom)
    if not polys:
        return Polygon()
    return max(polys, key=lambda p: p.area)


def kerf_offset(geom: BaseGeometry, kerf: float) -> BaseGeometry:
    """Compensate for beam width: outer edges grow, holes shrink by kerf/2.

    Mitre joins keep sharp corners (important for slots and tabs).
    """
    if kerf <= 0 or geom.is_empty:
        return geom
    return geom.buffer(kerf / 2.0, join_style="mitre", mitre_limit=3.0)


def rect(x0: float, y0: float, x1: float, y1: float) -> Polygon:
    return box(min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1))


def band_x(geom: BaseGeometry, y0: float, y1: float) -> list[tuple[float, float]]:
    """X-intervals where `geom` overlaps the horizontal band y0..y1 (sorted)."""
    inter = geom.intersection(rect(-BIG, y0, BIG, y1))
    spans = []
    for p in as_polygons(inter):
        minx, _, maxx, _ = p.bounds
        spans.append((minx, maxx))
    spans.sort()
    merged: list[list[float]] = []
    for a, b in spans:
        if merged and a <= merged[-1][1] + 1e-9:
            merged[-1][1] = max(merged[-1][1], b)
        else:
            merged.append([a, b])
    return [(a, b) for a, b in merged]


def section(mesh: trimesh.Trimesh, origin, normal, x_axis, y_axis, snap: float = 1e-5) -> BaseGeometry:
    """Planar cross-section of a mesh as a shapely (Multi)Polygon.

    The result is expressed in 2D plane coordinates (u, v) where
    u = dot(p - origin, x_axis), v = dot(p - origin, y_axis).
    Nested contours are resolved with even-odd (XOR) so holes come out right.
    """
    origin = np.asarray(origin, float)
    segs = trimesh.intersections.mesh_plane(mesh, plane_normal=normal, plane_origin=origin)
    if len(segs) == 0:
        return Polygon()
    xa = np.asarray(x_axis, float)
    ya = np.asarray(y_axis, float)
    rel = segs - origin
    uv = np.stack([rel @ xa, rel @ ya], axis=-1)
    if snap:
        uv = np.round(uv / snap) * snap
    lines = [LineString(s) for s in uv if np.linalg.norm(s[0] - s[1]) > 0]
    if not lines:
        return Polygon()
    noded = unary_union(lines)
    # polygonize returns the disjoint faces of the arrangement; take each face's
    # outer ring as a filled contour and XOR them (even-odd rule) so that
    # nested contours alternate solid / hole.
    faces = sorted((Polygon(f.exterior) for f in polygonize(noded)), key=lambda p: -p.area)
    if not faces:
        return Polygon()
    result = reduce(lambda a, b: a.symmetric_difference(b), faces)
    return result.buffer(0)


def transform2d(geom: BaseGeometry, angle_deg: float, dx: float, dy: float) -> BaseGeometry:
    g = affinity.rotate(geom, angle_deg, origin=(0, 0)) if angle_deg else geom
    return affinity.translate(g, dx, dy)
