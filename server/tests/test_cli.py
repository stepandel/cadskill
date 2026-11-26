"""The `cadskill` command: its arguments, the daemon's tool calls, the page export and the skill install."""
import argparse
import json

import pytest

from cadskill_mcp import cli, daemon, server
from cadskill_mcp.store import Store


@pytest.fixture(autouse=True)
def fresh(tmp_path, runner, monkeypatch):
    monkeypatch.setattr(server, "store", Store(tmp_path / "models"))
    monkeypatch.setattr(server, "runner", runner)
    server._shown.update(model=None, version=0)
    server._mesh_cache.clear()
    monkeypatch.setattr(cli, "_desktop_config", lambda: tmp_path / "Claude" / "claude_desktop_config.json")   # never the real one


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
    start = page.index("window.CADSKILL_MODEL = ") + len("window.CADSKILL_MODEL = ")
    data = json.loads(page[start:page.index(";</script>", start)].replace("<\\/", "</"))
    assert data["model"] == "plate" and data["version"] == 1 and data["parts"][0]["name"] == "plate"
    assert page.index("window.CADSKILL_MODEL") < page.index(server.MODULE_TAG)       # set before the viewer starts


def test_install_and_uninstall(tmp_path, monkeypatch, capsys):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    settings = tmp_path / "claude" / "settings.json"
    assert cli.main(["install"]) == 0
    skill = tmp_path / "claude" / "skills" / "cadskill" / "SKILL.md"
    assert skill.read_text().startswith("---\nname: cadskill\n") and not settings.exists()

    settings.write_text('{"permissions": {"allow": ["Bash(ls:*)"]}, "model": "x"}')
    assert cli.main(["install", "--allow"]) == 0 and cli.main(["install", "--allow"]) == 0
    assert json.loads(settings.read_text()) == {"permissions": {"allow": ["Bash(ls:*)", "Bash(cadskill:*)"]}, "model": "x"}

    assert cli.main(["uninstall"]) == 0 and not skill.exists()


def test_desktop_registration(tmp_path, monkeypatch):
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    config = cli._desktop_config()
    program = tmp_path / "bin" / "cadskill-mcp"
    program.parent.mkdir()
    program.write_text("")
    monkeypatch.setattr(cli.shutil, "which", lambda name: str(program) if name == "cadskill-mcp" else None)
    config.parent.mkdir()
    config.write_text('{"mcpServers": {"other": {"command": "x"}}, "preferences": {"a": 1}}')

    assert cli.main(["install", "--desktop"]) == 0
    assert json.loads(config.read_text()) == {
        "mcpServers": {"other": {"command": "x"}, "cadskill": {"command": str(program), "args": []}},
        "preferences": {"a": 1}}
    assert json.loads(config.with_suffix(".json.before-cadskill").read_text())["mcpServers"] == {"other": {"command": "x"}}

    assert cli.main(["uninstall"]) == 0
    assert json.loads(config.read_text())["mcpServers"] == {"other": {"command": "x"}}


def test_models_move_from_the_old_folder(tmp_path, monkeypatch):
    from cadskill_mcp import store
    old, new = tmp_path / "CadDraft", tmp_path / "CadSkill"
    (old / "plate").mkdir(parents=True)
    (old / "plate" / "current.py").write_text("x")
    monkeypatch.delenv("CADSKILL_HOME", raising=False)
    monkeypatch.setattr(store, "LEGACY_ROOT", old)
    monkeypatch.setattr(store, "DEFAULT_ROOT", new)
    assert store.root() == new and (new / "plate" / "current.py").read_text() == "x" and not old.exists()
    old.mkdir()                                    # once the new folder exists, an old one is left alone
    assert store.root() == new and old.exists()
