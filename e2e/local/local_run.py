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
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[2]
SETTINGS = Path(__file__).resolve().parent / "settings.json"
TEST_REPO = "https://github.com/prettytable/prettytable.git"
TEST_REF = "3.18.0"
# Machine-specific: a Python 3.10+ for the test project, and the folders that hold
# lizard/jscpd/semgrep. Override with CLEAN_LEDGER_E2E_PYTHON and
# CLEAN_LEDGER_E2E_TOOL_DIRS (os.pathsep-separated).
PYTHON = os.environ.get("CLEAN_LEDGER_E2E_PYTHON", shutil.which("python3.12") or "python3")
TOOL_DIRS = [Path(p) for p in os.environ.get("CLEAN_LEDGER_E2E_TOOL_DIRS", os.pathsep.join([
    str(Path.home() / ".debt-tools" / "venv" / "bin"),
    str(Path.home() / ".debt-tools" / "node_modules" / ".bin")])).split(os.pathsep) if p]
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


def prepare(run_dir: Path, repo: str = TEST_REPO, ref: str = TEST_REF, setup: str | None = None) -> Path:
    """Fresh clone at the ref on local `main`, no remote. Without `setup` (the
    default prettytable test): a project venv in .venv (git-ignored) with the
    tools linked into .venv/bin. With `setup` (any other project): the shell
    command is run once here, and the tools are linked into .clean-ledger-tools/,
    which is kept out of git through .git/info/exclude."""
    project = run_dir / "project"
    must(["git", "clone", "-q", repo, str(project)])
    must(["git", "checkout", "-q", "-B", "main", ref], project)
    must(["git", "remote", "remove", "origin"], project)
    must(["git", "config", "user.name", "Clean Ledger E2E"], project)
    must(["git", "config", "user.email", "e2e@localhost.invalid"], project)
    if setup is not None:
        with open(project / ".git" / "info" / "exclude", "a") as fh:
            fh.write("\n.clean-ledger-tools/\n")
        tools = project / ".clean-ledger-tools"
        (tools / "cache").mkdir(parents=True)
        for d in TOOL_DIRS:
            for tool in ("lizard", "jscpd", "semgrep"):
                if (d / tool).exists() and not (tools / tool).exists():
                    (tools / tool).symlink_to(d / tool)
        r = subprocess.run(setup, shell=True, cwd=project, capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(f"local_run: setup command failed:\n{(r.stdout + r.stderr)[-2000:]}")
        if must(["git", "status", "--porcelain"], project):
            sys.exit("local_run: project working tree is not clean after setup:\n"
                     + must(["git", "status", "--porcelain"], project))
        return project
    must([PYTHON, "-m", "venv", str(project / ".venv")])
    must([str(project / ".venv" / "bin" / "pip"), "install", "-q", "-e", f"{project}[tests]"])
    # Inside the Bash sandbox, env settings may not reach the shell and pip
    # cannot use the macOS keychain. So the tools are linked into .venv/bin and
    # pip's site config (always read) points at a CA bundle.
    for d in TOOL_DIRS:
        for tool in ("lizard", "jscpd", "semgrep"):
            src, dst = d / tool, project / ".venv" / "bin" / tool
            if src.exists() and not dst.exists():
                dst.symlink_to(src)
    ca = must([str(project / ".venv" / "bin" / "python"), "-c", "import pip._vendor.certifi as c; print(c.where())"])
    # cert alone is not enough: pip >= 24.2 still asks the OS trust store unless
    # legacy-certs is set (verified under a sandbox profile that denies trustd).
    (project / ".venv" / "pip.conf").write_text(f"[global]\ncert = {ca}\nuse-deprecated = legacy-certs\n")
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
    # Tool caches live inside a git-ignored folder of the project, which the
    # sandbox lets commands write; ~/.semgrep, ~/.npm and the pip cache do not.
    home = project / ".clean-ledger-tools" if (project / ".clean-ledger-tools").is_dir() else project / ".venv"
    cache = home / "cache" if home.name == ".clean-ledger-tools" else home / "clean-ledger-cache"
    cache.mkdir(parents=True, exist_ok=True)
    tool_bin = home if home.name == ".clean-ledger-tools" else home / "bin"
    env["PATH"] = os.pathsep.join([str(tool_bin), *map(str, TOOL_DIRS), env.get("PATH", "")])
    env["SEMGREP_SETTINGS_FILE"] = str(cache / "semgrep-settings.yml")
    env["SEMGREP_LOG_FILE"] = str(cache / "semgrep.log")
    env["SEMGREP_VERSION_CACHE_PATH"] = str(cache / "semgrep-version")
    env["PIP_CACHE_DIR"] = str(cache / "pip")
    env["npm_config_cache"] = str(cache / "npm")
    # The sandbox cannot reach the macOS keychain, so give Python tools a CA bundle.
    venv_python = project / ".venv" / "bin" / "python"
    ca = sh([str(venv_python) if venv_python.exists() else sys.executable, "-c",
             "import pip._vendor.certifi as c; print(c.where())"]).stdout.strip()
    if ca:
        env["PIP_CERT"] = env["SSL_CERT_FILE"] = env["REQUESTS_CA_BUNDLE"] = ca
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
    # Re-run the project's tests with the command the run itself configured
    # (any language); fall back to the default prettytable venv.
    cfg = project / ".ledger" / "config.json"
    test_cmd = json.loads(cfg.read_text()).get("test_command", "") if cfg.exists() else ""
    if test_cmd:
        t = subprocess.run(test_cmd, shell=True, cwd=project, capture_output=True, text=True, timeout=3600)
    else:
        t = sh([str(project / ".venv" / "bin" / "python"), "-m", "pytest", "-q", "-p", "no:cacheprovider"], project)
    (out / "final-tests.txt").write_text(t.stdout + t.stderr)
    (out / "final-tests-exit.txt").write_text(f"{t.returncode}\n")


def prepare_session(run_dir: Path, repo: str = TEST_REPO, ref: str = TEST_REF, setup: str | None = None,
                    plugin_source: str | None = None) -> Path:
    """Set up a project for a Claude Code *desktop* session to run Clean Ledger in:
    plugin enabled for this folder only (local scope), sandbox and permission
    settings in .claude/settings.local.json, and .claude/ kept out of git.
    `plugin_source` is a marketplace source such as a GitHub "owner/repo"
    (installs exactly like a user would); default: this checkout."""
    project = prepare(run_dir, repo, ref, setup)
    with open(project / ".git" / "info" / "exclude", "a") as fh:
        fh.write("\n.claude/\n")
    # `marketplace update` matters: an already-known marketplace is otherwise
    # served from Claude Code's cache, so a fresh install can get an old version.
    for cmd in (["claude", "plugin", "marketplace", "add", plugin_source or str(PLUGIN), "--scope", "local"],
                ["claude", "plugin", "marketplace", "update", "clean-ledger-marketplace"],
                ["claude", "plugin", "install", "clean-ledger@clean-ledger-marketplace", "--scope", "local"]):
        must(cmd, project)
    local = project / ".claude" / "settings.local.json"
    cfg = json.loads(local.read_text()) if local.exists() else {}
    ours = json.loads(SETTINGS.read_text())
    cfg["permissions"] = ours["permissions"]
    cfg["sandbox"] = ours["sandbox"]
    env = child_env(project)
    cfg["env"] = {k: env[k] for k in ("PATH", "SEMGREP_SETTINGS_FILE", "SEMGREP_LOG_FILE",
                                      "SEMGREP_VERSION_CACHE_PATH", "PIP_CACHE_DIR", "npm_config_cache",
                                      "PIP_CERT", "SSL_CERT_FILE", "REQUESTS_CA_BUNDLE") if k in env}
    local.write_text(json.dumps(cfg, indent=2) + "\n")
    if must(["git", "status", "--porcelain"], project):
        sys.exit("local_run: project not clean after session setup")
    return project


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--prepare-session", action="store_true",
                    help="prepare a folder for a desktop-app session to run in, then stop")
    ap.add_argument("--collect", metavar="RUN_DIR", help="collect evidence from a finished session run and judge it")
    ap.add_argument("--repo", default=TEST_REPO, help="test project to clone (default: prettytable)")
    ap.add_argument("--ref", default=TEST_REF, help="tag or branch of the test project")
    ap.add_argument("--setup", help="shell command to prepare a non-default project (e.g. 'npm install')")
    ap.add_argument("--plugin-source", help="marketplace source to install from, e.g. owner/clean-ledger")
    ap.add_argument("--max-fixes", type=int, default=1)
    ap.add_argument("--budget", type=float, default=20.0)
    ap.add_argument("--timeout-min", type=int, default=180)
    ap.add_argument("--runs-dir", default=str(PLUGIN.parent / "clean-ledger-e2e-runs"))
    args = ap.parse_args()

    if args.collect:
        run_dir = Path(args.collect)
        project, out = run_dir / "project", run_dir / "out"
        if run_dir.name.endswith("-session"):
            (out / "session-mode.txt").write_text("desktop session\n")
        collect(project, out, (out / "base-commit.txt").read_text().strip())
        return subprocess.call([sys.executable, str(PLUGIN / "e2e" / "judge.py"), str(out)])
    if not shutil.which("claude"):
        sys.exit("local_run: claude CLI not found")
    if args.prepare_session:
        run_dir = Path(args.runs_dir) / (dt.datetime.now().strftime("%Y%m%d-%H%M%S") + "-session")
        (run_dir / "out").mkdir(parents=True)
        project = prepare_session(run_dir, args.repo, args.ref, args.setup, args.plugin_source)
        (run_dir / "out" / "base-commit.txt").write_text(must(["git", "rev-parse", "HEAD"], project) + "\n")
        (run_dir / "out" / "plugin-commit.txt").write_text(must(["git", "rev-parse", "HEAD"], PLUGIN) + "\n")
        print(project)
        return 0
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
