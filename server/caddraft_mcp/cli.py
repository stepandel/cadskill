"""The `caddraft` command: CadDraft for any agent that can run a shell command.

Each subcommand is one tool of the MCP server (server.py), asked of a
background process that keeps the CAD kernel loaded (daemon.py). Answers are
printed as text; pictures are written to a file and the path is printed, for
the agent to open. `caddraft install` puts the skill that teaches all this
into Claude's skills folder.

This module imports nothing heavy, so a command costs little more than the
request it sends.
"""
from __future__ import annotations

import argparse
import base64
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from importlib.metadata import version as _installed
from pathlib import Path

from .store import clean, root

VERSION = _installed("caddraft-mcp")
SKILL_NAME = "cad-modeling"
SKILL_SOURCE = Path(__file__).parent / "skill"
WORK_DIR = ".caddraft"            # in the current folder: pictures and pages for the agent to open
START_WAIT = 100                  # how long one command waits for a kernel that is still starting
VIEWS = ["four", "iso", "front", "back", "left", "right", "top", "bottom"]
FORMATS = ["step", "stl", "3mf", "brep", "glb", "svg", "html"]

_local = urllib.request.build_opener(urllib.request.ProxyHandler({}))     # never send a local request to a proxy


class Failure(Exception):
    """Something to print and exit 1."""


# ---------------------------------------------------------------- the background process

def _state() -> dict | None:
    try:
        return json.loads((root() / ".daemon.json").read_text())
    except (OSError, ValueError):
        return None


def _post(state: dict, tool: str, args: dict, timeout: float) -> dict:
    request = urllib.request.Request(
        state["url"] + "call", data=json.dumps({"tool": tool, "args": args}).encode(),
        headers={"authorization": f"Bearer {state['token']}", "content-type": "application/json"})
    with _local.open(request, timeout=timeout) as response:
        return json.load(response)


def _alive(state: dict | None) -> dict | None:
    if not state:
        return None
    try:
        return _post(state, "ping", {}, 3)
    except (OSError, ValueError, KeyError):
        return None


def _daemon(start: bool = True) -> dict | None:
    """The running background process, started first if need be."""
    state = _state()
    pong = _alive(state)
    if pong and pong.get("version") == VERSION:
        return state
    if pong:                                         # left over from an older install: replace it
        _stop(state)
    if not start:
        return None
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    with open(base / ".daemon.log", "ab") as log:
        subprocess.Popen([sys.executable, "-m", "caddraft_mcp.daemon"], cwd=base, stdin=subprocess.DEVNULL,
                         stdout=log, stderr=log, start_new_session=True)
    deadline = time.monotonic() + 30
    while time.monotonic() < deadline:
        time.sleep(0.2)
        state = _state()
        if _alive(state):
            return state
    raise Failure(f"The CadDraft background process did not start. See {base / '.daemon.log'}.")


def _stop(state: dict) -> None:
    try:
        _post(state, "stop", {}, 3)
    except (OSError, ValueError):
        return
    for _ in range(50):
        if not _alive(state):
            return
        time.sleep(0.1)


def call(tool: str, args: dict, timeout: float = 60) -> dict:
    """Ask the background process to run one tool, waiting out a kernel that is still starting."""
    args = {k: v for k, v in args.items() if v is not None}
    state = _daemon()
    began, told = time.monotonic(), False
    while True:
        try:
            reply = _post(state, tool, args, timeout + 60)
        except (OSError, ValueError) as exc:
            raise Failure(f"The CadDraft background process stopped answering ({exc}). Run the command again.") from None
        if not reply.get("starting") or time.monotonic() - began > START_WAIT:
            return reply
        if not told:
            print("The CAD kernel is starting (one to two minutes the first time on a computer). Waiting...",
                  file=sys.stderr, flush=True)
            told = True
        time.sleep(3)


# ---------------------------------------------------------------- arguments

def _model(value: str) -> str:
    """A model is named directly or by its script: `bracket` and `parts/bracket.py` are the same model."""
    return clean(Path(value).stem if value.endswith(".py") else value)


