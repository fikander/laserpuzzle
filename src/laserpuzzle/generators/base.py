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

Put the module in `laserpuzzle/generators/`; it is auto-imported.
Fabrication params (thickness, kerf, clearance, sheet...) are added
automatically - read them from `v` too.
"""

from __future__ import annotations

import importlib
import pkgutil
from dataclasses import dataclass
from pathlib import Path
from typing import ClassVar

from ..core.design import Design
from ..core.params import FABRICATION_PARAMS, Param, Values

_REGISTRY: dict[str, type["Generator"]] = {}


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
    _REGISTRY[cls.id] = cls
    return cls


def _discover() -> None:
    pkg = importlib.import_module("laserpuzzle.generators")
    for mod in pkgutil.iter_modules(pkg.__path__):
        if not mod.name.startswith("_") and mod.name != "base":
            importlib.import_module(f"laserpuzzle.generators.{mod.name}")


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
