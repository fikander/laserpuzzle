"""3D sanity checks on an assembled Design.

`collisions` extrudes every part to its real thickness, places it in the
world and reports pairs whose solids overlap by more than `tol_mm3`.
Half-lap joints that touch exactly have ~zero overlap volume; a negative
clearance (press fit) shows small overlaps - that is expected, so the
threshold scales with thickness.
"""

from __future__ import annotations

import itertools

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


def collisions(design: Design, tol_mm3: float | None = None) -> list[dict]:
    try:
        import manifold3d  # noqa: F401
    except ImportError:  # pragma: no cover
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
        tol = tol_mm3 if tol_mm3 is not None else max(0.5, 0.05 * pa.thickness * pb.thickness * 10)
        if vol > tol:
            out.append({"a": pa.name, "b": pb.name, "volume_mm3": round(vol, 2)})
    return out
