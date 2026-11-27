"""The CadQuery side: runs model scripts and answers questions about the result.

This module runs in a child process (see runner.py) so a script that hangs or
crashes the kernel cannot take the MCP server down. Every request names the
script it is about; results are cached by the script's hash, so the worker can
be killed and restarted at any time without the server tracking its state.
"""
from __future__ import annotations

import contextlib
import hashlib
import io
import math
import os
import traceback
from collections import OrderedDict

SCRIPT_NAME = "<model>"
CACHE_SIZE = 4
MAX_OUTPUT = 4000
MAX_ROWS = 200
MESH_TOLERANCE = 0.03
MESH_ANGLE = 0.3

_cache: "OrderedDict[str, list[dict]]" = OrderedDict()   # source and input context hash -> parts


class ModelError(Exception):
    """A problem to report to the caller as-is (bad selector, unknown part...)."""


# ---------------------------------------------------------------- running a script

def _shapes_of(obj):
    """Turn anything a script may show into a list of (shape, name, color) tuples."""
    import cadquery as cq

    if isinstance(obj, cq.Assembly):
        out = []
        for name, node in obj.traverse():
            shapes = _shapes_of(node.obj) if node.obj is not None else []
            if not shapes:
                continue
            loc, parent = node.loc, node.parent
            while parent is not None:          # world placement = every ancestor's location, outermost first
                loc = parent.loc * loc
                parent = parent.parent
            color = node.color.toTuple()[:3] if node.color is not None else None
            for shape, _, _ in shapes:
                out.append((shape.moved(loc), name.split("/")[-1], color))
        return out
    if isinstance(obj, cq.Workplane):
        shapes = [v for v in obj.vals() if isinstance(v, cq.Shape)]
        if not shapes:
            return []
        return [(shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes), None, None)]
    if isinstance(obj, cq.Sketch):
        faces = [f for f in obj.faces().vals() if isinstance(f, cq.Shape)]
        return [(cq.Compound.makeCompound(faces), None, None)] if faces else []
    if isinstance(obj, cq.Shape):
        return [(obj, None, None)]
    if isinstance(obj, (list, tuple)):
        return [s for item in obj for s in _shapes_of(item)]
    raise ModelError(f"show_object() cannot display a {type(obj).__name__}. Pass a Workplane, a Shape or an Assembly.")


def _color(options):
    if not options or "color" not in options:
        return None
    import cadquery as cq

    c = options["color"]
    if isinstance(c, str):
        return cq.Color(c).toTuple()[:3]
    c = tuple(float(x) for x in c)[:3]
    return tuple(x / 255 for x in c) if max(c) > 1 else c


def _error_report(exc: BaseException, code: str) -> dict:
    """Where in the script it went wrong, in the script's own line numbers."""
    line = None
    if isinstance(exc, SyntaxError) and exc.filename == SCRIPT_NAME:
        line = exc.lineno
    else:
        for frame in traceback.extract_tb(exc.__traceback__):
            if frame.filename == SCRIPT_NAME:
                line = frame.lineno          # the last script frame is the line that failed
    lines = code.splitlines()
    message = str(exc) or type(exc).__name__
    if isinstance(exc, SyntaxError):
        message = exc.msg
    return {
        "type": type(exc).__name__,
        "message": message,
        "line": line,
        "source": lines[line - 1].strip() if line and 0 < line <= len(lines) else None,
    }


