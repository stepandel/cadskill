"""Replay is optional; opening it must preserve the saved model."""
import json
import re
import urllib.request
from urllib.parse import parse_qs, urlsplit

import pytest

from cadskill_mcp import replay, server
from cadskill_mcp.store import Store


def test_missing_replay_is_actionable(tmp_path, monkeypatch):
    store = Store(tmp_path / "models")
    store.save("part", "result = cq.Workplane().box(1, 2, 3)", "part")
    monkeypatch.setattr(server, "store", store)
    monkeypatch.setattr(replay, "available", lambda: False)
    reply = server.open_build_steps("part", 1)
    assert reply.isError and "cadskill[replay]" in reply.content[0].text
    assert store.version("part") == 1


def test_build_steps_keeps_requested_revision(tmp_path, monkeypatch):
    store = Store(tmp_path / "models")
    store.save("part", "first", "part")
    store.save("part", "second", "part")
    monkeypatch.setattr(server, "store", store)
    requested = []
    def open_replay(store, model, revision, back):
        store.code(model, revision)
        requested.append((model, revision, back))
        return "http://127.0.0.1:8000/replay"
    monkeypatch.setattr(server.replay_server, "open", open_replay)
    reply = server.open_build_steps("part", 1)
    assert not reply.isError and reply.structuredContent["version"] == 1
    url = urlsplit(reply.structuredContent["url"])
    assert url.path == "/" and url.netloc != "127.0.0.1:8000"
    assert parse_qs(url.query) == {"model": ["part"], "version": ["1"], "view": ["steps"]}
    assert requested[0][:2] == ("part", 1) and "?model=part" in requested[0][2]
    assert server.open_build_steps("part", 99).isError
    assert store.version("part") == 2


@pytest.mark.skipif(not replay.available(), reason="optional Replay dependencies are not installed")
def test_upstream_notebook_renders_saved_geometry(tmp_path):
    store = Store(tmp_path / "models")
    store.save("part", "part = cq.Workplane().box(10, 8, 3).faces('>Z').workplane().hole(2)\nshow_object(part)", "part")
    app = replay.ReplayServer()
    try:
        url = app.open(store, "part", 1, "http://127.0.0.1:8791/?model=part")
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
        with opener.open(url, timeout=90) as response:
            page = response.read().decode()
            assert response.headers["Content-Security-Policy"] == "frame-ancestors 'self' http://127.0.0.1:8791"
        outputs = [json.loads(text) for text in re.findall(
            r'<script type="application/vnd.voila.cell-output\+json">(.*?)</script>', page, re.S)]
        assert any("Build steps" in item.get("data", {}).get("text/html", "")
                   and "v1" in item["data"]["text/html"] for item in outputs)
        assert any("application/vnd.jupyter.widget-view+json" in item.get("data", {}) for item in outputs)
        assert not any(item.get("output_type") == "error" for item in outputs)
        with opener.open(url + "&embedded=1&theme=dark", timeout=90) as response:
            embedded = response.read().decode()
        embedded_outputs = [json.loads(text) for text in re.findall(
            r'<script type="application/vnd.voila.cell-output\+json">(.*?)</script>', embedded, re.S)]
        html_outputs = " ".join(item.get("data", {}).get("text/html", "") for item in embedded_outputs)
        assert "color-scheme:dark" in html_outputs
        assert "Back to revisions" not in html_outputs
        assert not any(item.get("output_type") == "error" for item in embedded_outputs)
        assert any("application/vnd.jupyter.widget-view+json" in item.get("data", {}) for item in embedded_outputs)
        assert store.version("part") == 1
    finally:
        app.stop()
