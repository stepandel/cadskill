"""CadSkill MCP server: the tools Claude uses to build and check a CAD model.

The model is a CadQuery script. Claude sends or edits the script; the server
runs it in a worker process, keeps every successful run as a version, and
answers with numbers and pictures so Claude can check its own work. A viewer
page shows the same model to the person, inline where the host supports MCP
Apps and on a local address otherwise.
"""
from __future__ import annotations

import base64
import json
import threading
from functools import partial
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Annotated, Literal
from urllib.parse import parse_qs, urlencode, urlparse

import anyio
from mcp.server.fastmcp import FastMCP
from mcp.types import CallToolResult, ImageContent, TextContent
from pydantic import BaseModel, Field

from .runner import DEFAULT_TIMEOUT, Problem, Runner, Starting
from .store import Store, clean
from .replay import ReplayServer

VIEWER_URI = "ui://cadskill/viewer.html"
VIEWER_FILE = Path(__file__).parent / "static" / "viewer.html"
VIEWER_PORT = 8791
SHOWS_VIEWER = {"ui": {"resourceUri": VIEWER_URI}}
APP_ONLY = {"ui": {"visibility": ["app"]}}
MODULE_TAG = '<script type="module">'         # where the built viewer's code starts

INSTRUCTIONS = """\
CadSkill builds 3D CAD models from CadQuery (Python) scripts. The script is the model.

Loop: run_model with a full script -> read the numbers and look at the four views -> fix with
edit_model (exact text replacement) -> repeat. Use inspect to list faces or edges before writing a
selector, render for a closer or sectioned view, measure to check a distance, export for files.

Script rules: `cq` is already imported; units are millimetres; call
show_object(part, name="...", options={"color": "steelblue"}) once per part; put dimensions in
named constants at the top. A failed run changes nothing: the previous version stays current.

If a tool answers that the CAD kernel is still starting, that is normal on first use (one to two
minutes, once per computer). Tell the user it is warming up, wait about 20 seconds, and repeat the call.

For requests to show, view or inspect a model or its history, show the inline MCP App when
available. Otherwise call open_viewer with the model name and open its URL in the host's
in-app browser. Include that live URL in the reply and reuse it as the model changes.
HTML exports are offline snapshots without history: export or open them only when the user
asks for an HTML file, offline copy or snapshot. A previous HTML link is not the live viewer.
Open an external system browser only when the user asks for it. Keep the same model name
for revisions so their version history stays together.

The viewer labels saved versions Revisions. For build-step inspection call open_build_steps
and open its URL in the host browser panel (optional cadskill[replay]). This uses upstream
Jupyter CadQuery Replay for Workplane/Sketch chains. Direct solids and STEP imports have no
original feature tree. For selective changes edit the current Python source and rebuild;
restore_version replaces the whole design with a saved revision, recorded as a new version.
"""

mcp = FastMCP("cadskill", instructions=INSTRUCTIONS)
store = Store()
runner = Runner(start_wait=25)   # a call made while the kernel is still starting answers within 25 s
_shown = {"model": None, "version": 0}       # what the viewer should be displaying
_mesh_cache: dict[tuple[str, int], dict] = {}
replay_server = ReplayServer()


# ---------------------------------------------------------------- helpers

class Selection(BaseModel):
    """Part of a model: a whole part, or some of its faces, edges or vertices."""

    part: str | None = Field(None, description="Part name. May be omitted when the model has one part.")
    kind: Literal["faces", "edges", "vertices"] | None = Field(None, description="Omit to mean the whole part.")
    selector: str | None = Field(None, description="CadQuery selector string, e.g. '>Z', '|Z', '%CYLINDER'.")
    index: list[int] | None = Field(None, description="Row numbers from inspect, instead of or as well as a selector.")


Model = Annotated[str, Field(description="Model name. Each name is a separate model with its own versions.")]


async def _work(op: str, timeout: float = DEFAULT_TIMEOUT, **kwargs):
    return await anyio.to_thread.run_sync(partial(runner.call, op, timeout, **kwargs))


def _text(text: str, error: bool = False, **extra) -> CallToolResult:
    return CallToolResult(content=[TextContent(type="text", text=text)], isError=error, **extra)