def _vector(value: str) -> list[float]:
    try:
        numbers = [float(v) for v in value.split(",")]
    except ValueError:
        numbers = []
    if len(numbers) != 3:
        raise argparse.ArgumentTypeError(f"expected three numbers like 0,-1,0, not '{value}'")
    return numbers


def _names(value: str) -> list[str]:
    return [v.strip() for v in value.split(",") if v.strip()]


def _selection(value: str) -> dict:
    """PART, KIND, PART/KIND, any of them with :SELECTOR or @ROWS. E.g. `lid/faces:>Z`, `edges@3,4`, `post`."""
    if value.lstrip().startswith("{"):
        try:
            return json.loads(value)
        except ValueError:
            raise argparse.ArgumentTypeError(f"not valid JSON: {value}") from None
    out: dict = {}
    head, _, selector = value.partition(":")
    if selector:
        out["selector"] = selector
    head, _, rows = head.partition("@")
    if rows:
        try:
            out["index"] = [int(v) for v in rows.split(",")]
        except ValueError:
            raise argparse.ArgumentTypeError(f"rows after @ must be numbers like @3,4, not '{rows}'") from None
    part, _, kind = head.rpartition("/")
    if not part and kind not in ("faces", "edges", "vertices"):
        part, kind = kind, ""
    if kind and kind not in ("faces", "edges", "vertices"):
        raise argparse.ArgumentTypeError(f"'{kind}' is not faces, edges or vertices")
    if part:
        out["part"] = part
    if kind:
        out["kind"] = kind
    if ("selector" in out or "index" in out) and "kind" not in out:
        raise argparse.ArgumentTypeError(f"say what to select in '{value}': faces, edges or vertices before the : or @")
    return out


def _parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="caddraft", description="Build, check and export CAD models from CadQuery scripts.")
    p.add_argument("--version", action="version", version=f"caddraft {VERSION}")
    sub = p.add_subparsers(dest="command", required=True, metavar="command")
    selection = "PART, KIND or PART/KIND, then :SELECTOR or @ROWS. E.g. 'lid/faces:>Z', 'edges@3,4', 'post'."

    def add(name: str, summary: str, model: bool = True) -> argparse.ArgumentParser:
        s = sub.add_parser(name, help=summary, description=summary)
        if model:
            s.add_argument("model", help="Model name, or its script (bracket.py is the model 'bracket').")
        return s

    s = add("run", "Build a model from a script and save it as a new version.", model=False)
    s.add_argument("script", help="The CadQuery script. Its file name is the model's name.")
    s.add_argument("--model", help="Model name, if not the script's file name.")
    s.add_argument("--note", help="A few words on what this version changes.")
    s.add_argument("--timeout", type=int, default=60, metavar="SECONDS")
    s.add_argument("--png", help=f"Where to write the picture. Default: {WORK_DIR}/MODEL.png")

    s = add("render", "Draw the current version. Views have no perspective.")
    s.add_argument("--view", choices=VIEWS, default="four", help="'four' is iso + top + front + right in one picture.")
    s.add_argument("--direction", type=_vector, metavar="X,Y,Z", help="Camera position relative to the model, instead of a view. Write --direction=-1,1,1 when it starts with a minus.")
    s.add_argument("--parts", type=_names, metavar="A,B", help="Only draw these parts.")
    s.add_argument("--section", type=_vector, metavar="X,Y,Z",
                   help="Cut with a plane and remove the side this normal points to. 0,-1,0 removes the front half.")
    s.add_argument("--section-at", type=_vector, metavar="X,Y,Z", help="A point on the section plane. Default: the origin.")
    s.add_argument("--highlight", type=_selection, metavar="SELECTION", help="Draw these in red, the rest faded. " + selection)
    s.add_argument("--width", type=int, default=1000)
    s.add_argument("--height", type=int, default=760)
    s.add_argument("--png", help=f"Where to write the picture. Default: {WORK_DIR}/MODEL-render.png")

    s = add("inspect", "List a part's faces, edges or vertices with position, type, size and direction.")
    s.add_argument("kind", nargs="?", choices=["faces", "edges", "vertices"], default="faces")
    s.add_argument("--part", help="Part name. May be omitted when the model has one part.")
    s.add_argument("--selector", help="CadQuery selector to filter by, e.g. '>Z' or '%%CIRCLE'.")

    s = add("measure", "Shortest distance between two selections, and the angle when both are flat or straight.")
    s.add_argument("a", type=_selection, metavar="A", help=selection)
    s.add_argument("b", type=_selection, metavar="B")

    s = add("export", "Write the current version to a file.")
    s.add_argument("format", choices=FORMATS, help="html is the 3D viewer with the model inside: one file, no server.")
    s.add_argument("--parts", type=_names, metavar="A,B", help="Only export these parts.")
    s.add_argument("--out", help=f"Where to write it. Default: the model's exports folder ({WORK_DIR}/MODEL.html for html).")

    s = add("import", "Copy a STEP, BREP or other file into a model, for its script to load with asset(\"name\").")
    s.add_argument("file")

    add("show", "Print the current script, its version number and its parts.")
    add("versions", "List a model's saved versions, oldest first.")
    s = add("restore", "Go back to an earlier version: it is rebuilt and saved as the newest.")
    s.add_argument("version", type=int)
    s.add_argument("--to", metavar="SCRIPT", help="Also write the restored script to this file.")
    s.add_argument("--png", help=f"Where to write the picture. Default: {WORK_DIR}/MODEL.png")
    add("models", "List the models saved on this computer.", model=False)

    s = add("view", "Open the live 3D viewer in the browser. It follows the model as it changes.", model=False)
    s.add_argument("--no-open", action="store_true", help="Only print the address.")

    s = add("install", "Install the CadDraft skill for Claude.", model=False)
    s.add_argument("--project", action="store_true", help="Into this project (.claude/skills) instead of your home folder.")
    s.add_argument("--allow", action="store_true",
                   help="Also let Claude run caddraft commands without asking each time (edits Claude's settings.json).")
    s = add("uninstall", "Remove the CadDraft skill.", model=False)
    s.add_argument("--project", action="store_true")
    add("status", "Say whether the background process is running.", model=False)
    add("stop", "Stop the background process.", model=False)
    add("mcp", "Run the MCP server on stdio instead (for hosts that use MCP).", model=False)
    return p


