// laserpuzzle preview UI. Plain ES modules + three.js from CDN, no build step.
import * as THREE from "three";
import { OrbitControls } from "three/addons/controls/OrbitControls.js";
import { STLLoader } from "three/addons/loaders/STLLoader.js";
import api from "laserpuzzle/api";

const $ = (s) => document.querySelector(s);
const state = { generators: [], gen: null, result: null, timer: null, seq: 0 };

const GROUP_COLORS = { layer: 0xd9b98c, spine: 0xb08552, spacer: 0xe8d3b0, part: 0xd9b98c };
const groupColor = (g) => GROUP_COLORS[g] ?? new THREE.Color().setHSL((hash(g) % 360) / 360, 0.35, 0.65).getHex();
function hash(s) { let h = 0; for (const c of s) h = (h * 31 + c.charCodeAt(0)) | 0; return Math.abs(h); }

const store = {
  get(k) { try { return JSON.parse(localStorage.getItem(k)); } catch { return null; } },
  set(k, v) { try { localStorage.setItem(k, JSON.stringify(v)); } catch {} },
};

// ------------------------------------------------------------------ form
async function init() {
  state.generators = await api.generators();
  if (!api.save) $(".save-row").hidden = true;
  const sel = $("#generator");
  sel.innerHTML = state.generators.map((g) => `<option value="${g.id}">${g.name}</option>`).join("");
  sel.value = store.get("lp.gen") ?? state.generators[0]?.id;
  sel.onchange = () => { store.set("lp.gen", sel.value); firstFit = true; buildForm(); };
  await buildForm();
}

async function buildForm() {
  const gen = state.generators.find((g) => g.id === $("#generator").value) ?? state.generators[0];
  state.gen = gen;
  $("#gen-desc").textContent = gen.description;
  $("#gen-desc").title = gen.description;
  const saved = store.get("lp.params." + gen.id) ?? {};
  const form = $("#form");
  form.innerHTML = "";
  const groups = {};
  for (const p of gen.params) (groups[p.group] ??= []).push(p);
  for (const [name, params] of Object.entries(groups)) {
    const det = document.createElement("details");
    det.open = name !== "Material & machine" || !store.get("lp.fabClosed");
    det.innerHTML = `<summary>${name}</summary><div></div>`;
    if (name === "Material & machine") det.ontoggle = () => store.set("lp.fabClosed", !det.open);
    for (const p of params) det.lastChild.appendChild(await field(p, saved[p.name] ?? p.default));
    form.appendChild(det);
  }
  form.oninput = () => { persist(); schedule(); };
  schedule(0);
}

async function field(p, value) {
  const div = document.createElement("div");
  div.className = "field " + p.kind;
  const unit = p.unit ? `<span class="unit">${p.unit}</span>` : "";
  const help = p.help ? `<div class="help">${p.help}</div>` : "";
  const attrs = (o) => Object.entries(o).filter(([, v]) => v !== null && v !== undefined).map(([k, v]) => `${k}="${v}"`).join(" ");
  if (p.kind === "bool") {
    div.innerHTML = `<label><input type="checkbox" name="${p.name}" ${value ? "checked" : ""}> ${p.label}</label>${help}`;
  } else if (p.kind === "choice") {
    div.innerHTML = `<label>${p.label}${unit}</label><select name="${p.name}">${p.choices.map((c) => `<option ${c === value ? "selected" : ""}>${c}</option>`).join("")}</select>${help}`;
  } else if (p.kind === "file") {
    const files = api.listFiles ? await api.listFiles(p.accept) : [];
    if (!files.includes(value)) value = files[0] ?? "";
    div.innerHTML = `<label>${p.label}</label>
      <div class="file-row"><select name="${p.name}">${files.map((f) => `<option ${f === value ? "selected" : ""}>${f}</option>`).join("")}</select>
      <button type="button" title="Upload a file">Upload…</button></div>
      <input type="file" accept="${p.accept.join(",")}" hidden>${help}`;
    const [btn, input, select] = [div.querySelector("button"), div.querySelector("input[type=file]"), div.querySelector("select")];
    btn.onclick = () => input.click();
    input.onchange = async () => {
      if (!input.files[0]) return;
      let path;
      try { path = await api.upload(input.files[0]); } catch (e) { setStatus(`upload failed: ${e.message}`, "error"); return; }
      input.value = "";
      if (![...select.options].some((o) => o.value === path)) select.add(new Option(path, path));
      select.value = path; persist(); schedule(0);
    };
  } else if (p.kind === "color") {
    div.innerHTML = `<label>${p.label}</label><input type="color" name="${p.name}" value="${value ?? "#000000"}">${help}`;
  } else {
    const type = p.kind === "str" ? "text" : "number";
    const step = p.step ?? (p.kind === "int" ? 1 : "any");
    div.innerHTML = `<label>${p.label}${unit}</label><input type="${type}" name="${p.name}" value="${value ?? ""}" ${attrs({ min: p.min, max: p.max, step })}>${help}`;
  }
  return div;
}

