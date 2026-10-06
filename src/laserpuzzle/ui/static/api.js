// Backend interface of the UI. app.js talks only to this module, never to fetch("/api/...") directly, so the
// same UI can run against another backend: index.html's importmap maps "laserpuzzle/api" to this file, and a
// different host page can map it to its own module exporting the same shape.
//
//   name                          string, for display / debugging
//   generators()                  -> [schema]                       (Generator.schema() of each generator)
//   listFiles(exts)    optional   -> [path]                         (input files to offer; omit = upload only)
//   upload(file: File)            -> path                           (value for a "file" param)
//   generate({generator, params, check}) -> Run.preview() JSON, or {error: message}; never throws
//   file(run, name)               -> Blob; name = "all.zip" | "sheet<N>.svg" | "sheet<N>.dxf" | "model.stl"
//   save(run, name)    optional   -> {dir, files} or {error}        (write outputs on the backend's disk)
//
// This default implementation talks HTTP to `laserpuzzle ui` (ui/server.py). URLs are relative so the UI also
// works when served under a sub-path.

async function json(res) {
  const data = await res.json().catch(() => ({}));
  if (!res.ok && !data.error) data.error = data.detail || `${res.status} ${res.statusText}`;
  return data;
}

async function check(res) {
  if (!res.ok) throw new Error((await json(res)).error);
  return res;
}

export default {
  name: "http",

  async generators() {
    return (await check(await fetch("api/generators"))).json();
  },

  async listFiles(exts) {
    return (await check(await fetch("api/files?ext=" + encodeURIComponent(exts.join(","))))).json();
  },

  async upload(file) {
    const fd = new FormData();
    fd.append("file", file);
    return (await (await check(await fetch("api/upload", { method: "POST", body: fd }))).json()).path;
  },

  async generate(req) {
    try {
      return await json(await fetch("api/generate", {
        method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(req),
      }));
    } catch (e) {
      return { error: String(e) };
    }
  },

  async file(run, name) {
    return (await check(await fetch(`api/runs/${run}/${name}`))).blob();
  },

  async save(run, name) {
    return json(await fetch(`api/runs/${run}/save`, {
      method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ name }),
    }));
  },
};
