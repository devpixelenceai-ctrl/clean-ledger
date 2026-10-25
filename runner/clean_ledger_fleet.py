#!/usr/bin/env python3
"""clean-ledger-fleet - run Clean Ledger on many repositories in parallel.

  python3 runner/clean_ledger_fleet.py plan   fleet.json    # clone and check everything (no Claude calls)
  python3 runner/clean_ledger_fleet.py run    fleet.json    # plan, run every repo, judge, report
  python3 runner/clean_ledger_fleet.py report <run-dir>     # rebuild the fleet report

Each repository gets its own folder <runs_dir>/<stamp>/<name>/ with:
  project/  a fresh clone at the requested ref, on a local branch, with its git
            remote removed (so nothing can be pushed)
  out/      evidence for the judge (git bundle, transcript, test results, verdict)

Executors (where the Clean Ledger run happens):
  docker   one throwaway container per repo from runner/Dockerfile (recommended)
  local    headless `claude -p` on this machine, sandboxed, plugin loaded per run
  command  any program, given {project} {out} {max_fixes} placeholders (testing)

Standard library only. See docs/fleet.md.
"""

from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import importlib.util
import json
import os
import re
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path

PLUGIN = Path(__file__).resolve().parent.parent
JUDGE = PLUGIN / "e2e" / "judge.py"
SANDBOX_SETTINGS = PLUGIN / "skills" / "clean-ledger" / "assets" / "settings.sandboxed.json"
NAME = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,62}$")
DEFAULTS = {"max_fixes": 1, "budget_usd": 20, "timeout_min": 180, "model": ""}
LANGS = {".py": "Python", ".js": "JavaScript", ".ts": "TypeScript", ".jsx": "JavaScript", ".tsx": "TypeScript",
         ".java": "Java", ".kt": "Kotlin", ".go": "Go", ".rb": "Ruby", ".rs": "Rust", ".cs": "C#",
         ".php": "PHP", ".swift": "Swift", ".c": "C", ".cpp": "C++", ".scala": "Scala"}
KEY_VARS = ("ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN")


class FleetError(Exception):
    pass


# ---------------------------------------------------------------- config
def load_config(path: Path) -> dict:
    try:
        cfg = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as e:
        raise FleetError(f"cannot read {path}: {e}")
    if not isinstance(cfg, dict):
        raise FleetError("config must be a JSON object")
    executor = cfg.get("executor", "docker")
    if executor not in ("docker", "local", "command"):
        raise FleetError(f"unknown executor {executor!r} (docker, local or command)")
    if executor == "command" and not (isinstance(cfg.get("command"), list) and cfg["command"]):
        raise FleetError("executor 'command' needs a non-empty \"command\" list")
    repos = cfg.get("repos")
    if not isinstance(repos, list) or not repos:
        raise FleetError("config needs a non-empty \"repos\" list")
    seen = set()
    defaults = {**DEFAULTS, **(cfg.get("defaults") or {})}
    out = []
    for i, r in enumerate(repos):
        if not isinstance(r, dict) or not r.get("url"):
            raise FleetError(f"repos[{i}] needs a \"url\"")
        name = r.get("name") or Path(str(r["url"]).rstrip("/")).name.removesuffix(".git")
        if not NAME.match(name):
            raise FleetError(f"repos[{i}]: invalid name {name!r} (letters, digits, . _ -)")
        if name in seen:
            raise FleetError(f"duplicate repo name {name!r}")
        seen.add(name)
        out.append({**defaults, **r, "name": name})
    base = path.resolve().parent
    runs_dir = Path(cfg.get("runs_dir", "fleet-runs"))
    return {
        "executor": executor,
        "image": cfg.get("image", "clean-ledger-runner:latest"),
        "command": cfg.get("command", []),
        "max_parallel": max(1, int(cfg.get("max_parallel", 2))),
        "tool_dirs": [os.path.expanduser(d) for d in cfg.get("tool_dirs", [])],
        "runs_dir": runs_dir if runs_dir.is_absolute() else base / runs_dir,
        "repos": out,
    }