def _execute(code: str, model_dir: str, keep_objects: bool = False) -> dict:
    """Run the script. Returns {'parts': [...], 'stdout': str} or {'error': {...}, 'stdout': str}."""
    import cadquery as cq

    shown: list[tuple] = []
    objects = []

    def show_object(obj, name=None, options=None, **_):
        if keep_objects:
            objects.append((obj, name, options))
        for shape, own_name, own_color in _shapes_of(obj):
            shown.append((shape, name or own_name, _color(options) or own_color))

    def asset(filename: str) -> str:
        path = os.path.join(model_dir, "assets", filename)
        if not os.path.exists(path):
            raise ModelError(f"No imported file named '{filename}'. Use the import_file tool first.")
        return path

    env = {"__name__": "__cadskill__", "cq": cq, "cadquery": cq, "show_object": show_object,
           "debug": lambda *a, **k: None, "asset": asset, "math": math}
    out = io.StringIO()
    old_cwd = os.getcwd()
    try:
        os.makedirs(model_dir, exist_ok=True)
        os.chdir(model_dir)
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(out):
            exec(compile(code, SCRIPT_NAME, "exec"), env)
            if not shown and "result" in env:
                show_object(env["result"])
        if not shown:
            raise ModelError("The script ran but showed nothing. Call show_object(part, name='...') for each part.")
    except BaseException as exc:  # noqa: BLE001 - a script may raise anything, including SystemExit
        return {"error": _error_report(exc, code), "stdout": out.getvalue()[-MAX_OUTPUT:]}
    finally:
        os.chdir(old_cwd)

    parts, used = [], set()
    for i, (shape, name, color) in enumerate(shown):
        base = name or (f"part{i + 1}" if len(shown) > 1 else "part")
        name, n = base, 2
        while name in used:                  # names are how tools refer to parts, so they must be unique
            name, n = f"{base}-{n}", n + 1
        used.add(name)
        parts.append({"name": name, "shape": shape, "color": color})
    result = {"parts": parts, "stdout": out.getvalue()[-MAX_OUTPUT:]}
    if keep_objects:
        result.update(shown=objects, env=env)
    return result


def _load(code: str, model_dir: str) -> list[dict]:
    """Parts for a script, from the cache or by running it. Raises ModelError if the script fails."""
    key = _key(code, model_dir)
    if key in _cache:
        _cache.move_to_end(key)
        return _cache[key]
    result = _execute(code, model_dir)
    if "error" in result:
        e = result["error"]
        raise ModelError(f"The current script no longer runs: {e['message']}" + (f" (line {e['line']})" if e["line"] else ""))
    _remember(key, result["parts"])
    return result["parts"]


def _remember(key: str, parts: list[dict]) -> None:
    _cache[key] = parts
    _cache.move_to_end(key)
    while len(_cache) > CACHE_SIZE:
        _cache.popitem(last=False)


def _key(code: str, model_dir: str) -> str:
    # The same source can import different geometry in two models or revisions.
    from pathlib import Path
    assets = Path(model_dir) / "assets"
    inputs = [(str(p.relative_to(assets)), p.stat().st_size, p.stat().st_mtime_ns)
              for p in sorted(assets.rglob("*")) if p.is_file()] if assets.exists() else []
    return hashlib.sha256((code + "\0" + os.path.realpath(model_dir) + repr(inputs)).encode()).hexdigest()


# ---------------------------------------------------------------- describing parts

def _r(v: float, digits: int = 3) -> float:
    return round(float(v), digits) + 0.0     # + 0.0 turns -0.0 into 0.0


def _vec(v) -> list[float]:
    return [_r(v.x), _r(v.y), _r(v.z)]


def _summary(part: dict) -> dict:
    """Size, topology and mass properties. Kept on the part: on big imports this takes seconds."""
    if "summary" not in part:
        part["summary"] = _measure_part(part)
    return part["summary"]


def _measure_part(part: dict) -> dict:
    shape = part["shape"]
    bb = shape.BoundingBox()
    info = {
        "name": part["name"],
        "size": [_r(bb.xlen), _r(bb.ylen), _r(bb.zlen)],
        "min": [_r(bb.xmin), _r(bb.ymin), _r(bb.zmin)],
        "max": [_r(bb.xmax), _r(bb.ymax), _r(bb.zmax)],
        "solids": len(shape.Solids()),
        "faces": len(shape.Faces()),
        "edges": len(shape.Edges()),
        "valid": bool(shape.isValid()),
    }
    try:
        info["volume"] = _r(shape.Volume())
        info["area"] = _r(shape.Area())
        info["center_of_mass"] = _vec(shape.Center())
    except Exception:  # noqa: BLE001 - wires and empty compounds have no mass properties
        pass
    if part["color"]:
        info["color"] = [_r(c) for c in part["color"]]
    return info


