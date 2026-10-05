# Architecture

```
 inputs (STL, drawings, numbers)
        │
        ▼
 ┌──────────────┐   Values (coerced from Param declarations + FABRICATION_PARAMS)
 │  Generator   │──────────────────────────────────────────────────────────────┐
 │ (plug-in)    │                                                              │
 └──────┬───────┘                                                              │
        │ Design: parts (nominal 2D outline + 3D transform), hardware,         │
        │         warnings, notes, stats, source mesh                          │
        ▼                                                                      │
 ┌──────────────┐  layout.fabricate: kerf offset + label strokes               │
 │   Pipeline   │  layout.nest:      parts → sheets                            │
 │ pipeline.run │  validate.collisions: 3D overlap check                       │
 └──────┬───────┘                                                              │
        ▼                                                                      │
   Run ──► export.sheet_svg / sheet_dxf / zip / write(outdir)                  │
       └─► preview() JSON ──► web UI (three.js assembly + SVG sheets)  ◄───────┘
```

## Layers of responsibility

| Layer | Knows about | Must not know about |
|---|---|---|
| `core/*` | geometry, materials, files | specific puzzle types |
| `generators/*` | how to design one kind of puzzle | kerf, nesting, file formats, UI |
| `pipeline.py` | orchestration | generator internals |
| `ui/`, `cli.py` | presenting `Run` | geometry |

This split is what makes new generators cheap: a generator only produces a `Design`.

## Data model (`core/design.py`)

- **Part** — one piece to cut.
  - `outline`: shapely Polygon/MultiPolygon in the part's local XY plane, **nominal** dimensions, holes = cut-outs.
  - `thickness`: material thickness (local Z from 0 to t).
  - `transform`: 4×4 rigid transform local → world (assembled position). Helpers: `horizontal(z)`,
    `vertical_xz(y, t)`, `vertical_yz(x, t)`, `plane_transform(origin, x_axis, y_axis, t, centered)`.
  - `engrave`: LineStrings to score; `label`: short text auto-placed and engraved.
  - `explode`: world-space offset for the exploded preview (UI multiplies by the slider value).
  - `group`: colour + BOM grouping; `quantity`: identical copies.
- **Hardware** — bought items (dowels, axles, balls, magnets). Rendered in preview, listed in BOM.
- **Design** — parts + hardware + `warnings` + `notes` (assembly steps) + `stats` + `source_mesh`.

## Coordinate conventions

- Millimetres everywhere. World Z up; models rest on z=0 and are centred on the Z axis (`core/mesh.py`).
- Sheets: origin bottom-left, y up (like the part's local frame). SVG export flips y so the file shows
  parts as seen from above (+Z); engraving ends up on the top face and text reads correctly.

## Fabrication parameters

`core/params.FABRICATION_PARAMS` are appended to every generator: `thickness`, `kerf`, `clearance`,
`sheet_width`, `sheet_height`, `part_spacing`, `labels`.

- `clearance` is a **design** concern: generators widen slots/holes by it (negative = press fit).
- `kerf` is a **fabrication** concern: applied only in `layout.fabricate` via `geometry.kerf_offset`
  (outer edges grow by kerf/2, holes shrink by kerf/2, mitre joins keep corners sharp).

## Validation

`validate.collisions` extrudes every part, places it with its transform and intersects all pairs whose
bounding boxes overlap (manifold3d). Any overlap above a small tolerance is reported. Every generator
test should assert there are no collisions at clearance 0. Planned: assemblability check (each part has a
collision-free insertion path) — see roadmap.

## UI

`laserpuzzle ui` starts FastAPI (`ui/server.py`) with `workdir` = current folder.

| Endpoint | Purpose |
|---|---|
| `GET /api/generators` | generator schemas (params incl. fabrication) → form |
| `GET /api/files?ext=.stl` | input files in workdir |
| `POST /api/upload` | save into `workdir/inputs/` |
| `POST /api/generate` | `{generator, params, check}` → preview JSON (cached run id) |
| `GET /api/runs/{id}/sheetN.svg|.dxf`, `all.zip`, `model.stl` | downloads / ghost model |
| `POST /api/runs/{id}/save` | write to `workdir/output/<name>/` |

Frontend: `ui/static/{index.html,app.js,style.css}`, no build step, three.js via importmap from jsdelivr.
Each part is an `ExtrudeGeometry` of its outline placed with `matrix` (column-major); explode offsets are
applied to a wrapper group. Last-used params are stored per generator in localStorage.