def _png(data: bytes) -> ImageContent:
    return ImageContent(type="image", data=base64.b64encode(data).decode(), mimeType="image/png")


def _fmt(v: float) -> str:
    return f"{v:.3f}".rstrip("0").rstrip(".")


def _describe(parts: list[dict]) -> str:
    lines = []
    for p in parts:
        bits = [" × ".join(_fmt(v) for v in p["size"]) + " mm"]
        if "volume" in p:
            bits.append(f"volume {_fmt(p['volume'])} mm³")
            bits.append(f"area {_fmt(p['area'])} mm²")
        bits.append(f"{p['solids']} solid{'s' if p['solids'] != 1 else ''}, {p['faces']} faces, {p['edges']} edges")
        bits.append("x {}..{}, y {}..{}, z {}..{}".format(*(_fmt(v) for pair in zip(p["min"], p["max"]) for v in pair)))
        if not p["valid"]:
            bits.append("NOT A VALID SOLID")
        lines.append(f"- {p['name']}: " + "; ".join(bits))
    return "\n".join(lines)


def _require(model: str) -> str:
    code = store.current(model)
    if code is None:
        raise Problem(f"There is no model named '{clean(model)}' yet. Build it first.")
    return code


def _context(model: str, version: int | None = None) -> str:
    version = store.version(model) if version is None else version
    try:
        store.check_environment(model, version)
    except ValueError as exc:
        raise Problem(str(exc)) from exc
    return str(store.context(model, version))


async def _run(model: str, code: str, note: str | None, timeout: float, what: str,
               source_dir: str | None = None) -> CallToolResult:
    """Run a script and, if it works, make it the current version."""
    with store.build(model, Path(source_dir) if source_dir else None) as directory:
        return await _run_in(model, code, note, timeout, what, str(directory))


async def _run_in(model: str, code: str, note: str | None, timeout: float, what: str,
                  directory: str) -> CallToolResult:
    model = clean(model)
    was = store.version(model)
    try:
        out = await _work("run", timeout, code=code, model_dir=directory)
    except Starting as exc:
        return _text(str(exc), error=True)
    except Problem as exc:
        return _text(f"{exc}\nThe model is unchanged" + (f" (still version {was})." if was else "."), error=True)
    printed = f"\nPrinted by the script:\n{out['stdout'].rstrip()}" if out["stdout"].strip() else ""
    if "error" in out:
        e = out["error"]
        where = f"line {e['line']}: {e['source']}\n" if e["line"] else ""
        state = f"The model is unchanged (still version {was})." if was else "Nothing was saved."
        return _text(f"The script failed. {state}\n{where}{e['type']}: {e['message']}{printed}", error=True)
    parts = out["parts"]
    summary = ", ".join(f"{p['name']} {'×'.join(_fmt(v) for v in p['size'])}" for p in parts)
    n = store.save(model, code, summary, note, source_dir=Path(directory))
    _shown.update(model=model, version=n)
    content = [TextContent(type="text", text=f"{what} Model '{model}' is now version {n}, {len(parts)} part"
                                             f"{'s' if len(parts) != 1 else ''}:\n{_describe(parts)}{printed}")]
    try:
        shot = await _work("render", code=code, model_dir=_context(model, n), spec={})
        content.append(_png(shot["png"]))
    except Problem as exc:
        content.append(TextContent(type="text", text=f"(No picture: {exc})"))
    return CallToolResult(content=content, structuredContent={"model": model, "version": n})


# ---------------------------------------------------------------- building

@mcp.tool(meta=SHOWS_VIEWER)
async def run_model(
    code: Annotated[str, Field(description="The complete CadQuery script.")],
    model: Model = "default",
    note: Annotated[str | None, Field(description="A few words on what this version changes.")] = None,
    timeout_seconds: Annotated[int, Field(ge=1, le=600)] = DEFAULT_TIMEOUT,
) -> CallToolResult:
    """Build the model from a complete CadQuery script and save it as a new version.

    Returns each part's size, volume and extents, anything the script printed, and one picture with
    four views (iso, top, front, right). If the script fails you get the failing line and the model
    stays as it was. For a small change to an existing model, edit_model is cheaper.
    """
    return await _run(model, code, note, timeout_seconds, "Built.")


