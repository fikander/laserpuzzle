"""Joints for boxes and moving assemblies, pivots and the range-of-motion collision check."""

import math

import numpy as np
import pytest
from shapely.geometry import Point, Polygon

from laserpuzzle.core import export, layout
from laserpuzzle.core.design import (Design, Part, Pivot, cam_value, horizontal, plane_transform, rotation_about,
                                     vertical_xz, vertical_yz)
from laserpuzzle.core.gears import center_distance, gear_ratio, mesh_rotation, rack, spur_gear
from laserpuzzle.core.geometry import as_polygons, rect
from laserpuzzle.core.joints import cross_lap, finger_joint, hinge_length, living_hinge, pin_joint
from laserpuzzle.core.validate import cam_extremes, collisions, motion_collisions, sweep_poses

T = 3.0


# ------------------------------------------------------------------- boxes
def box(W=80.0, D=50.0, H=40.0, t=T):
    """Six walls drawn to the full outer size, so neighbours overlap at every edge."""
    return {
        "bottom": Part("bottom", rect(-W / 2, -D / 2, W / 2, D / 2), t, horizontal(0)),
        "top": Part("top", rect(-W / 2, -D / 2, W / 2, D / 2), t, horizontal(H - t)),
        "front": Part("front", rect(-W / 2, 0, W / 2, H), t, vertical_xz(-D / 2 + t / 2, t)),
        "back": Part("back", rect(-W / 2, 0, W / 2, H), t, vertical_xz(D / 2 - t / 2, t)),
        "left": Part("left", rect(-D / 2, 0, D / 2, H), t, vertical_yz(-W / 2 + t / 2, t)),
        "right": Part("right", rect(-D / 2, 0, D / 2, H), t, vertical_yz(W / 2 - t / 2, t)),
    }


EDGES = [("bottom", "front"), ("bottom", "back"), ("bottom", "left"), ("bottom", "right"),
         ("top", "front"), ("top", "back"), ("top", "left"), ("top", "right"),
         ("front", "left"), ("front", "right"), ("back", "left"), ("back", "right")]


def test_unjointed_box_overlaps():
    assert len(collisions(Design(parts=list(box().values())))) == 12


@pytest.mark.parametrize("clearance", [0.0, 0.1])
def test_finger_jointed_box_has_no_overlap_and_stays_in_one_piece(clearance):
    parts = box()
    for a, b in EDGES:
        j = finger_joint(parts[a], parts[b], clearance=clearance)
        assert j.warnings == []
        assert j.info["fingers"] % 2 == 1 and j.info["fingers"] >= 3
    for p in parts.values():
        assert len(as_polygons(p.outline)) == 1, p.name
    assert collisions(Design(parts=list(parts.values()))) == []


def test_finger_joint_splits_overlap_evenly():
    parts = box()
    a, b = parts["bottom"], parts["front"]
    area_a, area_b = a.area(), b.area()
    j = finger_joint(a, b, n=5)
    assert j.info == {"fingers": 5, "length": 80.0, "finger_width": 16.0}
    # bottom keeps 3 of 5 segments of the 80 x 3 overlap, front keeps 2
    assert area_a - a.area() == pytest.approx(2 * 16 * T)
    assert area_b - b.area() == pytest.approx(3 * 16 * T)
    with pytest.raises(ValueError, match="odd"):
        fresh = box()
        finger_joint(fresh["bottom"], fresh["front"], n=4)


def test_finger_joint_at_an_angle():
    """A lid hinged up 60 deg from a wall: corner overlap is a parallelogram prism."""
    wall = Part("wall", rect(-30, 0, 30, 40), T, vertical_xz(0.0, T))
    a = math.radians(60)
    # plate rising from the wall's top edge, tilted 60 deg from horizontal, reaching through it
    lid = Part("lid", rect(-30, -4, 30, 30), T,
               plane_transform((0, -T / 2, 40 - T), (1, 0, 0), (0, math.cos(a), math.sin(a))))
    assert collisions(Design(parts=[wall, lid]))
    j = finger_joint(wall, lid)
    assert j.warnings == []
    assert collisions(Design(parts=[wall, lid])) == []


def test_finger_joint_t_joint_gives_tabs_and_slots():
    shelf = Part("shelf", rect(-30, -20, 30, 20), T, horizontal(20))
    side = Part("side", rect(-20, 0, 20, 40), T, vertical_xz(0.0, T))   # crosses the shelf's middle
    j = finger_joint(side, shelf, n=5, a_ends=False)
    assert collisions(Design(parts=[shelf, side])) == []
    assert len(shelf.outline.interiors) == 2       # side keeps segments 1 and 3: two tabs, two slots
    assert j.warnings == []