def op_run(code: str, model_dir: str) -> dict:
    result = _execute(code, model_dir)
    if "error" in result:
        return result
    _remember(_key(code, model_dir), result["parts"])
    return {"parts": [_summary(p) for p in result["parts"]], "stdout": result["stdout"]}


def _part(parts: list[dict], name: str | None) -> dict:
    if name is None:
        if len(parts) == 1:
            return parts[0]
        raise ModelError("This model has several parts; name one of: " + ", ".join(p["name"] for p in parts))
    for p in parts:
        if p["name"] == name:
            return p
    raise ModelError(f"No part named '{name}'. Parts: " + ", ".join(p["name"] for p in parts))


KINDS = {"faces": "Faces", "edges": "Edges", "vertices": "Vertices"}


def _select(parts: list[dict], sel: dict) -> tuple[list, list[int], str]:
    """Resolve {'part', 'kind', 'selector', 'index'} to (shapes, their indices, kind).

    With no kind the whole part is selected. Indices are positions in the
    part's own face/edge/vertex list, which is what `inspect` prints.
    """
    import cadquery as cq

    part = _part(parts, sel.get("part"))
    kind = sel.get("kind")
    if not kind:
        return [part["shape"]], [], "part"
    if kind not in KINDS:
        raise ModelError("kind must be one of: faces, edges, vertices.")
    everything = getattr(part["shape"], KINDS[kind])()
    chosen = list(range(len(everything)))
    if sel.get("selector"):
        try:
            picked = getattr(cq.Workplane("XY").newObject([part["shape"]]), kind)(sel["selector"]).vals()
        except Exception as exc:  # noqa: BLE001
            raise ModelError(f"Selector '{sel['selector']}' is not valid: {exc}") from exc
        chosen = [i for i, s in enumerate(everything) if any(s.isSame(p) for p in picked)]
    if sel.get("index") is not None:
        wanted = sel["index"] if isinstance(sel["index"], list) else [sel["index"]]
        bad = [i for i in wanted if not 0 <= i < len(everything)]
        if bad:
            raise ModelError(f"{part['name']} has {len(everything)} {kind}; no index {bad[0]}.")
        chosen = [i for i in chosen if i in wanted]
    return [everything[i] for i in chosen], chosen, kind


def _radius(shape) -> float | None:
    from OCP.BRepAdaptor import BRepAdaptor_Curve, BRepAdaptor_Surface
    from OCP.GeomAbs import GeomAbs_Circle, GeomAbs_Cone, GeomAbs_Cylinder, GeomAbs_Sphere, GeomAbs_Torus

    try:
        if shape.ShapeType() == "Edge":
            c = BRepAdaptor_Curve(shape.wrapped)
            return _r(c.Circle().Radius()) if c.GetType() == GeomAbs_Circle else None
        s = BRepAdaptor_Surface(shape.wrapped)
        t = s.GetType()
        if t == GeomAbs_Cylinder:
            return _r(s.Cylinder().Radius())
        if t == GeomAbs_Sphere:
            return _r(s.Sphere().Radius())
        if t == GeomAbs_Torus:
            return _r(s.Torus().MinorRadius())
        if t == GeomAbs_Cone:
            return _r(s.Cone().RefRadius())
    except Exception:  # noqa: BLE001
        pass
    return None


def op_inspect(code: str, model_dir: str, sel: dict) -> dict:
    parts = _load(code, model_dir)
    sel = {**sel, "kind": sel.get("kind") or "faces"}
    shapes, indices, kind = _select(parts, sel)
    rows = []
    for i, s in list(zip(indices, shapes))[:MAX_ROWS]:
        row = {"index": i}
        if kind == "vertices":
            row["at"] = _vec(s.Center())
        else:
            row["type"] = s.geomType()
            row["center"] = _vec(s.Center())
            radius = _radius(s)
            if radius is not None:
                row["radius"] = radius
            if kind == "faces":
                row["area"] = _r(s.Area())
                if s.geomType() == "PLANE":
                    row["normal"] = _vec(s.normalAt())
            else:
                row["length"] = _r(s.Length())
                if s.geomType() == "LINE":
                    row["from"], row["to"] = _vec(s.startPoint()), _vec(s.endPoint())
        rows.append(row)
    return {"part": _part(parts, sel.get("part"))["name"], "kind": kind, "matched": len(shapes),
            "shown": len(rows), "rows": rows}