@mcp.tool(meta=SHOWS_VIEWER)
async def edit_model(
    old: Annotated[str, Field(description="Exact text in the current script. Must match once unless replace_all is set.")],
    new: Annotated[str, Field(description="Text to put in its place.")],
    model: Model = "default",
    replace_all: bool = False,
    note: Annotated[str | None, Field(description="A few words on what this version changes.")] = None,
    timeout_seconds: Annotated[int, Field(ge=1, le=600)] = DEFAULT_TIMEOUT,
) -> CallToolResult:
    """Change the current script by exact text replacement, then rebuild and save a new version.

    Same result as run_model. If the edited script fails, the edit is discarded.
    """
    try:
        code = _require(model)
    except Problem as exc:
        return _text(str(exc), error=True)
    count = code.count(old)
    if count == 0:
        return _text("That text is not in the current script. Read it with get_model and copy the text exactly.", error=True)
    if count > 1 and not replace_all:
        return _text(f"That text appears {count} times. Include more surrounding text, or set replace_all.", error=True)
    return await _run(model, code.replace(old, new), note, timeout_seconds, "Edited.")


@mcp.tool()
async def get_model(model: Model = "default") -> CallToolResult:
    """Return the model's current script, its version number and its parts."""
    try:
        code = _require(model)
        out = await _work("run", code=code, model_dir=_context(model))
    except Problem as exc:
        return _text(str(exc), error=True)
    parts = _describe(out["parts"]) if "parts" in out else f"(the script currently fails: {out['error']['message']})"
    return _text(f"Model '{clean(model)}', version {store.version(model)}:\n{parts}\n\n```python\n{code.rstrip()}\n```")


@mcp.tool()
def list_models() -> str:
    """List the models saved on this computer."""
    models = store.models()
    if not models:
        return f"No models yet. They are saved under {store.base}."
    return f"Models in {store.base}:\n" + "\n".join(
        f"- {m['model']}: {m['versions']} version{'s' if m['versions'] != 1 else ''}, last {m['last']['time']} ({m['last']['summary']})"
        for m in models)


@mcp.tool()
def list_versions(model: Model = "default") -> str:
    """List a model's saved versions, oldest first. Every successful run is one version."""
    versions = store.versions(model)
    if not versions:
        return f"There is no model named '{clean(model)}' yet."
    return "\n".join(f"{v['version']}. {v['time']}  {v['summary']}" + (f"  — {v['note']}" if v.get("note") else "") for v in versions)


@mcp.tool(meta=SHOWS_VIEWER)
async def restore_version(version: int, model: Model = "default") -> CallToolResult:
    """Go back to an earlier version. This is undo: the old script is rebuilt and saved as the newest version."""
    try:
        code = store.code(model, version)
        directory = _context(model, version)
    except KeyError:
        return _text(f"Model '{clean(model)}' has no version {version}. See list_versions.", error=True)
    except Problem as exc:
        return _text(str(exc), error=True)
    return await _run(model, code, f"restored version {version}", DEFAULT_TIMEOUT, f"Restored version {version}.", directory)


# ---------------------------------------------------------------- checking

@mcp.tool()
async def render(
    model: Model = "default",
    view: Annotated[Literal["four", "iso", "front", "back", "left", "right", "top", "bottom"],
                    Field(description="'four' is iso + top + front + right in one picture.")] = "four",
    direction: Annotated[list[float] | None, Field(description="Camera position relative to the model, e.g. [1, 1, 1], "
                         "instead of a named view.", min_length=3, max_length=3)] = None,
    parts: Annotated[list[str] | None, Field(description="Only draw these parts.")] = None,
    section_normal: Annotated[list[float] | None, Field(description="Cut the model with a plane and remove the side this "
                              "normal points to, to see inside. E.g. [0, -1, 0] removes the front half.",
                              min_length=3, max_length=3)] = None,
    section_origin: Annotated[list[float] | None, Field(description="A point on the section plane. Default: the origin.",
                              min_length=3, max_length=3)] = None,
    highlight: Annotated[Selection | None, Field(description="Draw these faces or edges in red and the rest faded. "
                         "Use it to check what a selector matches.")] = None,
    width: Annotated[int, Field(ge=200, le=2000)] = 1000,
    height: Annotated[int, Field(ge=200, le=2000)] = 760,
) -> CallToolResult:
    """Draw the current model. Views have no perspective, so lengths can be compared by eye."""
    spec: dict = {"view": "iso" if direction and view == "four" else view, "direction": direction, "parts": parts,
                  "width": width, "height": height}
    if section_normal:
        spec["section"] = {"normal": section_normal, "origin": section_origin or [0, 0, 0]}
    if highlight:
        spec["highlight"] = highlight.model_dump(exclude_none=True)
    try:
        shot = await _work("render", code=_require(model), model_dir=_context(model), spec=spec)
    except Problem as exc:
        return _text(str(exc), error=True)
    return CallToolResult(content=[TextContent(type="text", text="Views: " + ", ".join(shot["views"])), _png(shot["png"])])


