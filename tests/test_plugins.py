import sys
from importlib import metadata

import pytest

from laserpuzzle.generators import base
from laserpuzzle.pipeline import run

PLUGIN = '''
from laserpuzzle.core.design import Design, Part, horizontal
from laserpuzzle.core.geometry import rect
from laserpuzzle.generators.base import Generator, register


@register
class Square(Generator):
    id = "plugin-square"
    name = "Plugin square"
    description = "test plugin"

    def generate(self, v, ctx):
        d = Design()
        d.parts.append(Part("Square", rect(0, 0, 20, 20), v.thickness, horizontal(0)))
        return d
'''


@pytest.fixture
def plugins(tmp_path, monkeypatch):
    """Copy of the registry plus fake entry points: call plugins({"name": "module.path"})."""
    monkeypatch.setattr(base, "_REGISTRY", base.registry())   # built-in modules are cached, won't re-register
    monkeypatch.setattr(base, "_discovered", False)
    monkeypatch.syspath_prepend(str(tmp_path))
    (tmp_path / "lp_test_plugin.py").write_text(PLUGIN)

    def install(eps: dict[str, str]):
        fake = [metadata.EntryPoint(name, value, base.ENTRY_POINT_GROUP) for name, value in eps.items()]
        monkeypatch.setattr(base.metadata, "entry_points",
                            lambda group: fake if group == base.ENTRY_POINT_GROUP else [])
    yield install
    sys.modules.pop("lp_test_plugin", None)


def test_plugin_generator_is_registered_and_runs(plugins):
    plugins({"square": "lp_test_plugin"})
    reg = base.registry()
    assert "plugin-square" in reg and "vehicle" in reg
    r = run("plugin-square", {})
    assert [p.name for p in r.design.parts] == ["Square"]
    assert r.collisions == []


def test_broken_plugin_warns_and_builtins_survive(plugins):
    plugins({"broken": "lp_no_such_module"})
    with pytest.warns(UserWarning, match="broken"):
        reg = base.registry()
    assert "vehicle" in reg


def test_duplicate_id_from_another_class_is_rejected(plugins):
    reg = base.registry()
    clash = type("Clash", (base.Generator,), {"id": "vehicle"})
    with pytest.raises(ValueError, match="already used"):
        base.register(clash)
    assert base.get("vehicle") is reg["vehicle"]
