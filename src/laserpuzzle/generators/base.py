"""Generator plug-in interface and registry.

A generator turns inputs (files + parameters) into a `Design`. To add one:

    from laserpuzzle.generators.base import Generator, register
    from laserpuzzle.core.params import Param

    @register
    class MyThing(Generator):
        id = "my-thing"
        name = "My thing"
        description = "..."
        params = [Param("size", "float", 50, unit="mm")]

        def generate(self, v, ctx):
            design = Design()
            ...
            return design

Put the module in `laserpuzzle/generators/`; it is auto-imported. Generators
from other installed packages are loaded through the `laserpuzzle.generators`
entry point group (value = module to import), see docs/adding-a-generator.md.
Fabrication params (thickness, kerf, clearance, sheet...) are added
automatically - read them from `v` too.
"""

from __future__ import annotations

import importlib
import pkgutil
import warnings
from importlib import metadata
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ..core.design import Design
from ..core.params import FABRICATION_PARAMS, Param, Values

_REGISTRY: dict[str, type["Generator"]] = {}
ENTRY_POINT_GROUP = "laserpuzzle.generators"


@dataclass
class Context:
    workdir: Path

    def resolve(self, path: str) -> Path:
        p = Path(path).expanduser()
        if not p.is_absolute():
            p = self.workdir / p
        if not p.exists():
            raise FileNotFoundError(f"input file not found: {path}")
        return p


class Generator:
    id: ClassVar[str] = ""
    name: ClassVar[str] = ""
    description: ClassVar[str] = ""
    params: ClassVar[list[Param]] = []

    @classmethod
    def all_params(cls) -> list[Param]:
        return list(cls.params) + list(FABRICATION_PARAMS)

    @classmethod
    def schema(cls) -> dict:
        return {
            "id": cls.id,
            "name": cls.name,
            "description": cls.description,
            "params": [p.to_schema() for p in cls.all_params()],
        }

    def generate(self, v: Values, ctx: Context) -> Design:  # pragma: no cover - interface
        raise NotImplementedError


def register(cls: type[Generator]) -> type[Generator]:
    if not cls.id:
        raise ValueError(f"{cls.__name__} has no id")
    prev = _REGISTRY.get(cls.id)
    if prev is not None and _qualname(prev) != _qualname(cls):
        raise ValueError(f"generator id {cls.id!r} of {_qualname(cls)} is already used by {_qualname(prev)}")
    _REGISTRY[cls.id] = cls
    return cls


def _qualname(cls: type) -> str:
    return f"{cls.__module__}.{cls.__qualname__}"


def _discover() -> None:
    pkg = importlib.import_module("laserpuzzle.generators")
    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.name.startswith("_") and mod.name != "base":
            importlib.import_module(f"laserpuzzle.generators.{mod.name}")
    # plugins: importing the module registers its generators. A broken plugin
    # must not take the built-in generators down with it, so warn and go on.
    for ep in metadata.entry_points(group=ENTRY_POINT_GROUP):
        try:
            ep.load()
        except Exception as e:
            warnings.warn(f"laserpuzzle plugin {ep.name!r} ({ep.value}) failed to load: {type(e).__name__}: {e}",
                          stacklevel=2)


_discovered = False


def registry() -> dict[str, type[Generator]]:
    global _discovered
    if not _discovered:      # not "if not _REGISTRY": importing one generator module directly registers it
        _discover()
        _discovered = True
    return dict(_REGISTRY)


def get(gen_id: str) -> type[Generator]:
    reg = registry()
    if gen_id not in reg:
        raise KeyError(f"unknown generator {gen_id!r}; available: {sorted(reg)}")
    return reg[gen_id]