@mcp.tool()
async def inspect(
    model: Model = "default",
    part: Annotated[str | None, Field(description="Part name. May be omitted when the model has one part.")] = None,
    kind: Literal["faces", "edges", "vertices"] = "faces",
    selector: Annotated[str | None, Field(description="CadQuery selector to filter by, e.g. '>Z' or '%CIRCLE'. "
                        "Omit to list everything.")] = None,
) -> CallToolResult:
    """List a part's faces, edges or vertices with their position, type, size and direction.

    Use it before writing a selector, and to check what a selector really matches. The index column
    can be passed to render (highlight) and measure.
    """
    sel = {"part": part, "kind": kind, "selector": selector}
    try:
        out = await _work("inspect", code=_require(model), model_dir=_context(model), sel=sel)
    except Problem as exc:
        return _text(str(exc), error=True)
    head = f"{out['part']}: {out['matched']} {out['kind']}" + (f" match '{selector}'" if selector else "")
    if out["shown"] < out["matched"]:
        head += f" (first {out['shown']} listed)"
    rows = "\n".join(json.dumps(r, separators=(", ", ": ")) for r in out["rows"])
    return _text(head + ("\n" + rows if rows else ""))


@mcp.tool()
async def measure(a: Selection, b: Selection, model: Model = "default") -> CallToolResult:
    """Shortest distance between two selections, with the two closest points.

    Also gives the angle when both are a single flat face or a single straight edge.
    """
    try:
        out = await _work("measure", code=_require(model), model_dir=_context(model),
                          a=a.model_dump(exclude_none=True), b=b.model_dump(exclude_none=True))
    except Problem as exc:
        return _text(str(exc), error=True)
    text = f"Distance {_fmt(out['distance'])} mm, between {out['from']} and {out['to']}."
    if "angle_degrees" in out:
        text += f" Angle {_fmt(out['angle_degrees'])}°."
    return _text(text)


# ---------------------------------------------------------------- files

@mcp.tool()
async def export(
    format: Literal["step", "stl", "3mf", "brep", "glb", "svg", "html"],
    model: Model = "default",
    parts: Annotated[list[str] | None, Field(description="Only export these parts. Default: all.")] = None,
    path: Annotated[str | None, Field(description="Where to write the file. Default: the model's exports folder.")] = None,
) -> CallToolResult:
    """Write the current model to a file and return its path.

    STEP and GLB keep part names and colours. STL and 3MF are meshes for printing. SVG is a line drawing.
    HTML is the 3D viewer with this version of the model inside it: one file that opens in any browser
    and needs no server, for sharing or for publishing as a page.
    """
    try:
        code = _require(model)
        target = str(Path(path).expanduser()) if path else store.export_path(model, f"{clean(model)}-v{store.version(model)}.{format}")
        if format == "html":
            if parts:
                raise Problem("An HTML export always holds the whole model; leave parts out.")
            page = await anyio.to_thread.run_sync(standalone_page, model, store.version(model))
            Path(target).parent.mkdir(parents=True, exist_ok=True)
            Path(target).write_text(page)
            return _text(f"Wrote {target} ({len(page.encode()):,} bytes): the viewer with '{clean(model)}' "
                         f"version {store.version(model)} inside. This is an offline snapshot without version history; "
                         "use the live viewer for model previews and history.")
        out = await _work("export", 180, code=code, model_dir=_context(model), fmt=format, path=target, names=parts)
    except Problem as exc:
        return _text(str(exc), error=True)
    return _text(f"Wrote {out['path']} ({out['bytes']:,} bytes): " + ", ".join(out["parts"]) + ".")