# ---------------------------------------------------------------- helpers
def sh(cmd: list[str], cwd: Path | None = None, env: dict | None = None,
       timeout: int | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True, timeout=timeout)


def must(cmd: list[str], cwd: Path | None = None) -> str:
    r = sh(cmd, cwd)
    if r.returncode != 0:
        raise FleetError(f"{' '.join(cmd)} failed: {(r.stderr or r.stdout).strip()[:500]}")
    return r.stdout.strip()


def languages(project: Path) -> dict[str, int]:
    counts: Counter = Counter()
    for p in project.rglob("*"):
        parts = set(p.parts)
        if p.is_file() and not parts & {".git", "node_modules", "vendor", ".venv", "dist", "build"}:
            if p.suffix in LANGS:
                counts[LANGS[p.suffix]] += 1
    return dict(counts.most_common(4))


# ---------------------------------------------------------------- plan
def prepare_repo(repo: dict, folder: Path) -> dict:
    """Fresh clone at the ref, on a local branch, without a remote."""
    project, out = folder / "project", folder / "out"
    out.mkdir(parents=True, exist_ok=True)
    must(["git", "clone", "-q", str(repo["url"]), str(project)])
    branch = repo.get("base_branch") or "main"
    if repo.get("ref"):
        must(["git", "checkout", "-q", "-B", branch, repo["ref"]], project)
    else:
        must(["git", "checkout", "-q", "-B", branch], project)
    for remote in must(["git", "remote"], project).split():
        must(["git", "remote", "remove", remote], project)
    must(["git", "config", "user.name", "Clean Ledger Fleet"], project)
    must(["git", "config", "user.email", "fleet@localhost.invalid"], project)
    base = must(["git", "rev-parse", "HEAD"], project)
    (out / "base-commit.txt").write_text(base + "\n")
    info = {"name": repo["name"], "url": repo["url"], "ref": repo.get("ref", ""), "branch": branch,
            "base_commit": base, "commits": int(must(["git", "rev-list", "--count", "HEAD"], project)),
            "languages": languages(project), "status": "planned"}
    (out / "plan.json").write_text(json.dumps(info, indent=2) + "\n")
    return info


def executor_problems(cfg: dict) -> list[str]:
    """What stops the chosen executor from running (names only, never values)."""
    problems = []
    if cfg["executor"] == "docker":
        if not shutil.which("docker"):
            problems.append("docker is not installed")
        elif sh(["docker", "image", "inspect", cfg["image"]]).returncode != 0:
            problems.append(f"image {cfg['image']} not found (build it: docker build -f runner/Dockerfile -t {cfg['image']} .)")
        if not any(os.environ.get(k) for k in KEY_VARS):
            problems.append("no ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN in the environment")
    elif cfg["executor"] == "local":
        if not shutil.which("claude"):
            problems.append("claude CLI not found")
        for tool in ("lizard", "jscpd"):
            path = os.pathsep.join([*cfg["tool_dirs"], os.environ.get("PATH", "")])
            if not shutil.which(tool, path=path):
                problems.append(f"{tool} not found on PATH or in tool_dirs")
    elif cfg["executor"] == "command" and not shutil.which(cfg["command"][0]):
        problems.append(f"command {cfg['command'][0]!r} not found")
    return problems


def plan(cfg: dict, stamp: str | None = None) -> Path:
    run_dir = cfg["runs_dir"] / (stamp or dt.datetime.now().strftime("%Y%m%d-%H%M%S"))
    run_dir.mkdir(parents=True, exist_ok=False)
    rows = []
    for repo in cfg["repos"]:
        try:
            rows.append(prepare_repo(repo, run_dir / repo["name"]))
        except FleetError as e:
            rows.append({"name": repo["name"], "url": repo["url"], "status": "error", "error": str(e)})
    problems = executor_problems(cfg)
    summary = {"executor": cfg["executor"], "executor_problems": problems, "repos": rows,
               "config": {k: (str(v) if isinstance(v, Path) else v) for k, v in cfg.items() if k != "repos"}}
    (run_dir / "fleet-plan.json").write_text(json.dumps(summary, indent=2) + "\n")
    return run_dir


