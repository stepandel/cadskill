---
name: cadskill
description: Design 3D parts and assemblies with CadQuery and the `cadskill` command. Use to build, change, measure, export or view physical parts and assemblies, produce STEP/STL/3MF files, show an existing model in 3D, or browse its version history.
---

# Modelling with CadSkill

You build models by writing a CadQuery (Python) script to a file and running
it with `cadskill`. The script is the model: every dimension and every step is
in it. You do not see the model unless you look, so check your work with the
numbers `cadskill` prints and the pictures it writes.

This skill works in Claude Code and Codex. If `cadskill` is not found, use
the install instructions for the current agent (macOS or Linux):

- Claude Code: `curl -LsSf https://raw.githubusercontent.com/stepandel/cadskill/main/install.sh | sh`
- Codex: `curl -LsSf https://raw.githubusercontent.com/stepandel/cadskill/main/install.sh | sh -s -- --agent codex`

Tell the user which command to run and to open a new terminal afterward,
then stop.

## The loop

1. **Write the whole script** to a file in the user's project, e.g.
   `bracket.py`. The file name is the model's name.
2. **Build it**: `cadskill run bracket.py`. It prints each part's size, volume
   and extents, and writes one picture with four views (iso, top, front,
   right) to `.cadskill/bracket.png`.
3. **Open the picture** with an image-viewing tool (such as Codex's
   `view_image`) and compare it with what
   was asked for, view by view. Wrong proportions, a missing hole or a feature
   on the wrong face are easy to see and easy to miss in the numbers.
4. **Change the script** with your normal file editing, then run it again.
5. **Check before you say it is done**: sizes match the request, each part is
   one valid solid, and you have looked at the views after the last change.

Every successful run is saved as a numbered version. A failed run changes
nothing: it names the failing line, and `inspect`, `render`, `measure` and
`export` keep answering about the last version that built.

Keep the same script and model name for revisions of the same design. Use
`--note` to describe each change, rather than creating `_v2` / `_v3` model
names that split the history. If the script is renamed, pass `--model` with
the original model name to keep its history together.

**First use on a computer is slow.** The first command starts the CAD kernel,
which takes one to two minutes once per computer and a few seconds after
that. `cadskill` waits for it. If it still answers that the kernel is
starting, nothing is wrong: tell the user it is warming up and run the same
command again. Do not rewrite the script or give up.

## Showing the user

The default interactive preview is the **live viewer with Revisions**. For
"show it", "how can I look at it?", "open the model" or "show history", use
this procedure even if an earlier message links an exported HTML file:

1. Run `cadskill view MODEL --no-open`. It returns an HTTP URL for that
   model, including its history; later builds of other models do not switch
   this view. Use the returned URL, not a guessed port or local file path.
2. In Codex desktop, use the available `open_in_codex` tool with
   `{"target":{"type":"browser","url":"THE_RETURNED_URL"},"placement":"right"}`.
   If unavailable, use an available built-in browser tool. Reuse the same
   tab for later revisions. Verify the requested model and the Revisions
   control are visible before saying it is open.
3. In the reply, link **View in 3D** to that live HTTP URL. Share the latest
   four-view PNG inline after meaningful changes using an absolute path:
   `![Model views](/absolute/path/.cadskill/bracket.png)`.

If no in-app browser is available, provide the live URL and PNG. Use bare
`cadskill view MODEL` or macOS `open` only when the user explicitly asks for
the system browser.

**HTML exports are offline snapshots without History.** Do not export,
open or link a local `.html` file as the default model preview. Export HTML
only when the user requests an HTML file, offline copy or snapshot; label
that link **HTML snapshot (no history)**. A host's native artifact surface
can display such a requested snapshot. STEP/STL/3MF download links are
separate from the live preview.

## Script rules

- `cq` (CadQuery), `math`, `show_object` and `asset` are already available.
  Do not import cadquery or call exporters yourself.
- Units are millimetres. Z is up.
- Put every dimension in a named constant at the top, and derive the rest
  from them. A later "make it 10 mm longer" is then a one-line edit.
- Call `show_object(part, name="lid", options={"color": "steelblue"})` once
  per part. Names are how the commands refer to parts, so make them
  meaningful and keep them stable between versions.
- One solid per physical part. Parts that are separate pieces in reality stay
  separate objects; do not union them.
- Assemblies: build a `cq.Assembly`, add parts with `name=`, `loc=` and
  `color=`, and show the assembly. Each child becomes a named part.

```python
LENGTH, WIDTH, THICKNESS = 60, 40, 5
HOLE_D, HOLE_INSET = 4.5, 6
CORNER_R = 4

plate = (
    cq.Workplane("XY")
    .box(LENGTH, WIDTH, THICKNESS)
    .edges("|Z").fillet(CORNER_R)
    .faces(">Z").workplane()
    .rect(LENGTH - 2 * HOLE_INSET, WIDTH - 2 * HOLE_INSET, forConstruction=True)
    .vertices().hole(HOLE_D)
)
show_object(plate, name="plate")
```

## Commands

`MODEL` is the model's name or its script: `bracket` and `bracket.py` mean
the same. Quote anything with `>`, `<`, `|`, `%` or `#` in it. `cadskill
COMMAND --help` lists every option.