@mcp.tool()
def import_file(
    path: Annotated[str, Field(description="A STEP, BREP or other file on this computer.")],
    model: Model = "default",
) -> CallToolResult:
    """Copy a file into the model so its script can load it, e.g. cq.importers.importStep(asset("bracket.step"))."""
    try:
        name = store.add_asset(model, path)
    except FileNotFoundError:
        return _text(f"There is no file at {path}.", error=True)
    return _text(f"Imported as '{name}'. In the script, load it with asset(\"{name}\"), for example:\n"
                 f"part = cq.importers.importStep(asset(\"{name}\"))")


# ---------------------------------------------------------------- viewer

def _mesh_for(model: str, version: int) -> dict:
    """Meshes for one version, for the viewer. Blocking; cached for the latest few."""
    model = clean(model)
    key = (model, version)
    if key not in _mesh_cache:
        code = store.code(model, version)
        out = runner.call("mesh", code=code, model_dir=_context(model, version))
        if len(_mesh_cache) >= 4:
            _mesh_cache.pop(next(iter(_mesh_cache)))
        _mesh_cache[key] = {"model": model, "version": version, **out}
    return _mesh_cache[key]


@mcp.tool(meta=APP_ONLY, structured_output=False)
async def get_mesh(model: str, version: int) -> CallToolResult:
    """Triangle meshes of one version of a model. Used by the viewer, not meant for the assistant."""
    try:
        data = await anyio.to_thread.run_sync(_mesh_for, model, version)
    except (Problem, KeyError) as exc:
        return _text(str(exc), error=True)
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(data))])


def _history(model: str) -> dict:
    """A model's versions for the viewer's history panel, oldest first."""
    model = clean(model)
    return {"model": model, "versions": store.versions(model)}


@mcp.tool(meta=APP_ONLY, structured_output=False)
def get_history(model: str) -> CallToolResult:
    """The saved versions of a model. Used by the viewer's history panel, not meant for the assistant."""
    return CallToolResult(content=[TextContent(type="text", text=json.dumps(_history(model)))])


def _viewer_html() -> str:
    if VIEWER_FILE.exists():
        return VIEWER_FILE.read_text()
    return "<!doctype html><title>CadSkill</title><p>The viewer has not been built. Run <code>npm run build</code>.</p>"


def standalone_page(model: str, version: int) -> str:
    """The viewer page with one version's meshes written into it. Blocking."""
    html = _viewer_html()
    if MODULE_TAG not in html:
        raise Problem("The viewer has not been built. Run `npm run build`.")
    data = json.dumps(_mesh_for(model, version)).replace("</", "<\\/")      # must not end the script element early
    return html.replace(MODULE_TAG, f"<script>window.CADSKILL_MODEL = {data};</script>\n{MODULE_TAG}", 1)


@mcp.resource(VIEWER_URI, name="CadSkill viewer", mime_type="text/html;profile=mcp-app")
def viewer() -> str:
    """The 3D viewer shown beside run_model, edit_model and restore_version."""
    return _viewer_html()


