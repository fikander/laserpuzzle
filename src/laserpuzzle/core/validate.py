"""3D sanity checks on an assembled Design.

`collisions` extrudes every part to its real thickness, places it in the
world and reports pairs whose solids overlap by more than `tol_mm3`.
Half-lap joints that touch exactly have ~zero overlap volume; a negative
clearance (press fit) shows small overlaps - that is expected, so the
threshold scales with thickness.

Two backends compute the overlap volumes: natively trimesh + the `manifold3d`
package; in the browser (Pyodide) the page loads manifold's own WASM build
(npm `manifold-3d`) and exposes it as `globalThis.manifold`, used through
`js_collisions`. Both give the same volumes.
"""

from __future__ import annotations

import itertools
import sys
from typing import Any, Callable

import numpy as np
import trimesh

from .design import Design, Part
from .geometry import as_polygons


def part_mesh(part: Part) -> trimesh.Trimesh | None:
    meshes = []
    for poly in as_polygons(part.outline):
        try:
            meshes.append(trimesh.creation.extrude_polygon(poly, part.thickness))
        except Exception:  # pragma: no cover - degenerate polygon
            continue
    if not meshes:
        return None
    m = trimesh.util.concatenate(meshes) if len(meshes) > 1 else meshes[0]
    m.apply_transform(part.transform)
    return m


def _bbox_overlap(a: np.ndarray, b: np.ndarray, eps: float = 1e-6) -> bool:
    return bool(np.all(a[0] < b[1] - eps) and np.all(b[0] < a[1] - eps))


def _tolerance(pa: Part, pb: Part, tol_mm3: float | None) -> float:
    return tol_mm3 if tol_mm3 is not None else max(0.5, 0.05 * pa.thickness * pb.thickness * 10)


def collisions(design: Design, tol_mm3: float | None = None) -> list[dict]:
    try:
        import manifold3d  # noqa: F401
    except ImportError:
        if sys.platform == "emscripten":  # pragma: no cover - only under Pyodide
            try:
                from js import manifold
                from pyodide.ffi import to_js
            except ImportError:
                manifold = None
            if manifold is not None:
                return js_collisions(design, manifold, to_js, tol_mm3)
            return [{"error": "manifold WASM not loaded (globalThis.manifold) - collision check skipped"}]
        return [{"error": "manifold3d not installed - collision check skipped"}]
    meshes = [(p, part_mesh(p)) for p in design.parts]
    meshes = [(p, m) for p, m in meshes if m is not None]
    out = []
    for (pa, ma), (pb, mb) in itertools.combinations(meshes, 2):
        if not _bbox_overlap(ma.bounds, mb.bounds):
            continue
        try:
            inter = trimesh.boolean.intersection([ma, mb], engine="manifold")
            with np.errstate(all="ignore"):
                vol = float(abs(inter.volume)) if inter is not None and len(inter.faces) else 0.0
            if not np.isfinite(vol):
                vol = 0.0
        except Exception as e:  # pragma: no cover
            out.append({"a": pa.name, "b": pb.name, "error": str(e)})
            continue
        if vol > _tolerance(pa, pb, tol_mm3):
            out.append({"a": pa.name, "b": pb.name, "volume_mm3": round(vol, 2)})
    return out


def js_collisions(design: Design, manifold: Any, to_js: Callable = lambda x: x,
                  tol_mm3: float | None = None) -> list[dict]:
    """`collisions` on manifold's JS API (`Module()` after `setup()`), for Pyodide.

    `to_js` converts Python lists for JS calls (pyodide.ffi.to_js). WASM objects
    are not garbage collected, so every solid is `delete()`d.
    """
    solids = []
    try:
        for p in design.parts:
            rings = []
            for poly in as_polygons(p.outline):
                rings.append([list(c) for c in poly.exterior.coords[:-1]])
                rings += [[list(c) for c in r.coords[:-1]] for r in poly.interiors]
            if not rings:
                continue
            cs = manifold.CrossSection.new(to_js(rings), "EvenOdd")
            flat = manifold.Manifold.extrude(cs, p.thickness)
            # JS Mat4 is column-major
            solid = flat.transform(to_js(np.asarray(p.transform, float).T.ravel().tolist()))
            cs.delete()
            flat.delete()
            b = solid.boundingBox()
            solids.append((p, solid, np.array([list(b.min), list(b.max)], float)))
        out = []
        for (pa, sa, ba), (pb, sb, bb) in itertools.combinations(solids, 2):
            if not _bbox_overlap(ba, bb):
                continue
            inter = sa.intersect(sb)
            vol = abs(float(inter.volume()))
            inter.delete()
            if not np.isfinite(vol):
                vol = 0.0
            if vol > _tolerance(pa, pb, tol_mm3):
                out.append({"a": pa.name, "b": pb.name, "volume_mm3": round(vol, 2)})
        return out
    finally:
        for _, s, _ in solids:
            s.delete()
