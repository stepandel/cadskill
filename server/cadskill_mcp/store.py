"""Models on disk. One folder per model:

    <root>/<model>/current.py          the script the model is built from
    <root>/<model>/versions/0001.py    every script that ran successfully, in order
    <root>/<model>/versions/0001/      imported assets and environment for that version
    <root>/<model>/versions.json       one line of metadata per version
    <root>/<model>/assets/             files imported for the script to load
    <root>/<model>/exports/            files written by the export tool

The folder is plain files on purpose: a person can read, copy or version it.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import re
import shutil
import tempfile
import time
from contextlib import contextmanager
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path

DEFAULT_ROOT = Path.home() / "Documents" / "CadSkill"
LEGACY_ROOT = Path.home() / "Documents" / "CadDraft"      # the folder's name before the project was CadSkill


def environment() -> dict:
    """Versions of the runtime that constructs the geometry; no CAD imports needed."""
    packages = {}
    for name in ("cadquery", "cadquery-ocp"):
        try:
            packages[name] = version(name)
        except PackageNotFoundError:
            pass
    return {"python": platform.python_version(), "packages": packages}


def root() -> Path:
    if os.environ.get("CADSKILL_HOME"):
        return Path(os.environ["CADSKILL_HOME"]).expanduser()
    if not DEFAULT_ROOT.exists() and LEGACY_ROOT.is_dir():
        try:
            LEGACY_ROOT.rename(DEFAULT_ROOT)       # carry models made under the old name over, once
        except OSError:
            return LEGACY_ROOT
    return DEFAULT_ROOT


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

    def context(self, model: str, n: int | None = None) -> Path:
        """Execution directory for a saved revision. Legacy revisions use their live assets."""
        n = self.version(model) if n is None else n
        saved = self.dir(model) / "versions" / f"{n:04d}"
        return saved if (saved / "environment.json").exists() else self.dir(model)

    def check_environment(self, model: str, n: int) -> None:
        path = self.context(model, n) / "environment.json"
        if not path.exists():
            return                         # older saves did not record the runtime
        expected, actual = json.loads(path.read_text()), environment()
        differences = [f"{name}=={value}" for name, value in expected["packages"].items()
                       if actual["packages"].get(name) != value]
        if expected["python"].split(".")[:2] != actual["python"].split(".")[:2]:
            differences.append("Python " + expected["python"])
        if differences:
            raise ValueError("This revision was built with " + ", ".join(differences)
                             + ". Use those versions to rebuild it; the saved model is unchanged.")

    @contextmanager
    def build(self, model: str, source_dir: Path | None = None):
        """Freeze build inputs before execution, including newly imported files.

        Current saved inputs win name collisions with the working directory.
        import_file gives changed contents a new name, so edits after restoring
        an old revision keep using that revision's originals.
        """
        directory = self.dir(model)
        directory.mkdir(parents=True, exist_ok=True)
        with tempfile.TemporaryDirectory(prefix=".build-", dir=directory) as tmp:
            staged = Path(tmp)
            sources = [source_dir] if source_dir is not None else list(dict.fromkeys([directory, self.context(model)]))
            for source in sources:
                if (source / "assets").exists():
                    shutil.copytree(source / "assets", staged / "assets", dirs_exist_ok=True)
            (staged / "assets").mkdir(exist_ok=True)
            yield staged

    def save(self, model: str, code: str, summary: str, note: str | None = None,
             source_dir: Path | None = None) -> int:
        """Record a script that ran successfully as the next version and make it current."""
        d = self.dir(model)
        (d / "versions").mkdir(parents=True, exist_ok=True)
        versions = self.versions(model)
        n = (versions[-1]["version"] + 1) if versions else 1
        snapshot = d / "versions" / f"{n:04d}"
        assets = (source_dir or d) / "assets"
        snapshot.mkdir(parents=True, exist_ok=True)
        if assets.exists():
            shutil.copytree(assets, snapshot / "assets", dirs_exist_ok=True)
        else:
            (snapshot / "assets").mkdir(exist_ok=True)
        (snapshot / "environment.json").write_text(json.dumps(environment(), indent=2) + "\n")
        (d / "versions" / f"{n:04d}.py").write_text(code)
        (d / "current.py").write_text(code)
        entry = {"version": n, "time": time.strftime("%Y-%m-%d %H:%M:%S"), "summary": summary,
                 "inputs_saved": True}
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
        target = dest / src.name
        if target.exists():
            digest = hashlib.sha256(src.read_bytes()).hexdigest()
            if digest == hashlib.sha256(target.read_bytes()).hexdigest():
                return target.name
            target = dest / f"{src.stem}-{digest}{src.suffix}"
        shutil.copy2(src, target)
        return target.name

    def export_path(self, model: str, filename: str) -> str:
        return str(self.dir(model) / "exports" / filename)
