"""Rebuilding revisions uses their own inputs, not today's imported files."""
import json

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from cadskill_mcp import server
from cadskill_mcp.store import Store


@pytest.fixture
def anyio_backend():
    return "asyncio"


def test_asset_collision_preserves_existing_input(tmp_path):
    store = Store(tmp_path / "models")
    source = tmp_path / "stock.step"
    source.write_bytes(b"original")
    assert store.add_asset("part", str(source)) == "stock.step"
    source.write_bytes(b"replacement")
    other = store.add_asset("part", str(source))
    assert other != "stock.step"
    assert (store.dir("part") / "assets" / "stock.step").read_bytes() == b"original"
    assert store.add_asset("part", str(source)) == other


@pytest.mark.anyio
async def test_restore_rebuilds_with_saved_imports(tmp_path, runner, monkeypatch):
    store = Store(tmp_path / "models")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "runner", runner)
    server._mesh_cache.clear()
    asset = tmp_path / "length.txt"
    asset.write_text("10")
    store.add_asset("part", str(asset))
    code = 'length = float(open(asset("length.txt")).read())\nshow_object(cq.Workplane().box(length, 4, 2))'
    async with connect(server.mcp._mcp_server) as client:
        first = await client.call_tool("run_model", {"model": "part", "code": code})
        assert not first.isError
        # Even an external change to the working inputs cannot change old geometry.
        (store.dir("part") / "assets" / "length.txt").write_text("20")
        asset.write_text("30")
        new_name = store.add_asset("part", str(asset))
        second = await client.call_tool("run_model", {"model": "part", "code": code.replace('length.txt', new_name)})
        assert not second.isError and "30 × 4 × 2" in second.content[0].text
        assert server._mesh_for("part", 1)["parts"][0]["size"] == [10.0, 4.0, 2.0]
        restored = await client.call_tool("restore_version", {"model": "part", "version": 1})
        assert not restored.isError and "10 × 4 × 2" in restored.content[0].text
        assert (store.context("part", 3) / "assets" / "length.txt").read_text() == "10"
        edited = await client.call_tool("edit_model", {"model": "part", "old": "box(length, 4, 2)", "new": "box(length, 4, 3)"})
        assert not edited.isError and "10 × 4 × 3" in edited.content[0].text

        metadata = store.context("part", 1) / "environment.json"
        saved = json.loads(metadata.read_text())
        assert "cadquery" in saved["packages"]
        saved["packages"]["cadquery"] = "0.0.0"
        metadata.write_text(json.dumps(saved))
        mismatch = await client.call_tool("restore_version", {"model": "part", "version": 1})
        assert mismatch.isError and "cadquery==0.0.0" in mismatch.content[0].text
        assert store.version("part") == 4


@pytest.mark.anyio
async def test_remove_hole_keeps_new_pin_length_and_restore(tmp_path, runner, monkeypatch):
    store = Store(tmp_path / "models")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(server, "runner", runner)
    code = '''PIN_LENGTH = 0.8
INCLUDE_HOLE = True
part = cq.Workplane().box(30, 20, 6)
if INCLUDE_HOLE:
    part = part.faces('>Z').workplane().pushPoints([(-8, 0)]).hole(4)
pin = cq.Workplane().circle(2).extrude(PIN_LENGTH).translate((8, 0, 3))
part = part.union(pin)
show_object(part)
'''
    async with connect(server.mcp._mcp_server) as client:
        assert not (await client.call_tool("run_model", {"code": code})).isError
        assert not (await client.call_tool("edit_model", {"old": "PIN_LENGTH = 0.8", "new": "PIN_LENGTH = 1.7"})).isError
        removed = await client.call_tool("edit_model", {"old": "INCLUDE_HOLE = True", "new": "INCLUDE_HOLE = False"})
        assert not removed.isError
        parts = runner.call("run", code=store.current("default"), model_dir=str(store.context("default")))["parts"]
        assert parts[0]["valid"] and parts[0]["solids"] == 1
        assert parts[0]["max"][2] == 4.7
        assert parts[0]["volume"] == pytest.approx(3600 + 3.141592653589793 * 4 * 1.7, abs=0.001)
        assert not (await client.call_tool("restore_version", {"version": 1})).isError
        restored = runner.call("run", code=store.current("default"), model_dir=str(store.context("default")))["parts"][0]
        assert restored["max"][2] == 3.8 and restored["volume"] < parts[0]["volume"]
        assert len(store.versions("default")) == 4