def test_finger_joint_rejects_parallel_plates():
    with pytest.raises(ValueError, match="parallel"):
        finger_joint(Part("a", rect(0, 0, 10, 10), T, horizontal(0)), Part("b", rect(0, 0, 10, 10), T, horizontal(2)))


# --------------------------------------------------------------- cross_lap
def test_cross_lap_spans_each_vs_combined():
    """Plate `b` (a fork with two prongs) crosses plate `a` twice along the joint line."""
    def make():
        a = Part("a", rect(-30, 0, 30, 60), T, vertical_xz(0.0, T))
        fork = rect(-20, 0, 20, 60).difference(rect(-21, 20, 10, 40))   # prongs at z 0..20 and 40..60, spine y>10
        return a, Part("b", fork, T, vertical_yz(0.0, T))

    a, b = make()
    j = cross_lap(a, b, spans="each")
    assert [tuple(s) for s in j.info["spans"]] == [(0.0, 20.0), (40.0, 60.0)]
    assert collisions(Design(parts=[a, b])) == []
    assert all(len(as_polygons(p.outline)) == 1 for p in (a, b))
    # combined: one slot to the overall middle (z=30) cuts b's lower prong clean off
    a, b = make()
    j = cross_lap(a, b, spans="combined")
    assert collisions(Design(parts=[a, b])) == []
    assert any("pieces" in w for w in j.warnings)
    # auto picks "each" here (fewer pieces)
    a, b = make()
    assert cross_lap(a, b).info["mode"] == "each"


def test_cross_lap_auto_falls_back_to_combined():
    """Like a slice through the rim of a head sitting on a body: b's material along the joint line is
    split by a 0.8 mm sliver (z 30..30.8). Joining the upper span on its own would slot `a` from the
    bottom to z~31, above a's body (z 30), cutting a's right end off; one slot to the overall middle
    keeps both plates whole."""
    def make():
        head = Polygon([(-12, 30), (0, 40), (12, 30)])
        a = Part("a", rect(-20, 0, 20, 30).union(head), T, vertical_xz(0.0, T))
        b_shape = rect(-20, 0, 20, 30).union(rect(-20, 30.8, 20, 31.5))
        b_shape = b_shape.union(rect(-20, 0, -15, 31.5)).union(rect(15, 0, 20, 31.5))   # posts hold the bar
        return a, Part("b", b_shape, T, vertical_yz(10.0, T))

    a, b = make()
    j = cross_lap(a, b, spans="each")
    assert len(j.info["spans"]) == 2 and len(as_polygons(a.outline)) == 2
    a, b = make()
    j = cross_lap(a, b)
    assert j.info["mode"] == "combined" and j.warnings == []
    assert len(as_polygons(a.outline)) == 1 and len(as_polygons(b.outline)) == 1
    assert collisions(Design(parts=[a, b])) == []


# --------------------------------------------------------------- pin joint
def hinge_pair(gap=2 * T):
    base = Part("base", rect(-10, -10, 60, 10), T, vertical_xz(0.0, T))
    arm = Part("arm", rect(-10, -8, 50, 8), T, vertical_xz(T + gap, T))
    return base, arm


def test_pin_joint_holes_pin_and_washers():
    base, arm = hinge_pair()
    j = pin_joint([base, arm], (0, 0, 0), (0, 1, 0), 4.0, fits={"base": -0.1}, washer_thickness=T, extra=2)
    assert j.warnings == []
    hb, ha = base.outline.interiors[0], arm.outline.interiors[0]
    assert Polygon(hb).area == pytest.approx(math.pi * (3.9 / 2) ** 2, rel=0.01)
    assert Polygon(ha).area == pytest.approx(math.pi * (4.15 / 2) ** 2, rel=0.01)
    assert len(j.parts) == 2 and all(p.group == "washer" for p in j.parts)
    pin, = j.hardware
    assert pin.size["height"] == pytest.approx(4 * T + 4)
    design = Design(parts=[base, arm, *j.parts], hardware=j.hardware)
    assert collisions(design) == []


def test_pin_joint_warns_about_play_and_misses():
    base, arm = hinge_pair(gap=T + 1.0)
    j = pin_joint([base, arm], (0, 0, 0), (0, 1, 0), 4.0, washer_thickness=T)
    assert any("play" in w for w in j.warnings)
    base, arm = hinge_pair()
    j = pin_joint([base, arm], (0, 0, 9.5), (0, 1, 0), 4.0)
    assert any("weak" in w for w in j.warnings)
    with pytest.raises(ValueError, match="perpendicular"):
        pin_joint([base], (0, 0, 0), (1, 0, 0), 4.0)


