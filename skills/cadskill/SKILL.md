---
name: cadskill
description: Design 3D parts and assemblies with the CadSkill tools (run_model, edit_model, inspect, render, measure, export). Use when the user asks to model, design, draw, modify or export a physical part, enclosure, bracket, fixture or other 3D object, asks for a STEP, STL or 3MF file, or wants to change or measure a model made earlier.
---

# Modelling with CadSkill

You build models by writing a CadQuery (Python) script. The script is the
model: every dimension and every step is in it, and each successful run is
saved as a numbered version. You do not see the model unless you look, so
check your work with the numbers and pictures the tools return.

## The loop

1. **Write the whole script** and call `run_model`. Read the reply: each
   part's size, volume and extents, and one picture with four views.
2. **Look at the picture.** Compare it with what was asked for, view by view.
   Wrong proportions, a missing hole or a feature on the wrong face are easy
   to see and easy to miss in the numbers.
3. **Change it with `edit_model`** (exact text replacement in the current
   script). Send a full script again only when most of it changes.
4. **Check before you say it is done**: sizes match the request, each part is
   one valid solid, and you have looked at the views after the last change.

A failed run changes nothing. The reply names the failing line; fix that line
with `edit_model` against the script as it was before the failed edit.

**First use on a computer is slow.** If a tool replies that the CAD kernel is
still starting, nothing is wrong: the first start takes one to two minutes,
once per computer. Tell the user it is warming up, wait about 20 seconds and
make the same call again. Do not rewrite the script or give up.

## Script rules

- `cq` (CadQuery), `math`, `show_object` and `asset` are already available.
- Units are millimetres. Z is up.
- Put every dimension in a named constant at the top, and derive the rest
  from them. A later "make it 10 mm longer" is then a one-line edit.
- Call `show_object(part, name="lid", options={"color": "steelblue"})` once
  per part. Names are how the other tools refer to parts, so make them
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

## Selecting faces and edges

Most mistakes are a selector that matches something other than what you
meant. Do not guess:

- `inspect` lists a part's faces or edges with position, type, normal and
  size. Pass a `selector` to see exactly what it matches.
- `render` with `highlight` draws the matched faces or edges in red.

Common selectors: `>Z` / `<Z` furthest along an axis; `|Z` parallel to an
axis; `#Z` perpendicular to it; `%CYLINDER`, `%PLANE`, `%CIRCLE` by type;
combine with `and`, `or`, `not`, e.g. `|Z and >X`. After a boolean or a
fillet, faces and edges are renumbered, so re-inspect instead of reusing
index numbers from an earlier version.

## Looking closer

- `render` with a named `view`, or a `direction` for an odd angle.
- `render` with `section_normal` to cut the model open. Use it for anything
  with internal features: bores, pockets, wall thickness, clearances.
- `measure` for the gap between two parts, the distance between two faces, or
  the angle between them. Use it to confirm fits and clearances instead of
  reasoning from the script.

## When a step fails

- **Fillet or chamfer fails**: the radius is too large for the smallest
  adjacent face or edge. Reduce it, apply it before the feature that created
  the small edge, or select fewer edges.
- **Selector matches nothing**: the geometry is not where you assumed.
  `inspect` the part and pick from what is there.
- **Shell fails**: thickness is larger than a local radius or feature;
  reduce it or shell before adding small features.
- **Boolean gives an invalid or empty result**: the bodies only touch on a
  face or edge. Overlap them by a small amount.
- **"Stopped after N seconds"**: an endless loop or a very heavy operation
  (large patterns of booleans). Simplify, or raise `timeout_seconds`.
- If a version went wrong in a way that is hard to repair, `list_versions`
  and `restore_version` go back to one that was right.

## Files in and out

- `export` writes STEP (exact geometry, keeps names and colours), STL or 3MF
  (meshes for printing), GLB, BREP or an SVG line drawing, and returns the
  path. Tell the user where the file is.
- To build on an existing STEP file, call `import_file` with its path, then
  load it in the script: `cq.importers.importStep(asset("name.step"))`.

## Showing the user

Use the inline MCP App when the host displays it. If it does not, call
`open_viewer` to get the live viewer URL; this does not launch a browser.
In Codex desktop, use the available `open_in_codex` tool with
`{"target":{"type":"browser","url":"THE_RETURNED_URL"},"placement":"right"}`.
If that tool is unavailable but a built-in browser tool is available, open
the URL there. Reuse the same tab as the model changes, and check that the
model loads before saying it is visible.

For a snapshot in a host that displays HTML artifacts, `export` with
`format="html"` writes a self-contained viewer. Display that file as an
artifact and update it after model changes. If neither preview surface is
available, share the rendered pictures and live viewer link. Open a system
browser only when the user asks for it.

## Working with the user

- State the key dimensions you used, and name any you had to assume.
- Use a separate `model` name for each unrelated design so their version
  histories do not mix.
- The script runs as ordinary Python on the user's computer. Only use it for
  modelling; do not read or write files outside the model, and do not use
  the network.
