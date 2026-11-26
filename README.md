# CadSkill

3D CAD for Claude. Claude builds real solid models by writing
[CadQuery](https://cadquery.readthedocs.io) scripts, checks them with
measurements and rendered views, and exports STEP, STL and other files. A
viewer page shows the person the same model as it changes.

There are no modelling controls for the person to operate. You describe the
part; Claude does the modelling.

## Install

### What you need

- macOS or Linux. (Windows is not supported yet: the background process is
  written for macOS and Linux.)
- [uv](https://docs.astral.sh/uv/), which installs Python 3.12 and the CAD
  libraries for you:
  ```sh
  curl -LsSf https://astral.sh/uv/install.sh | sh
  ```
- About 1.5 GB of disk space for CadQuery, OpenCASCADE and VTK.
- A copy of this repository:
  ```sh
  git clone https://github.com/stepandel/cad-modeling.git
  cd cad-modeling
  ```

Node is not needed to install: the viewer is built and committed.

### For Claude Code (and any agent with a shell)

```sh
uv tool install ./server    # installs the `cadskill` and `cadskill-mcp` commands
cadskill install            # copies the skill to ~/.claude/skills/cadskill
```

If uv says its tool folder is not on your `PATH`, run `uv tool update-shell`
and open a new terminal.

Then start a new Claude Code session and ask for a part, for example "model a
60 × 40 mm mounting plate with four M4 holes". The first build on a computer
takes one to two minutes while the CAD kernel loads (see
[The first start is slow](#the-first-start-is-slow)); after that it is quick.

Options for `cadskill install`:

| Option | What it does |
|---|---|
| `--project` | Install the skill into `./.claude/skills` for the current project only |
| `--allow` | Add `Bash(cadskill:*)` to that folder's `settings.json`, so Claude does not ask before each command. Building a model runs its script as Python, so this lets Claude run Python without asking; leave it out to approve commands as they come |
| `--desktop` | Also register the MCP server with the Claude desktop app (below) |

### For Claude desktop chat

Chat sessions cannot read skills from `~/.claude` or run commands, but they
can use the desktop app's local MCP servers. After the two commands above:

```sh
cadskill install --desktop
```

This adds a `cadskill` entry to `claude_desktop_config.json` (keeping a copy
of the file as it was, next to it, ending in `.before-cadskill`). Quit and
reopen the Claude desktop app; the CadSkill tools then appear in chat.

### As a Claude plugin

The repository is also a Claude plugin that runs the MCP server. Use this
where the host shows the viewer inline (MCP Apps), or in Cowork. Use either
the plugin or the `cadskill` skill, not both: the two skills share a name and
teach different ways to call the tools.

- **Claude Code**: `claude --plugin-dir .` from this folder.
- **Cowork**: `npm run package`, then upload `dist/cadskill-plugin.zip` at
  Customize > Plugins > Add > Upload plugin. Cowork runs a plugin's local
  server only when the session runs on your computer.

The plugin needs uv but no separate install: `uv` sets up the server the
first time the plugin starts it.

### Check that it works

```sh
cadskill --version
cadskill status      # "Not running" is fine: the first command starts it
cadskill models      # lists saved models (none on a new install)
```

### What goes where

| What | Where | Why |
|---|---|---|
| The skill | `~/.claude/skills/cadskill/SKILL.md` | Tells Claude how to model with `cadskill` and check its work |
| The commands | `cadskill`, `cadskill-mcp`, in uv's tool folder | Run the scripts and serve the tools; nothing of them lives in Claude's folder |
| Your models | `~/Documents/CadSkill/` (or `$CADSKILL_HOME`) | Every version of every model, as plain files |

Nothing else goes into Claude's folder: no hook, and no MCP entry unless you
ask for `--desktop`. Showing a model as an artifact needs nothing installed
either; Claude publishes the page `cadskill export MODEL html` writes.

### Update

From your copy of the repository:

```sh
git pull
uv tool install --force --reinstall-package cadskill-mcp ./server   # plain --force reuses the old build
cadskill install            # add --desktop / --allow / --project as you used them before
cadskill stop               # the next command starts the background process on the new code
```

If you registered the desktop app, quit and reopen it as well.

### Moving over from CadDraft

This project used to be called CadDraft. If you installed it under that name,
remove the old command, skill and desktop entry first, then install as above:

```sh
caddraft stop               # the old background process, if one is running
caddraft uninstall
uv tool uninstall caddraft-mcp
```

(`caddraft uninstall` says your models are in `~/Documents/CadDraft`; they
are, until CadSkill moves them.)

Your models move by themselves: the first time CadSkill runs, it renames
`~/Documents/CadDraft` to `~/Documents/CadSkill` if the new folder does not
exist yet.

### Uninstall

```sh
cadskill uninstall          # removes the skill, and the desktop app's entry if there is one
uv tool uninstall cadskill-mcp
```

Your models stay in `~/Documents/CadSkill/`; delete that folder too if you
want them gone.

## How Claude works with a model

The model is a CadQuery script in a file. Claude writes `bracket.py`, runs
`cadskill run bracket.py`, reads the sizes it prints and opens the four-view
picture it writes to `.cadskill/bracket.png`, edits the file and runs it
again. Each successful run is saved as a version. A script that fails changes
nothing: the reply names the failing line and the previous version stays
current.

| Command | Purpose |
|---|---|
| `cadskill run SCRIPT` | Build and save a new version; write the four-view picture |
| `cadskill render MODEL` | A named view or custom direction; `--section` cut; `--highlight` what a selector matches |
| `cadskill inspect MODEL` | List a part's faces, edges or vertices with position, type, normal and size |
| `cadskill measure MODEL A B` | Shortest distance (and angle, where it applies) between two selections |
| `cadskill export MODEL FORMAT` | STEP, STL, 3MF, GLB, BREP, SVG, or HTML |
| `cadskill import MODEL FILE` | Make a STEP or BREP file available to the script |
| `cadskill show`, `versions`, `restore`, `models` | The saved script, history, undo, all models |
| `cadskill view` | Open the live viewer in the browser |
| `cadskill status`, `stop` | The background process |

**Seeing the model.** `cadskill view` opens a local page that follows the
model as Claude rebuilds it. `cadskill export MODEL html` writes the same
viewer with the model inside it as one file that needs no server: it opens
from disk, and Claude can publish it as an artifact.

**The background process.** Loading the CAD kernel is too slow to do on every
command, so the first command starts a process that keeps it loaded and
serves the viewer page; it stops after an hour without commands. It listens
on this computer only, and a command must present a token kept in a file only
you can read, so a web page open in your browser cannot use it to run a
script.

## The plugin and MCP server

The same tools are also an MCP server, packaged as a Claude plugin. Use this
where a host shows the viewer inline (MCP Apps), or for a client that speaks
MCP but has no shell. Use one or the other, not both: the two skills have the
same name and teach different ways to call the tools.

| Piece | What it is |
|---|---|
| MCP server (`cadskill-mcp`, or `cadskill mcp`) | The tools below, over stdio |
| Skill (`skills/cadskill/`) | The same guidance, written for the MCP tools |
| Viewer | Offered to the host as an MCP App |

Claude sends a full script with `run_model` or changes the current one with
`edit_model`. Each reply carries every part's size, volume and extents,
anything the script printed, and one picture with four views.

| Tool | Purpose |
|---|---|
| `run_model` | Build from a complete script and save a new version |
| `edit_model` | Exact text replacement in the current script, then rebuild |
| `get_model` | The current script, version number and parts |
| `render` | A named view or custom direction; optional section cut; highlight what a selector matches |
| `inspect` | List a part's faces, edges or vertices with position, type, normal and size |
| `measure` | Shortest distance (and angle, where it applies) between two selections |
| `export` | STEP, STL, 3MF, GLB, BREP, SVG or HTML |
| `import_file` | Make a STEP or BREP file available to the script |
| `list_versions`, `restore_version` | History and undo |
| `list_models` | Models saved on this computer |
| `open_viewer` | Address of the live viewer page |
| `get_mesh`, `get_history` | Used by the viewer only; hidden from Claude by hosts that support MCP Apps |

Models are plain files, one folder each, under `~/Documents/CadSkill/`
(set `CADSKILL_HOME` to move them): `current.py`, every version under
`versions/`, imported files under `assets/`, exported files under `exports/`.

To install the plugin, see [As a Claude plugin](#as-a-claude-plugin).

## The first start is slow

**The first start on a computer takes one to two minutes.** Measured on an
Apple-silicon Mac: 85 to 97 seconds, almost all of it macOS checking the
large native CAD libraries (OpenCASCADE and VTK) the first time each is
loaded. It is not the download and not Python compiling. The `cadskill`
command waits for it (up to 100 seconds per command, then says to run the
command again). What the plugin's server does about it:

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

## What has and has not been tried

Tested here: every `cadskill` command against the real kernel, the skill
install, the live viewer page, the single-file HTML export opened with no
server, the server over stdio and every tool. `claude plugin validate .`
passes.

Not yet tried:

- **A Claude session driving the installed skill** from a first request to a
  finished part.
- **The HTML export as a published artifact.** It publishes; whether the
  viewer draws inside the artifact frame has not been looked at.
- **Windows.** The background process is written for macOS and Linux.

The plugin, not yet tried in a real host:

- **The inline viewer.** The server offers the viewer as an MCP App
  (`ui://cadskill/viewer.html`). Whether the Claude desktop app renders it
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
npm run build               # bundles the viewer into server/cadskill_mcp/static/viewer.html
npm test                    # server tests against the real kernel (uv run --project server pytest)
npm run package             # build + dist/cadskill-plugin.zip
uv run --project server cadskill-mcp --page   # serve only the viewer page, at http://127.0.0.1:8791/
uv run --project server cadskill run part.py  # the command, straight from the source
```

After changing the server while a background process is running, `cadskill
stop` so the next command starts one with the new code.

The built `viewer.html` is committed so an installed plugin needs no Node.
Rebuild and commit it whenever `src/` changes.

## Layout

| Path | What it is |
|---|---|
| `.claude-plugin/plugin.json` | Plugin manifest; starts the server with `uv run` |
| `skills/cadskill/SKILL.md` | The plugin's skill (MCP tools) |
| `server/cadskill_mcp/skill/SKILL.md` | The skill `cadskill install` copies (`cadskill` commands) |
| `server/cadskill_mcp/cli.py` | The `cadskill` command and the skill installer |
| `server/cadskill_mcp/daemon.py` | The background process the command talks to |
| `server/cadskill_mcp/server.py` | The tools, the viewer resource and the local viewer page |
| `server/cadskill_mcp/worker.py` | Everything that touches CadQuery: running scripts, describing parts, meshing, rendering, exporting |
| `server/cadskill_mcp/runner.py` | Starts the worker process and replaces it on a timeout or crash |
| `server/cadskill_mcp/store.py` | Models and versions on disk |
| `server/tests/` | Tests through the worker process and through an MCP client |
| `src/index.html` | The viewer's markup and styles |
| `src/ui/app.js` | Viewer entry point |
| `src/ui/host.js` | Gets models from the host (MCP App), by polling the local server, or from the page itself (HTML export) |
| `src/ui/viewer.js` | Three.js view: parts, selection, picking, camera, theme |
| `src/ui/readout.js` | The top-right readout and the dock's part label |
| `scripts/build.mjs` | Bundles the viewer into one HTML file |
| `scripts/package.mjs` | Zips the plugin for upload |

## How it fits together

`server.py` holds the tools. MCP reaches them directly; the `cadskill`
command reaches the same functions through `daemon.py`, so the two cannot
drift apart. Every operation that needs geometry goes to
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
