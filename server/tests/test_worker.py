"""The geometry side, against the real kernel, through the real worker process."""
import math
import struct

import pytest

from cadbench_mcp.runner import Problem, Runner, Starting


def run(runner, code, tmp_path, **kw):
    return runner.call("run", code=code, model_dir=str(tmp_path), **kw)


def test_plate_numbers(runner, plate, tmp_path):
    out = run(runner, plate, tmp_path)
    (p,) = out["parts"]
    expected = (40 * 24 - (4 - math.pi) * 4**2 - math.pi * 4**2) * 6     # 5376
    assert p["name"] == "plate"
    assert p["volume"] == pytest.approx(expected, rel=1e-6)
    assert p["size"] == [40, 24, 6]
    assert p["valid"] and p["solids"] == 1


def test_result_variable_and_print(runner, tmp_path):
    out = run(runner, 'print("hello")\nresult = cq.Workplane().box(1, 2, 3)', tmp_path)
    assert out["parts"][0]["volume"] == 6
    assert "hello" in out["stdout"]


def test_assembly_parts_are_placed(runner, tmp_path):
    code = '''
a = cq.Assembly()
a.add(cq.Workplane().box(10, 10, 10), name="base", color=cq.Color("blue"))
a.add(cq.Workplane().box(2, 2, 2), name="lid", loc=cq.Location((0, 0, 20)))
show_object(a)
'''
    base, lid = run(runner, code, tmp_path)["parts"]
    assert (base["name"], lid["name"]) == ("base", "lid")
    assert lid["center_of_mass"] == [0, 0, 20]
    assert base["color"][2] > 0.5


def test_errors_name_the_line(runner, tmp_path):
    syntax = run(runner, "x = 1\ny = (\n", tmp_path)["error"]
    assert syntax["type"] == "SyntaxError" and syntax["line"] in (2, 3)
    kernel = run(runner, "b = cq.Workplane().box(10, 10, 10)\nb = b.edges().fillet(50)\nshow_object(b)", tmp_path)["error"]
    assert kernel["line"] == 2 and "fillet" in kernel["source"]
    nothing = run(runner, "x = 1", tmp_path)["error"]
    assert "showed nothing" in nothing["message"]


def test_timeout_restarts_the_kernel(runner, plate, tmp_path):
    with pytest.raises(Problem, match="Stopped after"):
        run(runner, "while True: pass", tmp_path, timeout=2)
    assert run(runner, plate, tmp_path)["parts"][0]["size"] == [40, 24, 6]


def test_inspect_and_selectors(runner, plate, tmp_path):
    ask = lambda **sel: runner.call("inspect", code=plate, model_dir=str(tmp_path), sel=sel)
    top = ask(kind="faces", selector=">Z")
    assert top["matched"] == 1 and top["rows"][0]["normal"] == [0, 0, 1]
    bore = [r for r in ask(kind="faces")["rows"] if r["type"] == "CYLINDER" and r["radius"] == 4 and r["center"][:2] == [0, 0]]
    assert len(bore) == 1
    assert ask(kind="edges", selector="|Z")["matched"] >= 4
    with pytest.raises(Problem, match="not valid"):
        ask(kind="faces", selector="nonsense!!")
    with pytest.raises(Problem, match="No part named"):
        ask(part="missing")


def test_measure(runner, two, tmp_path):
    m = lambda a, b: runner.call("measure", code=two, model_dir=str(tmp_path), a=a, b=b)
    assert m({"part": "plate"}, {"part": "post"})["distance"] == pytest.approx(5, abs=1e-3)   # 30 - 20 - 5
    faces = m({"part": "plate", "kind": "faces", "selector": ">Z"}, {"part": "plate", "kind": "faces", "selector": "<Z"})
    assert faces["distance"] == 6 and faces["angle_degrees"] == 180


def png_size(data):
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    return struct.unpack(">II", data[16:24])


def test_render(runner, two, tmp_path):
    shot = lambda **spec: runner.call("render", code=two, model_dir=str(tmp_path), spec=spec)
    four = shot()
    assert four["views"] == ["iso", "top", "front", "right"] and png_size(four["png"]) == (1000, 760)
    top, front = shot(view="top", width=400, height=300), shot(view="front", width=400, height=300)
    assert png_size(top["png"]) == (400, 300) and top["png"] != front["png"]
    cut = shot(view="front", width=400, height=300, section={"origin": [0, 0, 0], "normal": [0, -1, 0]})
    assert cut["png"] != front["png"]
    lit = shot(view="iso", width=400, height=300, highlight={"part": "plate", "kind": "faces", "selector": ">Z"})
    assert lit["png"] != shot(view="iso", width=400, height=300)["png"]
    with pytest.raises(Problem, match="view must be"):
        shot(view="sideways")


def test_mesh(runner, two, tmp_path):
    import base64

    parts = runner.call("mesh", code=two, model_dir=str(tmp_path))["parts"]
    assert [p["name"] for p in parts] == ["plate", "post"] and parts[1]["color"][0] == 1
    p = parts[0]
    assert len(base64.b64decode(p["indices"])) == p["triangles"] * 12
    assert len(base64.b64decode(p["positions"])) == len(base64.b64decode(p["normals"]))


def test_export_step_round_trip(runner, two, tmp_path):
    out = runner.call("export", code=two, model_dir=str(tmp_path), fmt="step", path=str(tmp_path / "exports" / "m.step"), names=None)
    assert out["bytes"] > 1000 and out["parts"] == ["plate", "post"]
    back = run(runner, f'show_object(cq.importers.importStep(r"{out["path"]}"))', tmp_path)
    assert sum(p["volume"] for p in back["parts"]) == pytest.approx(5376 + math.pi * 25 * 20, rel=1e-4)
    for fmt in ("stl", "3mf", "brep", "glb", "svg"):
        made = runner.call("export", code=two, model_dir=str(tmp_path), fmt=fmt, path=str(tmp_path / "exports" / f"m.{fmt}"), names=["plate"])
        assert made["bytes"] > 100, fmt


def test_a_call_during_startup_says_so_instead_of_hanging(plate, tmp_path):
    r = Runner(start_wait=0.05)
    try:
        r.warm()
        with pytest.raises(Starting, match="still starting"):
            r.call("run", code=plate, model_dir=str(tmp_path))
        assert r._ready.wait(300)                       # the background start carries on regardless
        assert r.call("run", code=plate, model_dir=str(tmp_path))["parts"][0]["size"] == [40, 24, 6]
    finally:
        r.stop()
