# CadSkill

3D CAD for Claude and Codex. Your agent builds real solid models by writing
[CadQuery](https://cadquery.readthedocs.io) scripts, checks them with
measurements and rendered views, and exports STEP, STL and other files.

Install on macOS or Linux with one line:

```sh
curl -LsSf https://raw.githubusercontent.com/stepandel/cadskill/main/install.sh | sh
```

or, if you already have [uv](https://docs.astral.sh/uv/):

```sh
uv tool install cadskill
cadskill install
```

For Codex, add `--agent codex` to the installer or run:

```sh
cadskill install --agent codex
```

This installs the skill into `~/.agents/skills/cadskill`; add `--project`
to use `./.agents/skills/cadskill` instead. Then start a new Codex session
and ask it to model a part, or invoke `$cadskill` explicitly.

The skill opens `cadskill view MODEL --no-open` in the app's browser pane
for model previews and version history. It links to this live HTTP URL.
HTML exports are offline snapshots without revisions and are used only for
requested HTML files or offline copies. Keep the same model name across
revisions so their history stays together.

The live viewer has **Revisions** for saved designs and **Build steps** for
upstream Jupyter CadQuery Replay. Install the optional tools with
`uv tool install --force 'cadskill[replay]'`, then restart CadSkill. Use
`cadskill replay MODEL --version N --no-open` for an in-app preview URL.
The URL opens the CadSkill Build steps panel, styled like Revisions.
Assemblies start with an Assembly overview listing each part's recorded steps.
Selecting a step draws its geometry in the main canvas, with the other parts
faded for context. Assembly (Final model for one part) restores the complete
saved design. Assembly placement and constraints are not recorded operations.
No notebook viewer service is started.
Replay inspects supported Workplane/Sketch chains; direct solids and STEP
imports do not provide their original feature history. Feature changes are
made by editing the Python recipe and rebuilding. Retain Workplane/Sketch
chains through builders, cutters and final assembly parts so Replay can
inspect them; early extraction to raw Shapes disconnects their later history.

New revisions preserve imported files and record the CAD runtime versions.
Restoration uses those inputs, and reports incompatible runtime versions.
Older saves can only use their remaining inputs.

This package provides two commands: `cadskill`, which your agent runs from a
shell, and `cadskill-mcp`, an MCP server with the same tools. See the
[project page](https://github.com/stepandel/cadskill) for everything else.