def op_measure(code: str, model_dir: str, a: dict, b: dict) -> dict:
    import cadquery as cq
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape

    parts = _load(code, model_dir)
    sa, _, ka = _select(parts, a)
    sb, _, kb = _select(parts, b)
    if not sa or not sb:
        raise ModelError("One of the selections matched nothing.")
    one = lambda shapes: shapes[0] if len(shapes) == 1 else cq.Compound.makeCompound(shapes)  # noqa: E731
    dist = BRepExtrema_DistShapeShape(one(sa).wrapped, one(sb).wrapped)
    if not dist.IsDone():
        raise ModelError("The kernel could not measure between these selections.")
    p1, p2 = dist.PointOnShape1(1), dist.PointOnShape2(1)
    out = {"distance": _r(dist.Value()), "from": [_r(p1.X()), _r(p1.Y()), _r(p1.Z())], "to": [_r(p2.X()), _r(p2.Y()), _r(p2.Z())]}

    def direction(shapes, kind):
        if len(shapes) != 1:
            return None
        s = shapes[0]
        if kind == "faces" and s.geomType() == "PLANE":
            return s.normalAt()
        if kind == "edges" and s.geomType() == "LINE":
            return s.endPoint() - s.startPoint()
        return None

    da, db = direction(sa, ka), direction(sb, kb)
    if da is not None and db is not None:
        out["angle_degrees"] = _r(math.degrees(da.getAngle(db)), 2)
    return out


# ---------------------------------------------------------------- meshes for the viewer

def _triangulate(shape, tolerance):
    """Mesh the shape and read the triangulation into numpy arrays.

    Does what cq.Shape.tessellate does, but much faster on big parts: OCCT meshes
    the faces in parallel, and triangles are read with Triangle(i) rather than by
    iterating Triangles(), which in OCP costs ~60 µs per triangle (9 s for a
    150k-triangle STEP import).
    """
    import numpy as np
    from OCP.BRep import BRep_Tool
    from OCP.BRepMesh import BRepMesh_IncrementalMesh
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopLoc import TopLoc_Location
    from OCP.TopoDS import TopoDS

    BRepMesh_IncrementalMesh(shape.wrapped, tolerance, False, MESH_ANGLE, True)
    verts, tris, offset = [], [], 0
    explorer = TopExp_Explorer(shape.wrapped, TopAbs_FACE)
    while explorer.More():
        face = TopoDS.Face_s(explorer.Current())
        explorer.Next()
        loc = TopLoc_Location()
        poly = BRep_Tool.Triangulation_s(face, loc)
        if poly is None:
            continue
        v = np.array([poly.Node(i).Coord() for i in range(1, poly.NbNodes() + 1)], dtype=np.float64)
        t = np.array([poly.Triangle(i).Get() for i in range(1, poly.NbTriangles() + 1)], dtype=np.int64) - 1
        if not loc.IsIdentity():
            trsf = loc.Transformation()
            m = np.array([[trsf.Value(r, c) for c in range(1, 5)] for r in range(1, 4)])
            v = v @ m[:, :3].T + m[:, 3]
        if face.Orientation() == TopAbs_REVERSED:
            t = t[:, [0, 2, 1]]
        verts.append(v)
        tris.append(t + offset)
        offset += len(v)
    if not verts:
        return np.zeros((0, 3)), np.zeros((0, 3), dtype=np.uint32)
    return np.concatenate(verts), np.concatenate(tris).astype(np.uint32)


