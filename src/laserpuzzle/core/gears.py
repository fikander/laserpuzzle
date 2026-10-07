"""Involute spur gears and racks as 2D outlines.

Metric module system: pitch diameter = module x teeth, addendum = module,
dedendum = 1.25 x module. A gear outline is centred on (0, 0) with tooth 0
pointing along +x. Outlines are nominal (no kerf); `backlash` thins every
tooth at the pitch circle so meshing gears don't touch on both flanks.

Gears with fewer than ~17 teeth (20 deg pressure angle) are undercut when cut
by a real hob; here the flank simply continues radially below the base
circle, which is close enough for plywood gears but meshes less smoothly.

Placing a pair: put gear 2 at `center_distance` on gear 1's +x side and turn
it by `mesh_rotation`. To animate or check it through its motion, give each
gear a `design.Pivot`, the driven one with driver=(gear 1, gear_ratio(z1, z2)).
"""

from __future__ import annotations

import math

import numpy as np
from shapely import affinity
from shapely.geometry import Point, Polygon
from shapely.ops import unary_union

from .geometry import clean


def pitch_radius(module: float, teeth: int) -> float:
    return module * teeth / 2


def center_distance(module: float, z1: int, z2: int) -> float:
    """Axle distance of two meshing external gears."""
    return module * (z1 + z2) / 2


def gear_ratio(z1: int, z2: int) -> float:
    """Angle of gear 2 per angle of gear 1 when they mesh (external gears turn opposite ways)."""
    return -z1 / z2


def mesh_rotation(z1: int, z2: int, angle1: float = 0.0) -> float:
    """Rotation (deg) of gear 2, placed on gear 1's +x side, so its teeth mesh with gear 1
    turned by `angle1` deg."""
    return (180.0 + 180.0 / z2 + gear_ratio(z1, z2) * angle1) % (360.0 / z2)


def _inv(a: float) -> float:
    return math.tan(a) - a


def spur_gear(module: float, teeth: int, pressure_angle: float = 20.0, backlash: float = 0.0,
              bore: float = 0.0, steps: int = 8) -> Polygon:
    """Involute spur gear outline. `bore` = centre hole diameter (0 = none)."""
    if teeth < 6:
        raise ValueError("spur_gear: at least 6 teeth")
    if module <= 0:
        raise ValueError("spur_gear: module must be > 0")
    alpha = math.radians(pressure_angle)
    rp = pitch_radius(module, teeth)
    rb = rp * math.cos(alpha)
    ra = rp + module
    rr = rp - 1.25 * module
    # half the tooth's angular thickness at the pitch circle
    half = (math.pi * module / 2 - backlash) / (2 * rp)
    if half <= 0:
        raise ValueError("spur_gear: backlash larger than the tooth")

    def flank_angle(r: float) -> float:          # polar angle of the +flank at radius r
        ar = math.acos(min(1.0, rb / r))
        return half + _inv(alpha) - _inv(ar)

    r0 = max(rb, rr)
    radii = [r0 + (ra - r0) * (i / steps) for i in range(steps + 1)]
    flank = [(r, flank_angle(r)) for r in radii]
    tip_angle = flank[-1][1]
    if tip_angle <= 0:                           # pointed tooth: clip the tip
        flank = [(r, a) for r, a in flank if a > 0]
        tip_angle = flank[-1][1] if flank else 0.0
    upper = [(r * math.cos(a), r * math.sin(a)) for r, a in flank]
    tip = [(ra * math.cos(a), ra * math.sin(a)) for a in np.linspace(-tip_angle, tip_angle, 5)[1:-1]]
    lower = [(x, -y) for x, y in upper]              # root -> tip, then across the tip, then back down
    tooth = Polygon([(0.0, 0.0), *lower, *tip, *reversed(upper)])
    teeth_polys = [affinity.rotate(tooth, 360.0 * k / teeth, origin=(0, 0)) for k in range(teeth)]
    gear = unary_union([Point(0, 0).buffer(rr, quad_segs=max(16, teeth)), *teeth_polys])
    if bore > 0:
        gear = gear.difference(Point(0, 0).buffer(bore / 2, quad_segs=24))
    return clean(gear)


def rack(module: float, teeth: int, height: float, pressure_angle: float = 20.0,
         backlash: float = 0.0) -> Polygon:
    """Straight rack along +x starting at x=0; pitch line at y=0, teeth point +y,
    solid body down to y = -height. Meshes with a gear whose centre is at y = pitch radius."""
    alpha = math.radians(pressure_angle)
    p = math.pi * module
    ha, hf = module, 1.25 * module
    if height <= hf:
        raise ValueError("rack: height must exceed the dedendum (1.25 x module)")
    tan = math.tan(alpha)
    half = (p / 2 - backlash) / 2                # half tooth width at the pitch line
    pts = [(0.0, -height), (0.0, -hf)]
    for k in range(teeth):
        c = p * (k + 0.5)
        pts += [(c - half - hf * tan, -hf), (c - half + ha * tan, ha),
                (c + half - ha * tan, ha), (c + half + hf * tan, -hf)]
    pts += [(p * teeth, -hf), (p * teeth, -height)]
    return clean(Polygon(pts))
