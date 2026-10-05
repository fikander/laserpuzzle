import pytest

from laserpuzzle.generators.vehicle import PRESETS
from laserpuzzle.pipeline import run


@pytest.mark.parametrize("preset", list(PRESETS))
def test_presets_generate_without_collisions(preset):
    r = run("vehicle", {"preset": preset})
    assert r.collisions == []
    assert r.design.warnings == []
    groups = {p.group for p in r.design.parts}
    assert {"side", "panel", "wheel", "hub", "bearing"} <= groups
    # Every body panel is tabbed into both sides: each side has >= 1 slot per panel plus 2 axle holes.
    panels = [p for p in r.design.parts if p.group == "panel"]
    for side in (p for p in r.design.parts if p.group == "side"):
        assert len(side.outline.interiors) >= len(panels) + 2


def test_sedan_dimensions_and_rod_length():
    r = run("vehicle", {"preset": "sedan", "scale": 36, "thickness": 3})
    st = r.design.stats
    assert st["scale"] == "1:36"
    assert 125 < st["length_mm"] < 140
    # rod spans the body + 2 x (play + spacer + inner + middle layer); the cap has no hole.
    assert st["rod_length_mm"] == pytest.approx(st["body_width_mm"] + 2 * (0.5 + 3 * 3), abs=0.05)
    caps = [p for p in r.design.parts if p.name.startswith("Wheel cap")]
    assert len(caps) == 4 and all(len(c.outline.interiors) == 0 for c in caps)


def test_length_overrides_scale():
    r = run("vehicle", {"preset": "bus", "length": 150})
    assert r.design.stats["scale"] == f"1:{10000 / 150:.0f}"


def test_press_fit_still_has_no_gaps_and_loose_fit_no_collisions():
    r = run("vehicle", {"clearance": 0.1})
    assert r.collisions == []


def test_cut_windows_make_holes():
    engraved = run("vehicle", {"windows": "engrave"}).design.parts[0]
    cut = run("vehicle", {"windows": "cut"}).design.parts[0]
    assert len(cut.outline.interiors) == len(engraved.outline.interiors) + PRESETS["sedan"]["windows"]


def test_true_scale_wheels_too_small_for_axle():
    with pytest.raises(ValueError, match="too small"):
        run("vehicle", {"preset": "sedan", "toy_proportions": False, "rear_hitch": False})
    # With a hitch the floor height is fixed, so automatic wheels grow just enough for the axle.
    r = run("vehicle", {"preset": "sedan", "toy_proportions": False})
    assert r.design.stats["wheel_diameter_mm"] == pytest.approx(2 * (5 + 3 + 1.5 + 1.5))


def test_two_layer_wheels_and_no_pads():
    r = run("vehicle", {"wheel_layers": 2, "bearing_pads": 0, "hub_spacer": False})
    assert r.collisions == []
    assert not any(p.group == "bearing" for p in r.design.parts)
    assert sum(p.group == "wheel" for p in r.design.parts) == 8
    assert not any(h.name == "O-ring tyre" for h in r.design.hardware)


# ---------------------------------------------------------------- hitch
import math  # noqa: E402

import numpy as np  # noqa: E402

from laserpuzzle.core.design import Design, Part  # noqa: E402
from laserpuzzle.core.validate import collisions  # noqa: E402


def couple(car: dict, trailer: dict, angle_deg: float = 0.0, shift: float = 0.0) -> list[dict]:
    """Place the trailer's ring on the car's peg, swung by angle_deg; return car/trailer collisions."""
    cd = run("vehicle", car, check=False).design
    td = run("vehicle", trailer, check=False).design
    a = math.radians(angle_deg)
    rot = np.eye(4)
    rot[:2, :2] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    to_peg, from_ring = np.eye(4), np.eye(4)
    to_peg[0, 3] = cd.stats["hitch_rear_x"] + shift
    from_ring[0, 3] = -td.stats["hitch_front_x"]
    m = to_peg @ rot @ from_ring
    parts = [Part("car:" + p.name, p.outline, p.thickness, p.transform) for p in cd.parts]
    parts += [Part("tr:" + p.name, p.outline, p.thickness, m @ p.transform) for p in td.parts]
    return [c for c in collisions(Design(parts=parts)) if c["a"][:3] != c["b"][:3]]


@pytest.mark.parametrize("car,trailer", [("sedan", "trailer-box"), ("jeep", "trailer-caravan"),
                                         ("van", "trailer-container"), ("trailer-caravan", "trailer-flatbed")])
@pytest.mark.parametrize("angle", [0, 35, -35])
def test_trailer_couples_and_swings_without_collisions(car, trailer, angle):
    assert couple({"preset": car}, {"preset": trailer}, angle) == []


def test_misaligned_ring_is_detected():
    hits = couple({"preset": "sedan"}, {"preset": "trailer-box"}, shift=3.0)
    assert any("Hitch peg" in (c["a"] + c["b"]) for c in hits)


def test_all_vehicles_share_the_hitch_height():
    floors = {p: run("vehicle", {"preset": p}, check=False).design.stats["floor_height_mm"] for p in PRESETS}
    assert set(floors.values()) == {5.0}            # hitch 8 - 3 mm sheet


def test_trailer_parts_and_no_hitch_option():
    r = run("vehicle", {"preset": "trailer-box", "rear_hitch": False})
    names = {p.name for p in r.design.parts}
    assert {"Drawbar", "Support foot"} <= names and "Hitch peg" not in names
    assert "Top" not in names                        # open box: no top panel
    car = run("vehicle", {"preset": "sedan", "rear_hitch": False}).design
    assert not any(p.group == "hitch" for p in car.parts)