def _mesh(shape, tolerance=MESH_TOLERANCE):
    """Triangles with per-vertex normals. Vertices are not shared between faces, so creases stay sharp."""
    import numpy as np

    v, t = _triangulate(shape, tolerance)
    n = np.zeros_like(v)
    if len(t):
        face_n = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
        for k in range(3):
            np.add.at(n, t[:, k], face_n)
        length = np.linalg.norm(n, axis=1, keepdims=True)
        n = np.divide(n, length, out=np.zeros_like(n), where=length > 0)
    return v.astype(np.float32), n.astype(np.float32), t


def op_mesh(code: str, model_dir: str) -> dict:
    key = _key(code, model_dir)[:12]
    return {"parts": [_viewer_part(p, p["name"], f"{key}-{i}")
                      for i, p in enumerate(_load(code, model_dir))]}


def _viewer_part(part: dict, identity: str, key: str, primitives: bool = False) -> dict:
    import base64
    import numpy as np

    shape = part["shape"]
    v, n, t = _mesh(shape)
    kind = "surface"
    if primitives and not len(t):
        from OCP.BRepAdaptor import BRepAdaptor_Curve
        from OCP.GCPnts import GCPnts_QuasiUniformDeflection
        segments = []
        for edge in shape.Edges():
            curve = BRepAdaptor_Curve(edge.wrapped)
            sample = GCPnts_QuasiUniformDeflection(curve, MESH_TOLERANCE)
            if sample.IsDone():
                for i in range(1, sample.NbPoints()):
                    segments.extend([sample.Value(i).Coord(), sample.Value(i + 1).Coord()])
        if segments:
            v, kind = np.array(segments, dtype=np.float32), "curve"
        else:
            v = np.array([vertex.Center().toTuple() for vertex in shape.Vertices()], dtype=np.float32)
            kind = "point"
        if not len(v):
            raise ModelError("This step has no displayable geometry. Choose another step or Final model.")
    info = _summary(part)
    b64 = lambda a: base64.b64encode(a.tobytes()).decode()  # noqa: E731
    return {"id": identity, "key": key, "name": part["name"], "color": info.get("color"), "kind": kind,
            "size": info["size"], "volume": info.get("volume") if info["solids"] else None,
            "triangles": int(len(t)), "positions": b64(v), "normals": b64(n), "indices": b64(t)}


def op_build_steps(code: str, model_dir: str) -> dict:
    from .replay import list_steps
    return list_steps(code, model_dir)


def op_step_mesh(code: str, model_dir: str, chain: int, step: int) -> dict:
    from .replay import step_mesh
    return step_mesh(code, model_dir, chain, step)


# ---------------------------------------------------------------- pictures

VIEWS = {              # name -> (where the camera sits relative to the model, which way is up)
    "iso": ((1, -1, 0.8), (0, 0, 1)),
    "front": ((0, -1, 0), (0, 0, 1)),
    "back": ((0, 1, 0), (0, 0, 1)),
    "right": ((1, 0, 0), (0, 0, 1)),
    "left": ((-1, 0, 0), (0, 0, 1)),
    "top": ((0, 0, 1), (0, 1, 0)),
    "bottom": ((0, 0, -1), (0, 1, 0)),
}
FOUR = ["iso", "top", "front", "right"]
PART_COLOR = (0.62, 0.68, 0.74)
HIGHLIGHT = (0.92, 0.26, 0.21)


def _polydata(shape, tolerance):
    import numpy as np
    import vtk
    from vtk.util import numpy_support

    v, n, t = _mesh(shape, tolerance)
    pd = vtk.vtkPolyData()
    pts = vtk.vtkPoints()
    pts.SetData(numpy_support.numpy_to_vtk(v, deep=True))
    pd.SetPoints(pts)
    cells = vtk.vtkCellArray()
    offsets = numpy_support.numpy_to_vtkIdTypeArray(np.arange(0, 3 * len(t) + 1, 3, dtype=np.int64), deep=True)
    conn = numpy_support.numpy_to_vtkIdTypeArray(t.astype(np.int64).ravel(), deep=True)
    cells.SetData(offsets, conn)
    pd.SetPolys(cells)
    pd.GetPointData().SetNormals(numpy_support.numpy_to_vtk(n, deep=True))
    return pd


