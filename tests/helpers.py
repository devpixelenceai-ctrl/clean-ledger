"""Shared helpers for the Clean Ledger test suite (standard library only)."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
LEDGER_PY = PLUGIN / "skills" / "clean-ledger" / "scripts" / "ledger.py"
MEASURE_SH = PLUGIN / "skills" / "clean-ledger" / "scripts" / "measure.sh"
GUARD_PY = PLUGIN / "hooks" / "guard.py"

GIT_ENV = {
    "GIT_AUTHOR_NAME": "Test", "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test", "GIT_COMMITTER_EMAIL": "test@example.com",
}


def run(cmd: list[str], cwd: Path, env: dict | None = None, stdin: str | None = None) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **GIT_ENV, **(env or {})}
    return subprocess.run(cmd, cwd=cwd, env=full_env, input=stdin, capture_output=True, text=True)


def git(repo: Path, *args: str) -> str:
    r = run(["git", *args], repo)
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} failed: {r.stderr}")
    return r.stdout.strip()


def make_repo(files: dict[str, str], branch: str = "main") -> Path:
    """Create a temporary git repo with `files` committed on `branch`."""
    repo = Path(tempfile.mkdtemp(prefix="ledger-test-"))
    git(repo, "init", "-q", "-b", branch)
    for name, content in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", "initial")
    return repo


def commit_all(repo: Path, message: str) -> None:
    git(repo, "add", "-A")
    git(repo, "commit", "-q", "-m", message)


def ledger(repo: Path, *args: str, env: dict | None = None) -> subprocess.CompletedProcess:
    """Run the repo's copy of ledger.py if it exists, else the plugin's."""
    script = repo / ".ledger" / "ledger.py"
    if not script.exists():
        script = LEDGER_PY
    return run([sys.executable, str(script), *args], repo, env)


def write_config(repo: Path, **overrides) -> None:
    cfg = {"branch": "clean-ledger", "base_branch": "main", "src_dirs": ["src"],
           "test_command": "true", "protected_paths": []}
    cfg.update(overrides)
    (repo / ".ledger").mkdir(exist_ok=True)
    (repo / ".ledger" / "config.json").write_text(json.dumps(cfg, indent=2) + "\n", encoding="utf-8")


def guard(payload: dict, env: dict | None = None, cwd: Path | None = None) -> subprocess.CompletedProcess:
    return run([sys.executable, str(GUARD_PY)], cwd or Path(payload.get("cwd", ".")), env,
               stdin=json.dumps(payload))
