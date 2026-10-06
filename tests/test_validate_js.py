"""`validate.js_collisions` against a stand-in for manifold's JS API built on the
`manifold3d` Python package (same C++ library), so the browser code path is
checked natively: ring/hole conversion, column-major transforms, volumes."""

import numpy as np
import manifold3d as m3

from laserpuzzle.core.validate import collisions, js_collisions
from laserpuzzle.pipeline import run


class _Box:
    def __init__(self, bb):
        self.min, self.max = bb[:3], bb[3:]


class _Solid:
    live = 0

    def __init__(self, m):
        self.m = m
        _Solid.live += 1

    def transform(self, mat4_colmajor):
        mat = np.asarray(mat4_colmajor, float).reshape(4, 4).T   # back to row-major
        return _Solid(self.m.transform(mat[:3]))

    def boundingBox(self):
        return _Box(self.m.bounding_box())

    def intersect(self, other):
        return _Solid(self.m ^ other.m)

    def volume(self):
        return self.m.volume()

    def delete(self):
        _Solid.live -= 1


class _CS:
    @staticmethod
    def new(rings, rule):
        assert rule == "EvenOdd"
        return _CrossSection(m3.CrossSection([np.asarray(r, float) for r in rings], m3.FillRule.EvenOdd))


class _CrossSection:
    def __init__(self, cs):
        self.cs = cs

    def delete(self):
        pass


class _Manifold:
    @staticmethod
    def extrude(cs, h):
        return _Solid(m3.Manifold.extrude(cs.cs, h))


class FakeManifoldJS:
    CrossSection = _CS
    Manifold = _Manifold


def _cases():
    yield run("vehicle", {}, check=False).design
    yield run("vehicle", {"clearance": -0.3}, check=False).design      # press fit: real overlaps
    yield run("fit-test", {}, check=False).design


def test_js_backend_matches_native_and_frees_solids():
    for design in _cases():
        _Solid.live = 0
        js = js_collisions(design, FakeManifoldJS)
        assert sorted(map(str, js)) == sorted(map(str, collisions(design)))
        assert _Solid.live == 0


def test_js_backend_finds_overlaps():
    design = run("vehicle", {"clearance": -0.3}, check=False).design
    assert len(js_collisions(design, FakeManifoldJS)) > 0
