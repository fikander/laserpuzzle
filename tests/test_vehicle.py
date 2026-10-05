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
        run("vehicle", {"preset": "sedan", "toy_proportions": False})


def test_two_layer_wheels_and_no_pads():
    r = run("vehicle", {"wheel_layers": 2, "bearing_pads": 0, "hub_spacer": False})
    assert r.collisions == []
    assert not any(p.group == "bearing" for p in r.design.parts)
    assert sum(p.group == "wheel" for p in r.design.parts) == 8
    assert not any(h.name == "O-ring tyre" for h in r.design.hardware)
