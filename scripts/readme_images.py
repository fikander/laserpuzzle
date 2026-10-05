"""Build a self-contained HTML page that renders README showcase scenes with three.js.

    python scripts/readme_images.py /tmp/scenes.html [three-base-url]   # default: jsdelivr CDN
    # serve the folder, open scenes.html#convoy (or #lineup, #exploded, #pawn) at 1600x900, screenshot.

The parts are the real generator output (same outlines, transforms, engraving);
the page only adds plywood materials with laser-darkened edges, lights and a camera.
Trailers are hitched the same way as in tests/test_vehicle.py: ring on peg.
"""

from __future__ import annotations

import json
import math
import sys
import warnings
from pathlib import Path

import numpy as np

from laserpuzzle.pipeline import run

warnings.filterwarnings("ignore")
ROOT = Path(__file__).resolve().parents[1]


def _rz(deg: float) -> np.ndarray:
    a = math.radians(deg)
    m = np.eye(4)
    m[:2, :2] = [[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]]
    return m


def _t(x: float, y: float = 0.0, z: float = 0.0) -> np.ndarray:
    m = np.eye(4)
    m[:3, 3] = (x, y, z)
    return m


def _items(design, m: np.ndarray, tone: str = "birch", explode: float = 0.0) -> list[dict]:
    out = []
    for p in design.parts:
        e = np.asarray(p.explode, float) * explode
        tf = _t(*e) @ m @ np.asarray(p.transform)
        out.append({
            "kind": "part", "tone": tone, "t": p.thickness,
            "shapes": [{"outer": list(map(list, poly.exterior.coords)),
                        "holes": [list(map(list, h.coords)) for h in poly.interiors]}
                       for poly in (p.outline.geoms if hasattr(p.outline, "geoms") else [p.outline])],
            "engrave": [list(map(list, l.coords)) for l in p.engrave],
            "m": tf.T.flatten().round(5).tolist(),
        })
    for h in design.hardware:
        if h.kind != "cylinder":
            continue
        tf = m @ np.asarray(h.transform)
        if explode and "O-ring" in h.name:              # follow the wheel's middle layer outwards
            tf = _t(0, np.sign(tf[1, 3] + 1e-9) * 32 * explode) @ tf
        out.append({"kind": "rubber" if "O-ring" in h.name else "steel", "r": h.size["radius"],
                    "h": h.size["height"], "m": tf.T.flatten().round(5).tolist()})
    return out


def train(presets: list[str], m0: np.ndarray, swing: list[float], tones: list[str]) -> list[dict]:
    """A towing vehicle followed by hitched trailers; swing[i] = angle of trailer i (deg)."""
    items, m = [], m0
    prev = None
    for i, pr in enumerate(presets):
        d = run("vehicle", {"preset": pr}, check=False).design
        if prev is not None:
            m = m @ _t(prev.meta["hitch_rear_x"]) @ _rz(swing[i - 1]) @ _t(-d.meta["hitch_front_x"])
        items += _items(d, m, tones[i % len(tones)])
        prev = d
    return items


def scenes() -> dict[str, dict]:
    s: dict[str, dict] = {}
    s["convoy"] = {
        "items": train(["jeep", "trailer-caravan"], _t(40, -70) @ _rz(-6), [10], ["birch", "maple"])
        + train(["sedan", "trailer-box", "trailer-flatbed"], _t(170, 75) @ _rz(-3), [-9, 7],
                ["walnut", "birch", "maple"]),
        "view": [1.0, -1.25, 0.42], "fit": 0.6,
    }
    rows = [["bus", "van", "pickup"], ["jeep", "sedan", "hatchback", "sports"]]       # back row, front row
    items, k = [], 0
    for r_i, row in enumerate(rows):
        ds = [run("vehicle", {"preset": pr}, check=False).design for pr in row]
        total = sum(d.stats["length_mm"] for d in ds) + 30 * (len(ds) - 1)
        x = total / 2
        for d in ds:
            L = d.stats["length_mm"]
            items += _items(d, _t(x - L / 2 + (20 if r_i else -20), -120.0 * r_i), ["birch", "maple", "walnut"][k % 3])
            x -= L + 30
            k += 1
    s["lineup"] = {"items": items, "view": [0.5, -1.0, 0.5], "fit": 0.62}
    sedan = run("vehicle", {"preset": "sedan"}, check=False).design
    s["exploded"] = {"items": _items(sedan, np.eye(4), "birch", explode=1.6), "view": [0.9, -1.0, 0.8],
                     "fit": 0.72}
    pawn = run("stacked-layers", {"model": str(ROOT / "models/pawn.stl"), "height": 90}, check=False).design
    dowel = run("stacked-layers", {"model": str(ROOT / "models/pawn.stl"), "height": 90, "connector": "dowel",
                                   "dowel_diameter": 6, "spacer_diameter": 11}, check=False).design
    s["pawn"] = {"items": _items(pawn, _t(-40, 0), "birch") + _items(dowel, _t(40, 0), "walnut"),
                 "view": [0.9, -1.2, 0.55], "fit": 0.9}
    return s


