"""Command line entry point.

    laserpuzzle list
    laserpuzzle params stacked-layers
    laserpuzzle run stacked-layers --set model=pawn.stl --set thickness=3 -o output/pawn
    laserpuzzle ui [--port 8765] [--workdir .]
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .generators.base import get, registry


def _parse_sets(items: list[str]) -> dict[str, str]:
    out = {}
    for it in items:
        if "=" not in it:
            raise SystemExit(f"--set expects name=value, got {it!r}")
        k, v = it.split("=", 1)
        out[k.strip()] = v.strip()
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="laserpuzzle", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="list generators")
    pp = sub.add_parser("params", help="show a generator's parameters")
    pp.add_argument("generator")
    rp = sub.add_parser("run", help="generate cut files")
    rp.add_argument("generator")
    rp.add_argument("--set", "-s", action="append", default=[], metavar="NAME=VALUE")
    rp.add_argument("--params", type=Path, help="JSON file with parameter values")
    rp.add_argument("--out", "-o", type=Path, default=Path("output"))
    rp.add_argument("--no-check", action="store_true", help="skip 3D collision check")
    up = sub.add_parser("ui", help="start the preview web UI")
    up.add_argument("--host", default="127.0.0.1")
    up.add_argument("--port", type=int, default=8765)
    up.add_argument("--workdir", type=Path, default=Path("."))
    up.add_argument("--no-browser", action="store_true")
    a = ap.parse_args(argv)

    if a.cmd == "list":
        for gid, cls in sorted(registry().items()):
            print(f"{gid:20s} {cls.name} - {cls.description}")
        return 0
    if a.cmd == "params":
        for p in get(a.generator).all_params():
            extra = f" choices={p.choices}" if p.choices else ""
            print(f"[{p.group}] {p.name} ({p.kind}, default={p.default!r}{', ' + p.unit if p.unit else ''}){extra}\n    {p.help}")
        return 0
    if a.cmd == "run":
        from .pipeline import run

        raw = json.loads(a.params.read_text()) if a.params else {}
        raw.update(_parse_sets(a.set))
        r = run(a.generator, raw, workdir=Path.cwd(), check=not a.no_check)
        files = r.write(a.out)
        s = r.summary()
        print(f"{len(r.design.parts)} parts on {len(r.sheets)} sheet(s), cut length {s['cut_length_mm'] / 1000:.2f} m")
        for w in r.warnings:
            print("WARNING:", w, file=sys.stderr)
        for f in files:
            print("  wrote", f)
        return 0
    if a.cmd == "ui":
        from .ui.server import serve

        serve(a.host, a.port, a.workdir.resolve(), open_browser=not a.no_browser)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