# -------------------------------------------------------- pivots and motion
def test_rotation_about_moves_points_around_axis():
    m = rotation_about((10, 0, 0), (0, 0, 1), 90)
    assert m[:3, :3] @ np.array([20, 0, 0]) + m[:3, 3] == pytest.approx([10, 10, 0])


def arm_design(rng=(-30.0, 30.0)):
    """A base plate with a stop block; an arm on a pin that hits the block when lowered too far."""
    base, arm = hinge_pair()
    j = pin_joint([base, arm], (0, 0, 0), (0, 1, 0), 4.0, washer_thickness=T)
    # block below the arm's swing (world x 30..40, z -40..-30), as thick as the base-to-arm stack
    stop = Part("stop", rect(30, -40, 40, -30), 9.0, plane_transform((0, 9.0, 0), (1, 0, 0), (0, 0, 1)))
    d = Design(parts=[base, arm, stop, *j.parts], hardware=j.hardware)
    d.pivots.append(Pivot("hinge", (0, 0, 0), (0, 1, 0), parts=["arm"], hardware=["Pin"], range=rng))
    return d


def test_posed_moves_only_pivot_parts():
    d = arm_design()
    p = d.posed({"hinge": 90})
    assert np.allclose(p.parts[0].transform, d.parts[0].transform)
    tip = p.parts[1].transform @ np.array([50, 0, 0, 1])
    assert tip[[0, 2]] == pytest.approx([0, -50], abs=1e-9)      # +90 deg about +y swings +x down
    assert d.pivot_problems() == []


def test_motion_collisions_find_the_stop_and_respect_range():
    assert collisions(arm_design()) == []
    assert motion_collisions(arm_design((-20.0, 20.0))) == []
    hits = motion_collisions(arm_design((-20.0, 60.0)))
    assert [(h["a"], h["b"]) for h in hits] == [("arm", "stop")]
    assert hits[0]["pose"]["hinge"] > 20


def test_child_pivot_follows_parent():
    base, arm = hinge_pair()
    tip = Part("tip", rect(40, -5, 70, 5), T, vertical_xz(T + 2 * T, T))
    d = Design(parts=[base, arm, tip])
    d.pivots = [Pivot("shoulder", (0, 0, 0), (0, 1, 0), parts=["arm"]),
                Pivot("elbow", (45, 0, 0), (0, 1, 0), parts=["tip"], parent="shoulder")]
    m = d.motions({"shoulder": -90})
    # shoulder turns the elbow axis from (45, 0, 0) up to (0, 0, 45)
    p = d.posed({"shoulder": -90}).parts[2].transform @ np.array([45, 0, 0, 1])
    assert p[[0, 2]] == pytest.approx([0, 45], abs=1e-9)
    assert np.allclose(m["elbow"], m["shoulder"])
    q = d.posed({"shoulder": -90, "elbow": -90}).parts[2].transform @ np.array([55, 0, 0, 1])
    assert q[[0, 2]] == pytest.approx([-10, 45], abs=1e-9)     # elbow turns about the moved axis


def test_pivot_problems():
    d = Design(parts=[Part("a", rect(0, 0, 1, 1), T)])
    d.pivots = [Pivot("p", (0, 0, 0), (0, 0, 1), parts=["a", "nope"], parent="q", range=(10, 20))]
    probs = d.pivot_problems()
    assert any("nope" in p for p in probs) and any("q" in p for p in probs) and any("outside" in p for p in probs)
    d.pivots = [Pivot("p", (0, 0, 0), (0, 0, 1), parent="q"), Pivot("q", (0, 0, 0), (0, 0, 1), parent="p")]
    assert any("loops" in p for p in d.pivot_problems())


def test_sweep_poses_skip_driven_pivots():
    d = Design(pivots=[Pivot("a", (0, 0, 0), (0, 0, 1), range=(0, 30)),
                       Pivot("b", (0, 0, 0), (0, 0, 1), driver=("a", -2.0))])
    poses = sweep_poses(d, steps=4)
    assert all(set(p) == {"a"} for p in poses) and len(poses) == 3
    assert d.pivot_angles({"a": 10}) == {"a": 10.0, "b": -20.0}