# ---------------------------------------------------------------- output

def _work_file(name: str) -> Path:
    """A file in ./.caddraft, which is kept out of git."""
    folder = Path(WORK_DIR)
    if not folder.exists():
        folder.mkdir()
        (folder / ".gitignore").write_text("*\n")
    return folder / name


def _finish(reply: dict, png: Path | None = None) -> int:
    """Print an answer; write its picture, if any, to `png`."""
    print(reply["text"], file=sys.stderr if reply["error"] else sys.stdout)
    if reply.get("images") and png is not None:
        png.parent.mkdir(parents=True, exist_ok=True)
        png.write_bytes(base64.b64decode(reply["images"][0]))
        print(f"Picture: {png}")
    return 1 if reply["error"] else 0


# ---------------------------------------------------------------- installing the skill

def _claude_home(project: bool) -> Path:
    if project:
        return Path.cwd() / ".claude"
    return Path(os.environ.get("CLAUDE_CONFIG_DIR") or Path.home() / ".claude").expanduser()


ALLOW_RULE = "Bash(caddraft:*)"


def _install(project: bool, allow: bool) -> int:
    home = _claude_home(project)
    target = home / "skills" / SKILL_NAME
    if target.exists():
        shutil.rmtree(target)
    shutil.copytree(SKILL_SOURCE, target)
    print(f"Installed the skill: {target}")

    if allow:
        settings = home / "settings.json"
        try:
            data = json.loads(settings.read_text()) if settings.exists() else {}
        except ValueError:
            raise Failure(f"{settings} is not valid JSON, so it was left alone. Add \"{ALLOW_RULE}\" to "
                          "permissions.allow yourself.") from None
        rules = data.setdefault("permissions", {}).setdefault("allow", [])
        if ALLOW_RULE not in rules:
            rules.append(ALLOW_RULE)
            settings.write_text(json.dumps(data, indent=2) + "\n")
        print(f"Claude may now run caddraft commands without asking: {settings}")
    else:
        print("Claude will ask before each caddraft command until you allow it. `caddraft install --allow` allows "
              "them all up front; note that building a model runs its script as Python.")

    found = shutil.which("caddraft")
    if not found:
        print("\nWarning: `caddraft` is not on your PATH, so Claude will not find it.\n"
              "Install it for good with `uv tool install <path to this repo>/server`, then run `uv tool update-shell` "
              "if uv says its tool folder is not on your PATH.")
    print("\nStart a new Claude session and ask for a part, e.g. \"model a 60 x 40 mm mounting plate with four M4 holes\".")
    print("The first build on this computer takes a minute or two while the CAD kernel loads.")
    return 0


