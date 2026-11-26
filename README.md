# CAD Bench

A Claude plugin for 3D CAD. Claude builds real solid models by writing
[CadQuery](https://cadquery.readthedocs.io) scripts, checks them with
measurements and rendered views, and exports STEP, STL and other files. A
viewer page shows the person the same model as it changes.

There are no modelling controls for the person to operate. You describe the
part; Claude does the modelling through the plugin's tools.

## What is in the plugin

| Piece | What it is |
|---|---|
| MCP server (`server/`) | Python. Runs CadQuery scripts and exposes the tools below |
| Skill (`skills/cad-modeling/`) | Tells Claude how to model with the tools and check its work |
| Viewer (`src/`, built into the server) | Three.js page that displays the current model |

## How Claude works with a model

The model is a CadQuery script. Claude sends a full script with `run_model`
or changes the current one with `edit_model`. Each reply carries every part's
size, volume and extents, anything the script printed, and one picture with
four views. A script that fails changes nothing: the reply names the failing
line and the previous version stays current.

| Tool | Purpose |
|---|---|
| `run_model` | Build from a complete script and save a new version |
| `edit_model` | Exact text replacement in the current script, then rebuild |
| `get_model` | The current script, version number and parts |
| `render` | A named view or custom direction; optional section cut; highlight what a selector matches |
| `inspect` | List a part's faces, edges or vertices with position, type, normal and size |
| `measure` | Shortest distance (and angle, where it applies) between two selections |
| `export` | STEP, STL, 3MF, GLB, BREP or SVG |
| `import_file` | Make a STEP or BREP file available to the script |
| `list_versions`, `restore_version` | History and undo |
| `list_models` | Models saved on this computer |
| `open_viewer` | Address of the live viewer page |
| `get_mesh`, `get_history` | Used by the viewer only; hidden from Claude by hosts that support MCP Apps |

Models are plain files, one folder each, under `~/Documents/CAD Bench/`
(set `CADBENCH_HOME` to move them): `current.py`, every version under
`versions/`, imported files under `assets/`, exported files under `exports/`.

## Install

Requires [uv](https://docs.astral.sh/uv/). The server pins Python 3.12 and
its dependencies; `uv` downloads them (about 1.3 GB installed) the first time
the server starts.

**The first start on a computer takes one to two minutes.** Measured on an
Apple-silicon Mac: 85 to 97 seconds, almost all of it macOS checking the
large native CAD libraries (OpenCASCADE and VTK) the first time each is
loaded. It is not the download and not Python compiling. What the plugin does
about it:

- The server itself starts at once and begins loading CadQuery in the
  background, so the tools are listed immediately.
- A tool called before the kernel is ready answers within 25 seconds that it
  is still starting, and the skill tells Claude to say so and try again,
  instead of the call hanging.
- The plugin installs with `UV_LINK_MODE=hardlink`, so the checked library
  files are shared with `uv`'s cache. A later reinstall (a plugin update) then
  starts in about 12 seconds instead of paying the full cost again. This needs
  the plugin and `uv`'s cache on the same disk; otherwise `uv` copies and each
  reinstall is slow once.

After the first time, starting takes about 3 to 5 seconds.

- **Claude Code**: `claude --plugin-dir .` from this folder.
- **Cowork**: `npm run package`, then upload `dist/cad-bench-plugin.zip` at
  Customize > Plugins > Add > Upload plugin. Cowork runs a plugin's local
  server only when the session runs on your computer.

### What has and has not been tried

Tested here: the server over stdio, every tool, and the viewer as a local
page. `claude plugin validate .` passes.

Not yet tried in a real host:

- **The inline viewer.** The server offers the viewer as an MCP App
  (`ui://cad-bench/viewer.html`). Whether the Claude desktop app renders it
  inline from a plugin's local server is untested. If it does not, Claude
  still gets the pictures, and `open_viewer` gives a local address.
- **Cowork.** Whether `uv` can install the dependencies where Cowork runs
  the server is untested.
- **Plain chat.** Chat ignores a plugin's local server. The documented route
  there is a desktop extension (`.mcpb`); that packaging is not built yet.
- **Claude Code** shows MCP Apps as text, so there the viewer is the local
  page.

## Trust

A CadQuery script is ordinary Python. It runs on your computer with your
permissions, the same as any code Claude runs for you. The server runs
scripts in a separate process and stops them after a time limit, which
contains hangs and crashes; it is not a security sandbox.

## Develop

```sh
npm install                 # viewer build tools
npm run build               # bundles the viewer into server/cadbench_mcp/static/viewer.html
npm test                    # server tests against the real kernel (uv run --project server pytest)
npm run package             # build + dist/cad-bench-plugin.zip
uv run --project server cadbench-mcp --page   # serve only the viewer page, at http://127.0.0.1:8791/
```

The built `viewer.html` is committed so an installed plugin needs no Node.
Rebuild and commit it whenever `src/` changes.

## Layout

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest; starts the server with `uv run` |
| `skills/cad-modeling/SKILL.md` | The modelling skill |
| `server/cadbench_mcp/server.py` | The tools, the viewer resource and the local viewer page |
| `server/cadbench_mcp/worker.py` | Everything that touches CadQuery: running scripts, describing parts, meshing, rendering, exporting |
| `server/cadbench_mcp/runner.py` | Starts the worker process and replaces it on a timeout or crash |
| `server/cadbench_mcp/store.py` | Models and versions on disk |
| `server/tests/` | Tests through the worker process and through an MCP client |
| `src/index.html` | The viewer's markup and styles |
| `src/ui/app.js` | Viewer entry point |
| `src/ui/host.js` | Gets models from the host (MCP App) or by polling the local server |
| `src/ui/viewer.js` | Three.js view: parts, selection, picking, camera, theme |
| `src/ui/readout.js` | The top-right readout and the dock's part label |
| `scripts/build.mjs` | Bundles the viewer into one HTML file |
| `scripts/package.mjs` | Zips the plugin for upload |

## How it fits together

`server.py` is a thin MCP front. Every operation that needs geometry goes to
one long-lived worker process, which imports CadQuery once and caches the
shapes of the last few scripts by hash. Because each request names its
script, the worker holds no state the server depends on: it can be killed on
a timeout and the next request simply rebuilds.

Pictures are drawn off-screen with VTK (already a CadQuery dependency), with
no perspective so lengths can be compared by eye.

The viewer never sees a script. A build tool's result carries only the model
name and version; the viewer then asks for that version's meshes through
`get_mesh` (inline) or `/mesh` (local page), so triangle data stays out of
Claude's context. The History button in the viewer lists every saved version
(`get_history` or `/history`); picking one shows it without changing the
model, which stays at its latest version until Claude restores another.

## History

Earlier versions ran the OpenCASCADE kernel in the browser as WebAssembly,
with a step list edited in the page. The last commit of that design is
tagged `browser-kernel`.

## Dependencies

- `cadquery` (Apache-2.0) on the OpenCASCADE kernel (LGPL-2.1 with an
  exception), and `vtk` (BSD) for pictures
- `mcp`: the Model Context Protocol Python SDK (MIT)
- `three` 0.187.0 (MIT) and `@modelcontextprotocol/ext-apps` 2.0.4 in the
  viewer
- `esbuild` to build the viewer

Review the licences before distributing a build.