# -------------------------------------------------------------------- cams
def cam_design(lift=None):
    """An eccentric disc cam (r 20, 8 off its shaft) turning about +y, under a flat follower
    that slides up and down. `lift`: the follower's cam table; default = exactly what the cam
    pushes it to (the top of the turned disc), every 5 deg."""
    e, r = 8.0, 20.0
    cam = Part("cam", Point(e, 0).buffer(r, quad_segs=32), T, vertical_xz(0, T))
    top = lambda a: r - e * math.sin(math.radians(a))          # noqa: E731  # +a about +y swings +x down
    foot = Part("foot", rect(-30, -10, 30, 10), T, horizontal(top(0)))
    table = [(a, top(a) - top(0)) for a in range(0, 360, 5)] if lift is None else lift
    d = Design(parts=[cam, foot])
    d.pivots = [Pivot("shaft", (0, 0, 0), (0, 1, 0), parts=["cam"]),
                Pivot("follower", (0, 0, top(0)), (0, 0, 1), parts=["foot"], kind="slide",
                      range=(-2 * e, 2 * e), driver=("shaft", table))]
    return d


def test_cam_table_interpolates_and_repeats():
    t = [(0, 0.0), (90, 10.0), (180, 0.0), (270, -10.0)]
    assert cam_value(t, 45) == pytest.approx(5.0)
    assert cam_value(t, 315) == pytest.approx(-5.0)               # between the last point and 360 = 0
    assert cam_value(t, 360 + 90) == cam_value(t, -270) == pytest.approx(10.0)


def test_slide_pivot_follows_the_cam():
    d = cam_design()
    assert d.pivot_problems() == []
    ang = d.pivot_angles({"shaft": -90})
    assert ang["follower"] == pytest.approx(8.0)
    z = d.posed({"shaft": -90}).parts[1].transform[2, 3]
    assert z == pytest.approx(20.0 + 8.0)                          # moved straight up by the cam value
    assert collisions(d) == []
    assert motion_collisions(d) == []


def test_follower_that_does_not_lift_collides():
    hits = motion_collisions(cam_design(lift=[(0, 0.0), (180, 0.0)]))
    assert [(h["a"], h["b"]) for h in hits] == [("cam", "foot")]
    assert hits[0]["pose"]["shaft"] < 0                           # the half turn where the cam rises


def test_sweep_includes_cam_extremes_through_gears():
    d = cam_design()
    assert cam_extremes(d, d.pivots[0]) == [-90.0, 90.0]
    # crank geared 2:1 to the shaft: the cam peaks at crank -180 (shaft -90) and bottoms at crank 180
    d.pivots[0].driver = ("crank", 0.5)
    d.pivots.insert(0, Pivot("crank", (0, 0, 0), (0, 1, 0), range=(-180.0, 180.0)))
    assert cam_extremes(d, d.pivots[0]) == [-180.0, 180.0]
    assert {180.0, -180.0} <= {p["crank"] for p in sweep_poses(d)}


def test_pivot_problems_with_cams():
    d = cam_design(lift=[(0, 0.0), (400, 1.0)])
    assert any("rise within" in p for p in d.pivot_problems())
    d = cam_design()
    d.pivots[1].kind = "wobble"
    assert any("unknown kind" in p for p in d.pivot_problems())


# ------------------------------------------------------------------- gears
def gear_pair(z1=12, z2=20, m=3.0, backlash=0.15, phase=None):
    c = center_distance(m, z1, z2)
    g1 = Part("g1", spur_gear(m, z1, backlash=backlash, bore=4), T, horizontal(0))
    rot = mesh_rotation(z1, z2) if phase is None else phase
    g2 = Part("g2", spur_gear(m, z2, backlash=backlash, bore=4), T,
              rotation_about((c, 0, 0), (0, 0, 1), rot) @ plane_transform((c, 0, 0), (1, 0, 0), (0, 1, 0)))
    d = Design(parts=[g1, g2])
    d.pivots = [Pivot("g1", (0, 0, 0), (0, 0, 1), parts=["g1"], range=(0, 360 / z1)),
                Pivot("g2", (c, 0, 0), (0, 0, 1), parts=["g2"], driver=("g1", gear_ratio(z1, z2)))]
    return d


