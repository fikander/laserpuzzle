"""Glue: generator -> design -> fabricated parts -> sheets -> files / preview.

Both the CLI and the web UI call `run()`; keep all orchestration here so
the two never diverge.
"""

from __future__ import annotations

import io
import json
import time
import uuid
import zipfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np

from .core import export, layout, validate
from .core.design import Design, is_cam
from .core.geometry import as_polygons
from .core.params import coerce_values
from .generators.base import Context, get


@dataclass
class Run:
    id: str
    generator: str
    params: dict[str, Any]
    design: Design
    sheets: list[layout.Sheet]
    warnings: list[str]
    collisions: list[dict]
    timings: dict[str, float] = field(default_factory=dict)
    motion_collisions: list[dict] = field(default_factory=list)   # overlaps while pivots move

    # ---------------------------------------------------------------- files
    def colors(self) -> dict[str, str]:
        return {"cut_color": self.params.get("cut_color", export.CUT_COLOR),
                "engrave_color": self.params.get("engrave_color", export.ENGRAVE_COLOR)}

    def svg(self, i: int, show_sheet: bool = False) -> str:
        return export.sheet_svg(self.sheets[i], show_sheet=show_sheet, **self.colors())

    def dxf(self, i: int) -> bytes:
        return export.sheet_dxf(self.sheets[i], **self.colors())

    def summary(self) -> dict:
        return {
            "generator": self.generator,
            "params": self.params,
            "stats": self.design.stats,
            "bom": self.design.bom(),
            "notes": self.design.notes,
            "warnings": self.warnings,
            "collisions": self.collisions,
            "motion_collisions": self.motion_collisions,
            "sheet_count": len(self.sheets),
            "cut_length_mm": round(layout.total_cut_length(self.sheets), 1),
        }

    def write(self, outdir: Path) -> list[Path]:
        outdir.mkdir(parents=True, exist_ok=True)
        written = []
        for i in range(len(self.sheets)):
            p = outdir / f"sheet{i + 1}.svg"
            p.write_text(self.svg(i))
            written.append(p)
            p = outdir / f"sheet{i + 1}.dxf"
            p.write_bytes(self.dxf(i))
            written.append(p)
        p = outdir / "summary.json"
        p.write_text(json.dumps(self.summary(), indent=2, default=_json_default))
        written.append(p)
        if self.design.source_mesh is not None:
            p = outdir / "model_normalized.stl"
            self.design.source_mesh.export(p)
            written.append(p)
        return written

    def zip_bytes(self) -> bytes:
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
            for i in range(len(self.sheets)):
                z.writestr(f"sheet{i + 1}.svg", self.svg(i))
                z.writestr(f"sheet{i + 1}.dxf", self.dxf(i))
            z.writestr("summary.json", json.dumps(self.summary(), indent=2, default=_json_default))
        return buf.getvalue()

    # -------------------------------------------------------------- preview
    def preview(self) -> dict:
        parts = []
        for idx, p in enumerate(self.design.parts):
            shapes = []
            for poly in as_polygons(p.outline):
                shapes.append({
                    "outer": _pts(poly.exterior.coords),
                    "holes": [_pts(h.coords) for h in poly.interiors],
                })
            parts.append({
                "id": idx,
                "name": p.name,
                "group": p.group,
                "thickness": p.thickness,
                "shapes": shapes,
                "engrave": [_pts(l.coords) for l in p.engrave],
                "cuts": [_pts(l.coords) for l in p.cuts],
                "matrix": np.asarray(p.transform).T.flatten().round(5).tolist(),  # column-major for three.js
                "explode": list(map(float, p.explode)),
            })
        hardware = [{
            "name": h.name, "kind": h.kind, "size": h.size, "note": h.note,
            "matrix": np.asarray(h.transform).T.flatten().round(5).tolist(),
        } for h in self.design.hardware]
        part_ids = {p.name: i for i, p in enumerate(self.design.parts)}
        pivots = [{
            "name": v.name, "origin": [float(x) for x in v.origin], "axis": [float(x) for x in v.axis],
            "parts": [part_ids[n] for n in v.parts if n in part_ids],
            "hardware": [i for i, h in enumerate(self.design.hardware) if h.name in v.hardware],
            "range": [float(v.range[0]), float(v.range[1])], "parent": v.parent, "kind": v.kind,
            "driver": _driver_json(v.driver),
        } for v in self.design.pivots]
        hw_ids = {h.name: i for i, h in enumerate(self.design.hardware)}
        trajectories = [{
            "hardware": hw_ids.get(tr.hardware, -1),
            "times": [round(float(t), 4) for t in tr.times],
            "points": [[round(float(x), 2) for x in p] for p in tr.points],
            "pivots": {n: [round(float(x), 2) for x in v] for n, v in tr.pivots.items()},
            "loop": tr.loop,
        } for tr in self.design.trajectories]
        return {
            "run": self.id,
            "parts": parts,
            "hardware": hardware,
            "pivots": pivots,
            "trajectories": trajectories,
            "sheets": [{"index": s.index, "width": s.width, "height": s.height, "count": len(s.items),
                        "svg": export.sheet_svg(s, show_sheet=True, **self.colors()),
                        "utilisation": round(s.used_area() / (s.width * s.height), 3)} for s in self.sheets],
            "has_mesh": self.design.source_mesh is not None,
            **self.summary(),
            "timings": self.timings,
        }


