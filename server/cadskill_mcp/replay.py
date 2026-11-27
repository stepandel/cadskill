"""Serve upstream Jupyter CadQuery Replay through Voilà, without a custom recorder.

Each page executes an already-saved revision in its own notebook kernel. The
normal CAD worker never imports the optional notebook dependencies or enables
Replay's process-wide CadQuery hooks.
"""
from __future__ import annotations

import atexit
import contextlib
import html
import importlib.util
import io
import json
import os
import secrets
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path
from urllib.parse import parse_qs, quote, urlencode, urlsplit

from .runner import Problem
from .store import Store, clean

INSTALL = 'uv tool install --force "cadskill[replay]"'


def available() -> bool:
    return all(importlib.util.find_spec(name) is not None for name in ("jupyter_cadquery", "voila"))


def replay_revision(base: str, model: str, revision: int, back_url: str) -> None:
    """Notebook entry point. Keep the upstream widgets and recording logic intact."""
    import cadquery as cq
    import math
    from IPython.display import HTML, display
    from voila.utils import get_query_string
    with contextlib.redirect_stdout(io.StringIO()):
        from jupyter_cadquery import show, get_viewer
        from jupyter_cadquery.replay import enable_replay, disable_replay, replay

    store = Store(Path(base))
    store.check_environment(model, revision)
    directory = store.context(model, revision)
    query = parse_qs(get_query_string() or "")
    embedded = query.get("embedded") == ["1"]
    theme = "dark" if query.get("theme") == ["dark"] else "light"
    if embedded:
        paper, ink, muted, accent = (("#19212a", "#e4eaf0", "#94a2b0", "#6ea8ff") if theme == "dark"
                                     else ("#f7f9fa", "#17212b", "#586573", "#1b5fc9"))
        display(HTML(f'<style>:root {{color-scheme:{theme};}} '
                     f'body,.jp-Notebook {{background:{paper};color:{ink};}} '
                     'body {font:14px/1.45 system-ui,-apple-system,"Segoe UI",sans-serif;} '
                     '.jp-Notebook {padding:12px;} '
                     f'a {{color:{accent};}} p {{color:{muted};margin:8px 0;}}</style>'))
    else:
        display(HTML(f'<h2>{html.escape(model)} · v{revision} · Build steps</h2>'
                     f'<p><a target="_self" href="{html.escape(back_url, quote=True)}">Back to revisions</a></p>'))
    display(HTML('<p>Select a shape and one or more build steps to inspect its geometry.</p>' if embedded else
                 '<p>Select a shape, then select one or more recorded steps. '
                 'Replay covers CadQuery Workplane and Sketch chains. Direct solid operations '
                 'and imported STEP geometry do not supply an editable feature history.</p>'))
    if not (directory / "environment.json").exists():
        display(HTML('<p>This older revision has no saved input snapshot; it uses the available imported files.</p>'))
    shown = []

    def show_object(obj, name=None, options=None, **kwargs):
        shown.append((name or f"part{len(shown) + 1}", obj))

    def asset(filename):
        path = (directory / "assets" / filename).resolve()
        if not path.is_relative_to((directory / "assets").resolve()) or not path.is_file():
            raise FileNotFoundError(f"No saved imported file named {filename!r}")
        return str(path)

    env = {"__name__": "__cadskill__", "cq": cq, "cadquery": cq, "math": math,
           "asset": asset, "show_object": show_object, "debug": lambda *a, **k: None}
    with contextlib.redirect_stdout(io.StringIO()):
        enable_replay(warning=False)
    old_cwd = Path.cwd()
    try:
        os.chdir(directory)
        exec(compile(store.code(model, revision), "<model>", "exec"), env)
        if not shown and "result" in env:
            show_object(env["result"])
        candidates = []
        for name, obj in shown:
            if isinstance(obj, (cq.Workplane, cq.Sketch)):
                candidates.append((name, obj))
            elif isinstance(obj, cq.Assembly):
                candidates.extend((f"{name}/{path}", node.obj) for path, node in obj.traverse()
                                  if isinstance(node.obj, (cq.Workplane, cq.Sketch)))
        if not candidates:
            candidates = [(name, obj) for name, obj in env.items()
                          if not name.startswith("_") and isinstance(obj, (cq.Workplane, cq.Sketch))]
            if candidates:
                display(HTML('<p><strong>Partial build history.</strong> Only intermediate shapes '
                             'have recorded chains in this revision. The final assembly contains '
                             'direct solid operations that are not included below. '
                             f'Use {"Model" if embedded else "Back to revisions"} '
                             'to see the complete assembly.</p>'))
    finally:
        os.chdir(old_cwd)
        with contextlib.redirect_stdout(io.StringIO()):
            disable_replay()

    if not shown:
        raise ValueError("This revision did not show any geometry.")
    if not candidates:
        display(HTML('<p><strong>No replayable Workplane or Sketch was retained by this script.</strong> '
                     'The final geometry is shown below. Feature changes are made by editing '
                     'the saved Python recipe and rebuilding.</p>'))
        show(*(obj for _, obj in shown), names=[name for name, _ in shown], cad_width=800, height=550,
             theme=theme if embedded else "browser")
        return

    selected = query.get("shape", [candidates[0][0]])[0]
    objects = dict(candidates)
    if selected not in objects:
        raise ValueError(f"No recorded shape named {selected!r} in this revision.")
    links = []
    for name in objects:
        target = "?" + urlencode({**query, "shape": [name]}, doseq=True)
        label = html.escape(name)
        links.append(f'<strong>{label}</strong>' if name == selected
                     else f'<a target="_self" href="{html.escape(target, quote=True)}">{label}</a>')
    display(HTML('<p>Shape: ' + ' · '.join(links) + '</p>'))
    with contextlib.redirect_stdout(io.StringIO()):
        enable_replay(warning=False)
    try:
        recording = replay(objects[selected], cad_width=800, height=550,
                           show_bbox=False, show_result=True)
        # Replay opens a JupyterLab sidecar. Voilà presents that same
        # upstream widget in the page using its documented cell traits.
        viewer = getattr(recording, "viewer", None) or get_viewer("Replay")
        if viewer is not None:
            viewer.widget.title = None
            viewer.widget.anchor = None
            if embedded:
                viewer.widget.theme = theme
                viewer.widget.height = 360
            display(viewer.widget)
    finally:
        with contextlib.redirect_stdout(io.StringIO()):
            disable_replay()