function values() {
  const out = {};
  for (const p of state.gen.params) {
    const el = $("#form").elements[p.name];
    if (!el) continue;
    out[p.name] = p.kind === "bool" ? el.checked : el.value;
  }
  return out;
}
function persist() { store.set("lp.params." + state.gen.id, values()); }

function schedule(delay = 450) {
  clearTimeout(state.timer);
  if (delay > 0 && !$("#auto").checked) return;
  state.timer = setTimeout(generate, delay);
}

// -------------------------------------------------------------- generate
async function generate() {
  const seq = ++state.seq;
  setStatus("generating…", "busy");
  const params = values();
  const missing = state.gen.params.find((p) => p.kind === "file" && !params[p.name]);
  if (missing) { setStatus(`Upload a file for "${missing.label}" to start`); return; }
  const data = await api.generate({ generator: state.gen.id, params, check: $("#check").checked });
  if (seq !== state.seq) return; // a newer request superseded this one
  if (data.error) { setStatus(data.error, "error"); return; }
  state.result = data;
  const t = data.timings;
  setStatus(`${data.parts.length} parts · ${data.sheets.length} sheet(s) · ${(t.generate + t.nest + t.validate).toFixed(2)} s`);
  renderInfo(data);
  renderSheets(data);
  renderAssembly(data);
}
function setStatus(text, cls = "") { const s = $("#status"); s.textContent = text; s.className = "status " + cls; s.title = text; }

// ------------------------------------------------------------------ info
function renderInfo(d) {
  const dl = $("#downloads");
  const link = (file, text, cls = "") => `<a href="#" class="${cls}" data-file="${file}">${text}</a>`;
  dl.innerHTML = link("all.zip", "All files (.zip)", "primary") +
    d.sheets.map((s, i) => link(`sheet${i + 1}.svg`, `sheet ${i + 1} .svg`) + link(`sheet${i + 1}.dxf`, ".dxf")).join("");
  if (!$("#save-name").value) $("#save-name").value = (d.params.model || d.generator).split("/").pop().replace(/\.[^.]+$/, "");
  const warns = [...d.warnings, ...d.collisions.map((c) => c.error ? `collision check: ${c.error}` : `Overlap: ${c.a} ↔ ${c.b} (${c.volume_mm3} mm³)`)];
  $("#warnings-card").hidden = !warns.length;
  $("#warnings").innerHTML = warns.map((w) => `<li>${esc(w)}</li>`).join("");
  const s = d.stats, rows = [];
  for (const [k, v] of Object.entries(s)) if (typeof v !== "object") rows.push([k.replace(/_/g, " "), v]);
  if (s.footprint_mm) rows.push(["footprint mm", s.footprint_mm.join(" × ")]);
  rows.push(["cut length", (d.cut_length_mm / 1000).toFixed(2) + " m"]);
  d.sheets.forEach((sh, i) => rows.push([`sheet ${i + 1} use`, Math.round(sh.utilisation * 100) + "%"]));
  $("#stats").innerHTML = rows.map(([k, v]) => `<dt>${k}</dt><dd>${v}</dd>`).join("");
  $("#bom").innerHTML = d.bom.map((b) => `<tr><td>${esc(b.item)}${b.note ? ` <span class="muted small">(${esc(b.note)})</span>` : ""}</td><td>${b.count}</td></tr>`).join("");
  $("#notes").innerHTML = d.notes.map((n) => `<li>${esc(n)}</li>`).join("");
}
const esc = (s) => String(s).replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c]));