def _driver_json(driver) -> list | None:
    """[pivot, ratio] or, for a cam, [pivot, [[angle, value], ...]]."""
    if driver is None:
        return None
    if is_cam(driver):
        return [driver[0], [[float(a), float(b)] for a, b in driver[1]]]
    return [driver[0], float(driver[1])]


def _pts(coords) -> list[list[float]]:
    return [[round(x, 3), round(y, 3)] for x, y in list(coords)]


def _json_default(o):
    if isinstance(o, (np.floating, np.integer)):
        return o.item()
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


def run(generator_id: str, raw_params: dict[str, Any], workdir: str | Path = ".", check: bool = True) -> Run:
    gen_cls = get(generator_id)
    values = coerce_values(gen_cls.all_params(), raw_params)
    ctx = Context(workdir=Path(workdir).resolve())
    t0 = time.perf_counter()
    design = gen_cls().generate(values, ctx)
    t1 = time.perf_counter()

    fparts = []
    for p in design.parts:
        fparts += layout.fabricate(p, values["kerf"], values["labels"])
    sheets, nest_warnings = layout.nest(fparts, values["sheet_width"], values["sheet_height"], values["part_spacing"])
    t2 = time.perf_counter()
    collisions = validate.collisions(design) if check else []
    t3 = time.perf_counter()
    motion = validate.motion_collisions(design, rest=collisions) if check and design.pivots else []
    t4 = time.perf_counter()

    warnings = list(design.warnings) + nest_warnings
    if values["cut_color"] == values["engrave_color"]:
        warnings.append("Cut and engrave colours are the same - laser software can't tell cuts from engraving.")
    warnings += design.pivot_problems()
    warnings += design.trajectory_problems()
    if collisions:
        warnings.append(f"{len(collisions)} part pair(s) overlap in 3D - see collisions.")
    hits = [m for m in motion if "volume_mm3" in m]
    if hits:
        warnings.append(f"{len(hits)} part pair(s) collide while moving - see motion_collisions.")
    return Run(
        id=uuid.uuid4().hex[:10], generator=generator_id, params=dict(values), design=design,
        sheets=sheets, warnings=warnings, collisions=collisions, motion_collisions=motion,
        timings={"generate": round(t1 - t0, 3), "nest": round(t2 - t1, 3), "validate": round(t3 - t2, 3),
                 "motion": round(t4 - t3, 3)},
    )
