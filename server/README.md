# CadSkill

3D CAD for Claude. Claude builds real solid models by writing
[CadQuery](https://cadquery.readthedocs.io) scripts, checks them with
measurements and rendered views, and exports STEP, STL and other files.

Install on macOS or Linux with one line:

```sh
curl -LsSf https://raw.githubusercontent.com/stepandel/cad-modeling/main/install.sh | sh
```

or, if you already have [uv](https://docs.astral.sh/uv/):

```sh
uv tool install cadskill
cadskill install
```

This package provides two commands: `cadskill`, which Claude runs from a
shell, and `cadskill-mcp`, an MCP server with the same tools. See the
[project page](https://github.com/stepandel/cad-modeling) for everything else.
