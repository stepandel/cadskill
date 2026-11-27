"""Upstream recording, with step geometry delivered to the ordinary viewer."""
import base64
import json
import struct
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from cadskill_mcp import replay, server
from cadskill_mcp.runner import Problem, Runner
from cadskill_mcp.store import Store


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="module")
def recorder():
    if not replay.available():
        pytest.skip("optional Replay dependency is not installed")
    worker = Runner()
    yield worker
    worker.stop()


def test_missing_replay_is_actionable(tmp_path, monkeypatch):
    store = Store(tmp_path / "models")
    store.save("part", "result = cq.Workplane().box(1, 2, 3)", "part")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(replay, "available", lambda: False)
    reply = server.open_build_steps("part", 1)
    assert reply.isError and "cadskill[replay]" in reply.content[0].text
    assert store.version("part") == 1


def test_build_steps_link_selects_saved_revision(tmp_path, monkeypatch):
    store = Store(tmp_path / "models")
    store.save("part", "first", "part")
    store.save("part", "second", "part")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "require_replay", lambda: None)
    reply = server.open_build_steps("part", 1)
    assert not reply.isError and reply.structuredContent["version"] == 1
    url = urlsplit(reply.structuredContent["url"])
    assert url.path == "/"
    assert parse_qs(url.query) == {"model": ["part"], "version": ["1"], "view": ["steps"]}
    assert server.open_build_steps("part", 99).isError
    assert store.version("part") == 2


def test_upstream_operations_and_intermediate_solids(recorder, plate, tmp_path):
    args = {"code": plate, "model_dir": str(tmp_path)}
    data = recorder.call("build_steps", **args)
    assert not data["partial"]
    steps = data["chains"][0]["steps"]
    before_hole = next(s["index"] for s in steps if s["label"].startswith("fillet("))
    assert any(s["label"].startswith("hole(") for s in steps)
    before = recorder.call("step_mesh", **args, chain=0, step=before_hole)["parts"][0]
    after = recorder.call("step_mesh", **args, chain=0, step=steps[-1]["index"])["parts"][0]
    assert before["volume"] > after["volume"] == 5376
    assert after["kind"] == "surface" and after["triangles"] > 0
    assert recorder.call("run", **args)["parts"][0]["volume"] == 5376


def test_points_curves_and_faces_use_the_mesh_protocol(recorder, tmp_path):
    code = "part = cq.Workplane().moveTo(0, 0).lineTo(10, 0).lineTo(10, 10).close().extrude(3)\nshow_object(part)"
    args = {"code": code, "model_dir": str(tmp_path)}
    steps = recorder.call("build_steps", **args)["chains"][0]["steps"]
    for operation, kind in (("moveTo(", "point"), ("lineTo(", "curve"), ("extrude(", "surface")):
        index = next(s["index"] for s in steps if s["label"].startswith(operation))
        part = recorder.call("step_mesh", **args, chain=0, step=index)["parts"][0]
        assert part["kind"] == kind and base64.b64decode(part["positions"])
    assert part["volume"] == 150


def test_assembly_steps_keep_world_placement(recorder, tmp_path):
    code = "part = cq.Workplane().box(2, 3, 4)\na = cq.Assembly()\na.add(part, name='lid', loc=cq.Location((40, 0, 0)))\nshow_object(a)"
    args = {"code": code, "model_dir": str(tmp_path)}
    chain = recorder.call("build_steps", **args)["chains"][0]
    mesh = recorder.call("step_mesh", **args, chain=0, step=chain["steps"][-1]["index"])["parts"][0]
    encoded = base64.b64decode(mesh["positions"])
    x = struct.unpack(f"{len(encoded) // 4}f", encoded)[::3]
    assert min(x) == 39 and max(x) == 41


def test_partial_history_and_failed_recording_do_not_change_normal_builds(recorder, tmp_path):
    args = {"model_dir": str(tmp_path)}
    partial = "outline = cq.Workplane().box(5, 4, 3)\nresult = outline.val().cut(cq.Solid.makeCylinder(1, 10))\nshow_object(result)"
    data = recorder.call("build_steps", code=partial, **args)
    assert data["partial"] and data["chains"][0]["name"] == "outline"
    assert recorder.call("build_steps", code="show_object(cq.Solid.makeBox(2, 3, 4))", **args)["chains"] == []
    with pytest.raises(Problem, match="Cannot record"):
        recorder.call("build_steps", code="raise ValueError('broken')", **args)
    sketch = "part = cq.Workplane().sketch().rect(10, 8).finalize().extrude(2)\nshow_object(part)"
    data = recorder.call("build_steps", code=sketch, **args)
    assert data["chains"][0]["steps"]
    assert recorder.call("run", code=sketch, **args)["parts"][0]["volume"] == 160


@pytest.mark.anyio
async def test_step_api_uses_existing_viewer_without_saving(recorder, runner, tmp_path, plate, monkeypatch):
    store = Store(tmp_path / "models")
    store.save("part", plate, "plate")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "runner", runner)
    monkeypatch.setattr(server, "replay_runner", recorder)
    async with connect(server.mcp._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert tools["get_build_steps"].meta == server.APP_ONLY
        assert tools["get_step_mesh"].meta == server.APP_ONLY
        result = await client.call_tool("get_build_steps", {"model": "part", "version": 1})
        data = json.loads(result.content[0].text)
        assert not result.isError and data["chains"]
        index = data["chains"][0]["steps"][-1]["index"]
        mesh = await client.call_tool("get_step_mesh", {"model": "part", "version": 1, "chain": 0, "step": index})
        assert json.loads(mesh.content[0].text)["parts"][0]["volume"] == 5376
        assert (await client.call_tool("get_step_mesh", {"model": "part", "version": 1, "chain": -1, "step": 0})).isError
        base = server.start_viewer_page()
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(base + "build-steps?model=part&version=1", timeout=30) as response:
            assert json.load(response)["chains"]
        with opener.open(base + f"step-mesh?model=part&version=1&chain=0&step={index}", timeout=30) as response:
            assert json.load(response)["parts"][0]["triangles"] > 0
    assert store.version("part") == 1
