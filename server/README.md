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
HTML exports are offline snapshots without History and are used only for
requested HTML files or offline copies. Keep the same model name across
revisions so their history stays together.

This package provides two commands: `cadskill`, which your agent runs from a
shell, and `cadskill-mcp`, an MCP server with the same tools. See the
[project page](https://github.com/stepandel/cadskill) for everything else.
