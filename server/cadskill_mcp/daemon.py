"""The background process behind the `cadskill` command.

Loading CadQuery takes seconds (a minute or two the first time on a computer),
far too long to pay on every command. So the first `cadskill` command starts
this process, which keeps the kernel loaded, and every command after that is a
short request to it. It also serves the live viewer page. It stops by itself
after an hour without commands.

It runs the same tools as the MCP server (server.py), so the command line and
MCP behave identically. Requests arrive over HTTP on this computer only.
Because running a model means running Python, a request must carry a token
that is written to a file only this user can read: a web page open in the
browser can reach the port but cannot learn the token.
"""
from __future__ import annotations

import contextlib
import json
import os
import secrets
import threading
import time
from importlib.metadata import version as _installed
from pathlib import Path

import anyio
from mcp.types import CallToolResult

from . import server
from .runner import is_starting
from .store import root

IDLE_SECONDS = 3600
STATE_NAME = ".daemon.json"
LOCK_NAME = ".daemon.lock"
VERSION = _installed("cadskill")

_token = secrets.token_urlsafe(32)
_last = time.monotonic()
_stop = threading.Event()


def _call(tool: str, args: dict) -> dict:
    """Run one tool and reduce its answer to text, pictures and a flag."""
    try:
        # The tool manager checks the arguments against the tool's signature, as an MCP call would.
        result = anyio.run(server.mcp._tool_manager.call_tool, tool, args)
    except Exception as exc:  # noqa: BLE001 - whatever went wrong, the caller gets it as a message
        return {"error": True, "text": str(exc), "images": []}
    if not isinstance(result, CallToolResult):
        return {"error": False, "text": str(result), "images": []}
    failed = bool(result.isError)
    text = "\n".join(c.text for c in result.content if c.type == "text")
    return {
        "error": failed,
        "text": text,
        "images": [c.data for c in result.content if c.type == "image"],
        "data": result.structuredContent,
        "starting": failed and is_starting(text),      # not a failure: the caller should wait and repeat
    }


class _Handler(server._Page):
    """The viewer page, plus the endpoint the command line talks to."""

    def do_POST(self) -> None:  # noqa: N802 - name set by http.server
        global _last
        given = self.headers.get("authorization", "")
        if self.path != "/call" or not secrets.compare_digest(given.encode(), f"Bearer {_token}".encode()):
            self._send(403, "text/plain", b"Forbidden")
            return
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("content-length") or 0)))
            tool, args = body["tool"], body.get("args") or {}
        except (ValueError, KeyError, TypeError):
            self._send(400, "text/plain", b"Bad request")
            return
        _last = time.monotonic()
        if tool == "ping":
            reply = {"version": VERSION, "ready": server.runner.ready}
        elif tool == "stop":
            reply = {"stopping": True}
        else:
            reply = _call(tool, args)
            _last = time.monotonic()
        self._send(200, "application/json", json.dumps(reply).encode())
        if tool == "stop":
            _stop.set()


def _only_one(base: Path):
    """Hold a lock for as long as this process lives, or return None if another daemon has it."""
    try:
        import fcntl
    except ImportError:          # no file locks on this system: two daemons may briefly coexist, which is harmless
        return True
    handle = open(base / LOCK_NAME, "w")
    for _ in range(50):          # a daemon that was just told to stop needs a moment to let go
        try:
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
            return handle
        except OSError:
            time.sleep(0.2)
    return None


def main() -> None:
    base = root()
    base.mkdir(parents=True, exist_ok=True)
    lock = _only_one(base)
    if lock is None:
        return
    server.runner.warm()
    url = server.start_viewer_page(handler=_Handler)
    state = base / STATE_NAME
    fd = os.open(state, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"url": url, "token": _token, "pid": os.getpid(), "version": VERSION}, f)
    try:
        while not _stop.wait(15):
            if time.monotonic() - _last > IDLE_SECONDS:
                break
    finally:
        with contextlib.suppress(OSError, ValueError):       # leave the file alone if a newer daemon wrote it
            if json.loads(state.read_text()).get("token") == _token:
                state.unlink()
        server.runner.stop()
        server.replay_server.stop()


if __name__ == "__main__":
    main()