PAGE = r"""<!doctype html><html><head><meta charset="utf-8"><title>laserpuzzle scenes</title>
<style>html,body{margin:0;height:100%;overflow:hidden;
background:radial-gradient(ellipse at 50% 35%,#fbf6ee 0%,#efe4d3 55%,#dccab0 100%)}canvas{display:block}</style>
<script type="importmap">{"imports":{"three":"__THREE__/build/three.module.js",
"three/addons/":"__THREE__/examples/jsm/"}}</script></head><body>
<script type="module">
import * as THREE from "three";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
const SCENES = __DATA__;
const s = SCENES[location.hash.slice(1) || "convoy"];
const W = innerWidth, H = innerHeight;
const r = new THREE.WebGLRenderer({ antialias: true, alpha: true, preserveDrawingBuffer: true });
r.setPixelRatio(2); r.setSize(W, H); r.shadowMap.enabled = true; r.shadowMap.type = THREE.PCFSoftShadowMap;
r.toneMapping = THREE.ACESFilmicToneMapping; r.toneMappingExposure = 0.95;
document.body.appendChild(r.domElement);
const scene = new THREE.Scene();
scene.environment = new THREE.PMREMGenerator(r).fromScene(new RoomEnvironment(), 0.04).texture;
scene.environmentIntensity = 0.3;
const TONES = { birch: 0xdcb684, maple: 0xe6c592, walnut: 0xb98552 };
const edge = new THREE.MeshStandardMaterial({ color: 0x4a2c17, roughness: 0.95 });     // laser-burnt edges
const faces = {}; for (const k in TONES) faces[k] = new THREE.MeshStandardMaterial({ color: TONES[k], roughness: 0.78 });
const steel = new THREE.MeshStandardMaterial({ color: 0xb8bcc2, metalness: 0.9, roughness: 0.3 });
const rubber = new THREE.MeshStandardMaterial({ color: 0x222222, roughness: 0.9 });
const lineMat = new THREE.LineBasicMaterial({ color: 0x6b4226, transparent: true, opacity: 0.75 });
const root = new THREE.Group(); root.rotation.x = -Math.PI / 2; scene.add(root);   // data is Z-up
const P = (a) => a.map(([x, y]) => new THREE.Vector2(x, y));
for (const it of s.items) {
  const m = new THREE.Matrix4().fromArray(it.m);
  let obj;
  if (it.kind === "part") {
    obj = new THREE.Group();
    for (const sh of it.shapes) {
      const shape = new THREE.Shape(P(sh.outer)); for (const h of sh.holes) shape.holes.push(new THREE.Path(P(h)));
      const g = new THREE.ExtrudeGeometry(shape, { depth: it.t, bevelEnabled: false, curveSegments: 1 });
      const mesh = new THREE.Mesh(g, [faces[it.tone], edge]); mesh.castShadow = mesh.receiveShadow = true; obj.add(mesh);
    }
    for (const l of it.engrave) {
      const g = new THREE.BufferGeometry().setFromPoints(l.map(([x, y]) => new THREE.Vector3(x, y, it.t + 0.03)));
      obj.add(new THREE.Line(g, lineMat));
    }
  } else {
    let g;
    if (it.kind === "steel") { g = new THREE.CylinderGeometry(it.r, it.r, it.h, 32); g.rotateX(Math.PI / 2); }
    else g = new THREE.TorusGeometry(it.r - it.h * 0.4, it.h * 0.45, 16, 64);        // O-ring tyre
    g.translate(0, 0, it.h / 2);
    obj = new THREE.Mesh(g, it.kind === "steel" ? steel : rubber); obj.castShadow = true;
  }
  obj.matrixAutoUpdate = false; obj.matrix.copy(m); root.add(obj);
}
root.updateMatrixWorld(true);
const box = new THREE.Box3().setFromObject(root), c = box.getCenter(new THREE.Vector3()), sz = box.getSize(new THREE.Vector3());
root.position.y -= box.min.y; c.y -= box.min.y;
const ground = new THREE.Mesh(new THREE.PlaneGeometry(4000, 4000), new THREE.ShadowMaterial({ opacity: 0.22 }));
ground.rotation.x = -Math.PI / 2; ground.receiveShadow = true; scene.add(ground);
scene.add(new THREE.HemisphereLight(0xfff6e8, 0xb89a74, 0.9));
const sun = new THREE.DirectionalLight(0xfff1dd, 2.4); const R = Math.max(sz.x, sz.z);
sun.position.set(c.x - R * 0.6, R * 1.4, c.z + R * 0.9); sun.target.position.copy(c); scene.add(sun.target);
sun.castShadow = true; sun.shadow.mapSize.set(4096, 4096); sun.shadow.radius = 6; sun.shadow.bias = -0.0004;
Object.assign(sun.shadow.camera, { left: -R, right: R, top: R, bottom: -R, near: 1, far: R * 5 }); scene.add(sun);
const cam = new THREE.PerspectiveCamera(28, W / H, 1, 10000);
const [vx, vy, vz] = s.view;                     // view direction in data coords (Z up) -> three (Y up)
const dir = new THREE.Vector3(vx, vz, -vy).normalize();
const rad = sz.length() / 2, dist = rad / Math.sin(THREE.MathUtils.degToRad(cam.fov / 2)) * s.fit;
cam.position.copy(c).addScaledVector(dir, dist); cam.lookAt(c);
let frames = 0;                                  // keep drawing: headless screenshots can catch a stale frame
(function loop() { r.render(scene, cam); if (++frames === 10) document.title = "ready"; requestAnimationFrame(loop); })();
</script></body></html>"""


def main() -> None:
    out = Path(sys.argv[1] if len(sys.argv) > 1 else "scenes.html")
    three = sys.argv[2] if len(sys.argv) > 2 else "https://cdn.jsdelivr.net/npm/three@0.169.0"
    out.write_text(PAGE.replace("__DATA__", json.dumps(scenes())).replace("__THREE__", three))
    print(f"wrote {out} ({out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
