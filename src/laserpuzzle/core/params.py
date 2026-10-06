"""Typed parameter declarations.

Generators declare a list of `Param`s. The same declarations drive:
  * the CLI (`--set name=value`),
  * the web UI form (rendered from `Param.to_schema()`),
  * validation / coercion of incoming values (`coerce_values`).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

KINDS = {"float", "int", "bool", "choice", "str", "file", "color"}
_HEX = re.compile(r"#?([0-9a-fA-F]{6})")


@dataclass
class Param:
    name: str
    kind: str
    default: Any = None
    label: str = ""
    help: str = ""
    unit: str = ""
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: list[str] = field(default_factory=list)
    accept: list[str] = field(default_factory=list)  # for kind="file", e.g. [".stl"]
    group: str = "Model"

    def __post_init__(self) -> None:
        if self.kind not in KINDS:
            raise ValueError(f"unknown param kind {self.kind!r}")
        if not self.label:
            self.label = self.name.replace("_", " ").capitalize()

    def coerce(self, value: Any) -> Any:
        if value is None or value == "":
            return self.default
        k = self.kind
        if k == "float":
            v = float(value)
        elif k == "int":
            v = int(float(value))
        elif k == "bool":
            if isinstance(value, str):
                v = value.strip().lower() in {"1", "true", "yes", "on"}
            else:
                v = bool(value)
            return v
        elif k == "choice":
            v = str(value)
            if self.choices and v not in self.choices:
                raise ValueError(f"{self.name}: {v!r} not in {self.choices}")
            return v
        elif k == "color":
            m = _HEX.fullmatch(str(value).strip())
            if not m:
                raise ValueError(f"{self.name}: {value!r} is not a #rrggbb colour")
            return "#" + m[1].lower()
        else:
            return str(value)
        if self.min is not None and v < self.min:
            raise ValueError(f"{self.name}: {v} < min {self.min}")
        if self.max is not None and v > self.max:
            raise ValueError(f"{self.name}: {v} > max {self.max}")
        return v

    def to_schema(self) -> dict:
        return {
            "name": self.name,
            "kind": self.kind,
            "default": self.default,
            "label": self.label,
            "help": self.help,
            "unit": self.unit,
            "min": self.min,
            "max": self.max,
            "step": self.step,
            "choices": self.choices,
            "accept": self.accept,
            "group": self.group,
        }


class Values(dict):
    """Coerced parameter values with attribute access (`v.thickness`)."""

    def __getattr__(self, item: str) -> Any:
        try:
            return self[item]
        except KeyError as e:  # pragma: no cover
            raise AttributeError(item) from e


def coerce_values(params: list[Param], raw: dict[str, Any]) -> Values:
    known = {p.name for p in params}
    unknown = set(raw) - known
    if unknown:
        raise ValueError(f"unknown parameters: {sorted(unknown)}")
    return Values({p.name: p.coerce(raw.get(p.name)) for p in params})


# --- Fabrication parameters shared by every generator -------------------------

FAB = "Material & machine"

FABRICATION_PARAMS: list[Param] = [
    Param("thickness", "float", 3.0, "Material thickness", unit="mm", min=0.5, max=20, step=0.1,
          help="Measured thickness of the sheet (measure it - 3 mm plywood is often 2.8-3.2).", group=FAB),
    Param("kerf", "float", 0.15, "Kerf", unit="mm", min=0, max=1, step=0.01,
          help="Width of material removed by the beam. Outlines grow and holes shrink by kerf/2 on export.",
          group=FAB),
    Param("clearance", "float", 0.0, "Slot clearance", unit="mm", min=-0.5, max=1, step=0.02,
          help="Added to slot/hole widths. Negative = tighter press fit, positive = looser.", group=FAB),
    Param("sheet_width", "float", 600, "Sheet width", unit="mm", min=50, max=3000, step=10, group=FAB),
    Param("sheet_height", "float", 400, "Sheet height", unit="mm", min=50, max=3000, step=10, group=FAB),
    Param("part_spacing", "float", 3.0, "Part spacing", unit="mm", min=0, max=50, step=0.5,
          help="Gap between nested parts on the sheet.", group=FAB),
    Param("labels", "bool", True, "Engrave part labels",
          help="Engrave small part numbers to help assembly.", group=FAB),
    Param("cut_color", "color", "#ff0000", "Cut line colour",
          help="Colour of cut lines in SVG/DXF. There is no universal standard: match what your laser shop or "
               "software setup expects.", group=FAB),
    Param("engrave_color", "color", "#0000ff", "Engrave line colour",
          help="Colour of engraved (line/score) strokes in SVG/DXF. Must differ from the cut colour.", group=FAB),
]