def _edge_polydata(shape, tolerance):
    """The part's real edges as polylines, so pictures show the same outlines a drawing would."""
    import vtk
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection

    pts, lines = vtk.vtkPoints(), vtk.vtkCellArray()
    for e in shape.Edges():
        try:
            curve = BRepAdaptor_Curve(e.wrapped)
            disc = GCPnts_QuasiUniformDeflection(curve, tolerance)
            if not disc.IsDone() or disc.NbPoints() < 2:
                continue
            ids = []
            for i in range(1, disc.NbPoints() + 1):
                p = disc.Value(i)
                ids.append(pts.InsertNextPoint(p.X(), p.Y(), p.Z()))
            lines.InsertNextCell(len(ids), ids)
        except Exception:  # noqa: BLE001 - degenerate edges (sphere poles) have no curve
            continue
    pd = vtk.vtkPolyData()
    pd.SetPoints(pts)
    pd.SetLines(lines)
    return pd


def _section(shape, plane: dict):
    """Cut the part with a plane and keep the side behind it, so the inside is visible."""
    import cadquery as cq

    origin = cq.Vector(*plane.get("origin", (0, 0, 0)))
    normal = cq.Vector(*plane["normal"]).normalized()
    reach = shape.BoundingBox().DiagonalLength * 4 + 10
    block = cq.Workplane(cq.Plane(origin=origin.toTuple(), normal=normal.toTuple())).rect(reach, reach).extrude(reach).val()
    return shape.cut(block)


def op_render(code: str, model_dir: str, spec: dict) -> dict:
    import vtk

    everything = _load(code, model_dir)
    parts = [_part(everything, name) for name in spec["parts"]] if spec.get("parts") else everything
    view = spec.get("view") or "four"
    names = FOUR if view == "four" else [view]
    custom = spec.get("direction") if view != "four" else None
    if not custom and any(n not in VIEWS for n in names):
        raise ModelError("view must be one of: four, " + ", ".join(VIEWS) + " (or pass a direction).")
    width, height = int(spec.get("width") or 1000), int(spec.get("height") or 760)

    highlight = _select(everything, spec["highlight"])[0] if spec.get("highlight") else []

    shapes = []
    for p in parts:
        shape = p["shape"]
        if spec.get("section"):
            try:
                shape = _section(shape, spec["section"])
            except Exception as exc:  # noqa: BLE001
                raise ModelError(f"Could not section '{p['name']}': {exc}") from exc
        shapes.append((shape, p["color"]))
    diag = max((s.BoundingBox().DiagonalLength for s, _ in shapes), default=1.0) or 1.0
    tolerance = max(diag / 2000, 0.005)

    actors = []
    for shape, color in shapes:
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(_polydata(shape, tolerance))
        mapper.SetResolveCoincidentTopologyToPolygonOffset()
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        prop = actor.GetProperty()
        prop.SetColor(*(color or PART_COLOR))
        prop.SetAmbient(0.35)
        prop.SetDiffuse(0.7)
        prop.SetSpecular(0.05)
        if highlight:
            prop.SetOpacity(0.35)
        actors.append(actor)
        em = vtk.vtkPolyDataMapper()
        em.SetInputData(_edge_polydata(shape, tolerance))
        ea = vtk.vtkActor()
        ea.SetMapper(em)
        ea.GetProperty().SetColor(0.08, 0.1, 0.13)
        ea.GetProperty().SetLineWidth(1.6)
        ea.GetProperty().LightingOff()
        actors.append(ea)
    for h in highlight:
        mapper = vtk.vtkPolyDataMapper()
        mapper.SetInputData(_edge_polydata(h, tolerance) if h.ShapeType() == "Edge" else _polydata(h, tolerance))
        actor = vtk.vtkActor()
        actor.SetMapper(mapper)
        actor.GetProperty().SetColor(*HIGHLIGHT)
        actor.GetProperty().SetLineWidth(5)
        actor.GetProperty().LightingOff()
        actors.append(actor)

    win = vtk.vtkRenderWindow()
    win.SetOffScreenRendering(1)
    win.SetSize(width, height)
    win.SetMultiSamples(8)
    cols = 2 if len(names) > 1 else 1
    rows = math.ceil(len(names) / cols)
    for i, name in enumerate(names):
        ren = vtk.vtkRenderer()
        ren.SetBackground(0.96, 0.97, 0.98)
        col, row = i % cols, i // cols
        ren.SetViewport(col / cols, 1 - (row + 1) / rows, (col + 1) / cols, 1 - row / rows)
        for a in actors:
            ren.AddActor(a)
        direction, up = VIEWS.get(name, VIEWS["iso"])
        if custom:
            direction = tuple(float(d) for d in custom)
            steep = abs(direction[2]) > 0.99 * math.sqrt(sum(d * d for d in direction))
            up = (0, 1, 0) if steep else (0, 0, 1)
        cam = ren.GetActiveCamera()
        cam.ParallelProjectionOn()          # no perspective: lengths can be compared by eye
        cam.SetFocalPoint(0, 0, 0)
        cam.SetPosition(*direction)
        cam.SetViewUp(*up)
        ren.ResetCamera()
        cam.Zoom(1.25)
        ren.ResetCameraClippingRange()
        label = vtk.vtkTextActor()
        label.SetInput("CUSTOM" if custom else name.upper())
        label.GetTextProperty().SetColor(0.3, 0.36, 0.42)
        label.GetTextProperty().SetFontSize(15)
        label.SetPosition(10, 8)
        ren.AddViewProp(label)
        win.AddRenderer(ren)
    win.Render()
    grab = vtk.vtkWindowToImageFilter()
    grab.SetInput(win)
    grab.ReadFrontBufferOff()
    grab.Update()
    writer = vtk.vtkPNGWriter()
    writer.WriteToMemoryOn()
    writer.SetInputConnection(grab.GetOutputPort())
    writer.Write()
    data = bytes(memoryview(writer.GetResult()))
    win.Finalize()
    return {"png": data, "views": ["custom"] if custom else names}