# ---------------------------------------------------------------- execute
def execute(cfg: dict, repo: dict, folder: Path) -> int:
    project, out = folder / "project", folder / "out"
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    timeout = int(repo["timeout_min"]) * 60
    env = {k: v for k, v in os.environ.items() if k != "CLAUDECODE" and not k.startswith("CLAUDE_CODE_")
           or k == "CLAUDE_CODE_OAUTH_TOKEN"}
    if cfg["executor"] == "docker":
        cmd = ["docker", "run", "--rm", "--cap-drop", "ALL", "--security-opt", "no-new-privileges",
               "-e", "ANTHROPIC_API_KEY", "-e", "CLAUDE_CODE_OAUTH_TOKEN",
               "-e", f"MAX_FIXES={repo['max_fixes']}", "-e", f"MAX_BUDGET_USD={repo['budget_usd']}",
               "-e", f"RUN_TIMEOUT={repo['timeout_min']}m", "-e", f"MODEL={repo['model']}",
               "-v", f"{project}:/work/project", "-v", f"{out}:/out", cfg["image"], "fleet-run"]
        cwd = folder
    elif cfg["executor"] == "local":
        env = {k: v for k, v in env.items() if k not in KEY_VARS}  # use the existing login
        env["PATH"] = os.pathsep.join([*cfg["tool_dirs"], env.get("PATH", "")])
        cmd = ["claude", "-p", f"/clean-ledger:run {repo['max_fixes']}", "--plugin-dir", str(PLUGIN),
               "--settings", str(SANDBOX_SETTINGS), "--setting-sources", "project",
               "--strict-mcp-config", "--mcp-config", '{"mcpServers": {}}', "--permission-mode", "dontAsk",
               "--output-format", "stream-json", "--verbose", "--max-budget-usd", str(repo["budget_usd"])]
        if repo["model"]:
            cmd += ["--model", repo["model"]]
        cwd = project
    else:
        fill = {"project": str(project), "out": str(out), "max_fixes": str(repo["max_fixes"]), "name": repo["name"]}
        cmd = [part.format(**fill) for part in cfg["command"]]
        cwd = project
    transcript = out / "transcript.jsonl"
    with open(transcript, "a") as so, open(out / "runner-stderr.log", "a") as se:
        try:
            # local and command executors stream Claude Code's stream-json to stdout;
            # the docker container writes /out/transcript.jsonl itself.
            code = subprocess.run(cmd, cwd=cwd, env=env, stdout=se if cfg["executor"] == "docker" else so,
                                  stderr=se, stdin=subprocess.DEVNULL, timeout=timeout).returncode
        except subprocess.TimeoutExpired:
            code = 124
    if not transcript.stat().st_size:
        transcript.unlink()
    status = out / "run-status.json"
    if not status.exists():  # the docker container writes its own
        status.write_text(json.dumps({"started": started, "finished": dt.datetime.now(dt.timezone.utc).isoformat(),
                                      "claude_exit": code, "executor": cfg["executor"]}) + "\n")
    return code


