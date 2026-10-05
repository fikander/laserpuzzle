from pathlib import Path

import pytest
import trimesh

from laserpuzzle.pipeline import run

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def vase(tmp_path_factory):
    """A pawn-ish test body: cone base + cylinder neck + sphere head (Z up)."""
    d = tmp_path_factory.mktemp("m")
    base = trimesh.creation.cone(radius=15, height=25)
    neck = trimesh.creation.cylinder(radius=6, height=20)
    neck.apply_translation([0, 0, 25])
    head = trimesh.creation.icosphere(subdivisions=3, radius=9)
    head.apply_translation([0, 0, 40])
    m = trimesh.boolean.union([base, neck, head], engine="manifold")
    p = d / "vase.stl"
    m.export(p)
    return p


@pytest.mark.parametrize("connector", ["spine", "dowel"])
def test_generates_without_collisions(vase, connector):
    r = run("stacked-layers", {"model": str(vase), "up_axis": "z", "height": 50, "connector": connector,
                               "dowel_diameter": 4, "spacer_diameter": 9})
    assert r.design.stats["layers"] >= 5
    assert r.collisions == []
    assert len(r.sheets) == 1
    svg = r.svg(0)
    assert 'id="cut"' in svg and 'id="engrave"' in svg
    assert r.dxf(0).startswith(b"  0")


def test_collision_check_catches_press_fit(vase):
    r = run("stacked-layers", {"model": str(vase), "up_axis": "z", "height": 50, "clearance": -0.4})
    assert r.collisions, "a negative clearance should make layers overlap the spine"


def test_dowel_gap_rounded_to_thickness(vase):
    r = run("stacked-layers", {"model": str(vase), "up_axis": "z", "connector": "dowel", "layer_gap": 4,
                               "thickness": 3, "dowel_diameter": 4, "spacer_diameter": 9}, check=False)
    assert r.design.stats["gap_mm"] == 3


@pytest.mark.skipif(not (ROOT / "pawn.stl").exists(), reason="sample model not present")
def test_sample_pawn():
    r = run("stacked-layers", {"model": "pawn.stl"}, workdir=ROOT)
    assert r.collisions == []
    assert r.design.stats["mesh"]["up_axis"] == "y"