def _uninstall(project: bool) -> int:
    target = _claude_home(project) / "skills" / SKILL_NAME
    if target.exists():
        shutil.rmtree(target)
        print(f"Removed {target}")
    else:
        print(f"Nothing to remove at {target}")
    print(f"Your models are untouched in {root()}. To remove the command too: `uv tool uninstall caddraft-mcp`.")
    return 0


# ---------------------------------------------------------------- commands

def _run_command(a: argparse.Namespace) -> int:
    c = a.command
    if c == "install":
        return _install(a.project, a.allow)
    if c == "uninstall":
        return _uninstall(a.project)
    if c == "mcp":
        from .server import main as serve
        serve()
        return 0
    if c == "status":
        state = _daemon(start=False)
        if not state:
            print("Not running. It starts with the first command.")
            return 0
        pong = _post(state, "ping", {}, 3)
        print(f"Running at {state['url']} (process {state['pid']}); the CAD kernel is "
              f"{'ready' if pong['ready'] else 'still starting'}. Models are in {root()}.")
        return 0
    if c == "stop":
        state = _state()
        if _alive(state):
            _stop(state)
            print("Stopped.")
        else:
            print("Not running.")
        return 0
    if c == "view":
        url = _daemon()["url"]
        if not a.no_open:
            webbrowser.open(url)
        print(f"The live viewer is at {url} (this computer only). It updates after every build.")
        return 0
    if c == "models":
        return _finish(call("list_models", {}))

    if c == "run":
        script = Path(a.script)
        if not script.is_file():
            raise Failure(f"There is no script at {script}.")
        model = clean(a.model) if a.model else _model(a.script)
        reply = call("run_model", {"code": script.read_text(), "model": model, "note": a.note,
                                   "timeout_seconds": a.timeout}, a.timeout)
        return _finish(reply, Path(a.png) if a.png else _work_file(f"{model}.png"))

    model = _model(a.model)
    if c == "render":
        args = {"model": model, "view": a.view, "direction": a.direction, "parts": a.parts, "section_normal": a.section,
                "section_origin": a.section_at, "highlight": a.highlight, "width": a.width, "height": a.height}
        return _finish(call("render", args), Path(a.png) if a.png else _work_file(f"{model}-render.png"))
    if c == "inspect":
        return _finish(call("inspect", {"model": model, "part": a.part, "kind": a.kind, "selector": a.selector}))
    if c == "measure":
        return _finish(call("measure", {"model": model, "a": a.a, "b": a.b}))
    if c == "export":
        out = a.out or (str(_work_file(f"{model}.html")) if a.format == "html" else None)
        args = {"model": model, "format": a.format, "parts": a.parts, "path": str(Path(out).resolve()) if out else None}
        return _finish(call("export", args, 180))
    if c == "import":
        return _finish(call("import_file", {"model": model, "path": str(Path(a.file).expanduser().resolve())}))
    if c == "show":
        return _finish(call("get_model", {"model": model}))
    if c == "versions":
        return _finish(call("list_versions", {"model": model}))
    if c == "restore":
        reply = call("restore_version", {"model": model, "version": a.version})
        code = _finish(reply, Path(a.png) if a.png else _work_file(f"{model}.png"))
        if code == 0 and a.to:
            Path(a.to).write_text((root() / model / "current.py").read_text())
            print(f"Script written to {a.to}")
        return code
    raise Failure(f"Unknown command {c}.")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        return _run_command(args)
    except Failure as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