def collect(cfg: dict, folder: Path) -> None:
    project, out = folder / "project", folder / "out"
    sh(["git", "bundle", "create", str(out / "result.bundle"), "--all"], project)
    for name, cmd in {"branches.txt": ["git", "branch", "-a"], "remotes.txt": ["git", "remote", "-v"],
                      "git-status.txt": ["git", "status", "--porcelain"],
                      "git-log.txt": ["git", "log", "--all", "--format=%H %D | %s"]}.items():
        (out / name).write_text(sh(cmd, project).stdout)
    if (out / "final-tests-exit.txt").exists() or cfg["executor"] == "docker":
        return  # docker runs the project's tests inside the container, never on the host
    test_cmd = (json.loads((project / ".ledger" / "config.json").read_text()).get("test_command")
                if (project / ".ledger" / "config.json").exists() else "")
    if test_cmd:
        r = subprocess.run(test_cmd, shell=True, cwd=project, capture_output=True, text=True, timeout=3600)
        (out / "final-tests.txt").write_text(r.stdout + r.stderr)
        (out / "final-tests-exit.txt").write_text(f"{r.returncode}\n")


def judge(folder: Path) -> dict:
    spec = importlib.util.spec_from_file_location("clean_ledger_judge", JUDGE)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    rep = mod.judge(folder / "out")
    mod.write_report(folder / "out", rep)
    return {"passed": rep.passed, "failed": [r["check"] for r in rep.rows if r["status"] == "FAIL"],
            "warnings": [r["check"] for r in rep.rows if r["status"] == "WARN"], "info": rep.info}


def run_one(cfg: dict, repo: dict, folder: Path) -> dict:
    code = execute(cfg, repo, folder)
    collect(cfg, folder)
    verdict = judge(folder)
    verdict["exit"] = code
    (folder / "out" / "fleet-verdict.json").write_text(json.dumps(verdict, indent=2) + "\n")
    return verdict


def run(cfg: dict, stamp: str | None = None) -> Path:
    problems = executor_problems(cfg)
    if problems:
        raise FleetError("executor not ready: " + "; ".join(problems))
    run_dir = plan(cfg, stamp)
    planned = json.loads((run_dir / "fleet-plan.json").read_text())["repos"]
    ready = [r for r in cfg["repos"] if any(p["name"] == r["name"] and p["status"] == "planned" for p in planned)]
    with cf.ThreadPoolExecutor(max_workers=cfg["max_parallel"]) as pool:
        futures = {pool.submit(run_one, cfg, r, run_dir / r["name"]): r["name"] for r in ready}
        for fut in cf.as_completed(futures):
            name = futures[fut]
            try:
                v = fut.result()
                print(f"fleet: {name}: {'PASS' if v['passed'] else 'FAIL'}", flush=True)
            except Exception as e:  # noqa: BLE001 - one repo must not stop the fleet
                (run_dir / name / "out" / "fleet-verdict.json").write_text(
                    json.dumps({"passed": False, "failed": [f"runner error: {e}"], "warnings": [], "info": {}}) + "\n")
                print(f"fleet: {name}: ERROR {e}", flush=True)
    report(run_dir)
    return run_dir


# ---------------------------------------------------------------- report
def metric(d: dict | None, key: str):
    return None if not d else d.get(key)


def repo_row(folder: Path) -> dict:
    out, project = folder / "out", folder / "project"
    plan_info = json.loads((out / "plan.json").read_text()) if (out / "plan.json").exists() else {}
    verdict = json.loads((out / "fleet-verdict.json").read_text()) if (out / "fleet-verdict.json").exists() else None

    def show(path: str):
        r = sh(["git", "show", f"clean-ledger:{path}"], project) if project.exists() else None
        return json.loads(r.stdout) if r and r.returncode == 0 and r.stdout.strip() else None

    baseline, state = show(".ledger/baseline.json"), show(".ledger/state.json") or {}
    after = (json.loads((project / ".ledger" / "metrics.json").read_text())
             if (project / ".ledger" / "metrics.json").exists() else None)
    phases = state.get("phases", {})
    approved = sum(1 for p in "012345" if phases.get(p) == "approved")
    return {
        "name": folder.name, "url": plan_info.get("url", ""), "ref": plan_info.get("ref", ""),
        "languages": plan_info.get("languages", {}),
        "verdict": "not run" if verdict is None else ("PASS" if verdict["passed"] else "FAIL"),
        "failed_checks": (verdict or {}).get("failed", []),
        "phases_approved": approved, "blocked": bool(state.get("blocked")),
        "items_done": (verdict or {}).get("info", {}).get("items_done", []),
        "guard_blocks": (verdict or {}).get("info", {}).get("guard_blocks"),
        "complex_before": metric(baseline, "complex_functions"), "complex_after": metric(after, "complex_functions"),
        "max_ccn_before": metric(baseline, "max_ccn"), "max_ccn_after": metric(after, "max_ccn"),
        "dup_before": metric(baseline, "duplication_pct"), "dup_after": metric(after, "duplication_pct"),
    }


