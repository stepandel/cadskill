"""Adapt upstream Replay records to CadSkill's existing canvas.

Only the dedicated replay worker imports the optional library. Its recorder
and chain formatting are reused; no notebook UI or viewer server is started.
Recorded CAD objects stay in the worker. Only lists and meshes leave it.
"""
from __future__ import annotations

import contextlib
import importlib.util
import io
from collections import OrderedDict

from .runner import Problem

INSTALL = 'uv tool install --force "cadskill[replay]"'
_records = OrderedDict()


def available() -> bool:
    return importlib.util.find_spec("jupyter_cadquery") is not None


def require() -> None:
    if not available():
        raise Problem(f"Build steps needs the optional Replay components. Install them with:\n{INSTALL}\n"
                      "Then restart CadSkill. Revisions and the regular viewer work without them.")


def record(code: str, model_dir: str) -> dict:
    from . import worker
    key = worker._key(code, model_dir)
    if key in _records:
        _records.move_to_end(key)
        return _records[key]
    require()
    import cadquery as cq
    with contextlib.redirect_stdout(io.StringIO()), contextlib.redirect_stderr(io.StringIO()):
        from IPython.core.interactiveshell import InteractiveShell
        from jupyter_cadquery.replay import Replay, enable_replay, disable_replay, reset_replay
        InteractiveShell.instance()

        # Reuse Replay's traversal/formatting without constructing its notebook
        # UI. The optional dependency is bounded to the tested 5.3 API.
        class Chain(Replay):
            def __init__(self):
                pass

        original = (cq.Workplane.__getattribute__, cq.Sketch.__getattribute__)
        try:
            reset_replay()
            enable_replay(warning=False)
            result = worker._execute(code, model_dir, keep_objects=True)
            if "error" in result:
                error = result["error"]
                raise worker.ModelError(f"Cannot record build steps: {error['message']} (line {error['line']}).")
            candidates = []
            for obj, name, options in result["shown"]:
                if isinstance(obj, (cq.Workplane, cq.Sketch)):
                    candidates.append((name or "part", obj, None, worker._color(options)))
                elif isinstance(obj, cq.Assembly):
                    for path, node in obj.traverse():
                        if not isinstance(node.obj, (cq.Workplane, cq.Sketch)):
                            continue
                        location, parent = node.loc, node.parent
                        while parent is not None:
                            location = parent.loc * location
                            parent = parent.parent
                        color = node.color.toTuple()[:3] if node.color is not None else None
                        candidates.append((path, node.obj, location, color))
            partial = not candidates
            if partial:
                candidates = [(name, obj, None, None) for name, obj in result["env"].items()
                              if not name.startswith("_") and isinstance(obj, (cq.Workplane, cq.Sketch))]
            adapter, chains = Chain(), []
            for name, obj, location, color in candidates:
                entries = adapter.format_steps(adapter.to_array(obj, result_name=getattr(obj, "name", "")))
                if entries:
                    chains.append({"name": name, "entries": entries, "location": location, "color": color})
        finally:
            try:
                disable_replay()
                reset_replay()
            finally:
                # Upstream 5.3 restores Workplane only. Restore Sketch too,
                # including when recording or model execution fails.
                cq.Workplane.__getattribute__, cq.Sketch.__getattribute__ = original
    result = {"key": key, "chains": chains, "partial": partial}
    _records[key] = result
    while len(_records) > 4:
        _records.popitem(last=False)
    return result


def list_steps(code: str, model_dir: str) -> dict:
    recorded = record(code, model_dir)
    return {"partial": recorded["partial"], "chains": [
        {"id": i, "name": chain["name"], "steps": [
            {"index": n, "label": label} for n, (label, _) in enumerate(chain["entries"])]}
        for i, chain in enumerate(recorded["chains"])]}


def step_mesh(code: str, model_dir: str, chain: int, step: int) -> dict:
    import cadquery as cq
    from . import worker
    recorded = record(code, model_dir)
    if chain < 0 or chain >= len(recorded["chains"]):
        raise worker.ModelError("No such recorded shape. Refresh Build steps.")
    selected = recorded["chains"][chain]
    if step < 0 or step >= len(selected["entries"]):
        raise worker.ModelError("No such build step. Refresh Build steps.")
    label, obj = selected["entries"][step]
    if isinstance(obj, cq.Workplane):
        objects = obj.vals() or [obj.plane.origin]
    elif isinstance(obj, cq.Sketch):
        objects = obj.vals()
    else:
        objects = [obj]
    shapes = [cq.Vertex.makeVertex(*value.toTuple()) if isinstance(value, cq.Vector) else value
              for value in objects if isinstance(value, (cq.Vector, cq.Shape))]
    if not shapes:
        raise worker.ModelError("This step has no displayable geometry. Choose another step or Final model.")
    shape = shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)
    if selected["location"] is not None:
        shape = shape.moved(selected["location"])
    part = {"shape": shape, "name": selected["name"], "color": selected["color"]}
    data = worker._viewer_part(part, f"step-{chain}", f"{recorded['key'][:12]}-{chain}-{step}", primitives=True)
    data["name"] += f" · step {step + 1}"
    return {"chain": chain, "step": step, "label": label, "parts": [data]}
