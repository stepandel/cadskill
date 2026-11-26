"""Models on disk. One folder per model:

    <root>/<model>/current.py          the script the model is built from
    <root>/<model>/versions/0001.py    every script that ran successfully, in order
    <root>/<model>/versions.json       one line of metadata per version
    <root>/<model>/assets/             files imported for the script to load
    <root>/<model>/exports/            files written by the export tool

The folder is plain files on purpose: a person can read, copy or version it.
"""
from __future__ import annotations

import json
import os
import re
import shutil
import time
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Documents" / "CAD Bench"


def root() -> Path:
    return Path(os.environ.get("CADBENCH_HOME") or DEFAULT_ROOT).expanduser()


def clean(model: str | None) -> str:
    name = re.sub(r"[^a-z0-9_-]+", "-", (model or "default").strip().lower()).strip("-")
    return name or "default"


class Store:
    def __init__(self, base: Path | None = None) -> None:
        self.base = Path(base) if base else root()

    def dir(self, model: str) -> Path:
        return self.base / clean(model)

    def models(self) -> list[dict]:
        if not self.base.exists():
            return []
        out = []
        for d in sorted(self.base.iterdir()):
            if (d / "current.py").exists():
                versions = self.versions(d.name)
                out.append({"model": d.name, "versions": len(versions), "last": versions[-1] if versions else None})
        return out

    def current(self, model: str) -> str | None:
        path = self.dir(model) / "current.py"
        return path.read_text() if path.exists() else None

    def versions(self, model: str) -> list[dict]:
        path = self.dir(model) / "versions.json"
        return json.loads(path.read_text()) if path.exists() else []

    def version(self, model: str) -> int:
        """Number of the version current.py corresponds to (0 when there is none)."""
        versions = self.versions(model)
        return versions[-1]["version"] if versions else 0

    def code(self, model: str, n: int) -> str:
        path = self.dir(model) / "versions" / f"{n:04d}.py"
        if not path.exists():
            raise KeyError(n)
        return path.read_text()

    def save(self, model: str, code: str, summary: str, note: str | None = None) -> int:
        """Record a script that ran successfully as the next version and make it current."""
        d = self.dir(model)
        (d / "versions").mkdir(parents=True, exist_ok=True)
        versions = self.versions(model)
        n = (versions[-1]["version"] + 1) if versions else 1
        (d / "versions" / f"{n:04d}.py").write_text(code)
        (d / "current.py").write_text(code)
        entry = {"version": n, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": summary}
        if note:
            entry["note"] = note
        versions.append(entry)
        (d / "versions.json").write_text(json.dumps(versions, indent=1))
        return n

    def add_asset(self, model: str, source: str) -> str:
        src = Path(source).expanduser()
        if not src.is_file():
            raise FileNotFoundError(source)
        dest = self.dir(model) / "assets"
        dest.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, dest / src.name)
        return src.name

    def export_path(self, model: str, filename: str) -> str:
        return str(self.dir(model) / "exports" / filename)