def arrow(a, b) -> str:
    return "–" if a is None and b is None else f"{'?' if a is None else a} → {'?' if b is None else b}"


def report(run_dir: Path) -> Path:
    rows = [repo_row(d) for d in sorted(run_dir.iterdir()) if d.is_dir() and (d / "out").is_dir()]
    passed = sum(r["verdict"] == "PASS" for r in rows)
    lines = [f"# Clean Ledger fleet report", "", f"Run: `{run_dir.name}` — {passed}/{len(rows)} repositories passed the judge.",
             "", "| Repository | Verdict | Phases approved | Fixed | Complex fns | Max CCN | Duplication % | Guard blocks |",
             "|---|---|---|---|---|---|---|---|"]
    for r in rows:
        blocked = " (BLOCKED)" if r["blocked"] else ""
        lines.append(f"| {r['name']} | {r['verdict']}{blocked} | {r['phases_approved']}/6 | {len(r['items_done'])} | "
                     f"{arrow(r['complex_before'], r['complex_after'])} | {arrow(r['max_ccn_before'], r['max_ccn_after'])} | "
                     f"{arrow(r['dup_before'], r['dup_after'])} | {'–' if r['guard_blocks'] is None else r['guard_blocks']} |")
    failing = [r for r in rows if r["failed_checks"]]
    if failing:
        lines += ["", "## Failed checks", ""]
        lines += [f"- **{r['name']}**: " + "; ".join(r["failed_checks"]) for r in failing]
    lines += ["", "Per-repository evidence and the judge's full report are in `<repo>/out/judge-report.md`.",
              "A PASS from the judge is necessary, not sufficient: review each `clean-ledger` branch before merging."]
    (run_dir / "fleet-report.md").write_text("\n".join(lines) + "\n")
    (run_dir / "fleet-summary.json").write_text(json.dumps({"run": run_dir.name, "passed": passed,
                                                            "total": len(rows), "repos": rows}, indent=2) + "\n")
    return run_dir / "fleet-report.md"


# ---------------------------------------------------------------- main
def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    for name in ("plan", "run"):
        s = sub.add_parser(name)
        s.add_argument("config")
        s.add_argument("--stamp", help="run folder name (default: current time)")
    s = sub.add_parser("report")
    s.add_argument("run_dir")
    args = ap.parse_args()
    try:
        if args.cmd == "report":
            print(report(Path(args.run_dir)).read_text())
            return 0
        cfg = load_config(Path(args.config))
        if args.cmd == "plan":
            run_dir = plan(cfg, args.stamp)
            summary = json.loads((run_dir / "fleet-plan.json").read_text())
            for r in summary["repos"]:
                detail = r.get("error") or f"{r['commits']} commits, {', '.join(r['languages']) or 'no known language'}"
                print(f"{r['status']:8} {r['name']}: {detail}")
            for p in summary["executor_problems"]:
                print(f"not ready: {p}")
            print(f"plan: {run_dir}")
            return 0 if not summary["executor_problems"] and all(r["status"] == "planned" for r in summary["repos"]) else 1
        run_dir = run(cfg, args.stamp)
        print((run_dir / "fleet-report.md").read_text())
        return 0
    except FleetError as e:
        print(f"clean-ledger-fleet: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
