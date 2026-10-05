# laserpuzzle

Generate laser-cut 3D puzzles (flat parts that slot together into a 3D object) from 3D models,
drawings and parameters. Preview the assembly in 3D, check the cut sheets, export SVG/DXF.

Generators so far:

| id | what it makes |
|---|---|
| `stacked-layers` | Slices a model (e.g. a chess piece) into layers with gaps, joined by a central spine or a dowel + spacers |
| `fit-test` | Calibration coupon to find the right kerf / slot clearance for your material |

Planned: cars from 3 drawings, humanoid figures, simple mechanisms, marble runs — see [docs/roadmap.md](docs/roadmap.md).

## Install

Python 3.10+. With [uv](https://docs.astral.sh/uv/):

```bash
uv venv
source .venv/bin/activate
uv pip install -e ".[dev]"
```

(or `python3 -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]"`)

## Use

```bash
laserpuzzle ui                 # opens http://127.0.0.1:8765 — pick a generator and an STL, tweak, download
```

The UI lists model files from the current folder (and `inputs/`, where uploads go). **Save to output/** writes
`output/<name>/sheet1.svg`, `sheet1.dxf`, `summary.json` and the normalised model.

Command line:

```bash
laserpuzzle run stacked-layers -s model=pawn.stl -s thickness=3 -s layer_gap=3 -o output/pawn
laserpuzzle run fit-test -s thickness=3 -o output/fit
laserpuzzle params stacked-layers     # all parameters with help
```

Cut files: **red = cut, blue = engrave/score**, units mm. Import the SVG into LightBurn (or your laser software)
and assign settings per colour. Read [docs/fabrication.md](docs/fabrication.md) before your first cut.

## Docs

- [docs/architecture.md](docs/architecture.md) — how the pieces fit together
- [docs/adding-a-generator.md](docs/adding-a-generator.md) — write your own generator
- [docs/fabrication.md](docs/fabrication.md) — kerf, clearance, materials, laser software
- [docs/generators/](docs/generators/) — per-generator details
- [docs/roadmap.md](docs/roadmap.md) — planned generators and core features