# ---------------------------------------------------------------- files out

FORMATS = ("step", "stl", "3mf", "brep", "glb", "svg")


def op_export(code: str, model_dir: str, fmt: str, path: str, names: list[str] | None) -> dict:
    import cadquery as cq

    parts = _load(code, model_dir)
    if names:
        parts = [_part(parts, n) for n in names]
    if fmt not in FORMATS:
        raise ModelError("format must be one of: " + ", ".join(FORMATS))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    if fmt in ("step", "glb"):                  # these formats keep part names and colours
        assy = cq.Assembly()
        for p in parts:
            assy.add(p["shape"], name=p["name"], color=cq.Color(*p["color"]) if p["color"] else None)
        assy.export(path)
    else:
        shape = parts[0]["shape"] if len(parts) == 1 else cq.Compound.makeCompound([p["shape"] for p in parts])
        if fmt == "svg":
            cq.exporters.export(cq.Workplane("XY").newObject([shape]), path, opt={"showAxes": False, "projectionDir": (1, -1, 0.8)})
        else:
            cq.exporters.export(shape, path, tolerance=0.01, angularTolerance=0.1)
    return {"path": path, "bytes": os.path.getsize(path), "parts": [p["name"] for p in parts]}


# ---------------------------------------------------------------- request loop

OPS = {"run": op_run, "inspect": op_inspect, "measure": op_measure, "mesh": op_mesh, "render": op_render, "export": op_export,
       "build_steps": op_build_steps, "step_mesh": op_step_mesh}


def serve(conn) -> None:
    """Answer requests from the parent until the pipe closes."""
    import cadquery  # noqa: F401 - pay the import cost once, before the first request

    conn.send({"ready": True})
    while True:
        try:
            op, kwargs = conn.recv()
        except (EOFError, KeyboardInterrupt):
            return
        try:
            conn.send({"ok": OPS[op](**kwargs)})
        except ModelError as exc:
            conn.send({"problem": str(exc)})
        except BaseException as exc:  # noqa: BLE001
            conn.send({"problem": f"{type(exc).__name__}: {exc}"})
