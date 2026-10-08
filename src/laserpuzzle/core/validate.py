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

`motion_collisions` repeats the check while each `Pivot` sweeps through its
range (moving assemblies: pin joints, turntables, gears, cams). Only pairs whose
relative position changes are re-checked.

`trajectory_collisions` moves each travelling hardware item (a ball) along its
`Trajectory` and reports the parts it runs into. It is native only and not part
of `pipeline.run`; generators that emit trajectories check them in their tests.
"""

from __future__ import annotations

import itertools
import sys
from typing import Any, Callable

import numpy as np
import trimesh

from .design import Design, Hardware, Part, Pivot, is_cam, table_problem
from .geometry import as_polygons


def part_mesh(part: Part) -> trimesh.Trimesh | None:
    meshes = []
    for poly in as_polygons(part.outline):
        try:
            # manifold's triangulation: earcut (trimesh's default) can fill a hole in a plate with many slots,
            # which then shows up as a false overlap
            meshes.append(trimesh.creation.extrude_polygon(poly, part.thickness, engine="manifold"))
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


PairFilter = Callable[[Part, Part], bool]


def collisions(design: Design, tol_mm3: float | None = None, only: PairFilter | None = None) -> list[dict]:
    """Part pairs whose solids overlap. `only(a, b)` restricts the pairs checked."""
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
                return js_collisions(design, manifold, to_js, tol_mm3, only)
            return [{"error": "manifold WASM not loaded (globalThis.manifold) - collision check skipped"}]
        return [{"error": "manifold3d not installed - collision check skipped"}]
    pairs = [(a, b) for a, b in itertools.combinations(design.parts, 2) if only is None or only(a, b)]
    cache: dict[int, trimesh.Trimesh | None] = {}

    def mesh(p: Part):
        if id(p) not in cache:
            cache[id(p)] = part_mesh(p)
        return cache[id(p)]

    out = []
    for pa, pb in pairs:
        ma, mb = mesh(pa), mesh(pb)
        if ma is None or mb is None or not _bbox_overlap(ma.bounds, mb.bounds):
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
                  tol_mm3: float | None = None, only: PairFilter | None = None) -> list[dict]:
    """`collisions` on manifold's JS API (`Module()` after `setup()`), for Pyodide.

    `to_js` converts Python lists for JS calls (pyodide.ffi.to_js). WASM objects
    are not garbage collected, so every solid is `delete()`d.
    """
    solids = []
    pairs = [(a, b) for a, b in itertools.combinations(design.parts, 2) if only is None or only(a, b)]
    wanted = {id(p) for pair in pairs for p in pair}
    try:
        for p in design.parts:
            if id(p) not in wanted:
                continue
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
        by_id = {id(p): (s, b) for p, s, b in solids}
        out = []
        for pa, pb in pairs:
            if id(pa) not in by_id or id(pb) not in by_id:
                continue
            (sa, ba), (sb, bb) = by_id[id(pa)], by_id[id(pb)]
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


def cam_extremes(design: Design, free: Pivot) -> list[float]:
    """Values of the free pivot `free`, within its range, at which a cam-driven pivot (see
    `Pivot.driver`) it moves reaches its lowest or highest value. Cams geared to `free` count
    too; a cam driven by another cam doesn't."""
    piv = {p.name: p for p in design.pivots}
    lo, hi = free.range
    out: list[float] = []
    for q in design.pivots:
        if not is_cam(q.driver) or table_problem(q.driver[1]):
            continue
        ratio, cur, seen = 1.0, piv.get(q.driver[0]), set()
        while cur is not None and cur is not free and cur.name not in seen:   # geared links back to `free`
            seen.add(cur.name)
            if cur.driver is None or is_cam(cur.driver):
                cur = None
                break
            ratio *= float(cur.driver[1])
            cur = piv.get(cur.driver[0])
        if cur is not free or abs(ratio) < 1e-12:
            continue
        t = np.asarray(q.driver[1], float)
        for x in (t[np.argmin(t[:, 1]), 0], t[np.argmax(t[:, 1]), 0]):
            # driver angle x + 360 k = ratio * a, for every a in [lo, hi]
            ks = sorted(((ratio * lo - x) / 360.0, (ratio * hi - x) / 360.0))
            for k in range(int(np.ceil(ks[0] - 1e-9)), int(np.floor(ks[1] + 1e-9)) + 1):
                out.append(float((x + 360.0 * k) / ratio))
    return sorted({round(a, 6) for a in out if lo - 1e-9 <= a <= hi + 1e-9})


def sweep_poses(design: Design, steps: int = 7) -> list[dict[str, float]]:
    """Poses `motion_collisions` checks: each free pivot alone at `steps` values across its
    range (others at rest), plus where the cams it drives reach their extremes (`cam_extremes`),
    then all free pivots at their minimum and at their maximum."""
    free = [p for p in design.pivots if p.driver is None]
    poses: list[dict[str, float]] = []
    for p in free:
        lo, hi = p.range
        values = [float(a) for a in np.linspace(lo, hi, max(2, steps))]
        values += [a for a in cam_extremes(design, p) if all(abs(a - b) > 1e-6 for b in values)]
        poses += [{p.name: a} for a in values if abs(a) > 1e-9]
    if len(free) > 1:
        poses.append({p.name: float(p.range[0]) for p in free})
        poses.append({p.name: float(p.range[1]) for p in free})
    return poses


