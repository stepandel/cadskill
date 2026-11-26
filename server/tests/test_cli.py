"""The `caddraft` command: its arguments, the daemon's tool calls, the page export and the skill install."""
import argparse
import json

import pytest

from caddraft_mcp import cli, daemon, server
from caddraft_mcp.store import Store


@pytest.fixture(autouse=True)
def fresh(tmp_path, runner, monkeypatch):
    monkeypatch.setattr(server, "store", Store(tmp_path / "models"))
    monkeypatch.setattr(server, "runner", runner)
    server._shown.update(model=None, version=0)
    server._mesh_cache.clear()


def test_selection_spellings():
    assert cli._selection("post") == {"part": "post"}
    assert cli._selection("faces") == {"kind": "faces"}
    assert cli._selection("lid/faces:>Z") == {"part": "lid", "kind": "faces", "selector": ">Z"}
    assert cli._selection("edges:|Z and >X") == {"kind": "edges", "selector": "|Z and >X"}
    assert cli._selection("lid/edges@3,4") == {"part": "lid", "kind": "edges", "index": [3, 4]}
    assert cli._selection('{"part": "lid"}') == {"part": "lid"}
    for bad in (":>Z", "lid:>Z", "lid/sides", "edges@a"):
        with pytest.raises(argparse.ArgumentTypeError):
            cli._selection(bad)


def test_model_named_by_script():
    assert cli._model("parts/Wall Bracket.py") == "wall-bracket"
    assert cli._model("bracket") == "bracket"


def test_daemon_runs_tools(plate, tmp_path):
    built = daemon._call("run_model", {"code": plate, "model": "plate"})
    assert not built["error"] and "version 1" in built["text"] and len(built["images"]) == 1
    assert built["data"] == {"model": "plate", "version": 1}

    measured = daemon._call("measure", {"model": "plate", "a": {"kind": "faces", "selector": ">Z"},
                                        "b": {"kind": "faces", "selector": "<Z"}})
    assert "Distance 6 mm" in measured["text"]

    failed = daemon._call("run_model", {"code": "boom(", "model": "plate"})
    assert failed["error"] and not failed["starting"] and "still version 1" in failed["text"]
    assert daemon._call("render", {"model": "plate", "view": "sideways"})["error"]      # rejected by the tool's signature
    assert daemon._call("no_such_tool", {})["error"]


def test_export_page_holds_the_model(plate, tmp_path):
    daemon._call("run_model", {"code": plate, "model": "plate"})
    out = tmp_path / "page" / "plate.html"
    reply = daemon._call("export", {"model": "plate", "format": "html", "path": str(out)})
    assert not reply["error"], reply["text"]
    page = out.read_text()
    start = page.index("window.CADDRAFT_MODEL = ") + len("window.CADDRAFT_MODEL = ")
    data = json.loads(page[start:page.index(";</script>", start)].replace("<\\/", "</"))
    assert data["model"] == "plate" and data["version"] == 1 and data["parts"][0]["name"] == "plate"
    assert page.index("window.CADDRAFT_MODEL") < page.index(server.MODULE_TAG)       # set before the viewer starts


def test_install_and_uninstall(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    settings = tmp_path / "claude" / "settings.json"
    assert cli.main(["install"]) == 0
    skill = tmp_path / "claude" / "skills" / "cad-modeling" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: cad-modeling\n") and not settings.exists()

    settings.write_text('{"permissions": {"allow": ["Bash(ls:*)"]}, "model": "x"}')
    assert cli.main(["install", "--allow"]) == 0 and cli.main(["install", "--allow"]) == 0
    assert json.loads(settings.read_text()) == {"permissions": {"allow": ["Bash(ls:*)", "Bash(caddraft:*)"]}, "model": "x"}

    assert cli.main(["uninstall"]) == 0 and not skill.exists()
