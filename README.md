# CAD Bench

A CAD viewer and small parametric bench that runs entirely in the browser. The
OpenCASCADE geometry kernel is loaded as WebAssembly, so there is nothing to
install and files never leave the device. It is built to be published as a
Claude artifact, and also runs from any static file server.

This is the browser-only half of a two-part exploration. The second half, a
Python MCP server that lets Claude drive a server-side kernel, is not started.

## What it does

- Builds a sample mounting plate in the kernel and rebuilds it live from five
  sliders (length, width, thickness, hole diameter, corner radius).
- Opens STEP files (`.step`, `.stp`) by file picker or drag-and-drop, keeps the
  assembly structure, and places every part where the assembly puts it.
- Lists parts by sub-assembly with show/hide, selection, and a "show only
  selected" view.
- Reports size, volume and triangle count for the selected part.

Not there yet: export, saving, measuring between features, editing imported
parts.

## Run it locally

Requires Node 20 or newer.

```sh
npm install
npm start          # builds dist/ and serves it at http://127.0.0.1:8765/
npm test           # checks the geometry module against the real kernel
npm test -- path/to/model.step   # also loads a STEP file
```

Set `PORT` to serve on a different port.

## Layout

| Path | What it is |
|---|---|
| `src/index.html` | The page: interface, Three.js viewer, part list, theme |
| `src/cad-core.js` | Geometry logic: STEP import and assembly walk, sample part, mesh measurement |
| `src/cad-worker.js` | Web Worker that loads the kernel and runs `cad-core.js` off the main thread |
| `scripts/build.mjs` | Assembles `dist/` from `src/` and the two npm packages |
| `scripts/serve.mjs` | Dependency-free static server for `dist/` |
| `test/smoke.mjs` | Node test of `cad-core.js` |

`dist/` and `node_modules/` are generated and not committed.

## How it fits together

`index.html` starts `cad-worker.js` as a module worker. The worker downloads
the kernel binary, initialises [occt-wasm](https://www.npmjs.com/package/occt-wasm),
and answers two requests: build the sample plate from parameters, or load a
STEP file. Each answer is a list of parts with triangle meshes, which the page
hands to Three.js.

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

STEP part volumes come from the mesh, not the kernel. They are within a
fraction of a percent, and exact measurement was several seconds slower on a
27-part assembly. The sample plate uses the exact kernel value.

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