def motion_collisions(design: Design, steps: int = 7, tol_mm3: float | None = None,
                      rest: list[dict] | None = None) -> list[dict]:
    """Collisions that appear while the mechanism moves (see `sweep_poses`).

    Pairs that collide in the rest pose are `collisions`' business and are left out.
    Each colliding pair is reported once, at the pose with the largest overlap:
    {"a", "b", "volume_mm3", "pose": {pivot: degrees}}. `rest` = `collisions(design)` if already known.
    """
    if not design.pivots:
        return []
    problems = design.pivot_problems()
    if problems:
        return [{"error": "; ".join(problems)}]
    rest_pairs = {(r["a"], r["b"]) for r in (collisions(design, tol_mm3) if rest is None else rest)
                  if "volume_mm3" in r}
    worst: dict[tuple[str, str], dict] = {}
    for pose in sweep_poses(design, steps):
        mot = design.motions(pose)
        part_m = {n: mot[p.name] for p in design.pivots for n in p.parts}
        eye = np.eye(4)

        def moved_apart(a: Part, b: Part) -> bool:
            if (a.name, b.name) in rest_pairs:
                return False
            return not np.allclose(part_m.get(a.name, eye), part_m.get(b.name, eye), atol=1e-9)

        for r in collisions(design.posed(pose), tol_mm3, only=moved_apart):
            key = (r.get("a", ""), r.get("b", ""))
            if "error" in r:
                worst.setdefault(key, r)
            elif key not in worst or r["volume_mm3"] > worst[key].get("volume_mm3", 0):
                worst[key] = {**r, "pose": {k: round(v, 1) for k, v in pose.items()}}
    return list(worst.values())


def hardware_mesh(h: Hardware, shrink: float = 0.0) -> trimesh.Trimesh | None:
    """Solid of a hardware item ("sphere", "cylinder" or "box", see `Hardware`), `shrink` mm smaller all round."""
    s = h.size
    if h.kind == "sphere":
        m = trimesh.creation.icosphere(subdivisions=2, radius=max(1e-3, s["radius"] - shrink))
    elif h.kind == "cylinder":
        height = max(1e-3, s["height"] - 2 * shrink)
        m = trimesh.creation.cylinder(radius=max(1e-3, s["radius"] - shrink), height=height, sections=24)
        m.apply_translation((0.0, 0.0, height / 2 + shrink))          # axis = local z, base at 0
    elif h.kind == "box":
        m = trimesh.creation.box(extents=[max(1e-3, s[k] - 2 * shrink) for k in ("x", "y", "z")])
    else:
        return None
    m.apply_transform(h.transform)
    return m


def trajectory_collisions(design: Design, step: float | None = None, shrink: float = 0.2,
                          tol_mm3: float = 0.5) -> list[dict]:
    """Parts the travelling items of `design.trajectories` run into.

    Each item is placed along its path every `step` mm (default: a quarter of its smallest size), with the
    trajectory's pivots moving the parts, and checked `shrink` mm smaller all round (it rolls on the
    surfaces it touches). Each part it hits is reported once, at the first time:
    {"item", "part", "volume_mm3", "time"}. Native only (needs `manifold3d`).
    """
    try:
        import manifold3d  # noqa: F401
    except ImportError:
        return [{"error": "manifold3d not installed - trajectory check skipped"}]
    problems = design.trajectory_problems() + (design.pivot_problems() if design.pivots else [])
    if problems:
        return [{"error": "; ".join(problems)}]
    hw = {h.name: h for h in design.hardware}
    rest = {id(p): part_mesh(p) for p in design.parts}
    on_pivot = {n for p in design.pivots for n in p.parts}
    out: list[dict] = []
    for tr in design.trajectories:
        h = hw[tr.hardware]
        item = hardware_mesh(h, shrink)
        if item is None:
            continue
        size = min(h.size.values()) * (2 if h.kind in ("sphere", "cylinder") else 1)
        dist = step if step is not None else max(0.5, size / 4)
        start = np.asarray(h.transform, float)[:3, 3]
        times = np.asarray(tr.times, float)
        pts = np.asarray(tr.points, float)
        samples: list[float] = []
        for i in range(len(times) - 1):
            moved = float(np.linalg.norm(pts[i + 1] - pts[i]))
            turned = max([abs(v[i + 1] - v[i]) for v in tr.pivots.values()] or [0.0])
            n = max(1, int(np.ceil(max(moved / dist, turned / 5.0))))
            samples += [float(x) for x in np.linspace(times[i], times[i + 1], n, endpoint=False)]
        samples.append(float(times[-1]))
        hit: set[str] = set()
        for time in samples:
            pos, pose = tr.at(time)
            ball = item.copy()
            ball.apply_translation(pos - start)
            parts = design.posed(pose).parts if pose else design.parts
            for p, q in zip(design.parts, parts):
                if p.name in hit:
                    continue
                m = rest[id(p)]
                if m is None:
                    continue
                if p.name in on_pivot and pose:
                    m = part_mesh(q)
                if not _bbox_overlap(ball.bounds, m.bounds):
                    continue
                inter = trimesh.boolean.intersection([ball, m], engine="manifold")
                with np.errstate(all="ignore"):
                    vol = float(abs(inter.volume)) if inter is not None and len(inter.faces) else 0.0
                if np.isfinite(vol) and vol > tol_mm3:
                    hit.add(p.name)
                    out.append({"item": tr.hardware, "part": p.name, "volume_mm3": round(vol, 2),
                                "time": round(time, 3)})
    return out
