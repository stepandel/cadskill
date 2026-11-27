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


@pytest.mark.parametrize("no_open", [True, False])
def test_view_uses_live_model_url(monkeypatch, capsys, no_open):
    requests, opened = [], []
    url = "http://127.0.0.1:8791/?model=wall-bracket"

    def call(tool, args):
        requests.append((tool, args))
        return {"error": False, "text": f"The live viewer is at {url}", "data": {"url": url}}

    monkeypatch.setattr(cli, "call", call)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    assert cli.main(["view", "parts/Wall Bracket.py", *(["--no-open"] if no_open else [])]) == 0
    assert requests == [("open_viewer", {"model": "wall-bracket"})]
    assert opened == ([] if no_open else [url])
    assert url in capsys.readouterr().out


def test_view_does_not_open_browser_on_error(monkeypatch):
    opened = []
    monkeypatch.setattr(cli, "call", lambda *args: {"error": True, "text": "No such model."})
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    assert cli.main(["view", "missing"]) == 1
    assert not opened


def test_replay_uses_saved_revision_without_opening_browser(monkeypatch, capsys):
    requests, opened = [], []
    def call(tool, args):
        requests.append((tool, args))
        return {"error": False, "text": "Replay is ready", "data": {"url": "http://127.0.0.1:8000/"}}
    monkeypatch.setattr(cli, "call", call)
    monkeypatch.setattr(cli.webbrowser, "open", opened.append)
    assert cli.main(["replay", "Bracket.py", "--version", "2", "--no-open"]) == 0
    assert requests == [("open_build_steps", {"model": "bracket", "version": 2})]
    assert not opened


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


@pytest.mark.parametrize("project", [False, True])
def test_codex_install_and_uninstall(tmp_path, monkeypatch, capsys, project):
    home, workspace = tmp_path / "home", tmp_path / "project"
    home.mkdir()
    workspace.mkdir()
    monkeypatch.setattr(cli.Path, "home", lambda: home)
    monkeypatch.chdir(workspace)
    monkeypatch.setenv("CLAUDE_CONFIG_DIR", str(tmp_path / "claude"))
    scope = ["--project"] if project else []
    base = workspace if project else home

    # Keep an existing Claude skill and desktop registration while using Codex.
    claude_skill = cli._skill_target(project, "claude") / "SKILL.md"
    claude_skill.parent.mkdir(parents=True)
    claude_skill.write_text("existing Claude skill")
    desktop = cli._desktop_config()
    desktop.parent.mkdir(parents=True, exist_ok=True)
    desktop.write_text('{"mcpServers": {"cadskill": {"command": "existing"}}}')
    before_desktop = desktop.read_text()

    assert cli.main(["install", "--agent", "codex", *scope]) == 0
    skill = base / ".agents" / "skills" / "cadskill" / "SKILL.md"
    assert skill.read_text() == (cli.SKILL_SOURCE / "SKILL.md").read_text()
    assert not ((home if project else workspace) / ".agents").exists()
    assert not (base / ".agents" / "settings.json").exists()
    assert "Start a new Codex session" in capsys.readouterr().out

    # Reinstall replaces the old copy and removes obsolete skill resources.
    (skill.parent / "obsolete.txt").write_text("old resource")
    assert cli.main(["install", "--agent", "codex", *scope]) == 0
    assert not (skill.parent / "obsolete.txt").exists()
    assert cli.main(["uninstall", "--agent", "codex", *scope]) == 0
    assert not skill.parent.exists()
    assert claude_skill.read_text() == "existing Claude skill"
    assert desktop.read_text() == before_desktop


@pytest.mark.parametrize("option", ["--allow", "--desktop"])
def test_codex_rejects_claude_options_before_writing(tmp_path, monkeypatch, capsys, option):
    monkeypatch.chdir(tmp_path)
    assert cli.main(["install", "--agent", "codex", "--project", option]) == 1
    assert "apply to Claude only" in capsys.readouterr().err
    assert not (tmp_path / ".agents").exists()
    assert not (tmp_path / ".claude").exists()


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
