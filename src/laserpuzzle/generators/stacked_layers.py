"""Stacked layers: slice a 3D model into horizontal plates with gaps,
held together by a central connector.

Connectors
----------
spine  A vertical plate (the model's XZ silhouette, inset) joined to every
       layer with a half-lap: the spine gets a slot from its left edge to the
       middle of the overlap, the layer gets a slot from the middle to its
       right edge. Each layer is pushed onto the spine moving towards +X.
       Gaps between layers show the spine's silhouette.
dowel  A round rod (bought, not cut) through a hole in every layer, with
       laser-cut spacer rings filling the gaps. Gap is rounded to a whole
       number of sheet thicknesses.
"""

from __future__ import annotations

import math

from shapely.geometry import Point

from ..core.design import Design, Hardware, Part, horizontal, vertical_xz
from ..core.geometry import BIG, as_lines, as_polygons, band_x, clean, largest, rect, section
from ..core.mesh import UP_AXES, load_model
from ..core.params import Param, Values
from .base import Context, Generator, register

import numpy as np


@register
class StackedLayers(Generator):
    id = "stacked-layers"
    name = "Stacked layers"
    description = (
        "Slices a 3D model into horizontal layers separated by gaps and joins them with a "
        "central spine (half-lap) or a dowel with spacer rings. Good for chess pieces, "
        "vases, busts and other mostly-vertical objects."
    )
    params = [
        Param("model", "file", "", "3D model", accept=[".stl", ".obj", ".ply", ".3mf", ".glb"],
              help="Mesh file (STL recommended).", group="Model"),
        Param("up_axis", "choice", "auto", "Up axis", choices=UP_AXES,
              help="Which axis of the file points up. 'auto' = the longest one.", group="Model"),
        Param("flip", "bool", False, "Upside down", help="Flip if the model comes out inverted.", group="Model"),
        Param("rotate", "float", 0.0, "Rotate about vertical", unit="°", min=-180, max=180, step=5,
              help="Chooses which side of the model the spine runs along.", group="Model"),
        Param("height", "float", 60.0, "Height", unit="mm", min=0, max=1000, step=1,
              help="Scale the model to this height. 0 keeps the file's units (assumed mm).", group="Model"),
        Param("layer_gap", "float", 3.0, "Gap between layers", unit="mm", min=0, max=50, step=0.5, group="Layers"),
        Param("section_mode", "choice", "middle", "Layer outline", choices=["middle", "max", "min"],
              help="Where each layer samples the model: at its mid-height, the union (max) "
                   "or intersection (min) of its top and bottom faces.", group="Layers"),
        Param("min_feature", "float", 1.0, "Smallest feature", unit="mm", min=0, max=10, step=0.1,
              help="Features thinner than this are removed (laser-cut wood breaks below ~1 mm).",
              group="Layers"),
        Param("engrave_next", "bool", True, "Engrave next layer outline",
              help="Score the outline of the layer above onto each layer - looks nice and helps alignment.",
              group="Layers"),
        Param("connector", "choice", "spine", "Connector", choices=["spine", "dowel"], group="Connector"),
        Param("spine_margin", "float", 2.0, "Spine inset", unit="mm", min=0, max=30, step=0.5,
              help="How far the spine sits inside the model silhouette.", group="Connector"),
        Param("spine_min_width", "float", 8.0, "Spine minimum width", unit="mm", min=2, max=100, step=0.5,
              help="Keeps the spine at least this wide at thin necks.", group="Connector"),
        Param("dowel_diameter", "float", 6.0, "Dowel diameter", unit="mm", min=1, max=50, step=0.5,
              help="Measure your rod. The hole is this + clearance.", group="Connector"),
        Param("spacer_diameter", "float", 12.0, "Spacer outer diameter", unit="mm", min=2, max=100, step=0.5,
              group="Connector"),
    ]

    # ------------------------------------------------------------------ main
    def generate(self, v: Values, ctx: Context) -> Design:
        d = Design()
        if not v.model:
            raise ValueError("choose a model file")
        mesh, info = load_model(ctx.resolve(v.model), v.up_axis, v.flip, v.height, v.rotate)
        d.source_mesh = mesh
        if not info["watertight"]:
            d.warn("Mesh is not watertight - sections may have gaps. Repair it (e.g. in Meshmixer/Blender) if layers look wrong.")

        t = v.thickness
        c = v.clearance
        H = float(mesh.extents[2])
        gap = v.layer_gap
        if v.connector == "dowel" and gap > 0:
            k = max(1, round(gap / t))
            if abs(k * t - gap) > 1e-6:
                d.notes.append(f"Gap rounded to {k} spacer(s) x {t} mm = {k * t:.2f} mm.")
            gap = k * t
        pitch = t + gap
        n = int(math.floor((H - t) / pitch + 1e-9)) + 1
        if n < 2:
            raise ValueError(f"model is too short ({H:.1f} mm) for 2 layers at {pitch:.1f} mm pitch")
        z_bottoms = [i * pitch for i in range(n)]
        z_top = z_bottoms[-1] + t

        layers = []
        for i, zb in enumerate(z_bottoms):
            g = self._layer_outline(mesh, zb, t, v.section_mode, v.min_feature)
            layers.append(g)

        if v.connector == "spine":
            self._spine(d, mesh, layers, z_bottoms, z_top, v)
        else:
            self._dowel(d, layers, z_bottoms, z_top, gap, v)

        d.stats.update({
            "layers": n,
            "pitch_mm": round(pitch, 3),
            "gap_mm": round(gap, 3),
            "model_height_mm": round(H, 2),
            "assembled_height_mm": round(z_top, 2),
            "footprint_mm": [round(float(x), 1) for x in mesh.extents[:2]],
            "mesh": info,
        })
        if H - z_top > 0.5 * pitch:
            d.notes.append(f"Top {H - z_top:.1f} mm of the model is above the last layer; adjust height or gap to fit it.")
        return d

    # --------------------------------------------------------------- helpers
    @staticmethod
    def _layer_outline(mesh, zb: float, t: float, mode: str, min_feature: float):
        def sec(z):
            return section(mesh, (0, 0, z), (0, 0, 1), (1, 0, 0), (0, 1, 0))

        eps = min(0.05, t * 0.05)
        if mode == "middle":
            g = sec(zb + t / 2)
        else:
            parts = [sec(zb + eps), sec(zb + t / 2), sec(zb + t - eps)]
            g = parts[0]
            for p in parts[1:]:
                g = g.union(p) if mode == "max" else g.intersection(p)
        g = clean(g, simplify=0.03)
        if min_feature > 0 and not g.is_empty:
            r = min_feature / 2
            g = g.buffer(-r, join_style="round").buffer(r, join_style="round")
            g = clean(g, min_area=min_feature ** 2)
        return g

    @staticmethod
    def _next_outline_engrave(cur, nxt) -> list:
        if nxt is None or nxt.is_empty or cur.is_empty:
            return []
        return as_lines(nxt.boundary.intersection(cur.buffer(-0.4)))

    def _keep_main(self, d: Design, g, name: str, anchor=None):
        polys = as_polygons(g)
        if not polys:
            return g
        if anchor is not None:
            hit = [p for p in polys if p.intersects(anchor)]
            main = max(hit, key=lambda p: p.area) if hit else max(polys, key=lambda p: p.area)
        else:
            main = max(polys, key=lambda p: p.area)
        dropped = [p for p in polys if p is not main]
        if dropped:
            d.warn(f"{name}: {len(dropped)} detached island(s) ({sum(p.area for p in dropped):.0f} mm²) dropped - they would not be held by the connector.")
        return main

    # ----------------------------------------------------------------- spine
    def _spine(self, d: Design, mesh, layers, z_bottoms, z_top, v: Values) -> None:
        t, c = v.thickness, v.clearance
        slot_w = t + c
        sil = clean(section(mesh, (0, 0, 0), (0, 1, 0), (1, 0, 0), (0, 0, 1)), simplify=0.03)
        if sil.is_empty:
            raise ValueError("model has no material on the central XZ plane - try rotating it")
        w = v.spine_min_width
        spine = sil.buffer(-v.spine_margin).union(rect(-w / 2, 0, w / 2, z_top).intersection(sil))
        spine = spine.intersection(rect(-BIG, 0, BIG, z_top))
        spine = self._keep_main(d, clean(spine, min_area=1.0), "Spine")

        ext_y = float(mesh.extents[1])
        strip = rect(-BIG, -t / 2, BIG, t / 2)
        for i, (zb, g) in enumerate(zip(z_bottoms, layers)):
            name = f"Layer {i + 1:02d}"
            spans = band_x(spine, zb, zb + t)
            if g.is_empty:
                d.warn(f"{name}: model has no cross-section here - skipped.")
                continue
            if not spans:
                d.warn(f"{name}: spine does not reach this layer - it will be loose.")
                layer = largest(g)
            else:
                a, b = min(spans, key=lambda s: (0 if s[0] <= 0 <= s[1] else 1, -(s[1] - s[0])))
                mid = (a + b) / 2
                spine = spine.difference(rect(-BIG, zb - c / 2, mid, zb + t + c / 2))
                layer = g.difference(rect(mid, -slot_w / 2, BIG, slot_w / 2))
                layer = self._keep_main(d, clean(layer, min_area=1.0), name, anchor=Point(a + 0.25 * (b - a), 0))
                lx = band_x_strip(layer, strip)
                if lx and (lx[0] > a + 0.01):
                    d.warn(f"{name}: spine is wider than the layer on the -X side ({lx[0] - a:.1f} mm sticks out). Increase spine inset.")
                if b - a < 2 * t:
                    d.warn(f"{name}: joint is only {b - a:.1f} mm long - weak. Increase spine minimum width.")
            nxt = layers[i + 1] if i + 1 < len(layers) else None
            d.parts.append(Part(
                name=name, outline=layer, thickness=t, transform=horizontal(zb),
                engrave=self._next_outline_engrave(layer, nxt) if v.engrave_next else [],
                label=f"L{i + 1}", group="layer", explode=(0.0, 0.0, 1.2 * zb + 4 * i),
                meta={"z": zb},
            ))

        spine = self._keep_main(d, clean(spine, min_area=1.0), "Spine")
        d.parts.insert(0, Part(
            name="Spine", outline=spine, thickness=t, transform=vertical_xz(0.0, t),
            label="S", group="spine", explode=(0.0, ext_y * 1.2 + 10, 0.0),
        ))
        d.notes += [
            "Hold the spine upright with its slots on the left (-X).",
            "Slide each layer onto the spine moving it towards +X, notch first, so the layer's notch "
            "swallows the spine and the spine's slot holds the layer. Order does not matter; match the labels L1 (bottom) to L%d (top)." % len(layers),
            "If the fit is too loose or tight, change 'Slot clearance' and re-cut a test pair.",
        ]


    # ----------------------------------------------------------------- dowel
    def _dowel(self, d: Design, layers, z_bottoms, z_top, gap, v: Values) -> None:
        t, c = v.thickness, v.clearance
        hole_r = (v.dowel_diameter + c) / 2
        R = v.spacer_diameter / 2
        if R <= hole_r + 0.8:
            raise ValueError("spacer diameter must be at least ~2 mm larger than the dowel")
        hole = Point(0, 0).buffer(hole_r, quad_segs=32)
        for i, (zb, g) in enumerate(zip(z_bottoms, layers)):
            name = f"Layer {i + 1:02d}"
            if g.is_empty:
                d.warn(f"{name}: model has no cross-section here - skipped.")
                continue
            layer = self._keep_main(d, g, name, anchor=Point(0, 0))
            if not layer.buffer(-0.01).contains(Point(0, 0).buffer(hole_r + 1.0)):
                d.warn(f"{name}: too thin around the dowel (needs Ø{2 * hole_r + 2:.1f} mm). Use a thinner dowel.")
            layer = clean(layer.difference(hole), min_area=1.0)
            nxt = layers[i + 1] if i + 1 < len(layers) else None
            d.parts.append(Part(
                name=name, outline=layer, thickness=t, transform=horizontal(zb),
                engrave=self._next_outline_engrave(layer, nxt) if v.engrave_next else [],
                label=f"L{i + 1}", group="layer", explode=(0.0, 0.0, 1.5 * zb + 6 * i),
            ))
        if gap > 0:
            ring = Point(0, 0).buffer(R, quad_segs=32).difference(hole)
            k = int(round(gap / t))
            for i, zb in enumerate(z_bottoms[:-1]):
                for j in range(k):
                    z = zb + t + j * t
                    d.parts.append(Part(
                        name=f"Spacer {i + 1}.{j + 1}", outline=ring, thickness=t, transform=horizontal(z),
                        group="spacer", explode=(0.0, 0.0, 1.5 * z + 6 * (i + 0.5)),
                    ))
                    if not layers[i].is_empty and not layers[i + 1].is_empty:
                        if not layers[i].buffer(0.01).contains(Point(0, 0).buffer(R)):
                            d.warn(f"Spacer above layer {i + 1} is wider than the layer below - reduce spacer diameter.")
        d.hardware.append(Hardware(
            name=f"Dowel Ø{v.dowel_diameter:g} mm", kind="cylinder",
            size={"radius": v.dowel_diameter / 2, "height": round(z_top, 2)},
            transform=np.eye(4), note=f"cut to {z_top:.1f} mm",
        ))
        d.notes += [
            f"Cut a Ø{v.dowel_diameter:g} mm dowel to {z_top:.1f} mm.",
            "Thread L1, then spacers, then L2 ... up to the top layer. A drop of glue at the bottom and top layer locks it.",
        ]


def band_x_strip(geom, strip) -> list[float]:
    inter = geom.intersection(strip)
    if inter.is_empty:
        return []
    minx, _, maxx, _ = inter.bounds
    return [minx, maxx]
