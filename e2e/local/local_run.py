#!/usr/bin/env python3
"""local_run.py - run the Clean Ledger end-to-end test on this machine, without
Docker and without an API key, using the Claude Code login already here.

Safety: a fresh clone of the test project with its git remote removed; the
plugin loaded for this run only (--plugin-dir); Claude Code's Bash sandbox
(writes confined to the project folder and $TMPDIR, network limited to package
and Semgrep hosts, credential folders unreadable); permission mode dontAsk, so
anything not allowed is refused instead of prompting; user settings and MCP
servers not loaded; the Clean Ledger Guard hook active; a hard time limit.

Usage:
  python3 e2e/local/local_run.py --dry-run    # cheap probe of the sandbox and tools
  python3 e2e/local/local_run.py              # the full unattended run
Options: --max-fixes N (1), --budget USD (20), --timeout-min M (180), --runs-dir DIR
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
SETTINGS = Path(__file__).resolve().parent / "settings.json"
TEST_REPO = "https://github.com/prettytable/prettytable.git"
TEST_REF = "3.18.0"
PYTHON = "/opt/homebrew/bin/python3.12"
TOOL_DIRS = [Path.home() / ".debt-tools" / "venv" / "bin", Path.home() / ".debt-tools" / "node_modules" / ".bin"]
PROBE = Path.home() / "clean-ledger-sandbox-probe.txt"

DRY_RUN_PROMPT = f"""This is a sandbox probe. Run each command below as its own Bash call,
in order, and report one line per step: the step number, the exact exit code and the
last line of output (or the refusal message). Do not try workarounds if a step is refused.
1. lizard --version && jscpd --version && semgrep --version
2. python -m pytest -q -p no:cacheprovider | tail -1
3. semgrep scan --config p/default --metrics=off --quiet --json src | python -c "import json,sys;print(len(json.load(sys.stdin)['results']), 'findings')"
4. echo probe > {PROBE}
5. head -c 40 ~/.ssh/known_hosts
6. git status --short | wc -l
Finally, list the slash commands and subagent types you can see whose names contain "clean-ledger" or "ledger"."""


def sh(cmd: list[str], cwd: Path | None = None, env: dict | None = None, **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, **kw)


def must(cmd: list[str], cwd: Path | None = None, env: dict | None = None) -> str:
    r = sh(cmd, cwd, env)
    if r.returncode != 0:
        sys.exit(f"local_run: {' '.join(cmd)} failed:\n{r.stdout}\n{r.stderr}")
    return r.stdout.strip()


def prepare(run_dir: Path) -> Path:
    """Fresh clone at the tag on local `main`, no remote, project venv in .venv (git-ignored)."""
    project = run_dir / "project"
    must(["git", "clone", "-q", TEST_REPO, str(project)])
    must(["git", "checkout", "-q", "-B", "main", TEST_REF], project)
    must(["git", "remote", "remove", "origin"], project)
    must(["git", "config", "user.name", "Clean Ledger E2E"], project)
    must(["git", "config", "user.email", "e2e@localhost.invalid"], project)
    must([PYTHON, "-m", "venv", str(project / ".venv")])
    must([str(project / ".venv" / "bin" / "pip"), "install", "-q", "-e", f"{project}[tests]"])
    tests = sh([str(project / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"], project)
    if tests.returncode != 0:
        sys.exit("local_run: the test project's own suite fails before the run:\n" + tests.stdout[-2000:])
    if must(["git", "status", "--porcelain"], project):
        sys.exit("local_run: project working tree is not clean after setup")
    return project


def child_env(project: Path) -> dict:
    env = {k: v for k, v in os.environ.items()
           if k not in ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDECODE")
           and not k.startswith("CLAUDE_CODE_")}
    tmp = Path(tempfile.gettempdir())
    env["PATH"] = os.pathsep.join([str(project / ".venv" / "bin"), *map(str, TOOL_DIRS), env.get("PATH", "")])
    # Semgrep normally writes to ~/.semgrep, which the sandbox does not allow.
    env["SEMGREP_SETTINGS_FILE"] = str(tmp / "clean-ledger-e2e-semgrep-settings.yml")
    env["SEMGREP_LOG_FILE"] = str(tmp / "clean-ledger-e2e-semgrep.log")
    env["SEMGREP_VERSION_CACHE_PATH"] = str(tmp / "clean-ledger-e2e-semgrep-version")
    env["PIP_CACHE_DIR"] = str(tmp / "clean-ledger-e2e-pip-cache")
    return env


def run_claude(project: Path, out: Path, prompt: str, budget: float, timeout_min: int) -> int:
    cmd = ["claude", "-p", prompt,
           "--plugin-dir", str(PLUGIN),
           "--settings", str(SETTINGS),
           "--setting-sources", "project",
           "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}',
           "--permission-mode", "dontAsk",
           "--output-format", "stream-json", "--verbose",
           "--max-budget-usd", str(budget)]
    (out / "command.json").write_text(json.dumps({"cmd": cmd[:2] + ["<prompt>"] + cmd[3:], "prompt": prompt,
                                                  "cwd": str(project)}, indent=2) + "\n")
    started = dt.datetime.now(dt.timezone.utc)
    with open(out / "transcript.jsonl", "w") as so, open(out / "claude-stderr.log", "w") as se:
        proc = subprocess.Popen(cmd, cwd=project, env=child_env(project), stdout=so, stderr=se,
                                stdin=subprocess.DEVNULL, start_new_session=True)
        try:
            code = proc.wait(timeout=timeout_min * 60)
        except subprocess.TimeoutExpired:
            proc.terminate()
            try:
                proc.wait(timeout=60)
            except subprocess.TimeoutExpired:
                proc.kill()
            code = 124
    (out / "run-status.json").write_text(json.dumps({
        "started": started.isoformat(), "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
        "claude_exit": code, "timed_out": code == 124}) + "\n")
    return code


def collect(project: Path, out: Path, base: str):
    (out / "base-commit.txt").write_text(base + "\n")
    sh(["git", "bundle", "create", str(out / "result.bundle"), "--all"], project)
    for name, cmd in {"branches.txt": ["git", "branch", "-a"], "remotes.txt": ["git", "remote", "-v"],
                      "git-status.txt": ["git", "status", "--porcelain"],
                      "git-log.txt": ["git", "log", "--all", "--format=%H %D | %s"]}.items():
        (out / name).write_text(sh(cmd, project).stdout)
    t = sh([str(project / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"], project)
    (out / "final-tests.txt").write_text(t.stdout + t.stderr)
    (out / "final-tests-exit.txt").write_text(f"{t.returncode}\n")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--max-fixes", type=int, default=1)
    ap.add_argument("--budget", type=float, default=20.0)
    ap.add_argument("--timeout-min", type=int, default=180)
    ap.add_argument("--runs-dir", default=str(PLUGIN.parent / "clean-ledger-e2e-runs"))
    args = ap.parse_args()

    if not shutil.which("claude"):
        sys.exit("local_run: claude CLI not found")
    if PROBE.exists():
        sys.exit(f"local_run: remove {PROBE} first (left over from an earlier probe)")
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M%S") + ("-dry" if args.dry_run else "")
    run_dir = Path(args.runs_dir) / stamp
    out = run_dir / "out"
    out.mkdir(parents=True)
    print(f"local_run: preparing {run_dir}", flush=True)
    project = prepare(run_dir)
    base = must(["git", "rev-parse", "HEAD"], project)
    (out / "plugin-commit.txt").write_text(must(["git", "rev-parse", "HEAD"], PLUGIN) + "\n")

    prompt = DRY_RUN_PROMPT if args.dry_run else f"/clean-ledger:run {args.max_fixes}"
    budget = min(args.budget, 2.0) if args.dry_run else args.budget
    timeout = min(args.timeout_min, 15) if args.dry_run else args.timeout_min
    print(f"local_run: starting Claude Code ({'dry run' if args.dry_run else 'full run'}, "
          f"budget ${budget}, timeout {timeout} min)", flush=True)
    code = run_claude(project, out, prompt, budget, timeout)
    collect(project, out, base)
    probe_written = PROBE.exists()
    (out / "sandbox-probe.json").write_text(json.dumps({"probe_file_written_outside_project": probe_written}) + "\n")
    print(f"local_run: claude exited {code}; evidence in {out}")
    if probe_written:
        print(f"local_run: WARNING sandbox let a command write {PROBE}")
    if not args.dry_run:
        return subprocess.call([sys.executable, str(PLUGIN / "e2e" / "judge.py"), str(out)])
    return code


if __name__ == "__main__":
    sys.exit(main())
