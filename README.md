# CAD Bench

A CAD viewer and small parametric bench that runs entirely in the browser. The
OpenCASCADE geometry kernel is loaded as WebAssembly, so there is nothing to
install and files never leave the device. It is built to be published as a
Claude artifact, and also runs from any static file server.

This is the browser-only half of a two-part exploration. The second half, a
Python MCP server that lets Claude drive a server-side kernel, is not started.

## What it does

- Shows the model full-window, with one dock of controls at the bottom (fit
  view, edges, history, open file) and a size, volume and triangle readout
  top-right.
- Keeps a model as a history of steps (box, cylinder, round corners, hole,
  move, import) and rebuilds it live as you drag any step's sliders. The
  history opens from the dock as a floating panel. The sample mounting plate
  (40 × 24 × 6 mm) is three such steps.
- Keeps the exact kernel shape of every part, not only its mesh, so later
  steps can work on it: you can drill a hole in an imported part.
- Undo and redo, deleting a step, and rolling back to any earlier step.
- Saves the model in the browser and reopens it on the next visit.
- Opens STEP files (`.step`, `.stp`) by file picker or drag-and-drop, keeps the
  assembly structure, and places every part where the assembly puts it.
- Click a part to select it; the readout and dock then describe that part.
  With nothing selected they describe the whole model.

Not there yet: export, saving to a file or sharing a model with someone else,
measuring between features, a part list with show/hide, picking faces or edges
for a step (round corners only finds vertical edges; a hole is always along Z).

## Run it locally

Requires Node 20 or newer.

```sh
npm install
npm start          # builds dist/ and serves it at http://127.0.0.1:8765/
npm test           # checks the document model against the real kernel
npm test -- path/to/model.step   # also loads a STEP file
```

Set `PORT` to serve on a different port.

## Layout

| Path | What it is |
|---|---|
| `src/index.html` | The page's markup and styles |
| `src/ui/app.js` | Page entry point: redraws from each document answer, saving, opening files, dock buttons |
| `src/ui/viewer.js` | Three.js view: the drawn parts, selection, picking, camera, theme |
| `src/ui/history-panel.js` | The History panel: steps, sliders, rollback, delete, add |
| `src/ui/readout.js` | The top-right readout and the dock's part label |
| `src/ui/kernel-client.js` | Starts the worker and queues commands to it |
| `src/cad-doc.js` | The document: step list, the kernel shapes each step produces, undo, rollback |
| `src/cad-core.js` | Geometry helpers: STEP import and assembly walk, meshing, mesh measurement |
| `src/cad-store.js` | Saves the step list and imported files in the browser (IndexedDB) |
| `src/cad-worker.js` | Web Worker that loads the kernel and runs the document off the main thread |
| `scripts/build.mjs` | Assembles `dist/` from `src/` and the two npm packages |
| `scripts/serve.mjs` | Dependency-free static server for `dist/` |
| `test/smoke.mjs` | Node test of the document model |

`dist/` and `node_modules/` are generated and not committed.

## How it fits together

`ui/kernel-client.js` starts `cad-worker.js` as a module worker. The worker downloads
the kernel binary, initialises [occt-wasm](https://www.npmjs.com/package/occt-wasm),
and owns one `Model` from `cad-doc.js`. The page sends it commands (`add`,
`update`, `remove`, `roll`, `undo`, `redo`, `open`, `sample`, `load`); each
answer is the whole document state: the step list, any per-step errors, and the
parts to draw.

The document is the step list. A step is `{ id, op, params }`; steps that
change a part name it in `params.body`. Rebuilding walks the list and caches
each step's resulting shape under a key made from the step and its input, so
editing step N recomputes only N and what follows, and undo is a cache hit.
Shapes the current history no longer uses are released after a short grace
period. A part's key also tells the page whether it already holds that mesh,
so unchanged parts are not meshed or transferred again.

What is saved is the step list as JSON (`Model.toJSON()`), plus the original
text of each imported STEP file, stored separately. Shapes are never saved;
they are rebuilt. The same JSON is what a future Claude-driven server would
read and write.

Two details are easy to trip over:

- **The kernel binary is split in two.** The artifact host caps files at
  20 MiB and the binary is 20.4 MiB, so `build.mjs` writes `kernel-0.wasm` and
  `kernel-1.wasm` and the worker joins them. The piece count and byte total
  are hard-coded in `cad-worker.js`; the build fails with a clear message if
  an occt-wasm upgrade changes them.
- **Parts are meshed in their assembled position.** Some STEP files keep part
  geometry far from the origin (the test hand has coordinates around
  130,000 mm). Meshing in place and then moving 32-bit vertices loses
  precision, so each part is placed with the kernel's exact transform first
  and meshed afterwards.

Three more things to know:

- **Imported part volumes come from the mesh, not the kernel.** They are
  within a fraction of a percent, and exact measurement was several seconds
  slower on a 27-part assembly. Parts built from steps use the exact value.
- **Saving is per browser.** IndexedDB is tied to this browser and this
  address; where the browser gives the page no storage the History panel
  shows "not saved" and the page still works. Reopening an imported model reads the
  STEP file again, which takes as long as opening it did.
- **A step that fails keeps its place.** It is marked in the history with the
  reason, and the steps after it run on what exists. Adding a step that cannot
  build is refused instead.

## Publishing as a Claude artifact

Run `npm run build` and publish every file in `dist/` with its relative path.
Artifact pages may only fetch their own files, which is why Three.js and the
kernel are vendored into `dist/` instead of loaded from a CDN.

## Dependencies

- `occt-wasm` 5.18.5: OpenCASCADE compiled to WebAssembly. The package is
  MIT OR Apache-2.0; the OpenCASCADE kernel inside it is LGPL-2.1 with an
  exception.
- `three` 0.187.0: rendering (MIT)

Versions are pinned exactly. Review the licences of both packages before
distributing a build.