class ReplayServer:
    """One optional local Voilà process per CadSkill server, with idle kernel culling."""

    def __init__(self):
        self.process = None
        self.base = None
        self.url = None
        self.token = None
        self.lock = threading.Lock()
        atexit.register(self.stop)

    def stop(self):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=5)
        self.process = None

    def open(self, store: Store, model: str, revision: int, back_url: str) -> str:
        if not available():
            raise Problem(f"Build steps needs the optional Replay components. Install them with:\n{INSTALL}\n"
                          "Then restart CadSkill. Revisions and the regular viewer work without them.")
        store.code(model, revision)       # only saved scripts can be opened
        store.check_environment(model, revision)
        with self.lock:
            directory = store.base.resolve() / ".replay"
            directory.mkdir(parents=True, exist_ok=True, mode=0o700)
            notebooks = directory / "notebooks"
            notebooks.mkdir(exist_ok=True)
            name = f"{clean(model)}-v{revision}.ipynb"
            source = ("from cadskill_mcp.replay import replay_revision\n"
                      f"replay_revision({str(store.base.resolve())!r}, {clean(model)!r}, {revision!r}, {back_url!r})")
            notebook = {"nbformat": 4, "nbformat_minor": 5,
                        "metadata": {"kernelspec": {"display_name": "CadSkill Replay", "language": "python",
                                                   "name": "cadskill-replay"}},
                        "cells": [{"id": "replay", "cell_type": "code", "metadata": {},
                                   "source": source, "outputs": [], "execution_count": None}]}
            (notebooks / name).write_text(json.dumps(notebook))
            if self.process is None or self.process.poll() is not None or self.base != directory:
                self.stop()
                self.base = directory
                kernels = directory / "jupyter" / "kernels" / "cadskill-replay"
                kernels.mkdir(parents=True, exist_ok=True)
                (kernels / "kernel.json").write_text(json.dumps({"argv": [sys.executable, "-m", "ipykernel_launcher",
                                                                           "-f", "{connection_file}"],
                                                              "display_name": "CadSkill Replay", "language": "python"}))
                with socket.socket() as sock:
                    sock.bind(("127.0.0.1", 0))
                    port = sock.getsockname()[1]
                self.token = secrets.token_urlsafe(32)
                self.url = f"http://127.0.0.1:{port}/"
                env = dict(os.environ)
                env["JUPYTER_PATH"] = str(directory / "jupyter") + os.pathsep + env.get("JUPYTER_PATH", "")
                env["PYTHONPATH"] = str(Path(__file__).resolve().parent.parent) + os.pathsep + env.get("PYTHONPATH", "")
                config = directory / "jupyter_server_config.py"
                parent = urlsplit(back_url)
                origin = f"{parent.scheme}://{parent.netloc}"
                if parent.scheme != "http" or parent.hostname != "127.0.0.1":
                    raise Problem("Replay can only be embedded by the local CadSkill viewer.")
                config.write_text("c.ServerApp.jpserver_extensions = " + repr({
                    "jupyterlab": False, "jupyter_lsp": False, "jupyter_cadquery": True,
                    "voila.server_extension": True}) + "\n"
                    + "c.ServerApp.tornado_settings = " + repr({"headers": {
                        "Content-Security-Policy": "frame-ancestors 'self' " + origin}}) + "\n")
                args = [sys.executable, "-m", "jupyter_server", "--no-browser",
                        f"--config={config}",
                        f"--ServerApp.root_dir={notebooks}", "--ServerApp.ip=127.0.0.1",
                        f"--ServerApp.port={port}", "--ServerApp.port_retries=0",
                        "--ServerApp.shutdown_no_activity_timeout=900",
                        f"--IdentityProvider.token={self.token}", "--MappingKernelManager.cull_idle_timeout=600",
                        "--MappingKernelManager.cull_interval=60", "--MappingKernelManager.cull_connected=True"]
                with (directory / "server.log").open("ab") as log:
                    self.process = subprocess.Popen(args, env=env, cwd=directory, stdin=subprocess.DEVNULL,
                                                    stdout=log, stderr=log)
                # Starting the HTTP listener does not execute the model or wait for the CAD kernel.
                deadline = time.monotonic() + 20
                opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
                while time.monotonic() < deadline:
                    if self.process.poll() is not None:
                        raise Problem(f"The Replay view could not start. See {directory / 'server.log'}.")
                    try:
                        with opener.open(self.url + "api?" + urlencode({"token": self.token}), timeout=1):
                            break
                    except (OSError, urllib.error.URLError):
                        time.sleep(0.2)
                else:
                    self.stop()
                    raise Problem("The Replay view is still starting. Try Build steps again.")
            return self.url + "voila/render/" + quote(name) + "?" + urlencode({"token": self.token})
