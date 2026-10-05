import math

import pytest

from laserpuzzle.core.design import Design, Part, horizontal, plane_transform, vertical_xz, vertical_yz
from laserpuzzle.core.geometry import as_polygons, rect
from laserpuzzle.core.joints import cross_lap, tab_positions, tab_slot
from laserpuzzle.core.validate import collisions

T = 3.0


def wall_on_floor():
    floor = Part("floor", rect(-30, -20, 30, 20), T, horizontal(-T))
    wall = Part("wall", rect(-20, 0, 20, 30), T, vertical_xz(0.0, T))
    return floor, wall


def test_tab_positions_even_and_inside_margins():
    spans = tab_positions(44, 2, 9, 3)
    assert spans == [(8.0, 17.0), (27.0, 36.0)]
    assert tab_positions(5, 1, 9, 3) == []


@pytest.mark.parametrize("clearance", [0.0, 0.1])
def test_tab_slot_wall_on_floor(clearance):
    floor, wall = wall_on_floor()
    floor_area, wall_area = floor.area(), wall.area()
    j = tab_slot(wall, floor, ((-20, 0), (20, 0)), clearance=clearance, n_tabs=2, tab_width=8)
    assert j.warnings == []
    # Tabs go down through the whole floor: 2 x 8 x 3 mm added, same removed (+ clearance).
    assert wall.area() == pytest.approx(wall_area + 2 * 8 * T)
    assert wall.outline.bounds[1] == pytest.approx(-T)
    slot = (8 + clearance) * (T + clearance)
    assert floor.area() == pytest.approx(floor_area - 2 * slot)
    assert len(floor.outline.interiors) == 2
    assert collisions(Design(parts=[floor, wall])) == []


def test_tab_slot_auto_tab_count_and_protrude():
    floor, wall = wall_on_floor()
    j = tab_slot(wall, floor, ((20, 0), (-20, 0)), protrude=1.0)  # edge direction must not matter
    assert len(j.added["wall"]) == round((40 - 2 * T) / (2.5 * 3 * T))
    assert wall.outline.bounds[1] == pytest.approx(-T - 1.0)
    assert collisions(Design(parts=[floor, wall])) == []


def test_tab_slot_inclined_panel_between_sides():
    """A windscreen-like panel at 30 deg, tabbed into two upright side plates."""
    half = 25.0
    sides = [Part(f"side{s}", rect(-10, 0, 50, 40), T, vertical_xz(s * half, T)) for s in (-1, 1)]
    inner = half - T / 2
    a = math.radians(30)
    panel = Part("panel", rect(0, 0, 2 * inner, 30), T,
                 plane_transform((0, -inner, 10), (0, 1, 0), (math.cos(a), 0, math.sin(a))))
    for side, edge in ((sides[0], ((0, 0), (0, 30))), (sides[1], ((2 * inner, 0), (2 * inner, 30)))):
        j = tab_slot(panel, side, edge, n_tabs=2)
        assert j.warnings == []
        # The slot is the tab's tilted cross-section: a 9 x 3 rectangle rotated 30 deg.
        assert sum(s.area for s in j.removed[side.name]) == pytest.approx(2 * 9 * T, rel=1e-6)
    assert collisions(Design(parts=[*sides, panel])) == []


def test_tab_slot_warns_when_slot_near_face_edge():
    floor = Part("floor", rect(-30, -2, 30, 20), T, horizontal(-T))
    wall = Part("wall", rect(-20, 0, 20, 30), T, vertical_xz(0.0, T))
    j = tab_slot(wall, floor, ((-20, 0), (20, 0)), n_tabs=1)
    assert any("closer than" in w for w in j.warnings)


def test_tab_slot_rejects_parallel_edge():
    floor, _ = wall_on_floor()
    lid = Part("lid", rect(-10, -10, 10, 10), T, horizontal(5))
    with pytest.raises(ValueError, match="parallel"):
        tab_slot(lid, floor, ((-10, -10), (10, -10)))


@pytest.mark.parametrize("a_from", ["low", "high"])
@pytest.mark.parametrize("clearance", [0.0, 0.1])
def test_cross_lap_egg_crate(a_from, clearance):
    a = Part("a", rect(-30, 0, 30, 20), T, vertical_xz(0.0, T))
    b = Part("b", rect(-25, 0, 25, 20), T, vertical_yz(5.0, T))
    area_a, area_b = a.area(), b.area()
    j = cross_lap(a, b, clearance=clearance, a_from=a_from)
    assert j.warnings == []
    assert len(as_polygons(a.outline)) == 1 and len(as_polygons(b.outline)) == 1
    # Each plate loses a (t + c) wide slot reaching (just past) half of the 20 mm overlap.
    expect = (T + clearance) * (10 + clearance / 2)
    assert area_a - a.area() == pytest.approx(expect)
    assert area_b - b.area() == pytest.approx(expect)
    assert collisions(Design(parts=[a, b])) == []


def test_cross_lap_requires_crossing():
    a = Part("a", rect(-30, 0, 30, 20), T, vertical_xz(0.0, T))
    b = Part("b", rect(-25, 0, 25, 20), T, vertical_yz(50.0, T))
    with pytest.raises(ValueError):
        cross_lap(a, b)
