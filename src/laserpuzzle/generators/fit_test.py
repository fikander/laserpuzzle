"""Fit-test coupon: a comb of slots with stepped clearances plus a test key.

Cut this once per material/machine combination, push the key into each
slot and pick the clearance that feels right (snug press fit for permanent
joints, sliding fit for puzzles). Enter it as "Slot clearance" everywhere else.
It is also the reference example of a parametric generator (no input file).
"""

from __future__ import annotations

from ..core import font
from ..core.design import Design, Part, horizontal, plane_transform
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
        d.notes += [
            "Cut with your normal power/speed settings and the kerf entered under Material & machine.",
            "Push the key into each slot. Pick the clearance with the fit you want and use it as 'Slot clearance'.",
            "If even the loosest slot is tight, your kerf value is too small (or the sheet is thicker than entered).",
        ]
        return d

