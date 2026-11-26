"""The tools, called the way Claude calls them: through an MCP client session."""
import json
import urllib.request

import pytest
from mcp.shared.memory import create_connected_server_and_client_session as connect

from cadbench_mcp import server
from cadbench_mcp.store import Store


@pytest.fixture
def anyio_backend():
    return "asyncio"


@pytest.fixture(autouse=True)
def fresh(tmp_path, runner, monkeypatch):
    monkeypatch.setattr(server, "store", Store(tmp_path / "models"))
    monkeypatch.setattr(server, "runner", runner)
    server._shown.update(model=None, version=0)
    server._mesh_cache.clear()


def text(result):
    return "\n".join(c.text for c in result.content if c.type == "text")


@pytest.mark.anyio
async def test_build_edit_undo(plate):
    async with connect(server.mcp._mcp_server) as client:
        tools = {t.name: t for t in (await client.list_tools()).tools}
        assert {"run_model", "edit_model", "get_model", "render", "inspect", "measure", "export", "import_file",
                "list_versions", "restore_version", "list_models", "open_viewer", "get_mesh", "get_history"} <= set(tools)
        assert tools["run_model"].meta == {"ui": {"resourceUri": server.VIEWER_URI}}
        assert tools["get_mesh"].meta == {"ui": {"visibility": ["app"]}}     # hosts hide this one from the model
        assert tools["get_history"].meta == {"ui": {"visibility": ["app"]}}

        built = await client.call_tool("run_model", {"code": plate, "note": "first"})
        assert not built.isError and "version 1" in text(built) and "volume 5376 mm³" in text(built)
        assert [c.type for c in built.content] == ["text", "image"]
        assert built.structuredContent == {"model": "default", "version": 1}

        longer = await client.call_tool("edit_model", {"old": "LENGTH, WIDTH, THICKNESS = 40", "new": "LENGTH, WIDTH, THICKNESS = 60"})
        assert "version 2" in text(longer) and "60 × 24 × 6 mm" in text(longer)

        broken = await client.call_tool("edit_model", {"old": "fillet(CORNER)", "new": "fillet(500)"})
        assert broken.isError and "line 5" in text(broken) and "still version 2" in text(broken)
        missing = await client.call_tool("edit_model", {"old": "not in the script", "new": "x"})
        assert missing.isError and "not in the current script" in text(missing)

        current = text(await client.call_tool("get_model", {}))
        assert "version 2" in current and "THICKNESS = 60" in current and "fillet(CORNER)" in current

        back = await client.call_tool("restore_version", {"version": 1})
        assert "version 3" in text(back) and "40 × 24 × 6 mm" in text(back)
        history = text(await client.call_tool("list_versions", {}))
        assert history.count("\n") == 2 and "first" in history and "restored version 1" in history
        assert "default: 3 versions" in text(await client.call_tool("list_models", {}))
        assert (await client.call_tool("restore_version", {"version": 9})).isError


@pytest.mark.anyio
async def test_check_and_export(two, tmp_path):
    async with connect(server.mcp._mcp_server) as client:
        assert (await client.call_tool("inspect", {})).isError                # no model yet
        await client.call_tool("run_model", {"code": two, "model": "Two Parts"})
        m = {"model": "two-parts"}

        faces = text(await client.call_tool("inspect", {**m, "part": "plate", "selector": ">Z"}))
        assert faces.startswith("plate: 1 faces match '>Z'") and '"normal": [0.0, 0.0, 1.0]' in faces
        assert "name one of: plate, post" in text(await client.call_tool("inspect", m))

        gap = text(await client.call_tool("measure", {**m, "a": {"part": "plate"}, "b": {"part": "post"}}))
        assert gap.startswith("Distance 5 mm")

        shot = await client.call_tool("render", {**m, "view": "top", "width": 300, "height": 240,
                                                 "highlight": {"part": "plate", "kind": "faces", "selector": ">Z"},
                                                 "section_normal": [0, -1, 0]})
        assert [c.type for c in shot.content] == ["text", "image"] and shot.content[1].mimeType == "image/png"

        made = text(await client.call_tool("export", {**m, "format": "step"}))
        assert "two-parts-v1.step" in made and "plate, post" in made
        elsewhere = text(await client.call_tool("export", {**m, "format": "stl", "parts": ["post"], "path": str(tmp_path / "post.stl")}))
        assert (tmp_path / "post.stl").stat().st_size > 100 and "post." in elsewhere

        step = made.split(" (")[0].removeprefix("Wrote ")
        assert "bracket" not in text(await client.call_tool("import_file", {"path": step, "model": "copy"}))
        again = await client.call_tool("run_model", {"model": "copy", "code": 'show_object(cq.importers.importStep(asset("two-parts-v1.step")))'})
        assert not again.isError and "version 1" in text(again)
        assert (await client.call_tool("import_file", {"path": "/no/such/file.step"})).isError


@pytest.mark.anyio
async def test_viewer_gets_meshes(two):
    async with connect(server.mcp._mcp_server) as client:
        await client.call_tool("run_model", {"code": two, "note": "first"})
        history = json.loads(text(await client.call_tool("get_history", {"model": "default"})))
        assert [(v["version"], v.get("note")) for v in history["versions"]] == [(1, "first")]
        mesh = json.loads(text(await client.call_tool("get_mesh", {"model": "default", "version": 1})))
        assert [p["name"] for p in mesh["parts"]] == ["plate", "post"] and mesh["parts"][0]["triangles"] > 0

        page = await client.read_resource(server.VIEWER_URI)
        assert page.contents[0].mimeType == "text/html;profile=mcp-app" and "<" in page.contents[0].text

        address = text(await client.call_tool("open_viewer", {})).split(" at ")[1].split(" ")[0]
        get = lambda path: urllib.request.urlopen(address + path, timeout=30).read()
        assert json.loads(get("state")) == {"model": "default", "version": 1}
        assert json.loads(get("mesh?model=default&version=1"))["parts"][1]["name"] == "post"
        assert json.loads(get("history?model=default"))["versions"][0]["version"] == 1
        assert b"<" in get("")