def test_spur_gear_dimensions():
    g = spur_gear(2.0, 20)
    assert g.is_valid
    r = max(math.hypot(x, y) for x, y in g.exterior.coords)
    assert r == pytest.approx(2.0 * 20 / 2 + 2.0, abs=1e-6)          # addendum circle
    root = 2.0 * 20 / 2 - 1.25 * 2.0
    assert min(math.hypot(x, y) for x, y in g.exterior.coords) == pytest.approx(root, abs=0.05)   # polygonised circle
    assert g.contains(Point(21.5, 0.0))                              # tooth 0 points along +x
    assert not g.contains(Point(21.5 * math.cos(math.pi / 20), 21.5 * math.sin(math.pi / 20)))  # gap


def test_meshing_gears_turn_without_collision():
    d = gear_pair()
    assert collisions(d) == []
    assert motion_collisions(d) == []


def test_gears_out_of_phase_collide():
    assert collisions(gear_pair(phase=0.0))


def test_wrong_gear_ratio_shows_up_in_motion():
    d = gear_pair()
    d.pivots[1].driver = ("g1", +12 / 20)            # turning the same way: teeth crash
    assert [(h["a"], h["b"]) for h in motion_collisions(d)] == [("g1", "g2")]


def test_rack():
    r = rack(2.0, 10, 8.0)
    assert r.is_valid and r.bounds == pytest.approx((0, -8.0, 2 * math.pi * 10, 2.0))


# ------------------------------------------------------------ living hinge
def test_living_hinge_slits_export_and_preview():
    t = T
    p = Part("hinge", rect(0, 0, 80, 40), t, horizontal(0))
    region = rect(30, 0, 50, 40)
    j = living_hinge(p, region)                     # slits along y
    assert j.warnings == []
    assert j.info["rows"] == math.ceil(20 / (0.6 * t) - 0.5)
    assert p.cuts and all(region.buffer(1e-6).contains(l) for l in p.cuts)
    assert all(abs(l.coords[0][0] - l.coords[-1][0]) < 1e-9 for l in p.cuts)   # vertical
    assert p.area() == 80 * 40                      # no material removed
    assert hinge_length(90, 10, 3) == pytest.approx(math.pi / 2 * 11.5)

    fab = layout.fabricate(p, kerf=0.2, labels=False)
    sheets, _ = layout.nest(fab, 300, 200, 3)
    item = sheets[0].items[0]
    assert len(item.cuts) == len(p.cuts) and item.engrave == []
    total = sum(l.length for l in p.cuts)
    assert layout.total_cut_length(sheets) == pytest.approx(item.cut.length + total, rel=1e-6)
    svg = export.sheet_svg(sheets[0])
    assert svg.count("M") >= len(p.cuts) + 1
    dxf = export.sheet_dxf(sheets[0]).decode()
    assert dxf.count("LWPOLYLINE") >= len(p.cuts) + 1


def test_living_hinge_margin_keeps_edges_whole():
    p = Part("h", rect(0, 0, 60, 30), T)
    living_hinge(p, margin=2.0)
    inner = rect(2, 2, 58, 28).buffer(1e-6)
    assert all(inner.contains(l) for l in p.cuts)


def test_preview_carries_pivots_and_cuts():
    from laserpuzzle.generators.base import Generator, register, _REGISTRY
    from laserpuzzle.pipeline import run

    @register
    class _Arm(Generator):
        id = "_test-arm"
        name = "test arm"
        description = ""
        params = []

        def generate(self, v, ctx):
            d = arm_design((-20.0, 60.0))
            living_hinge(d.parts[0], rect(20, -10, 40, 10))
            return d

    try:
        r = run("_test-arm", {})
        pv = r.preview()
        assert pv["pivots"][0]["name"] == "hinge" and pv["pivots"][0]["parts"] == [1]
        assert pv["pivots"][0]["hardware"] == [0]
        assert pv["parts"][0]["cuts"]
        assert pv["motion_collisions"] and any("while moving" in w for w in r.warnings)
        assert "motion" in r.timings
    finally:
        _REGISTRY.pop("_test-arm", None)


def test_preview_carries_cam_drivers():
    from laserpuzzle.generators.base import Generator, register, _REGISTRY
    from laserpuzzle.pipeline import run

    @register
    class _Cam(Generator):
        id = "_test-cam"
        name = "test cam"
        description = ""
        params = []

        def generate(self, v, ctx):
            return cam_design()

    try:
        r = run("_test-cam", {})
        shaft, follower = r.preview()["pivots"]
        assert shaft["kind"] == "turn" and shaft["driver"] is None
        assert follower["kind"] == "slide" and follower["driver"][0] == "shaft"
        assert follower["driver"][1][18] == [90.0, pytest.approx(-8.0)]
        assert r.collisions == [] and r.motion_collisions == []
    finally:
        _REGISTRY.pop("_test-cam", None)
