"""Owns the worker process: starts it, sends it one request at a time, and
replaces it when a script hangs or takes the kernel down.

Starting the worker means importing CadQuery, which is slow the first time on
a computer (macOS checks each large native library on first load: about a
minute and a half) and a few seconds after that. So the worker is started in
the background, as early as possible, and a request that arrives before it is
ready waits only briefly before answering "still starting" instead of hanging.
"""
from __future__ import annotations

import multiprocessing as mp
import os
import threading
import time

START_TIMEOUT = 600      # give up on a kernel that has not started after this long
DEFAULT_TIMEOUT = 60


class Problem(Exception):
    """Something to tell the caller in plain words: a bad request, a timeout, a crash."""


class Starting(Problem):
    """The kernel is not ready yet. Nothing is wrong; the caller should try again shortly."""


def _child(conn) -> None:
    os.dup2(2, 1)        # the server speaks MCP on stdout; nothing in the worker may write there
    from . import worker

    worker.serve(conn)


class Runner:
    def __init__(self, start_wait: float = START_TIMEOUT) -> None:
        """start_wait: how long a request waits for a kernel that is still starting."""
        self.start_wait = start_wait
        self._state = threading.Lock()      # guards the fields below
        self._busy = threading.Lock()       # one request at a time on the pipe
        self._proc: mp.Process | None = None
        self._conn = None
        self._ready = threading.Event()
        self._booting = False
        self._boot_started = 0.0
        self._boot_error: str | None = None

    def warm(self) -> None:
        """Start the kernel in the background if it is not running or already starting."""
        with self._state:
            if self._booting or (self._proc is not None and self._proc.is_alive() and self._ready.is_set()):
                return
            self._discard()
            self._booting, self._boot_started, self._boot_error = True, time.monotonic(), None
            ctx = mp.get_context("spawn")
            parent, child = ctx.Pipe()
            proc = ctx.Process(target=_child, args=(child,), daemon=True)
            proc.start()
            child.close()
            self._proc, self._conn = proc, parent
        threading.Thread(target=self._await_ready, args=(proc, parent), daemon=True).start()

    def _await_ready(self, proc, conn) -> None:
        error = None
        try:
            if conn.poll(START_TIMEOUT):
                conn.recv()
            else:
                error = "The CAD kernel did not start. Check that CadQuery is installed for this server."
        except (EOFError, OSError):
            error = "The CAD kernel exited while starting. Check that CadQuery is installed for this server."
        with self._state:
            if self._proc is not proc:       # replaced or stopped while starting
                return
            self._booting = False
            if error:
                self._boot_error = error
                self._discard()
            else:
                self._ready.set()

    def _discard(self) -> None:
        """Drop the current process. Caller holds _state."""
        self._ready.clear()
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

    def stop(self) -> None:
        with self._state:
            self._booting = False
            self._discard()

    def call(self, op: str, timeout: float = DEFAULT_TIMEOUT, **kwargs):
        """Run one worker operation. Raises Problem with a message meant for the caller."""
        self.warm()
        if not self._ready.wait(self.start_wait):
            with self._state:
                error, self._boot_error = self._boot_error, None
                waited = int(time.monotonic() - self._boot_started)
            if error:
                raise Problem(error)
            raise Starting(
                f"The CAD kernel is still starting ({waited} s so far). The first start on a computer takes one to "
                "two minutes while the system checks the CAD libraries; later starts take a few seconds. "
                "Nothing is wrong and nothing was changed. Try the same call again in about 20 seconds.")
        with self._busy:
            with self._state:
                conn = self._conn
            if conn is None:                 # stopped between the wait and here
                raise Starting("The CAD kernel is restarting. Try the same call again in a few seconds.")
            try:
                conn.send((op, kwargs))
                if not conn.poll(timeout):
                    self._restart()
                    raise Problem(f"Stopped after {timeout:g} seconds without finishing. The kernel was restarted; "
                                  "the model is unchanged. Look for an endless loop or a very heavy operation.")
                reply = conn.recv()
            except (EOFError, OSError):
                self._restart()
                raise Problem("The CAD kernel crashed on this request and was restarted; the model is unchanged.") from None
        if "problem" in reply:
            raise Problem(reply["problem"])
        return reply["ok"]

    def _restart(self) -> None:
        self.stop()
        self.warm()                          # be ready again by the time the caller has read the error
