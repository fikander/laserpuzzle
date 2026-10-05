"""Vehicle: a parametric push-toy car built as a box of flat panels.

Body
----
The car is described by a side profile: a closed polygon in the XZ plane
(front at +X, ground z=0) made of straight segments - front, hood,
windscreen, roof, rear window, boot, rear, floor. Every segment becomes a
panel spanning the car's width between two side plates; each side plate is
the whole profile grown by a small `rim`, so slots for the panel tabs stay
inside the side plate. Panels have their outer face on the profile line.

At each crease between two panels the longer panel runs to the outer
corner and the shorter one is trimmed just enough not to overlap it (cut
edges are square, so convex creases show a small V-notch). The panels'
short edges are joined to the sides with `joints.tab_slot`.

Running gear
------------
Steel rod axles pass through both side plates above the floor and turn in
running-fit holes (optionally doubled with glued bearing pads). Wheels sit
outside the body and are glued onto the rod (press fit): hub spacer, inner
layer, optional narrower middle layer (groove for an O-ring tyre) and an
outer cap without a hole, so no rod end is exposed.

Dimensions come from real-world presets scaled 1:N. "Toy proportions"
enlarges the wheels so the car rolls on carpet and the axle clears the floor.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from shapely import affinity
from shapely.geometry import LineString, Point, Polygon, box

from ..core.design import Design, Hardware, Part, plane_transform
from ..core.geometry import BIG, as_lines, as_polygons, clean, rect
from ..core.joints import tab_slot
from ..core.params import Param, Values
from .base import Context, Generator, register

# Real-world presets (mm). `top` runs from the front bumper over the roof to the
# rear: (segment name, end point x from the front, z above ground). The body
# starts at (0, floor) and the last point must be (length, floor).
PRESETS: dict[str, dict] = {
    "sedan": dict(length=4600, width=1800, wheel=650, front_axle=900, wheelbase=2700, floor=180, doors=2,
                  windows=2, top=[("front", 0, 720), ("hood", 1200, 900), ("windscreen", 1900, 1430),
                                  ("roof", 3000, 1450), ("rear window", 3700, 1050), ("boot", 4600, 1000),
                                  ("rear", 4600, 180)]),
    "hatchback": dict(length=4100, width=1780, wheel=630, front_axle=850, wheelbase=2600, floor=180, doors=2,
                      windows=2, top=[("front", 0, 720), ("hood", 1000, 880), ("windscreen", 1700, 1460),
                                      ("roof", 3350, 1470), ("hatch", 4100, 1000), ("rear", 4100, 180)]),
    "sports": dict(length=4400, width=1900, wheel=660, front_axle=950, wheelbase=2500, floor=120, doors=1,
                   windows=1, top=[("front", 0, 600), ("hood", 1600, 850), ("windscreen", 2300, 1180),
                                   ("roof", 2900, 1200), ("rear window", 3900, 950), ("boot", 4400, 900),
                                   ("rear", 4400, 120)]),
    "jeep": dict(length=4300, width=1850, wheel=760, front_axle=800, wheelbase=2500, floor=260, doors=2,
                 windows=3, top=[("front", 0, 1000), ("hood", 1300, 1100), ("windscreen", 1600, 1780),
                                 ("roof", 4300, 1800), ("rear", 4300, 260)]),
    "pickup": dict(length=5300, width=1900, wheel=780, front_axle=950, wheelbase=3300, floor=250, doors=1,
                   windows=1, top=[("front", 0, 1000), ("hood", 1400, 1150), ("windscreen", 2000, 1780),
                                   ("roof", 2900, 1800), ("cab back", 2950, 1150), ("bed cover", 5300, 1150),
                                   ("rear", 5300, 250)]),
    "van": dict(length=4900, width=1900, wheel=650, front_axle=900, wheelbase=3000, floor=180, doors=1,
                windows=3, top=[("front", 0, 800), ("hood", 600, 1000), ("windscreen", 1100, 1850),
                                ("roof", 4900, 1950), ("rear", 4900, 180)]),
    "bus": dict(length=10000, width=2500, wheel=1000, front_axle=2200, wheelbase=5500, floor=350, doors=0,
                windows=7, top=[("front", 0, 1300), ("windscreen", 150, 2900), ("roof", 9900, 3000),
                                ("rear", 10000, 350)]),
}

TOY_WHEEL = 1.35          # wheel enlargement in toy proportions
AXLE_GAP = 1.5            # rod surface to floor top
WHEEL_GAP = 0.5           # hub spacer to side plate (axial play)


@dataclass
class Panel:
    name: str
    a: np.ndarray             # outer start point (x, z)
    u: np.ndarray             # unit direction along the profile
    n: np.ndarray             # outward normal
    length: float
    s0: float = 0.0
    s1: float = 0.0

    def section(self, t: float, s0: float | None = None, s1: float | None = None) -> Polygon:
        """Cross-section in the XZ plane between along-positions s0..s1."""
        s0 = self.s0 if s0 is None else s0
        s1 = self.s1 if s1 is None else s1
        p = [self.a + self.u * s for s in (s0, s1)]
        return Polygon([tuple(p[0]), tuple(p[1]), tuple(p[1] - self.n * t), tuple(p[0] - self.n * t)])

    def along(self, pts) -> np.ndarray:
        return (np.asarray(pts, float) - self.a) @ self.u


@register
class Vehicle(Generator):
    id = "vehicle"
    name = "Vehicle (push toy)"
    description = (
        "Parametric toy car from presets (sedan, hatchback, sports, jeep, pickup, van, bus) at a chosen scale: "
        "side plates, a chain of tabbed body panels, steel-rod axles in bearing holes and laminated wheels "
        "with blind hub caps. No input drawing needed."
    )
    params = [
        Param("preset", "choice", "sedan", "Vehicle type", choices=list(PRESETS), group="Vehicle"),
        Param("scale", "float", 36.0, "Scale 1:N", min=5, max=200, step=1,
              help="Real-world dimensions are divided by N. 1:36 makes a ~13 cm sedan.", group="Vehicle"),
        Param("length", "float", 0.0, "Model length", unit="mm", min=0, max=1000, step=1,
              help="Overrides the scale to fit this length (0 = use scale).", group="Vehicle"),
        Param("toy_proportions", "bool", True, "Toy proportions",
              help=f"Wheels {TOY_WHEEL}x larger than scale: rolls better and leaves room for the axle.",
              group="Vehicle"),
        Param("width", "float", 0.0, "Body width", unit="mm", min=0, max=500, step=1,
              help="Width of the body between the wheels (0 = from preset and scale).", group="Vehicle"),
        Param("wheel_diameter", "float", 0.0, "Wheel diameter", unit="mm", min=0, max=200, step=0.5,
              help="0 = from preset and scale.", group="Wheels"),
        Param("wheel_layers", "int", 3, "Wheel layers", min=2, max=3,
              help="Layers per wheel including the blind outer cap (plus the hub spacer).", group="Wheels"),
        Param("tyre_groove", "bool", True, "Tyre groove",
              help="Middle layer smaller so an O-ring or rubber band can sit in it as a tyre (3 layers).",
              group="Wheels"),
        Param("groove_depth", "float", 1.5, "Groove depth", unit="mm", min=0.5, max=5, step=0.1, group="Wheels"),
        Param("hub_spacer", "bool", True, "Hub spacer",
              help="Small ring between wheel and body: less friction than the whole wheel face.", group="Wheels"),
        Param("rod_diameter", "float", 3.0, "Axle rod diameter", unit="mm", min=1, max=10, step=0.1,
              help="Measured diameter of the steel rod.", group="Axles"),
        Param("press_fit", "float", -0.1, "Press-fit hole offset", unit="mm", min=-1, max=1, step=0.01,
              help="Wheel hole = rod + this. Find it with the fit-test hole strip.", group="Axles"),
        Param("running_fit", "float", 0.15, "Running-fit hole offset", unit="mm", min=-0.5, max=1, step=0.01,
              help="Bearing hole = rod + this. Find it with the fit-test hole strip.", group="Axles"),
        Param("bearing_pads", "int", 1, "Bearing pads per side", min=0, max=2,
              help="Plates glued inside each side around the axle hole: longer bearing, less wobble.",
              group="Axles"),
        Param("rim", "float", 2.0, "Side rim", unit="mm", min=1.5, max=10, step=0.5,
              help="How far the side plates stand out beyond the body panels.", group="Body"),
        Param("corner_radius", "float", 1.5, "Corner radius", unit="mm", min=0, max=10, step=0.5,
              help="Rounds the outer corners of the side plates (no sharp points on a toy).", group="Body"),
        Param("windows", "choice", "engrave", "Windows", choices=["engrave", "cut", "none"], group="Body"),
        Param("details", "bool", True, "Engraved details",
              help="Doors, wheel arches, lights, grille.", group="Body"),
    ]

    # ------------------------------------------------------------------ main
    def generate(self, v: Values, ctx: Context) -> Design:
        d = Design()
        t = v.thickness
        pr = PRESETS[v.preset]
        N = pr["length"] / v.length if v.length > 0 else v.scale
        rod = v.rod_diameter

        W = v.width if v.width > 0 else pr["width"] / N
        D = v.wheel_diameter if v.wheel_diameter > 0 else pr["wheel"] / N * (TOY_WHEEL if v.toy_proportions else 1)
        R = D / 2
        z_axle = R
        # Floor: as close to scale as possible, between "side plates clear the ground"
        # and "axle runs above the floor".
        lo = v.rim + 2.0
        hi = z_axle - rod / 2 - AXLE_GAP - t
        if hi < lo:
            need = 2 * (lo + t + AXLE_GAP + rod / 2)
            raise ValueError(f"wheels (Ø{D:.1f} mm) are too small to run a Ø{rod:g} mm axle above the floor; "
                             f"use wheels of at least Ø{need:.1f} mm or turn on toy proportions")
        z_floor = min(max(pr["floor"] / N, lo), hi)
        if W < 4 * t + 10:
            raise ValueError(f"body is too narrow ({W:.1f} mm)")

        L = pr["length"] / N
        xm = lambda x_real: (pr["length"] / 2 - x_real) / N            # noqa: E731  front at +X
        pts = [np.array([xm(0), z_floor])]
        names = []
        for name, x, z in pr["top"]:
            pts.append(np.array([xm(x), z_floor if z == pr["floor"] else z / N]))
            names.append(name)
        names.append("floor")
        profile = Polygon([tuple(p) for p in pts])
        belt = next((pts[i][1] for i, nm in enumerate(names) if nm == "windscreen"), None)
        axles = [xm(pr["front_axle"]), xm(pr["front_axle"] + pr["wheelbase"])]

        panels = self._panels(pts, names, t)
        if any(p.s1 - p.s0 < 2 * t for p in panels):
            short = [p.name for p in panels if p.s1 - p.s0 < 2 * t]
            d.warn(f"Very short panel(s): {', '.join(short)} - tabs will be weak. Use a larger scale.")

        # ---- side plates (built in world XZ, then placed)
        side = profile.buffer(v.rim, join_style="mitre", mitre_limit=3.0)
        if v.corner_radius > 0:
            r = min(v.corner_radius, v.rim * 0.9)
            side = side.buffer(-r, join_style="round").buffer(r, join_style="round")
        run_r = (rod + v.running_fit) / 2
        engr: list[LineString] = []
        win_shapes = self._windows(profile, belt, pr["windows"], v.rim + t + 1.5) if belt is not None else []
        if v.windows == "cut":
            for w in win_shapes:
                side = side.difference(w)
        elif v.windows == "engrave":
            engr += [l for w in win_shapes for l in as_lines(w)]
        if v.details:
            engr += self._side_details(side, win_shapes, pr["doors"], belt, z_floor + t, axles, R, v.rim)
        for xa in axles:
            side = side.difference(Point(xa, z_axle).buffer(run_r, quad_segs=24))
        side = clean(side)

        Wi = W - 2 * t
        sides = []
        for s in (-1, 1):
            if s > 0:   # right: local x = -X so the outer face (local +Z) points to +Y
                outline = affinity.scale(side, -1, 1, origin=(0, 0))
                lines = [affinity.scale(l, -1, 1, origin=(0, 0)) for l in engr]
                tf = plane_transform((0, W / 2 - t, 0), (-1, 0, 0), (0, 0, 1))
            else:
                outline, lines = side, list(engr)
                tf = plane_transform((0, -W / 2 + t, 0), (1, 0, 0), (0, 0, 1))
            sides.append(Part("Side " + ("right" if s > 0 else "left"), outline, t, tf, engrave=lines,
                              group="side", explode=(0.0, s * (W + 10), 0.0)))
        d.parts += sides

        # ---- body panels
        for p in panels:
            origin = p.a - p.n * t
            tf = plane_transform((origin[0], -Wi / 2, origin[1]), (0, 1, 0), (p.u[0], 0, p.u[1]))
            part = Part(p.name.capitalize(), rect(0, p.s0, Wi, p.s1), t, tf,
                        engrave=self._panel_details(p, Wi, v) if v.details or v.windows == "engrave" else [],
                        group="panel", explode=(15 * p.n[0], 0.0, 15 * p.n[1]))
            d.parts.append(part)
            lp = p.s1 - p.s0
            margin = min(t, 0.2 * lp)
            tw = min(3 * t, 0.6 * lp)
            for sp, edge in ((sides[0], ((0, p.s0), (0, p.s1))), (sides[1], ((Wi, p.s0), (Wi, p.s1)))):
                j = tab_slot(part, sp, edge, clearance=v.clearance, tab_width=tw, margin=margin)
                for w in j.warnings:
                    d.warn(w)

        # ---- bearing pads
        floor_top = z_floor + t
        pw = rod + 8
        pad_top = z_axle + rod / 2 + 4
        interior = profile.buffer(-t, join_style="mitre", mitre_limit=3.0)
        for xa in axles:
            if not interior.contains(Point(xa, z_axle).buffer(rod / 2 + 0.5)):
                d.warn(f"Axle at x={xa:.1f} mm runs into a body panel - use smaller wheels or a taller body.")
        if v.bearing_pads:
            for xa in axles:
                pad = rect(xa - pw / 2, floor_top, xa + pw / 2, pad_top).intersection(interior)
                if not pad.buffer(1e-6).contains(Point(xa, z_axle).buffer(run_r + 1.0)):
                    d.warn(f"Bearing pad at x={xa:.1f} mm is cut short by the body - little wood around the hole.")
                pad = clean(pad.difference(Point(xa, z_axle).buffer(run_r, quad_segs=24)), min_area=1.0)
                for s in (-1, 1):
                    for k in range(v.bearing_pads):
                        y_in = W / 2 - t - (k + 1) * t       # inner face of this layer (|y|)
                        if s > 0:
                            o, tf = affinity.scale(pad, -1, 1, origin=(0, 0)), plane_transform(
                                (0, y_in, 0), (-1, 0, 0), (0, 0, 1))
                        else:
                            o, tf = pad, plane_transform((0, -y_in, 0), (1, 0, 0), (0, 0, 1))
                        d.parts.append(Part(f"Bearing pad {'F' if xa > 0 else 'R'}{'R' if s > 0 else 'L'}{k + 1}",
                                            o, t, tf, label="B", group="bearing",
                                            explode=(0.0, -s * 8 * (k + 1), 0.0)))

        # ---- wheels
        layers = self._wheel_layers(v, R, rod)
        y = W / 2 + WHEEL_GAP
        rod_end = y
        for li, (name, outline, has_hole) in enumerate(layers):
            for xa in axles:
                for s in (-1, 1):
                    if s > 0:
                        tf = plane_transform((xa, y, z_axle), (-1, 0, 0), (0, 0, 1))
                    else:
                        tf = plane_transform((xa, -y, z_axle), (1, 0, 0), (0, 0, 1))
                    cap = name == "Wheel cap"
                    d.parts.append(Part(
                        f"{name} {'F' if xa > 0 else 'R'}{'R' if s > 0 else 'L'}", outline, t, tf,
                        engrave=self._hubcap(R) if cap and v.details else [],
                        label=None if cap else name.split()[-1][0].upper(),
                        group="hub" if name == "Hub spacer" else "wheel",
                        explode=(0.0, s * (20 + 6 * li), 0.0)))
            y += t
            if has_hole:
                rod_end = y
        rod_len = 2 * rod_end
        for xa in axles:
            d.hardware.append(Hardware(
                name=f"Axle rod Ø{rod:g} mm", kind="cylinder", size={"radius": rod / 2, "height": round(rod_len, 2)},
                transform=plane_transform((xa, -rod_len / 2, z_axle), (0, 0, 1), (1, 0, 0)),
                note=f"steel rod cut to {rod_len:.1f} mm"))
        groove = v.tyre_groove and v.wheel_layers >= 3
        if groove:
            y_mid = W / 2 + WHEEL_GAP + t * (2 if v.hub_spacer else 1)      # middle layer, outer face side
            for xa in axles:
                for s in (-1, 1):
                    y0 = y_mid if s > 0 else -y_mid - t
                    d.hardware.append(Hardware(
                        name="O-ring tyre", kind="cylinder", size={"radius": round(R - 0.3, 2), "height": t},
                        transform=plane_transform((xa, y0, z_axle), (0, 0, 1), (1, 0, 0)),
                        note=f"ID ≈ {D - 2 * v.groove_depth - 1:.0f} mm, cord ≈ {min(t, 2 * v.groove_depth):.1f}"
                             " mm (or a rubber band)"))

        self._checks(d, panels, axles, z_axle, rod, pw, floor_top, t, R, D, W)

        total_w = 2 * y
        d.stats.update({
            "scale": f"1:{N:.0f}",
            "length_mm": round(L + 2 * v.rim, 1),
            "width_mm": round(total_w, 1),
            "body_width_mm": round(W, 1),
            "height_mm": round(max(p[1] for p in pts) + v.rim, 1),
            "wheel_diameter_mm": round(D, 1),
            "floor_height_mm": round(z_floor, 2),
            "rod_length_mm": round(rod_len, 1),
            "press_fit_hole_mm": round(rod + v.press_fit, 2),
            "running_fit_hole_mm": round(rod + v.running_fit, 2),
        })
        if v.toy_proportions:
            d.stats["note"] = "toy proportions (wheels not to scale)"
        d.notes += self._assembly(v, rod_len, groove, D)
        return d

    # --------------------------------------------------------------- panels
    @staticmethod
    def _panels(pts: list[np.ndarray], names: list[str], t: float) -> list[Panel]:
        n = len(pts)
        # Orientation: the loop runs front -> over the roof -> rear -> floor, i.e. clockwise
        # when seen with X right and Z up, so the right-hand normal (u.z, -u.x) points outward.
        panels = []
        for i in range(n):
            a, b = pts[i], pts[(i + 1) % n]
            ln = float(np.linalg.norm(b - a))
            if ln < 1e-6:
                raise ValueError(f"profile segment {names[i]} has zero length")
            u = (b - a) / ln
            panels.append(Panel(names[i], a, u, np.array([u[1], -u[0]]), ln, 0.0, ln))
        for i in range(n):
            a, b = panels[i], panels[(i + 1) % n]          # crease at the end of a / start of b
            win, lose = (a, b) if a.length >= b.length else (b, a)
            strip = lose.section(t, -BIG, BIG)
            inter = win.section(t, 0.0, win.length).intersection(strip).intersection(
                Point(*b.a).buffer(6 * t))
            if inter.area < 1e-9:
                continue
            al = lose.along(np.asarray(inter.exterior.coords) if isinstance(inter, Polygon)
                            else np.vstack([np.asarray(g.exterior.coords) for g in as_polygons(inter)]))
            if lose is b:
                b.s0 = max(b.s0, float(al.max()))
            else:
                a.s1 = min(a.s1, float(al.min()))
        for p in panels:
            if p.s1 - p.s0 <= 0.5:
                raise ValueError(f"panel {p.name} vanishes after trimming - profile too small for {t} mm sheet")
        return panels

    @staticmethod
    def _panel_details(p: Panel, Wi: float, v: Values) -> list[LineString]:
        lp = p.s1 - p.s0
        out: list[LineString] = []

        def rbox(x0, y0, x1, y1, r=0.8):
            g = box(x0, y0, x1, y1)
            r = min(r, (x1 - x0) / 3, (y1 - y0) / 3)
            return as_lines(g.buffer(-r).buffer(r)) if r > 0.05 else as_lines(g)

        glass = "window" in p.name or "windscreen" in p.name or p.name == "hatch"
        m = 1.5
        if glass and v.windows != "none" and lp > 2 * m + 1 and Wi > 2 * m + 1:
            out += rbox(m, p.s0 + m, Wi - m, p.s1 - m, 1.0)
        if not v.details or lp < 6:
            return out
        if p.name == "front":                       # local y runs upward
            top, h = p.s1, lp
            lw = 0.22 * Wi
            for x0 in (0.08 * Wi, Wi - 0.08 * Wi - lw):
                out += rbox(x0, top - 0.5 * h, x0 + lw, top - 0.2 * h)
            gx0, gx1 = 0.36 * Wi, 0.64 * Wi
            for k in range(3):
                yy = top - (0.25 + 0.12 * k) * h
                out.append(LineString([(gx0, yy), (gx1, yy)]))
            out.append(LineString([(0.04 * Wi, p.s0 + 0.18 * h), (0.96 * Wi, p.s0 + 0.18 * h)]))  # bumper
        elif p.name == "rear":                      # local y runs downward from the top
            top, h = p.s0, lp
            lw = 0.18 * Wi
            for x0 in (0.08 * Wi, Wi - 0.08 * Wi - lw):
                out += rbox(x0, top + 0.15 * h, x0 + lw, top + 0.4 * h)
            out += rbox(0.35 * Wi, top + 0.5 * h, 0.65 * Wi, top + 0.75 * h, 0.4)       # number plate
        return out

    # ---------------------------------------------------------------- sides
    @staticmethod
    def _windows(profile: Polygon, belt: float, count: int, inset: float) -> list[Polygon]:
        if count < 1:
            return []
        g = profile.buffer(-inset, join_style="mitre", mitre_limit=3.0).intersection(
            rect(-BIG, belt + 1.0, BIG, BIG))
        if g.is_empty:
            return []
        x0, _, x1, _ = g.bounds
        pillar = max(2.0, 0.08 * (x1 - x0) / count)
        for k in range(1, count):
            xc = x1 - (x1 - x0) * k / count
            g = g.difference(rect(xc - pillar / 2, -BIG, xc + pillar / 2, BIG))
        out = []
        for w in as_polygons(g):
            w = w.buffer(-0.8, join_style="round").buffer(0.8, join_style="round")
            if w.area > 6 and w.bounds[3] - w.bounds[1] > 2:
                out += as_polygons(w)
        return sorted(out, key=lambda w: -w.bounds[2])       # front first

    @staticmethod
    def _side_details(side, windows, doors, belt, floor_top, axles, R, rim) -> list[LineString]:
        out: list[LineString] = []
        inner = side.buffer(-1.0)
        arches = [Point(xa, R).buffer(R + 1.5, quad_segs=32) for xa in axles]
        for a in arches:                                    # wheel arch: upper half only
            out += as_lines(a.exterior.intersection(inner).intersection(rect(-BIG, R, BIG, BIG)))
        inner = inner.difference(arches[0].union(arches[1]))       # door lines stop at the arches
        if doors and windows and belt is not None:
            edges = [windows[0].bounds[2] + 1.0]
            for k in range(doors):
                if k + 1 < len(windows):
                    edges.append((windows[k].bounds[0] + windows[k + 1].bounds[2]) / 2)
                else:
                    edges.append(windows[-1].bounds[0] - 1.0)
            top = max(w.bounds[3] for w in windows[:doors]) + 1.0
            for x in edges:
                out += as_lines(LineString([(x, top), (x, floor_top + 1.0)]).intersection(inner))
            for x_rear in edges[1:]:                        # handle near the rear edge of each door
                out += as_lines(LineString([(x_rear + 2.0, belt - 2.5), (x_rear + 5.0, belt - 2.5)])
                                .intersection(inner))
        return out

    # --------------------------------------------------------------- wheels
    @staticmethod
    def _wheel_layers(v: Values, R: float, rod: float) -> list[tuple[str, Polygon, bool]]:
        hole = Point(0, 0).buffer((rod + v.press_fit) / 2, quad_segs=24)
        disc = Point(0, 0).buffer(R, quad_segs=48)
        layers = []
        if v.hub_spacer:
            layers.append(("Hub spacer", Point(0, 0).buffer(min(R - 1, rod / 2 + 3.5), quad_segs=32)
                           .difference(hole), True))
        layers.append(("Wheel inner", disc.difference(hole), True))
        if v.wheel_layers >= 3:
            mid = Point(0, 0).buffer(R - v.groove_depth, quad_segs=48) if v.tyre_groove else disc
            layers.append(("Wheel middle", mid.difference(hole), True))
        layers.append(("Wheel cap", disc, False))
        return layers

    @staticmethod
    def _hubcap(R: float) -> list[LineString]:
        out = as_lines(Point(0, 0).buffer(0.62 * R, quad_segs=32).exterior)
        out += as_lines(Point(0, 0).buffer(0.18 * R, quad_segs=16).exterior)
        for k in range(5):
            a = 2 * math.pi * k / 5
            c, s = math.cos(a), math.sin(a)
            out.append(LineString([(0.26 * R * c, 0.26 * R * s), (0.54 * R * c, 0.54 * R * s)]))
        return out

    # --------------------------------------------------------------- checks
    @staticmethod
    def _checks(d, panels, axles, z_axle, rod, pw, floor_top, t, R, D, W) -> None:
        ends = [p for p in panels if p.name in ("front", "rear")]
        for xa in axles:
            for p in ends:
                inner_x = (p.a - p.n * t)[0]
                if abs(inner_x - xa) < pw / 2 + 0.5:
                    d.warn(f"Axle at x={xa:.1f} is too close to the {p.name} panel - shorten the overhang.")
        if D + 2 > abs(axles[0] - axles[1]):
            d.warn("Wheels overlap each other - reduce wheel diameter.")
        if W < 3 * rod + 20:
            d.warn("Body is narrow: the axles will wobble. Add bearing pads or widen the body.")

    @staticmethod
    def _assembly(v: Values, rod_len: float, groove: bool, D: float) -> list[str]:
        rod = v.rod_diameter
        notes = [
            "Do a fit test first (generator 'fit-test', hole strip with your rod) and enter the press-fit and "
            "running-fit offsets under Axles.",
            f"Cut 2 rods Ø{rod:g} mm to {rod_len:.1f} mm (cut-off wheel or hacksaw). File the ends smooth "
            "and scuff 10 mm at each end with sandpaper so the glue grips.",
        ]
        if v.bearing_pads:
            notes.append("Glue the bearing pads (B) inside each side plate. Push a rod through the side hole "
                         "and the pads while the glue sets, so the holes line up; turn it now and then.")
        notes += [
            "Push the floor and the body panels into the slots of one side plate (each panel fits only its own "
            "slots), then press the second side on. Check the axles turn freely, then glue every joint with wood "
            "glue. Wipe off squeeze-out.",
            "Wheels: glue the layers of one wheel (spacer, inner, middle, cap) with epoxy or CA, pushing the rod "
            "in until it stops at the cap. Let it cure.",
            "Pass the rod through the body, slide the second wheel on with a strip of paper between each hub "
            "spacer and the side (axial play), and glue it the same way. Remove the paper.",
        ]
        if groove:
            notes.append(f"Optional tyres: O-rings in the wheel groove (inner Ø ≈ {D - 2 * v.groove_depth - 1:.0f}"
                         " mm) or wrapped rubber bands.")
        notes += [
            "Sand all edges, then finish with a toy-safe oil or paint (EN 71-3). Check that nothing can come off: "
            "wheels and small parts are a choking hazard for under-3s.",
            "Parts are not labelled on faces that show; match panels to sides by their tabs (each slot set is unique).",
        ]
        return notes
