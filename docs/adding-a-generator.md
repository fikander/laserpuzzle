# Adding a generator

A generator is a Python class that turns parameter values into a `Design`. It never deals with kerf,
nesting, file formats or the UI. Those come for free.

## 1. Skeleton

Create `src/laserpuzzle/generators/my_thing.py`:

```python
from shapely.geometry import Point

from ..core.design import Design, Part, horizontal, vertical_xz
from ..core.geometry import rect
from ..core.params import Param, Values
from .base import Context, Generator, register


@register
class Coaster(Generator):
    id = "coaster"                       # CLI / URL id, kebab-case
    name = "Coaster with stand"          # shown in UI
    description = "Round coaster plus an upright stand slotted into it."
    params = [
        Param("diameter", "float", 90, "Diameter", unit="mm", min=30, max=300, step=1, group="Shape"),
        Param("stand_height", "float", 40, unit="mm", min=10, max=200, group="Shape"),
    ]

    def generate(self, v: Values, ctx: Context) -> Design:
        d = Design()
        t, c = v.thickness, v.clearance            # fabrication params are always present
        r = v.diameter / 2

        # flat disc with a slot for the stand (slot width = t + clearance, NO kerf here)
        disc = Point(0, 0).buffer(r).difference(rect(-(t + c) / 2, -15, (t + c) / 2, 15))
        d.parts.append(Part("Disc", disc, t, horizontal(0), label="D", group="disc"))

        # upright plate in the XZ plane... (see design.py helpers for orientations)
        ...
        d.notes.append("Push the stand into the disc.")
        return d
```

It is discovered automatically: `laserpuzzle list`, the CLI and the UI pick it up.

## 2. Checklist

- **Nominal geometry only.** Outline = finished size. Add `v.clearance` to slot/hole widths; never add kerf.
- **Place every part in 3D** with a rigid transform so the preview and the collision check work.
  The part occupies local z ∈ [0, t]; use `centered=True` (or `vertical_xz/yz`) for plates that must be centred on a plane.
- **Joints must not overlap** at clearance 0. Half-laps: each plate loses exactly the half of the overlap the other keeps.
- **Moving parts**: build the rest pose, add a `design.Pivot` per axis (with a realistic `range`, `parent` for
  chained arms, `driver` for gears) and assert `r.motion_collisions == []` too.
- **Explode vectors**: give each part a direction that pulls it away along its assembly path.
- **Labels**: `label="L3"`; it's auto-sized to fit, or skipped if it doesn't.
- **Warnings** for fixable problems (`d.warn("Layer 7 is thinner than 2 mm")`), `ValueError` for impossible inputs.
- **Notes**: assembly steps, in order.
- **Stats**: a few numbers that help the user (part count is automatic).
- File inputs: `Param("model", "file", "", accept=[".stl"])`, then `ctx.resolve(v.model)`.
  For 3D models use `core.mesh.load_model` so orientation/scale handling is consistent.

## 3. Tests

Add `tests/test_<id>.py` with at least:

```python
from laserpuzzle.pipeline import run

def test_coaster():
    r = run("coaster", {})
    assert r.collisions == []
    assert len(r.sheets) == 1
```

Use synthetic meshes (`trimesh.creation`) rather than large files.

## 4. Docs

Add `docs/generators/<id>.md`: what it makes, parameters worth tuning, assembly, limitations.
Update the table in `README.md` and the status in `CLAUDE.md`.

## Generators in a separate package (plugins)

A generator doesn't have to live in this repo. Any installed package can contribute generators through the
`laserpuzzle.generators` entry point group; the value is a module that is imported, so its `@register`
decorators run:

```toml
# pyproject.toml of your package
[project.entry-points."laserpuzzle.generators"]
my-plugin = "my_plugin.generators"      # a module; import it to register its generators
```

After `pip install -e .` the generators appear in `laserpuzzle list`, the CLI and the UI like built-in ones.
Ids must be unique: registering an id that another generator class already uses raises `ValueError`.
A plugin that fails to import produces a warning and is skipped; built-in generators keep working.

## Useful core helpers

| Helper | Use |
|---|---|
| `geometry.section(mesh, origin, normal, x_axis, y_axis)` | planar cross-section → shapely, in plane coords |
| `geometry.clean(g, min_area, simplify)` | repair + drop crumbs |
| `geometry.band_x(g, y0, y1)` | x-intervals of a shape inside a horizontal band (joint placement) |
| `geometry.rect(x0, y0, x1, y1)` | axis-aligned rectangle (slots) |
| `design.plane_transform(...)` | any plate orientation |
| `joints.tab_slot(edge_part, face_part, edge, clearance=c)` | edge of one plate into slots in another (any angle) |
| `joints.cross_lap(a, b, clearance=c)` | two perpendicular plates slotted halfway into each other (each overlap span on its own) |
| `joints.finger_joint(a, b, clearance=c)` | box corners / T joints at any angle: draw both plates to full size, the overlap becomes alternating fingers |
| `joints.pin_joint(parts, origin, axis, d, fit=..., washer_thickness=t)` | holes for a pin through a stack, the pin as hardware, spacer washers |
| `joints.living_hinge(part, region)` | staggered slits (`Part.cuts`) that make a region bendable; size it with `joints.hinge_length` |
| `design.Pivot(name, origin, axis, parts=[...], range=(lo, hi))` | rotation axis for moving parts; checked by `validate.motion_collisions` |
| `design.Trajectory(hardware, times, points, pivots={...})` | an item (ball) travelling through the model, animated in the preview; check it in tests with `validate.trajectory_collisions` |
| `gears.spur_gear(module, teeth, backlash=b, bore=d)` | involute gear outline; place pairs with `center_distance` + `mesh_rotation` |
| `font.text_lines(text, h, cx, cy, angle)` | engrave arbitrary text as strokes |
| `mesh.load_model(path, up_axis, flip, height, rotate_z)` | normalised mesh |