| Command | What it does |
|---|---|
| `cadskill run SCRIPT [--model NAME] [--note "why"] [--timeout 120]` | Build and save a version; keep NAME stable across revisions |
| `cadskill render MODEL [--view top] [--direction 1,1,1]` | Another picture, to `.cadskill/MODEL-render.png` |
| `cadskill render MODEL --section 0,-1,0` | Cut the model open (removes the side the normal points to) |
| `cadskill render MODEL --highlight 'plate/faces:>Z'` | Draw what a selector matches in red |
| `cadskill inspect MODEL [faces\|edges\|vertices] [--part P] [--selector '%CYLINDER']` | List geometry with position, type, size, normal |
| `cadskill measure MODEL A B` | Shortest distance between two selections, and the angle if both are flat or straight |
| `cadskill export MODEL step\|stl\|3mf\|glb\|brep\|svg\|html [--out FILE]` | Write a file and print its path |
| `cadskill import MODEL FILE` | Copy a STEP or BREP file in, for the script to load with `asset("name.step")` |
| `cadskill show MODEL`, `versions MODEL`, `models` | The saved script, its history, all models |
| `cadskill restore MODEL N --to SCRIPT` | Go back to version N and write that script back to the file |
| `cadskill view MODEL --no-open` | Get a live model URL with History for the host's browser pane |
| `cadskill replay MODEL [--version N] --no-open` | Get the upstream Replay build-step view for a saved revision; requires `cadskill[replay]` |

## Revisions and build steps

**Revisions** are complete saved designs. Restore one with `cadskill restore
MODEL N --to SCRIPT`; it is rebuilt and saved as a new revision. New saves
preserve imported assets and record Python/CadQuery/kernel versions. A runtime
mismatch must be resolved before restoring; old saves without snapshots can
only use their remaining imported files.

**Build steps** inspect a single revision using upstream Jupyter CadQuery
Replay. Use `cadskill replay MODEL --version N --no-open` and open its returned
URL in the same in-app browser surface described above. The viewer's Build
steps button opens a panel like Revisions. Selected operations use the same
model canvas; Final model returns to the complete design. The returned command URL also
opens that page with Build steps selected. If the optional
components are missing, the command provides their installation instructions.
Replay supports recorded Workplane/Sketch chains; direct solids and imported
STEP parts do not carry their original feature history. Do not promise a
complete feature tree or rewrite a working model solely to suit Replay.

For "remove the holes but keep the longer pins", edit the current Python
recipe and rebuild. Use named intermediate variables, and ordinary Boolean
parameters for features that need repeated on/off changes. Preserve unrelated
dimensions, then verify the solid and relevant measurements. Restore an older
revision only when the user wants that whole earlier design. Replay is an
inspector, not an operation-suppression or undo engine.

A **selection** (for `--highlight` and `measure`) is `PART`, `KIND` or
`PART/KIND`, optionally followed by `:SELECTOR` or `@ROWS` (row numbers from
`inspect`): `post` is a whole part, `plate/faces:>Z` its top face,
`edges@3,4` two edges of the only part.

## Selecting faces and edges

Most mistakes are a selector that matches something other than what you
meant. Do not guess:

- `cadskill inspect MODEL faces` lists a part's faces with position, type,
  normal and size. Add `--selector` to see exactly what it matches.
- `cadskill render MODEL --highlight ...` draws the match in red.

Common selectors: `>Z` / `<Z` furthest along an axis; `|Z` parallel to an
axis; `#Z` perpendicular to it; `%CYLINDER`, `%PLANE`, `%CIRCLE` by type;
combine with `and`, `or`, `not`, e.g. `|Z and >X`. After a boolean or a
fillet, faces and edges are renumbered, so inspect again instead of reusing
row numbers from an earlier version.

## Looking closer

- `render --view` for a named view, `--direction` for an odd angle.
- `render --section` for anything with internal features: bores, pockets,
  wall thickness, clearances.
- `measure` for the gap between two parts, the distance between two faces, or
  the angle between them. Use it to confirm fits and clearances instead of
  reasoning from the script.

## When a step fails

- **Fillet or chamfer fails**: the radius is too large for the smallest
  adjacent face or edge. Reduce it, apply it before the feature that created
  the small edge, or select fewer edges.
- **Selector matches nothing**: the geometry is not where you assumed.
  Inspect the part and pick from what is there.
- **Shell fails**: thickness is larger than a local radius or feature;
  reduce it or shell before adding small features.
- **Boolean gives an invalid or empty result**: the bodies only touch on a
  face or edge. Overlap them by a small amount.
- **"Stopped after N seconds"**: an endless loop or a very heavy operation
  (large patterns of booleans). Simplify, or raise `--timeout`.
- If the script went wrong in a way that is hard to repair, `cadskill
  versions MODEL` and `cadskill restore MODEL N --to SCRIPT` go back to one
  that was right.

## Working with the user

- State the key dimensions you used, and name any you had to assume.
- When you export, tell the user where the file is.
- Use a separate script (and so a separate model name) for each unrelated
  design, so their version histories do not mix.
- `.cadskill/` holds pictures and exported pages for this project and is kept
  out of git. Saved versions live in the user's `Documents/CadSkill` folder.
- The script runs as ordinary Python on the user's computer. Only use it for
  modelling; do not read or write files outside the model, and do not use
  the network.
