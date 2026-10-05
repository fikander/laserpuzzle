# laserpuzzle — notes for Claude

Python tool that turns 3D models / drawings / parameters into **flat laser-cut parts that assemble into 3D objects**
(chess pieces, cars, figures, mechanisms, marble runs). Owner is learning laser CNC at a maker space; outputs are
cut on a real machine, so geometric correctness (kerf, fits, no collisions) matters more than features.

## Commands

```bash
uv venv && uv pip install -e ".[dev]"         # or: python -m venv .venv && pip install -e ".[dev]"
laserpuzzle list                               # generators
laserpuzzle params stacked-layers              # a generator's parameters
laserpuzzle run stacked-layers -s model=pawn.stl -s thickness=3 -o output/pawn
laserpuzzle ui                                 # web UI on http://127.0.0.1:8765, workdir = cwd
pytest -q                                      # ~2 s; run after every change
```

## Layout

```
src/laserpuzzle/
  core/            shared, generator-agnostic building blocks
    params.py      Param declarations -> CLI + UI form + validation; FABRICATION_PARAMS shared by all generators
    design.py      Design / Part / Hardware data model, plane transforms (horizontal, vertical_xz, ...)
    geometry.py    shapely helpers: mesh `section`, `clean`, `kerf_offset`, `band_x`, `rect`
    mesh.py        load + normalise meshes (Z up, base on z=0, centred, scaled)
    font.py        single-stroke font for engraved labels (no SVG <text>)
    layout.py      fabricate (kerf + labels) and shelf-nest onto sheets
    export.py      SVG (red=cut, blue=engrave, mm) and DXF (CUT/ENGRAVE layers)
    validate.py    3D collision check between extruded parts (manifold3d)
  generators/      one module per puzzle type, auto-discovered; base.py = interface + registry
  pipeline.py      run(): generator -> design -> sheets -> collisions; Run.preview()/write()/zip
  cli.py           argparse entry point
  ui/server.py     FastAPI app; ui/static/ = plain HTML/CSS/JS + three.js from CDN (no build step)
tests/             pytest; synthetic meshes, no network
docs/              architecture, adding generators, fabrication, per-generator docs, roadmap
```

## Conventions (keep these — generators and the UI rely on them)

- **Units are millimetres. World is Z-up**, model standing on z=0. `core.mesh.load_model` enforces this.
- A `Part.outline` is the **nominal** shape (what the finished part should measure). **Never apply kerf in a
  generator** — `layout.fabricate` does it at export. Generators *do* apply `clearance` to slot/hole widths.
- Part local frame: outline in local XY, thickness along local +Z from 0..t. `Part.transform` (4x4) places it in the
  world. Use `design.plane_transform` / `horizontal` / `vertical_xz` / `vertical_yz`; keep transforms rigid.
- Joints must produce **zero 3D overlap** at clearance 0. `validate.collisions` is the safety net; add a test that
  asserts `run(...).collisions == []` for every new generator / connector mode.
- Report problems through `design.warn(...)` (shown in UI and CLI), assembly steps through `design.notes`.
  Raise `ValueError` only for inputs that make generation impossible.
- Parameters: declare with `Param`; group them (`group=`) for the UI. Defaults must generate something sensible.
- Engraving goes in `Part.engrave` (LineStrings) or `Part.label` (short text, auto-fitted). Cut = red, engrave = blue.
- Keep the UI build-free (ES modules, importmap). Preview JSON shape is produced only by `Run.preview()`.

## Adding a generator

See `docs/adding-a-generator.md`. Short version: new module in `generators/`, `@register` a `Generator`
subclass with `id`, `name`, `description`, `params`, `generate(v, ctx) -> Design`; add docs in
`docs/generators/<id>.md` and tests. It appears in CLI and UI automatically.

## Gotchas

- Mesh sections: `geometry.section` uses even-odd on polygonized contours; non-watertight meshes give gaps (warn).
- SVG export flips Y (SVG y-down) so parts look as seen from above and engraved text reads correctly.
- `manifold3d` boolean intersections of exactly touching solids can return degenerate meshes → volume NaN; handled.
- Shapely `buffer` with `join_style="mitre"` for kerf keeps slot corners sharp; round joins would loosen fits.
- In this repo, `pawn.stl` is a Y-up sample model (auto up-axis detects it).

## Status / next steps

Done: core pipeline, `stacked-layers` (spine half-lap + dowel/spacers), `fit-test`, web UI with 3D + sheet preview.
Next (see `docs/roadmap.md`): joint library (`core/joints.py`: tab-slot, finger, T-slot, cross-lap), better
nesting, car generator from 3 orthographic views, humanoid, mechanisms, marble run.
