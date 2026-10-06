import io

import ezdxf
import numpy as np
import pytest
import trimesh
from shapely.geometry import Polygon, box

from laserpuzzle.core import font, layout
from laserpuzzle.core.design import Part, horizontal, vertical_xz
from laserpuzzle.core.geometry import band_x, kerf_offset, section
from laserpuzzle.core.params import FABRICATION_PARAMS, Param, coerce_values
from laserpuzzle.pipeline import run


def test_kerf_grows_outline_and_shrinks_holes():
    sq = box(0, 0, 10, 10).difference(box(4, 4, 6, 6))
    k = kerf_offset(sq, 0.2)
    minx, miny, maxx, maxy = k.bounds
    assert abs(maxx - minx - 10.2) < 1e-6
    hole = Polygon(k.interiors[0])
    assert abs(hole.area - 1.8 ** 2) < 1e-6


def test_section_resolves_holes():
    tube = trimesh.creation.annulus(r_min=5, r_max=10, height=20)
    g = section(tube, (0, 0, 0), (0, 0, 1), (1, 0, 0), (0, 1, 0))
    assert abs(g.area - np.pi * (100 - 25)) < 2.0


def test_band_x_merges_spans():
    g = box(0, 0, 2, 10).union(box(5, 0, 8, 10))
    assert band_x(g, 2, 3) == [(0.0, 2.0), (5.0, 8.0)]


def test_params_coerce_and_validate():
    ps = [Param("a", "float", 1.0, min=0), Param("b", "bool", False), Param("c", "choice", "x", choices=["x", "y"])]
    v = coerce_values(ps, {"a": "2.5", "b": "true"})
    assert v.a == 2.5 and v.b is True and v.c == "x"
    try:
        coerce_values(ps, {"a": -1})
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    assert {p.name for p in FABRICATION_PARAMS} >= {"thickness", "kerf", "clearance"}


def test_transforms_are_rigid():
    for m in (horizontal(5), vertical_xz(0, 3)):
        r = m[:3, :3]
        assert np.allclose(r @ r.T, np.eye(3))
        assert np.isclose(np.linalg.det(r), 1.0)


def test_nest_keeps_parts_on_sheet_and_apart():
    parts = [Part(f"p{i}", box(0, 0, 40 + i, 20), 3) for i in range(30)]
    fps = [fp for p in parts for fp in layout.fabricate(p, 0.1, labels=False)]
    sheets, warns = layout.nest(fps, 300, 200, spacing=2)
    assert not warns
    placed = [it.cut for s in sheets for it in s.items]
    assert len(placed) == 30
    for s in sheets:
        for it in s.items:
            minx, miny, maxx, maxy = it.cut.bounds
            assert minx >= 0 and miny >= 0 and maxx <= s.width and maxy <= s.height
        cuts = [it.cut for it in s.items]
        for i in range(len(cuts)):
            for j in range(i + 1, len(cuts)):
                assert cuts[i].intersection(cuts[j]).area < 1e-9


def test_font_renders_known_chars():
    lines = font.text_lines("L12", 3)
    assert len(lines) >= 4
    assert abs(font.text_width("AB", 6) - 10) < 1e-9


def test_fit_test_generator():
    from laserpuzzle.pipeline import run

    r = run("fit-test", {"count": 5, "rod_diameter": 0})
    assert len(r.design.parts) == 2
    assert r.collisions == []


def test_fit_test_hole_strip():
    from laserpuzzle.pipeline import run

    r = run("fit-test", {"rod_diameter": 3, "hole_first": -0.2, "hole_step": 0.05, "hole_count": 9})
    strip = next(p for p in r.design.parts if p.name == "Hole strip")
    diameters = sorted(2 * np.sqrt(Polygon(h).area / np.pi) for h in strip.outline.interiors)
    assert len(diameters) == 9
    assert np.allclose(diameters, [2.8 + 0.05 * i for i in range(9)], atol=0.01)
    assert r.design.stats["hole_offsets"][0] == -0.2
    assert len(r.design.hardware) == 1
    assert r.collisions == []


def test_color_param_coerce():
    p = Param("c", "color", "#ff0000")
    assert p.coerce("") == "#ff0000"
    assert p.coerce("00FF00") == "#00ff00"
    assert p.coerce(" #FFFF00 ") == "#ffff00"
    with pytest.raises(ValueError):
        p.coerce("red")


def _dxf_layers(r):
    return ezdxf.read(io.StringIO(r.dxf(0).decode())).layers


def test_line_colours_reach_svg_and_dxf():
    r = run("fit-test", {"cut_color": "#000000", "engrave_color": "#ffff00"})
    svg = r.svg(0)
    assert 'stroke="#000000"' in svg and 'stroke="#ffff00"' in svg and "#ff0000" not in svg
    assert 'stroke="#ffff00"' in r.preview()["sheets"][0]["svg"]
    layers = _dxf_layers(r)
    assert layers.get("ENGRAVE").color == 2 and layers.get("ENGRAVE").rgb == (255, 255, 0)
    assert layers.get("CUT").rgb == (0, 0, 0)
    assert not any("colours are the same" in w for w in r.warnings)


def test_same_line_colours_warn():
    r = run("fit-test", {"engrave_color": "#FF0000"})
    assert any("colours are the same" in w for w in r.warnings)


def test_default_line_colours():
    r = run("fit-test", {})
    assert 'stroke="#ff0000"' in r.svg(0) and 'stroke="#0000ff"' in r.svg(0)
    layers = _dxf_layers(r)
    assert layers.get("CUT").color == 1 and layers.get("ENGRAVE").color == 5
