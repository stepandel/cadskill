"""Owns the worker process: starts it, sends it one request at a time, and
replaces it when a script hangs or takes the kernel down."""
from __future__ import annotations

import multiprocessing as mp
import os
import threading

START_TIMEOUT = 300      # the first CadQuery import on a machine can take over a minute
DEFAULT_TIMEOUT = 60


class Problem(Exception):
    """Something to tell the caller in plain words: a bad request, a timeout, a crash."""


def _child(conn) -> None:
    os.dup2(2, 1)        # the server speaks MCP on stdout; nothing in the worker may write there
    from . import worker

    worker.serve(conn)


class Runner:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._proc: mp.Process | None = None
        self._conn = None

    def _start(self) -> None:
        ctx = mp.get_context("spawn")
        parent, child = ctx.Pipe()
        self._proc = ctx.Process(target=_child, args=(child,), daemon=True)
        self._proc.start()
        child.close()
        self._conn = parent
        if not parent.poll(START_TIMEOUT):
            self.stop()
            raise Problem("The CAD kernel did not start. Check that CadQuery is installed for this server.")
        try:
            parent.recv()
        except EOFError:
            self.stop()
            raise Problem("The CAD kernel exited while starting.") from None

    def stop(self) -> None:
        if self._proc is not None:
            if self._proc.is_alive():
                self._proc.terminate()
                self._proc.join(2)
                if self._proc.is_alive():
                    self._proc.kill()
            self._proc = None
        if self._conn is not None:
            self._conn.close()
            self._conn = None

    def call(self, op: str, timeout: float = DEFAULT_TIMEOUT, **kwargs):
        """Run one worker operation. Raises Problem with a message meant for the caller."""
        with self._lock:
            if self._proc is None or not self._proc.is_alive():
                self.stop()
                self._start()
            try:
                self._conn.send((op, kwargs))
                if not self._conn.poll(timeout):
                    self.stop()
                    raise Problem(f"Stopped after {timeout:g} seconds without finishing. The kernel was restarted; "
                                  "the model is unchanged. Look for an endless loop or a very heavy operation.")
                reply = self._conn.recv()
            except (EOFError, BrokenPipeError, ConnectionResetError):
                self.stop()
                raise Problem("The CAD kernel crashed on this request and was restarted; the model is unchanged.") from None
        if "problem" in reply:
            raise Problem(reply["problem"])
        return reply["ok"]