class _Page(BaseHTTPRequestHandler):
    """The same viewer as a plain local page, for hosts that do not show MCP Apps."""

    def log_message(self, *args) -> None:      # stdout belongs to the MCP protocol
        pass

    def _send(self, status: int, kind: str, body: bytes) -> None:
        self.send_response(status)
        self.send_header("content-type", kind)
        self.send_header("content-length", str(len(body)))
        self.send_header("cache-control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802 - name set by http.server
        url = urlparse(self.path)
        try:
            if url.path == "/":
                self._send(200, "text/html; charset=utf-8", _viewer_html().encode())
            elif url.path == "/state":
                requested = parse_qs(url.query).get("model")
                state = dict(_shown)
                if requested:
                    model = clean(requested[0])
                    _require(model)
                    state = {"model": model, "version": store.version(model)}
                elif state["model"] is None:    # nothing built in this session yet: show the newest saved model
                    models = store.models()
                    if models:
                        newest = max(models, key=lambda m: m["last"]["time"])
                        state = {"model": newest["model"], "version": newest["last"]["version"]}
                self._send(200, "application/json", json.dumps(state).encode())
            elif url.path == "/history":
                self._send(200, "application/json", json.dumps(_history(parse_qs(url.query)["model"][0])).encode())
            elif url.path == "/mesh":
                q = parse_qs(url.query)
                self._send(200, "application/json", json.dumps(_mesh_for(q["model"][0], int(q["version"][0]))).encode())
            elif url.path == "/build-steps":
                q = parse_qs(url.query)
                data = _build_steps(q["model"][0], int(q["version"][0]))
                self._send(200, "application/json", json.dumps(data).encode())
            else:
                self._send(404, "text/plain", b"Not found")
        except (Problem, KeyError, ValueError) as exc:
            self._send(400, "text/plain; charset=utf-8", str(exc).encode())


_http: ThreadingHTTPServer | None = None


def start_viewer_page(port: int = VIEWER_PORT, handler: type[BaseHTTPRequestHandler] | None = None) -> str:
    """Serve the viewer on this computer only and return its address."""
    global _http
    if _http is None:
        for candidate in range(port, port + 20):
            try:
                _http = ThreadingHTTPServer(("127.0.0.1", candidate), handler or _Page)
                break
            except OSError:
                continue
        else:
            raise Problem("No free port for the viewer page.")
        threading.Thread(target=_http.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{_http.server_address[1]}/"


@mcp.tool()
def open_viewer(model: Model | None = None) -> CallToolResult:
    """Get the address of a live 3D view without launching a browser.

    Use it when the conversation does not show the model inline. Open the URL in the host's
    in-app preview when available. Pass model to keep the page on that model and its history,
    even when other models are built. Omit model to follow the latest model.
    """
    try:
        if model is not None:
            model = clean(model)
            _require(model)
        url = start_viewer_page()
        if model is not None:
            url += "?" + urlencode({"model": model})
        return _text(f"The live viewer is at {url} (this computer only). It includes version history "
                     "and updates after every build. Open this URL in the host's browser panel.",
                     structuredContent={"url": url, "model": model})
    except Problem as exc:
        return _text(str(exc), error=True)


def _build_steps(model: str, version: int | None = None) -> dict:
    model = clean(model)
    _require(model)
    revision = store.version(model) if version is None else version
    try:
        back = start_viewer_page() + "?" + urlencode({"model": model})
        url = replay_server.open(store, model, revision, back)
    except (KeyError, ValueError) as exc:
        raise Problem(str(exc)) from exc
    return {"url": url, "model": model, "version": revision}


@mcp.tool()
def open_build_steps(model: Model = "default", version: int | None = None) -> CallToolResult:
    """Get CadSkill's Build steps view for a saved revision; no browser is launched.

    Optional: install cadskill[replay]. Open the returned URL in the host's in-app browser.
    Replay inspects recorded Workplane/Sketch operations. Direct solids and imported STEP
    files do not provide their original feature history. To change a feature, edit the source
    and rebuild; to restore the whole design, use restore_version.
    """
    try:
        data = _build_steps(model, version)
        data["url"] = start_viewer_page() + "?" + urlencode({
            "model": data["model"], "version": data["version"], "view": "steps"})
        return _text(f"Build steps for '{data['model']}' version {data['version']}: {data['url']}\n"
                     "Open this URL in the host's browser panel. Replay is embedded in the CadSkill viewer; "
                     "use Model or Revisions to switch views.",
                     structuredContent=data)
    except Problem as exc:
        return _text(str(exc), error=True)


def main() -> None:
    """Run the MCP server on stdio. With --page, only serve the viewer page (for working on the viewer)."""
    import sys

    runner.warm()        # start loading CadQuery now, so it is ready (or nearly) by the first tool call
    if "--page" in sys.argv:
        print(f"CadSkill viewer at {start_viewer_page()}", file=sys.stderr)
        threading.Event().wait()
    try:
        mcp.run()
    finally:
        replay_server.stop()
        runner.stop()


if __name__ == "__main__":
    main()