function renderSheets(d) {
  $("#sheets").innerHTML = d.sheets.map((s, i) =>
    `<div class="sheet"><h4><span>Sheet ${i + 1} — ${s.width} × ${s.height} mm, ${s.count} parts</span><span>${Math.round(s.utilisation * 100)}% used</span></h4>${s.svg.replace(/<\?xml[^>]*>/, "")}</div>`
  ).join("");
}

// downloads go through api.file() (a Blob), so they work with any backend, not only HTTP routes
$("#downloads").onclick = async (ev) => {
  const a = ev.target.closest("a[data-file]");
  if (!a || !state.result) return;
  ev.preventDefault();
  const { run, generator } = state.result, file = a.dataset.file;
  let blob;
  try { blob = await api.file(run, file); } catch (e) { setStatus(`download failed: ${e.message}`, "error"); return; }
  const url = URL.createObjectURL(blob);
  const tmp = Object.assign(document.createElement("a"), { href: url, download: file === "all.zip" ? `${generator}.zip` : file });
  document.body.appendChild(tmp); tmp.click(); tmp.remove();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
};

$("#save").onclick = async () => {
  if (!state.result || !api.save) return;
  const j = await api.save(state.result.run, $("#save-name").value);
  $("#save-result").textContent = j.dir ? `Saved ${j.files.length} files to ${j.dir}/` : (j.error || "save failed");
};

// --------------------------------------------------------------------- 3D
const three = (() => {
  const el = $("#viewport");
  const renderer = new THREE.WebGLRenderer({ antialias: true, preserveDrawingBuffer: true });
  renderer.setPixelRatio(window.devicePixelRatio);
  el.appendChild(renderer.domElement);
  const scene = new THREE.Scene();
  scene.background = new THREE.Color(0xf4f1ec);
  THREE.Object3D.DEFAULT_UP.set(0, 0, 1);
  const camera = new THREE.PerspectiveCamera(35, 1, 0.5, 20000);
  camera.up.set(0, 0, 1);
  const controls = new OrbitControls(camera, renderer.domElement);
  controls.enableDamping = true;
  scene.add(new THREE.HemisphereLight(0xffffff, 0x8a7a66, 1.6));
  const sun = new THREE.DirectionalLight(0xffffff, 1.6);
  sun.position.set(1, -1.4, 2);
  scene.add(sun);
  const grid = new THREE.GridHelper(400, 40, 0xd8d0c4, 0xe6e0d6);
  grid.rotation.x = Math.PI / 2;
  scene.add(grid);
  const root = new THREE.Group();
  scene.add(root);
  function resize() {
    const { clientWidth: w, clientHeight: h } = el;
    if (!w || !h) return;
    renderer.setSize(w, h); camera.aspect = w / h; camera.updateProjectionMatrix();
  }
  new ResizeObserver(resize).observe(el);
  (function loop() { controls.update(); renderer.render(scene, camera); requestAnimationFrame(loop); })();
  return { scene, camera, controls, root, renderer, grid, ghost: null, parts: [] };
})();

