"""Fit-test coupon: a comb of slots with stepped clearances plus a test key.

Cut this once per material/machine combination, push the key into each
slot and pick the clearance that feels right (snug press fit for permanent
joints, sliding fit for puzzles). Enter it as "Slot clearance" everywhere else.
The optional hole strip does the same for round rods (axles, dowels): holes
of rod diameter + stepped offsets. Push the rod through each and note the
offset for a press fit (wheel on axle) and a running fit (axle in bearing).
It is also the reference example of a parametric generator (no input file).
"""

from __future__ import annotations

import numpy as np
from shapely.geometry import Point

from ..core import font
from ..core.design import Design, Hardware, Part, horizontal, plane_transform
from ..core.geometry import rect
from ..core.params import Param, Values
from .base import Context, Generator, register


@register
class FitTest(Generator):
    id = "fit-test"
    name = "Fit test coupon"
    description = (
        "Calibration piece: slots with stepped clearances plus a key. Cut it first for every new "
        "material to find the right kerf and slot clearance."
    )
    params = [
        Param("first", "float", -0.15, "First clearance", unit="mm", min=-1, max=1, step=0.01, group="Coupon"),
        Param("step", "float", 0.05, "Clearance step", unit="mm", min=0.01, max=0.5, step=0.01, group="Coupon"),
        Param("count", "int", 7, "Number of slots", min=2, max=20, group="Coupon"),
        Param("slot_depth", "float", 10.0, "Slot depth", unit="mm", min=3, max=50, step=0.5, group="Coupon"),
        Param("rod_diameter", "float", 3.0, "Rod diameter", unit="mm", min=0, max=30, step=0.1,
              help="Measured diameter of your rod (axle, dowel). Adds a strip of test holes; 0 = no hole strip.",
              group="Hole strip"),
        Param("hole_first", "float", -0.2, "First hole offset", unit="mm", min=-1, max=1, step=0.01,
              help="Hole diameter = rod diameter + offset.", group="Hole strip"),
        Param("hole_step", "float", 0.05, "Hole offset step", unit="mm", min=0.01, max=0.5, step=0.01,
              group="Hole strip"),
        Param("hole_count", "int", 11, "Number of holes", min=2, max=25, group="Hole strip"),
    ]

    def generate(self, v: Values, ctx: Context) -> Design:
        d = Design()
        t = v.thickness
        pitch = max(10.0, t + 7)
        width = v.count * pitch + 6
        height = v.slot_depth + 14
        comb = rect(0, 0, width, height)
        engrave = []
        values = [round(v.first + i * v.step, 3) for i in range(v.count)]
        for i, c in enumerate(values):
            cx = 3 + pitch * (i + 0.5)
            w = t + c
            comb = comb.difference(rect(cx - w / 2, height - v.slot_depth, cx + w / 2, height + 1))
            engrave += font.text_lines(f"{c:+.2f}".replace("+", ""), 2.2, cx, (height - v.slot_depth) / 2, 90)
        d.parts.append(Part("Comb", comb, t, horizontal(0), engrave=engrave, group="comb",
                            explode=(0, 0, 0)))
        key = rect(0, 0, 20, v.slot_depth + 10)
        mid = min(range(len(values)), key=lambda i: abs(values[i]))
        cx = 3 + pitch * (mid + 0.5)
        # Preview: key stands upright in the slot closest to zero clearance.
        # It lies in the YZ plane (thickness along X, across the slot), local x -> world y.
        key_at = plane_transform((cx, height - v.slot_depth, -5), (0, 1, 0), (0, 0, 1), t, centered=True)
        d.parts.append(Part("Key", key, t, key_at, label="KEY", group="key",
                            explode=(0, 0, v.slot_depth + 15)))
        d.stats.update({"clearances": values, "nominal_thickness": t})
        if v.rod_diameter > 0:
            self._hole_strip(d, v)
        d.notes += [
            "Cut with your normal power/speed settings and the kerf entered under Material & machine.",
            "Push the key into each slot. Pick the clearance with the fit you want and use it as 'Slot clearance'.",
            "If even the loosest slot is tight, your kerf value is too small (or the sheet is thicker than entered).",
        ]
        return d


    @staticmethod
    def _hole_strip(d: Design, v: Values) -> None:
        rod = v.rod_diameter
        offsets = [round(v.hole_first + i * v.hole_step, 3) for i in range(v.hole_count)]
        if rod + offsets[0] < 0.5:
            raise ValueError("smallest test hole would be under 0.5 mm - raise 'First hole offset'")
        r_max = (rod + offsets[-1]) / 2
        pitch = max(rod + 4, 7.0)
        text_h = 2.2
        label_len = max(font.text_width(f"{o:+.2f}".replace("+", ""), text_h) for o in offsets)
        title_w = 7.0
        width = title_w + v.hole_count * pitch + 3
        hole_y = 3 + label_len + 2 + r_max
        height = hole_y + r_max + 3
        strip = rect(0, 0, width, height)
        engrave = font.text_lines(f"ROD {rod:g}", 3.0, title_w / 2 + 1, height / 2, 90)
        holes = []
        for i, o in enumerate(offsets):
            cx = title_w + pitch * (i + 0.5)
            holes.append(Point(cx, hole_y).buffer((rod + o) / 2, quad_segs=32))
            engrave += font.text_lines(f"{o:+.2f}".replace("+", ""), text_h, cx, 3 + label_len / 2, 90)
        for h in holes:
            strip = strip.difference(h)
        y0 = -height - 8
        d.parts.append(Part("Hole strip", strip, v.thickness, _translate(0, y0, 0),
                            engrave=engrave, group="holes"))
        # Preview: the rod sits in the hole closest to zero offset.
        mid = min(range(len(offsets)), key=lambda i: abs(offsets[i]))
        d.hardware.append(Hardware(
            name=f"Rod Ø{rod:g} mm", kind="cylinder", size={"radius": rod / 2, "height": 20.0},
            transform=_translate(title_w + pitch * (mid + 0.5), y0 + hole_y, -6),
            note="your axle / dowel stock (not cut)",
        ))
        d.stats.update({"hole_offsets": offsets, "rod_diameter": rod})
        d.notes += [
            f"Hole strip: push the Ø{rod:g} mm rod through each hole (numbers = hole diameter minus rod diameter).",
            "Press fit (wheel glued/pressed on an axle): the rod goes in with a firm push and cannot be turned by hand.",
            "Running fit (axle turning in a bearing): the rod spins freely with no visible wobble.",
            "Laser holes are slightly conical (wider on the top face); test from both sides and use the tighter result.",
        ]


def _translate(x: float, y: float, z: float) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m
