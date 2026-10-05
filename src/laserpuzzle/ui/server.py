"""FastAPI backend for the preview UI.

Runs locally (`laserpuzzle ui`). `workdir` is the project folder: input
files are listed from it, uploads go to `<workdir>/inputs/`, and "Save"
writes to `<workdir>/output/<name>/`.
"""

from __future__ import annotations

import re
import traceback
import webbrowser
from collections import OrderedDict
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, HTTPException, UploadFile
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from ..generators.base import registry
from ..pipeline import Run, run

STATIC = Path(__file__).parent / "static"
SKIP_DIRS = {".git", ".venv", "venv", "node_modules", "output", "__pycache__", ".pytest_cache"}


class GenerateRequest(BaseModel):
    generator: str
    params: dict[str, Any] = {}
    check: bool = True


class SaveRequest(BaseModel):
    name: str


def create_app(workdir: Path) -> FastAPI:
    app = FastAPI(title="laserpuzzle")
    runs: "OrderedDict[str, Run]" = OrderedDict()

    def get_run(rid: str) -> Run:
        if rid not in runs:
            raise HTTPException(404, "run expired - generate again")
        return runs[rid]

    @app.get("/")
    def index():
        return FileResponse(STATIC / "index.html")

    @app.get("/api/generators")
    def generators():
        return [cls.schema() for _, cls in sorted(registry().items())]

    @app.get("/api/files")
    def files(ext: str = ""):
        exts = {e.lower() for e in ext.split(",") if e}
        out = []
        for p in sorted(workdir.rglob("*")):
            rel = p.relative_to(workdir)
            if any(part in SKIP_DIRS or part.startswith(".") for part in rel.parts):
                continue
            if p.is_file() and (not exts or p.suffix.lower() in exts):
                out.append(str(rel))
        return out

    @app.post("/api/upload")
    async def upload(file: UploadFile = File(...)):
        name = re.sub(r"[^A-Za-z0-9._-]", "_", Path(file.filename or "upload").name)
        dest = workdir / "inputs" / name
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(await file.read())
        return {"path": str(dest.relative_to(workdir))}

    @app.post("/api/generate")
    def generate(req: GenerateRequest):
        try:
            r = run(req.generator, req.params, workdir=workdir, check=req.check)
        except (ValueError, FileNotFoundError, KeyError) as e:
            return JSONResponse({"error": str(e)}, status_code=400)
        except Exception as e:  # pragma: no cover - surface unexpected errors in the UI
            traceback.print_exc()
            return JSONResponse({"error": f"{type(e).__name__}: {e}"}, status_code=500)
        runs[r.id] = r
        while len(runs) > 20:
            runs.popitem(last=False)
        return r.preview()

    @app.get("/api/runs/{rid}/sheet{idx}.svg")
    def sheet_svg(rid: str, idx: int):
        r = get_run(rid)
        return Response(r.svg(idx - 1), media_type="image/svg+xml",
                        headers={"Content-Disposition": f'attachment; filename="sheet{idx}.svg"'})

    @app.get("/api/runs/{rid}/sheet{idx}.dxf")
    def sheet_dxf(rid: str, idx: int):
        r = get_run(rid)
        return Response(r.dxf(idx - 1), media_type="application/dxf",
                        headers={"Content-Disposition": f'attachment; filename="sheet{idx}.dxf"'})

    @app.get("/api/runs/{rid}/all.zip")
    def all_zip(rid: str):
        r = get_run(rid)
        return Response(r.zip_bytes(), media_type="application/zip",
                        headers={"Content-Disposition": f'attachment; filename="{r.generator}.zip"'})

    @app.get("/api/runs/{rid}/model.stl")
    def model_stl(rid: str):
        r = get_run(rid)
        if r.design.source_mesh is None:
            raise HTTPException(404, "no source mesh")
        return Response(r.design.source_mesh.export(file_type="stl"), media_type="model/stl")

    @app.post("/api/runs/{rid}/save")
    def save(rid: str, req: SaveRequest):
        r = get_run(rid)
        name = re.sub(r"[^A-Za-z0-9._-]", "_", req.name.strip()) or r.generator
        out = workdir / "output" / name
        files = r.write(out)
        return {"dir": str(out.relative_to(workdir)), "files": [str(f.relative_to(workdir)) for f in files]}

    app.mount("/static", StaticFiles(directory=STATIC), name="static")
    return app


def serve(host: str, port: int, workdir: Path, open_browser: bool = True) -> None:
    import uvicorn

    url = f"http://{host}:{port}/"
    print(f"laserpuzzle UI on {url}  (workdir: {workdir})")
    if open_browser:
        webbrowser.open(url)
    uvicorn.run(create_app(workdir), host=host, port=port, log_level="warning")