let firstFit = true;
function renderAssembly(d) {
  const { root } = three;
  root.clear();
  three.parts = [];
  for (const p of d.parts) {
    const wrap = new THREE.Group();           // explode offset lives here
    const body = new THREE.Group();           // part's own placement
    body.matrixAutoUpdate = false;
    body.matrix.fromArray(p.matrix);
    const color = groupColor(p.group);
    const mat = new THREE.MeshStandardMaterial({ color, roughness: 0.85, metalness: 0 });
    for (const s of p.shapes) {
      const shape = new THREE.Shape(s.outer.map(([x, y]) => new THREE.Vector2(x, y)));
      for (const h of s.holes) shape.holes.push(new THREE.Path(h.map(([x, y]) => new THREE.Vector2(x, y))));
      const geo = new THREE.ExtrudeGeometry(shape, { depth: p.thickness, bevelEnabled: false, curveSegments: 1 });
      const mesh = new THREE.Mesh(geo, mat);
      mesh.userData.part = p;
      body.add(mesh);
      body.add(new THREE.LineSegments(new THREE.EdgesGeometry(geo, 25), new THREE.LineBasicMaterial({ color: 0x5c4630, transparent: true, opacity: 0.55 })));
    }
    const eng = new THREE.Group();
    eng.name = "engrave";
    for (const l of p.engrave) {
      const pts = l.map(([x, y]) => new THREE.Vector3(x, y, p.thickness + 0.02));
      eng.add(new THREE.Line(new THREE.BufferGeometry().setFromPoints(pts), new THREE.LineBasicMaterial({ color: 0x7a4b1e })));
    }
    eng.visible = $("#engrave").checked;
    body.add(eng);
    wrap.add(body);
    wrap.userData = { explode: new THREE.Vector3(...p.explode), part: p, mat, color };
    root.add(wrap);
    three.parts.push(wrap);
  }
  for (const h of d.hardware) {
    if (h.kind !== "cylinder") continue;
    const g = new THREE.CylinderGeometry(h.size.radius, h.size.radius, h.size.height, 32);
    g.rotateX(Math.PI / 2); g.translate(0, 0, h.size.height / 2);
    const m = new THREE.Mesh(g, new THREE.MeshStandardMaterial({ color: 0x8c6b47, roughness: 0.7 }));
    m.matrixAutoUpdate = false; m.matrix.fromArray(h.matrix);
    root.add(m);
  }
  applyExplode();
  loadGhost(d);
  if (firstFit) { fitView(); firstFit = false; }
}

function applyExplode() {
  const f = +$("#explode").value;
  for (const w of three.parts) w.position.copy(w.userData.explode).multiplyScalar(f);
}

async function loadGhost(d) {
  if (three.ghost) { three.scene.remove(three.ghost); three.ghost = null; }
  if (!$("#ghost").checked || !d.has_mesh) return;
  const buf = await (await api.file(d.run, "model.stl")).arrayBuffer();
  const geo = new STLLoader().parse(buf);
  three.ghost = new THREE.Mesh(geo, new THREE.MeshBasicMaterial({ color: 0x3b82f6, transparent: true, opacity: 0.12, depthWrite: false }));
  three.scene.add(three.ghost);
}

function fitView() {
  const box = new THREE.Box3().setFromObject(three.root);
  if (box.isEmpty()) return;
  const c = box.getCenter(new THREE.Vector3()), size = box.getSize(new THREE.Vector3()).length();
  three.controls.target.copy(c);
  three.camera.position.copy(c).add(new THREE.Vector3(0.9, -1.6, 0.8).normalize().multiplyScalar(size * 1.6));
  three.camera.near = size / 100; three.camera.far = size * 100; three.camera.updateProjectionMatrix();
}

// click to identify a part
const ray = new THREE.Raycaster();
let selected = null;
three.renderer.domElement.addEventListener("click", (ev) => {
  const r = three.renderer.domElement.getBoundingClientRect();
  const v = new THREE.Vector2(((ev.clientX - r.left) / r.width) * 2 - 1, -((ev.clientY - r.top) / r.height) * 2 + 1);
  ray.setFromCamera(v, three.camera);
  const hit = ray.intersectObjects(three.root.children, true).find((h) => h.object.userData.part);
  if (selected) selected.userData.mat.color.setHex(selected.userData.color);
  selected = null;
  if (hit) {
    selected = three.parts.find((w) => w.userData.part === hit.object.userData.part);
    selected.userData.mat.color.setHex(0xf59e0b);
  }
  $("#picked").textContent = selected ? selected.userData.part.name : "";
});

$("#explode").oninput = applyExplode;
$("#ghost").onchange = () => state.result && loadGhost(state.result);
$("#engrave").onchange = () => three.root.traverse((o) => { if (o.name === "engrave") o.visible = $("#engrave").checked; });
$("#reset-view").onclick = fitView;
$("#go").onclick = () => schedule(0);
document.querySelectorAll(".tabs button").forEach((b) => b.onclick = () => {
  document.querySelectorAll(".tabs button, .tab").forEach((x) => x.classList.remove("active"));
  b.classList.add("active"); $("#tab-" + b.dataset.tab).classList.add("active");
});

init().catch((e) => setStatus(String(e), "error"));
