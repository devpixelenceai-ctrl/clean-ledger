#!/usr/bin/env python3
"""ledger.py - the deterministic engine behind Clean Ledger.

Standard library only. Run from the repository root.

Setup and measurement
  init        Create .ledger/ (copies this script and measure.sh, writes config.json)
  churn       Commits and authors per file from git history
  metrics     Summarise lizard / jscpd / semgrep reports into one JSON
  hotspots    Rank files by churn x complexity (+ security) into tiers
  gate        Fail (exit 1) if debt grew versus the baseline

Workflow state
  snapshot-baseline  Phase 0: copy metrics.json to baseline.json (refused after phase 0)
  render-gate Write the CI gate workflow with pinned tool versions
  queue       Build .ledger/queue.json (the Tier 1 fix queue) from hotspots; --order f1 f2 ... reorders it
  raise-baseline  Owner, after merging: current metrics become the baseline (never loosens the gate)
  start-item  Snapshot a file's metrics before fixing it
  skip-item   Take a file out of the queue with a reason (after it is reverted)
  verify      Objective acceptance checks for a phase (exit 1 on any FAIL)
  record      Record the auditor's verdict for a phase or item
  status      Show where the run is

Phases: 0 setup, 1 measure, 2 prioritise, 3 fix (per item), 4 prevent, 5 report.
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import shutil
import subprocess
import sys
from collections import defaultdict
from pathlib import Path

LEDGER = Path(".ledger")
REPORTS = LEDGER / "reports"
CONFIG = LEDGER / "config.json"
STATE = LEDGER / "state.json"
APPROVALS = LEDGER / "approvals.jsonl"
QUEUE = LEDGER / "queue.json"
ITEMS = LEDGER / "items"
VERIFY_DIR = LEDGER / "verify"

DEFAULT_CCN_LIMIT = 15
SEVERITY_WEIGHT = {"high": 2.0, "medium": 0.5, "low": 0.0}
SEMGREP_SEVERITY = {"ERROR": "high", "WARNING": "medium", "INFO": "low",
                    "CRITICAL": "high", "HIGH": "high", "MEDIUM": "medium", "LOW": "low"}
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(^|/)test_[^/]*$|"
                       r"_test\.[^/]+$|\.test\.[^/]+$|\.spec\.[^/]+$|Tests?\.(java|cs|kt|swift)$")
REGISTER_SECTIONS = ["## Totals", "## Hotspots", "## Dependencies", "## Team input",
                     "## Done", "## Observations"]
DEFAULT_CONFIG = {
    "branch": "clean-ledger",
    "base_branch": "main",
    "src_dirs": ["src"],
    "test_command": "",
    "test_timeout_seconds": 1800,
    "test_attempts": 2,
    "protected_paths": [],
    "hourly_cost": None,
    "currency": "USD",
    "max_fixes_per_run": 3,
    "max_attempts_per_step": 3,
    "tier1_size": 10,
    "ccn_limit": DEFAULT_CCN_LIMIT,
    "ci_file": ".github/workflows/ledger-gate.yml",
    "tool_dirs": [],
    "autopilot": True,
}
TOOLS = ("lizard", "jscpd", "semgrep")
VERSION = re.compile(r"\d+\.\d+\.\d+")


# ================================================================ helpers
def norm(path: str) -> str:
    p = path.replace("\\", "/")
    while p.startswith("./"):
        p = p[2:]
    return p


def sh(cmd: list[str] | str, timeout: int | None = None, check: bool = False,
       env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                          shell=isinstance(cmd, str), check=check, env=env)


def git(*args: str) -> str:
    r = sh(["git", *args])
    return r.stdout.strip() if r.returncode == 0 else ""


def now() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_json(path: Path, default=None):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def save_json(path: Path, data) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def config() -> dict:
    cfg = dict(DEFAULT_CONFIG)
    cfg.update(load_json(CONFIG, {}) or {})
    return cfg


def tool_path() -> str:
    """PATH with the configured `tool_dirs` (user-level tool installs) first."""
    dirs = [os.path.expanduser(d) for d in config().get("tool_dirs", [])]
    return os.pathsep.join([*dirs, os.environ.get("PATH", "")])


def tool_env() -> dict:
    return {**os.environ, "PATH": tool_path()}


def ca_bundle() -> str | None:
    """A CA bundle file from certifi (or pip's vendored copy), if available."""
    for mod in ("certifi", "pip._vendor.certifi"):
        try:
            return __import__(mod, fromlist=["where"]).where()
        except Exception:  # noqa: BLE001 - any import problem means "not available"
            continue
    return None


def tool_versions() -> dict:
    """Installed version of each analysis tool, or None if it is not found or
    its `--version` fails. Semgrep crashes at start-up when a sandbox hides the
    OS certificate store, so a failure is retried once with a CA bundle (the
    same fallback measure.sh uses)."""
    out = {}
    for tool in TOOLS:
        exe = shutil.which(tool, path=tool_path())
        version = None
        if exe:
            envs = [None]
            if ca_bundle():
                envs.append({**os.environ, "SSL_CERT_FILE": ca_bundle()})
            for env in envs:
                try:
                    r = sh([exe, "--version"], timeout=120, env=env)
                except (OSError, subprocess.TimeoutExpired):
                    continue
                m = VERSION.search(r.stdout + r.stderr) if r.returncode == 0 else None
                if m:
                    version = m.group(0)
                    break
        out[tool] = version
    return out


def slug(path: str) -> str:
    return re.sub(r"[^A-Za-z0-9]+", "-", path).strip("-").lower()


def is_test(path: str) -> bool:
    return bool(TEST_PATH.search(norm(path)))


def under(path: str, roots: list[str]) -> bool:
    """True if `path` is one of `roots` or inside one of them (`lib` matches
    `lib/x.js`, not `library.js`)."""
    p = norm(path)
    for r in roots:
        r = norm(r).strip("/")
        if r and (p == r or p.startswith(r + "/")):
            return True
    return False


# ================================================================ init
def cmd_init(args) -> int:
    here = Path(__file__).resolve().parent
    LEDGER.mkdir(exist_ok=True)
    for name in ("ledger.py", "measure.sh"):
        src = here / name
        if src.exists() and src.resolve() != (LEDGER / name).resolve():
            shutil.copy2(src, LEDGER / name)
            os.chmod(LEDGER / name, 0o755)
    cfg = config() if CONFIG.exists() else dict(DEFAULT_CONFIG)
    if args.src:
        cfg["src_dirs"] = args.src
    if args.test_command:
        cfg["test_command"] = args.test_command
    if args.base_branch:
        cfg["base_branch"] = args.base_branch
    if args.protected:
        cfg["protected_paths"] = args.protected
    if args.tool_dir:
        cfg["tool_dirs"] = args.tool_dir
    roadmap = here.parent / "ROADMAP.md"
    if roadmap.exists():
        cfg["roadmap"] = str(roadmap)
    save_json(CONFIG, cfg)
    gi = Path(".gitignore")
    lines = gi.read_text(encoding="utf-8").splitlines() if gi.exists() else []
    for entry in (".ledger/reports/", ".ledger/metrics.json", ".ledger/verify/"):
        if entry not in lines:
            lines.append(entry)
    gi.write_text("\n".join(lines) + "\n", encoding="utf-8")
    if not STATE.exists():
        save_json(STATE, {"started": now(), "phases": {}, "items": {}, "current": 0})
    print(f"ledger: initialised {LEDGER}/ ; edit {CONFIG} to confirm src_dirs and test_command")
    return 0


# ================================================================ churn
def cmd_churn(args) -> int:
    r = sh(["git", "log", f"--since={args.since}", "--no-merges", "--name-only", "--format=@@%ae"])
    if r.returncode != 0:
        print("ledger churn: git log failed: " + r.stderr, file=sys.stderr)
        return 2
    changes: dict[str, int] = defaultdict(int)
    authors: dict[str, set] = defaultdict(set)
    author = ""
    for line in r.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("@@"):
            author = line[2:]
            continue
        f = norm(line)
        if os.path.exists(f):
            changes[f] += 1
            authors[f].add(author)
    w = csv.writer(sys.stdout, lineterminator="\n")
    w.writerow(["file", "changes", "authors"])
    for f, n in sorted(changes.items(), key=lambda kv: (-kv[1], kv[0])):
        w.writerow([f, n, len(authors[f])])
    return 0


# ================================================================ readers
def read_lizard(path: Path) -> list[dict]:
    rows = []
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8", errors="replace") as fh:
        for rec in csv.reader(fh):
            if len(rec) < 8:
                continue
            try:
                nloc, ccn = int(rec[0]), int(rec[1])
            except ValueError:
                continue
            rows.append({"nloc": nloc, "ccn": ccn, "file": norm(rec[6]), "function": rec[7]})
    return rows


def jscpd_path(name: str, src_dirs: list[str]) -> str:
    """Turn a jscpd file name into a repo-relative path. Absolute names (from
    `jscpd --absolute`) are made relative to the repo root; a bare name such as
    `response.js` is resolved against src_dirs only when exactly one file matches."""
    p = Path(name)
    if p.is_absolute():
        try:
            return norm(p.resolve().relative_to(Path.cwd().resolve()).as_posix())
        except ValueError:
            return norm(name)
    if p.exists():
        return norm(name)
    hits = {norm(str(Path(d) / name)) for d in src_dirs if (Path(d) / name).is_file()}
    return hits.pop() if len(hits) == 1 else norm(name)


def read_jscpd(reports: Path) -> dict:
    """Totals come from jscpd. Per file, count the distinct lines of that file
    that sit inside any duplicated block (both copies of an in-file clone
    count; overlapping clones count once)."""
    data = load_json(reports / "jscpd-report.json")
    if not data:
        return {}
    total = data.get("statistics", {}).get("total", {})
    src_dirs = config().get("src_dirs", [])
    lines: dict[str, set[int]] = defaultdict(set)
    for d in data.get("duplicates", []):
        for side in ("firstFile", "secondFile"):
            f = d.get(side, {})
            if not f.get("name"):
                continue
            start, end = f.get("start"), f.get("end")
            if not (isinstance(start, int) and isinstance(end, int)):
                start, end = 1, int(d.get("lines", 0))
            lines[jscpd_path(f["name"], src_dirs)].update(range(start, end + 1))
    return {"percentage": float(total.get("percentage", 0.0)),
            "duplicated_lines": int(total.get("duplicatedLines", 0)),
            "per_file": {k: len(v) for k, v in lines.items()}}


def read_semgrep(reports: Path) -> dict:
    data = load_json(reports / "semgrep.json")
    totals = {"high": 0, "medium": 0, "low": 0}
    per_file: dict[str, dict] = defaultdict(lambda: {"high": 0, "medium": 0, "low": 0})
    if data is None:
        return {"totals": totals, "per_file": {}, "present": False}
    for r in data.get("results", []):
        sev = SEMGREP_SEVERITY.get(str(r.get("extra", {}).get("severity", "")).upper(), "low")
        totals[sev] += 1
        per_file[norm(r.get("path", ""))][sev] += 1
    return {"totals": totals, "per_file": dict(per_file), "present": True}


def read_churn(path: Path) -> dict[str, dict]:
    out = {}
    if path.exists():
        with path.open(newline="", encoding="utf-8") as fh:
            for row in csv.DictReader(fh):
                out[norm(row["file"])] = {"changes": int(row["changes"]), "authors": int(row.get("authors") or 0)}
    return out


def match_dup(file: str, per_file: dict[str, int]) -> int:
    return per_file.get(norm(file), 0)


# ================================================================ metrics
def compute_metrics(reports: Path, ccn_limit: int) -> dict:
    funcs = read_lizard(reports / "lizard.csv")
    dup = read_jscpd(reports)
    sem = read_semgrep(reports)
    return {
        "measured_at": now(),
        "commit": git("rev-parse", "--short", "HEAD"),
        "ccn_limit": ccn_limit,
        "functions": len(funcs),
        "complex_functions": sum(1 for f in funcs if f["ccn"] > ccn_limit),
        "max_ccn": max((f["ccn"] for f in funcs), default=0),
        "avg_ccn": round(sum(f["ccn"] for f in funcs) / len(funcs), 2) if funcs else 0,
        "duplication_pct": round(dup["percentage"], 2) if dup else None,
        "duplicated_lines": dup.get("duplicated_lines") if dup else None,
        "security": sem["totals"] if sem["present"] else None,
        "tools": tool_versions(),
    }


def cmd_metrics(args) -> int:
    json.dump(compute_metrics(Path(args.reports), args.ccn_limit or config()["ccn_limit"]), sys.stdout, indent=2)
    print()
    return 0


# ================================================================ hotspots
def pct_rank(values: dict[str, float]) -> dict[str, float]:
    n = len(values)
    if not n:
        return {}
    ordered = sorted(values.values())
    pos: dict[float, float] = {}
    i = 0
    while i < n:
        j = i
        while j + 1 < n and ordered[j + 1] == ordered[i]:
            j += 1
        pos[ordered[i]] = ((i + 1) + (j + 1)) / 2 / n
        i = j + 1
    return {k: pos[v] for k, v in values.items()}


def compute_hotspots(reports: Path, ccn_limit: int, tier1: int) -> list[dict]:
    churn = read_churn(reports / "churn.csv")
    funcs = read_lizard(reports / "lizard.csv")
    dup = read_jscpd(reports)
    sem = read_semgrep(reports)
    per_file: dict[str, dict] = defaultdict(lambda: {"max_ccn": 0, "complex": 0, "nloc": 0})
    for f in funcs:
        pf = per_file[f["file"]]
        pf["max_ccn"] = max(pf["max_ccn"], f["ccn"])
        pf["nloc"] += f["nloc"]
        pf["complex"] += 1 if f["ccn"] > ccn_limit else 0
    files = set(per_file) | set(sem.get("per_file", {}))
    if not files:
        return []
    cr = pct_rank({f: churn.get(f, {}).get("changes", 0) for f in files})
    xr = pct_rank({f: per_file[f]["max_ccn"] for f in files})
    rows = []
    for f in files:
        s = sem.get("per_file", {}).get(f, {"high": 0, "medium": 0, "low": 0})
        weight = sum(SEVERITY_WEIGHT[k] * v for k, v in s.items())
        rows.append({
            "file": f,
            "changes": churn.get(f, {}).get("changes", 0),
            "authors": churn.get(f, {}).get("authors", 0),
            "max_ccn": per_file[f]["max_ccn"],
            "complex_functions": per_file[f]["complex"],
            "nloc": per_file[f]["nloc"],
            "duplicated_lines": match_dup(f, dup.get("per_file", {}) if dup else {}),
            "sec_high": s["high"], "sec_medium": s["medium"], "sec_low": s["low"],
            "security_measured": sem["present"],
            "score": round(cr[f] * xr[f] * (1 + weight), 3),
        })
    rows.sort(key=lambda r: (-r["score"], r["file"]))
    for i, r in enumerate(rows):
        if r["sec_high"] > 0 or (i < tier1 and r["complex_functions"] > 0):
            r["tier"] = 1
        elif r["complex_functions"] > 0 and r["changes"] > 0:
            r["tier"] = 2
        else:
            r["tier"] = 3
    rows.sort(key=lambda r: (r["tier"], -r["score"], r["file"]))
    return rows


def security_cell(r: dict) -> str:
    """H/M/L counts, or n/a when Semgrep did not run (never 0/0/0)."""
    if not r.get("security_measured", True):
        return "n/a"
    return f"{r['sec_high']}/{r['sec_medium']}/{r['sec_low']}"


def cmd_hotspots(args) -> int:
    cfg = config()
    rows = compute_hotspots(Path(args.reports), cfg["ccn_limit"], args.tier1 or cfg["tier1_size"])
    if not rows:
        print("ledger hotspots: no lizard or semgrep data in " + args.reports, file=sys.stderr)
        return 2
    shown = rows[: args.limit] if args.limit else rows
    if args.json:
        json.dump(shown, sys.stdout, indent=2)
        print()
    elif args.markdown:
        print("| Tier | File | Changes | Authors | Max CCN | Complex fns | Dup lines | Security H/M/L | Score |")
        print("| --- | --- | --- | --- | --- | --- | --- | --- | --- |")
        for r in shown:
            print(f"| {r['tier']} | `{r['file']}` | {r['changes']} | {r['authors']} | {r['max_ccn']} | "
                  f"{r['complex_functions']} | {r['duplicated_lines']} | "
                  f"{security_cell(r)} | {r['score']} |")
    else:
        w = csv.DictWriter(sys.stdout, fieldnames=list(shown[0].keys()), lineterminator="\n")
        w.writeheader()
        w.writerows(shown)
    return 0


# ================================================================ gate
def gate_compare(base: dict, cur: dict, dup_tol: float) -> tuple[list[str], list[str]]:
    failures, notes = [], []

    def check(name, b, c, tol=0.0):
        if b is None or c is None:
            notes.append(f"skip  {name}: not measured")
        elif c > b + tol:
            failures.append(f"FAIL  {name}: {b} -> {c}")
        elif c < b:
            notes.append(f"good  {name}: {b} -> {c}")
        else:
            notes.append(f"ok    {name}: {c}")

    check("complex_functions", base.get("complex_functions"), cur.get("complex_functions"))
    check("duplication_pct", base.get("duplication_pct"), cur.get("duplication_pct"), dup_tol)
    bs, cs = base.get("security") or {}, cur.get("security") or {}
    check("security.high", bs.get("high"), cs.get("high"))
    check("security.medium", bs.get("medium"), cs.get("medium"))
    return failures, notes


def cmd_gate(args) -> int:
    base = load_json(Path(args.baseline))
    cur = load_json(Path(args.current))
    if base is None or cur is None:
        print("ledger gate: baseline or current metrics missing", file=sys.stderr)
        return 2
    failures, notes = gate_compare(base, cur, args.dup_tolerance)
    for line in notes + failures:
        print(line)
    print("\nLedger gate failed: this change adds technical debt." if failures else "\nLedger gate passed.")
    return 1 if failures else 0


# ================================================================ measurement runner
def run_measure() -> tuple[bool, str]:
    if not (LEDGER / "measure.sh").exists():
        return False, "missing .ledger/measure.sh"
    r = sh(["bash", str(LEDGER / "measure.sh")], timeout=3600, env=tool_env())
    return r.returncode == 0, (r.stdout + r.stderr)[-1500:]


def file_metrics(path: str) -> dict:
    cfg = config()
    rows = compute_hotspots(REPORTS, cfg["ccn_limit"], cfg["tier1_size"])
    for r in rows:
        if r["file"] == norm(path):
            return {k: r[k] for k in ("max_ccn", "complex_functions", "duplicated_lines",
                                       "sec_high", "sec_medium", "nloc")}
    return {"max_ccn": 0, "complex_functions": 0, "duplicated_lines": 0, "sec_high": 0, "sec_medium": 0, "nloc": 0}


# ================================================================ queue / items
def reorder_queue(order: list[str]) -> int:
    """Phase 2: put the queue in estimated-cost order. Items with high-severity
    security findings must stay ahead of the rest (roadmap: security first)."""
    queue = load_json(QUEUE, []) or []
    files = [q["file"] for q in queue]
    order = [norm(f) for f in order]
    if len(set(order)) != len(order) or sorted(order) != sorted(files):
        print("ledger queue --order: name every queued file exactly once; queued: " + ", ".join(files), file=sys.stderr)
        return 2
    by_file = {q["file"]: q for q in queue}
    new = [by_file[f] for f in order]
    security = [i for i, q in enumerate(new) if q.get("sec_high", 0) > 0]
    if security and max(security) >= len(security):
        print("ledger queue --order: items with high-severity security findings must come first", file=sys.stderr)
        return 2
    save_json(QUEUE, new)
    print(f"ledger: reordered {QUEUE}: " + ", ".join(order))
    return 0


def cmd_queue(args) -> int:
    if args.order:
        return reorder_queue(args.order)
    cfg = config()
    rows = compute_hotspots(REPORTS, cfg["ccn_limit"], cfg["tier1_size"])
    existing = {q["file"]: q for q in (load_json(QUEUE, []) or [])}
    queue = []
    for r in rows:
        if r["tier"] != 1:
            continue
        old = existing.get(r["file"], {})
        queue.append({"file": r["file"], "score": r["score"], "max_ccn": r["max_ccn"],
                      "sec_high": r["sec_high"], "status": old.get("status", "todo"),
                      "reason": old.get("reason", "")})
    save_json(QUEUE, queue)
    print(f"ledger: wrote {QUEUE} with {len(queue)} Tier 1 item(s)")
    for q in queue:
        print(f"  [{q['status']}] {q['file']} (score {q['score']}, max CCN {q['max_ccn']}, high sec {q['sec_high']})")
    return 0


def cmd_start_item(args) -> int:
    f = norm(args.file)
    if not Path(f).exists():
        print(f"ledger: {f} does not exist", file=sys.stderr)
        return 2
    if sh(["git", "status", "--porcelain"]).stdout.strip():
        print("ledger: working tree not clean; commit or revert first", file=sys.stderr)
        return 2
    ok, out = run_measure()
    if not ok:
        print("ledger: measurement failed\n" + out, file=sys.stderr)
        return 2
    snap = {"file": f, "started": now(), "start_commit": git("rev-parse", "HEAD"), "before": file_metrics(f)}
    save_json(ITEMS / f"{slug(f)}.json", snap)
    queue = load_json(QUEUE, []) or []
    for q in queue:
        if q["file"] == f:
            q["status"] = "in_progress"
    save_json(QUEUE, queue)
    print(json.dumps(snap, indent=2))
    return 0


def cmd_snapshot_baseline(args) -> int:
    """Phase 0: copy .ledger/metrics.json to .ledger/baseline.json. Refused
    once phase 0 is approved (the baseline is frozen from then on)."""
    state = load_json(STATE, {}) or {}
    if state.get("phases", {}).get("0") == "approved":
        print("ledger snapshot-baseline: refused; the baseline is frozen after phase 0 approval", file=sys.stderr)
        return 2
    metrics = load_json(LEDGER / "metrics.json")
    if not isinstance(metrics, dict):
        print("ledger snapshot-baseline: no .ledger/metrics.json; run `bash .ledger/measure.sh` first", file=sys.stderr)
        return 2
    save_json(LEDGER / "baseline.json", metrics)
    print("ledger: wrote .ledger/baseline.json from .ledger/metrics.json")
    return 0


def cmd_raise_baseline(args) -> int:
    """Owner, after merging a reviewed paydown: make the current metrics the new
    baseline. Refused during a run (before phase 5 is approved) and whenever any
    gated metric is worse than the baseline, so it can only tighten the gate."""
    state = load_json(STATE, {}) or {}
    if state.get("phases", {}).get("5") != "approved":
        print("ledger raise-baseline: refused; a run is in progress (phase 5 is not approved)", file=sys.stderr)
        return 2
    base, cur = load_json(LEDGER / "baseline.json"), load_json(LEDGER / "metrics.json")
    if not isinstance(base, dict) or not isinstance(cur, dict):
        print("ledger raise-baseline: need .ledger/baseline.json and .ledger/metrics.json "
              "(run `bash .ledger/measure.sh` first)", file=sys.stderr)
        return 2
    failures, notes = gate_compare(base, cur, 0.0)
    if failures:
        print("ledger raise-baseline: refused; these metrics are worse than the baseline:\n  "
              + "\n  ".join(failures), file=sys.stderr)
        return 2
    save_json(LEDGER / "baseline.json", cur)
    print("ledger: raised .ledger/baseline.json to the current metrics\n  " + "\n  ".join(notes))
    return 0


def cmd_skip_item(args) -> int:
    f = norm(args.file)
    queue = load_json(QUEUE, []) or []
    for q in queue:
        if q["file"] == f:
            q["status"] = "skipped"
            q["reason"] = args.reason
    save_json(QUEUE, queue)
    print(f"ledger: skipped {f}: {args.reason}")
    return 0


# ================================================================ verify
class Checks:
    def __init__(self):
        self.results: list[dict] = []

    def add(self, name: str, ok: bool, detail: str = "", warn_only: bool = False):
        status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        self.results.append({"check": name, "status": status, "detail": detail})

    @property
    def failed(self) -> bool:
        return any(r["status"] == "FAIL" for r in self.results)


def tree_clean(c: Checks):
    dirty = sh(["git", "status", "--porcelain"]).stdout.strip()
    c.add("working tree is clean (all work committed)", not dirty, dirty[:300])


def on_branch(c: Checks, cfg: dict):
    b = git("rev-parse", "--abbrev-ref", "HEAD")
    c.add(f"on work branch '{cfg['branch']}'", b == cfg["branch"], f"current: {b}")


# Lines that name failing tests: mocha/jest "1) name", pytest "FAILED ...",
# TAP "not ok", and common assertion / error wording.
FAILURE_LINE = re.compile(r"^\s*\d+\)\s|fail|error|✗|✖|not ok|expected|assert", re.I)


def failure_summary(output: str, limit: int = 15) -> str:
    """The lines most likely to name the failing tests, plus the last lines."""
    lines = [l.rstrip() for l in output.splitlines() if l.strip()]
    hits = [l for l in lines if FAILURE_LINE.search(l)][:limit]
    tail = lines[-5:]
    return "\n      ".join([*hits, "...", *tail] if hits else tail)[:3000]


def tests_pass(c: Checks, cfg: dict):
    """Run the test suite up to `test_attempts` times. A pass after a failure
    passes but adds a visible WARN; every run's full output is kept in
    .ledger/verify/tests-attempt<N>.log."""
    cmd = cfg.get("test_command")
    if not cmd:
        c.add("test command configured", False, "set test_command in .ledger/config.json")
        return
    attempts = max(1, int(cfg.get("test_attempts", 2)))
    VERIFY_DIR.mkdir(parents=True, exist_ok=True)
    for old in VERIFY_DIR.glob("tests-attempt*.log"):
        old.unlink()
    first_failure = ""
    for n in range(1, attempts + 1):
        log = VERIFY_DIR / f"tests-attempt{n}.log"
        try:
            r = sh(cmd, timeout=int(cfg.get("test_timeout_seconds", 1800)), env=tool_env())
            out, ok = r.stdout + r.stderr, r.returncode == 0
        except subprocess.TimeoutExpired as e:
            out, ok = f"{e.stdout or ''}{e.stderr or ''}\n[timed out]", False
        log.write_text(out, encoding="utf-8", errors="replace")
        if ok:
            c.add("test suite passes", True)
            if n > 1:
                c.add("test suite is stable", False,
                      f"failed on attempt 1, passed on attempt {n} (flaky); see {VERIFY_DIR}/tests-attempt1.log\n"
                      f"      {first_failure}", warn_only=True)
            return
        if n == 1:
            first_failure = failure_summary(out)
    c.add("test suite passes", False,
          f"failed {attempts} time(s); full output in {VERIFY_DIR}/tests-attempt*.log\n      {first_failure}")


def register_ok(c: Checks):
    p = Path("DEBT_REGISTER.md")
    if not p.exists():
        c.add("DEBT_REGISTER.md exists", False)
        return ""
    text = p.read_text(encoding="utf-8")
    missing = [s for s in REGISTER_SECTIONS if s.lower() not in text.lower()]
    c.add("DEBT_REGISTER.md has all required sections", not missing, "missing: " + ", ".join(missing) if missing else "")
    return text


def changed_since(commit: str, filt: str = "ACMRD") -> list[str]:
    out = git("diff", "--name-only", f"--diff-filter={filt}", f"{commit}..HEAD")
    return [norm(x) for x in out.splitlines() if x.strip()]


def source_untouched(c: Checks, cfg: dict):
    base = git("merge-base", cfg["base_branch"], "HEAD")
    if not base:
        c.add("source code unchanged in measurement phases", False, "cannot find merge-base with base branch")
        return
    changed = changed_since(base)
    hits = [p for p in changed if under(p, cfg["src_dirs"])]
    hits += [p for p in changed if is_test(p)]
    c.add("source code and tests unchanged (setup/measurement only)", not hits, ", ".join(sorted(set(hits)))[:300])


def protected_untouched(c: Checks, cfg: dict):
    """No protected path changed anywhere on the work branch."""
    base = git("merge-base", cfg["base_branch"], "HEAD")
    if not base:
        c.add("no protected paths changed", False, "cannot find merge-base with base branch")
        return
    hits = sorted(p for p in changed_since(base) if under(p, cfg.get("protected_paths", [])))
    c.add("no protected paths changed", not hits, ", ".join(hits)[:300])


def commits_with_files(start: str) -> list[tuple[str, str, list[str]]]:
    out = git("log", "--reverse", "--name-only", "--format=@@%H%x09%s", f"{start}..HEAD")
    commits, cur = [], None
    for line in out.splitlines():
        if line.startswith("@@"):
            sha, _, subj = line[2:].partition("\t")
            cur = (sha, subj, [])
            commits.append(cur)
        elif line.strip() and cur:
            cur[2].append(norm(line.strip()))
    return commits


def verify_phase0(c: Checks, cfg: dict):
    c.add("inside a git repository", bool(git("rev-parse", "--git-dir")))
    on_branch(c, cfg)
    c.add("config.json present", CONFIG.exists())
    missing_src = [d for d in cfg["src_dirs"] if not Path(d).exists()]
    c.add("src_dirs exist", bool(cfg["src_dirs"]) and not missing_src, "missing: " + ", ".join(missing_src))
    c.add(f"base branch '{cfg['base_branch']}' exists", bool(git("rev-parse", "--verify", "--quiet", cfg["base_branch"])))
    for name in ("ledger.py", "measure.sh"):
        c.add(f".ledger/{name} present", (LEDGER / name).exists())
    for tool in ("lizard", "jscpd"):
        c.add(f"{tool} installed", shutil.which(tool, path=tool_path()) is not None)
    c.add("semgrep installed (optional)", shutil.which("semgrep", path=tool_path()) is not None, warn_only=True)
    base = load_json(LEDGER / "baseline.json")
    c.add(".ledger/baseline.json valid", isinstance(base, dict) and "complex_functions" in base)
    cm = Path("CLAUDE.md")
    text = cm.read_text(encoding="utf-8").lower() if cm.exists() else ""
    for word in ("commands", "protected", "debt rules"):
        c.add(f"CLAUDE.md has a '{word}' section", f"# {word}" in text or f"## {word}" in text)
    c.add("BASELINE.md exists", Path("BASELINE.md").exists())
    gi = Path(".gitignore").read_text(encoding="utf-8") if Path(".gitignore").exists() else ""
    c.add(".gitignore excludes .ledger/reports/", ".ledger/reports" in gi)
    source_untouched(c, cfg)
    protected_untouched(c, cfg)
    tests_pass(c, cfg)
    tree_clean(c)


def verify_phase1(c: Checks, cfg: dict):
    on_branch(c, cfg)
    ok, out = run_measure()
    c.add("measurement runs", ok, "" if ok else out)
    liz = read_lizard(REPORTS / "lizard.csv")
    c.add("complexity report has functions", len(liz) > 0, f"{len(liz)} functions")
    c.add("churn report present", (REPORTS / "churn.csv").exists())
    c.add("duplication report present", (REPORTS / "jscpd-report.json").exists(), warn_only=True)
    text = register_ok(c)
    c.add("register contains the hotspot table", "| tier |" in text.lower())
    c.add("register lists at least one hotspot file", any(r["file"] in text for r in
          compute_hotspots(REPORTS, cfg["ccn_limit"], cfg["tier1_size"])[:5]))
    source_untouched(c, cfg)
    protected_untouched(c, cfg)
    tree_clean(c)


def verify_phase2(c: Checks, cfg: dict):
    on_branch(c, cfg)
    queue = load_json(QUEUE)
    c.add("queue.json exists and is a list", isinstance(queue, list))
    queue = queue or []
    text = register_ok(c)
    if queue:
        missing = [q["file"] for q in queue if not Path(q["file"]).exists()]
        c.add("every queued file exists", not missing, ", ".join(missing))
        c.add("every queued file is named in the register", all(q["file"] in text for q in queue))
    else:
        c.add("empty queue is explained in the register", "no tier 1" in text.lower())
    c.add("register has Tier 1 cost estimates", "monthly cost" in text.lower())
    source_untouched(c, cfg)
    protected_untouched(c, cfg)
    tree_clean(c)


def plan_path(f: str) -> Path:
    return ITEMS / f"{slug(f)}-plan.md"


def verify_phase3_plan(c: Checks, cfg: dict, item: str):
    f = norm(item)
    snap = load_json(ITEMS / f"{slug(f)}.json")
    if not snap:
        c.add("item was started with start-item", False, f"no snapshot for {f}")
        return
    on_branch(c, cfg)
    start = snap["start_commit"]
    changed = changed_since(start)
    c.add("characterization tests committed", any(is_test(p) for p in changed))
    c.add("target file not changed yet", f not in changed, "refactoring must wait for plan approval")
    src_changed = [p for p in changed if under(p, cfg["src_dirs"]) and not is_test(p)]
    c.add("no source code changed yet", not src_changed, ", ".join(src_changed)[:300])
    pp = plan_path(f)
    text = pp.read_text(encoding="utf-8").lower() if pp.exists() else ""
    c.add(f"plan written to {pp}", bool(text))
    for word in ("risk", "step"):
        c.add(f"plan covers '{word}'", word in text)
    tests_pass(c, cfg)
    tree_clean(c)


def verify_phase3(c: Checks, cfg: dict, item: str):
    f = norm(item)
    snap = load_json(ITEMS / f"{slug(f)}.json")
    if not snap:
        c.add("item was started with start-item", False, f"no snapshot for {f}")
        return
    on_branch(c, cfg)
    start = snap["start_commit"]
    approved = approvals()
    c.add("plan was approved by the auditor before refactoring", approved.get(f"3:{f}:plan") == "APPROVED")
    seq = commits_with_files(start)
    first_test = next((i for i, (_, _, fs) in enumerate(seq) if any(is_test(x) for x in fs)), None)
    first_src = next((i for i, (_, _, fs) in enumerate(seq) if f in fs), None)
    c.add("tests were committed before the first change to the target",
          first_test is not None and (first_src is None or first_test < first_src),
          f"first test commit #{first_test}, first target commit #{first_src}")
    commits = git("log", "--format=%s", f"{start}..HEAD").splitlines()
    c.add("work committed in small steps (>= 2 commits)", len(commits) >= 2, f"{len(commits)} commits")
    c.add("at least one refactor(...)/fix(...) commit",
          any(m.startswith(("refactor(", "fix(")) for m in commits))
    changed = changed_since(start, "ACMR")
    deleted = changed_since(start, "D")
    c.add("characterization tests added or updated", any(is_test(p) for p in changed),
          "test files changed: " + ", ".join(p for p in changed if is_test(p))[:300])
    c.add("no test files deleted", not any(is_test(p) for p in deleted), ", ".join(deleted)[:300])
    prot = sorted(p for p in changed + deleted if under(p, cfg.get("protected_paths", [])))
    c.add("no protected paths touched", not prot, ", ".join(prot)[:300])
    control = (".ledger/ledger.py", ".ledger/measure.sh", ".ledger/baseline.json", ".ledger/config.json")
    stray = [p for p in changed + deleted if p in control]
    c.add("no edits to ledger control files", not stray, ", ".join(stray))
    tests_pass(c, cfg)
    ok, out = run_measure()
    c.add("measurement runs", ok, "" if ok else out)
    before, after = snap["before"], file_metrics(f)
    worse = [k for k in ("max_ccn", "complex_functions", "sec_high", "sec_medium") if after[k] > before[k]]
    better = [k for k in ("max_ccn", "complex_functions", "duplicated_lines", "sec_high", "sec_medium")
              if after[k] < before[k]]
    c.add("no metric for this file got worse", not worse, f"before {before} after {after}")
    c.add("at least one metric for this file improved", bool(better), "improved: " + ", ".join(better))
    base = load_json(LEDGER / "baseline.json", {})
    cur = load_json(LEDGER / "metrics.json", {})
    fails, _ = gate_compare(base, cur, 0.1)
    c.add("whole-repo gate versus baseline passes", not fails, "; ".join(fails))
    text = register_ok(c)
    done = text.split("## Done", 1)[1] if "## Done" in text else ""
    c.add("item recorded in the register's Done section", f in done)
    tree_clean(c)


def verify_phase3_overall(c: Checks, cfg: dict):
    on_branch(c, cfg)
    queue = load_json(QUEUE, []) or []
    approved = approvals()
    stuck = [q["file"] for q in queue if q["status"] == "in_progress"]
    c.add("no item left in progress", not stuck, ", ".join(stuck))
    for q in queue:
        if q["status"] == "done":
            c.add(f"fix approved: {q['file']}", approved.get(f"3:{q['file']}") == "APPROVED")
        elif q["status"] == "skipped":
            c.add(f"skip has a reason: {q['file']}", bool(q.get("reason")))
            snap = load_json(ITEMS / f"{slug(q['file'])}.json")
            if snap:
                diff = git("diff", "--name-only", snap["start_commit"], "HEAD", "--", q["file"])
                c.add(f"skipped item fully reverted: {q['file']}", not diff)
    done = sum(q["status"] == "done" for q in queue)
    todo = sum(q["status"] == "todo" for q in queue)
    c.add("fix budget respected or queue finished",
          todo == 0 or done >= int(cfg.get("max_fixes_per_run", 3)) or not queue
          or all(q["status"] != "todo" for q in queue[:int(cfg.get("max_fixes_per_run", 3))]),
          f"{done} done, {todo} still to do")
    ok, out = run_measure()
    c.add("measurement runs", ok, "" if ok else out)
    fails, _ = gate_compare(load_json(LEDGER / "baseline.json", {}), load_json(LEDGER / "metrics.json", {}), 0.1)
    c.add("whole-repo gate versus baseline passes", not fails, "; ".join(fails))
    protected_untouched(c, cfg)
    tests_pass(c, cfg)
    tree_clean(c)


def verify_phase4(c: Checks, cfg: dict):
    on_branch(c, cfg)
    ci = Path(cfg["ci_file"])
    c.add(f"CI workflow {ci} exists", ci.exists())
    text = ci.read_text(encoding="utf-8") if ci.exists() else ""
    c.add("CI workflow runs the ledger gate", "ledger.py gate" in text)
    pinned = (load_json(LEDGER / "baseline.json", {}) or {}).get("tools") or {}
    if pinned:
        wanted = [pin_text(tool, v) for tool, v in pinned.items() if v and pin_text(tool, v)]
        missing = [w for w in wanted if w not in text]
        c.add("CI workflow pins the baseline tool versions", not missing, "missing: " + ", ".join(missing))
    else:
        c.add("CI workflow pins the baseline tool versions", False,
              "baseline.json has no tool versions; cannot check", warn_only=True)
    ok, out = run_measure()
    c.add("measurement runs", ok, "" if ok else out)
    fails, _ = gate_compare(load_json(LEDGER / "baseline.json", {}), load_json(LEDGER / "metrics.json", {}), 0.1)
    c.add("gate passes locally", not fails, "; ".join(fails))
    protected_untouched(c, cfg)
    tests_pass(c, cfg)
    tree_clean(c)


def pin_text(tool: str, version: str) -> str:
    """How the gate workflow installs `tool` at `version`."""
    return {"lizard": f"lizard=={version}", "semgrep": f"semgrep=={version}",
            "jscpd": f"jscpd@{version}"}.get(tool, "")


def cmd_render_gate(args) -> int:
    """Write the CI gate workflow from the template, pinning the locally
    installed tool versions; the Semgrep step is dropped if it is not installed."""
    cfg = config()
    versions = tool_versions()
    missing = [t for t in ("lizard", "jscpd") if not versions[t]]
    if missing:
        print("ledger render-gate: not installed (or no version found): " + ", ".join(missing), file=sys.stderr)
        return 2
    lines = []
    for line in Path(args.template).read_text(encoding="utf-8").splitlines():
        if "{{SEMGREP_VERSION}}" in line and not versions["semgrep"]:
            continue
        for tool in TOOLS:
            if versions[tool]:
                line = line.replace("{{" + tool.upper() + "_VERSION}}", versions[tool])
        lines.append(line)
    out = Path(cfg["ci_file"])
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"ledger: wrote {out} (" + ", ".join(f"{t} {v}" for t, v in versions.items() if v) + ")")
    return 0


def verify_phase5(c: Checks, cfg: dict):
    on_branch(c, cfg)
    for name in ("PROGRESS.md", "PR_DESCRIPTION.md"):
        c.add(f"{name} exists", Path(name).exists())
    approved = approvals()
    for ph in ("0", "1", "2", "3", "4"):
        c.add(f"phase {ph} approved by the auditor", approved.get(ph) == "APPROVED")
    for q in load_json(QUEUE, []) or []:
        key = f"3:{q['file']}"
        if q["status"] == "done":
            c.add(f"fix approved: {q['file']}", approved.get(key) == "APPROVED")
        elif q["status"] == "in_progress":
            c.add(f"no unfinished item: {q['file']}", False, "in progress; finish, revert or mark skipped")
    protected_untouched(c, cfg)
    tests_pass(c, cfg)
    tree_clean(c)


def cmd_verify(args) -> int:
    cfg = config()
    c = Checks()
    ph = str(args.phase)
    step = args.step if (ph == "3" and args.item) else None
    {"0": lambda: verify_phase0(c, cfg), "1": lambda: verify_phase1(c, cfg),
     "2": lambda: verify_phase2(c, cfg),
     "3": lambda: (verify_phase3_overall(c, cfg) if not args.item else
                   (verify_phase3_plan if step == "plan" else verify_phase3)(c, cfg, args.item)),
     "4": lambda: verify_phase4(c, cfg), "5": lambda: verify_phase5(c, cfg)}[ph]()
    label = f"phase {ph}" + (f" item {norm(args.item)} ({step})" if args.item else "")
    result = {"phase": ph, "item": norm(args.item) if args.item else None, "step": step, "verified_at": now(),
              "commit": git("rev-parse", "--short", "HEAD"), "passed": not c.failed, "checks": c.results}
    save_json(verify_file(ph, args.item, step), result)
    print(f"Objective checks for {label} at {result['commit']}:")
    for r in c.results:
        print(f"  {r['status']:4}  {r['check']}" + (f"  -- {r['detail']}" if r["detail"] and r["status"] != "PASS" else ""))
    n_fail = sum(r["status"] == "FAIL" for r in c.results)
    print(f"\nRESULT: {'PASS' if not c.failed else 'FAIL'} ({len(c.results) - n_fail}/{len(c.results)} checks passed)")
    return 1 if c.failed else 0


def verify_file(ph: str, item: str | None, step: str | None) -> Path:
    name = f"phase-{ph}"
    if item:
        name += f"-{slug(item)}"
        if step == "plan":
            name += "-plan"
    return VERIFY_DIR / f"{name}.json"


# ================================================================ record / status
def approvals() -> dict:
    out = {}
    if APPROVALS.exists():
        for line in APPROVALS.read_text(encoding="utf-8").splitlines():
            try:
                a = json.loads(line)
            except json.JSONDecodeError:
                continue
            key = a["phase"] if not a.get("item") else f"{a['phase']}:{a['item']}"
            if a.get("step") == "plan":
                key += ":plan"
            out[key] = a["verdict"]
    return out


def cmd_record(args) -> int:
    ph = str(args.phase)
    item = norm(args.item) if args.item else None
    step = args.step if (ph == "3" and item) else None
    if args.verdict == "APPROVED":
        v = load_json(verify_file(ph, item, step))
        head = git("rev-parse", "--short", "HEAD")
        if not v or not v.get("passed") or v.get("commit") != head:
            print("ledger record: refusing APPROVED - no passing objective verification at the current "
                  "commit. Run `ledger.py verify` first.", file=sys.stderr)
            return 2
    entry = {"at": now(), "phase": ph, "item": item, "step": step, "verdict": args.verdict, "by": args.by,
             "attempt": args.attempt, "commit": git("rev-parse", "--short", "HEAD"), "notes": args.notes}
    APPROVALS.parent.mkdir(exist_ok=True)
    with APPROVALS.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry) + "\n")
    state = load_json(STATE, {"phases": {}, "items": {}, "current": 0})
    if item:
        state.setdefault("items", {})[item + (":plan" if step == "plan" else "")] = args.verdict.lower()
        if args.verdict == "APPROVED" and step != "plan":
            queue = load_json(QUEUE, []) or []
            for q in queue:
                if q["file"] == item:
                    q["status"] = "done"
            save_json(QUEUE, queue)
    else:
        state.setdefault("phases", {})[ph] = args.verdict.lower()
        if args.verdict == "APPROVED":
            state["current"] = max(int(state.get("current", 0)), int(ph) + 1)
    if args.verdict == "BLOCKED":
        state["blocked"] = {"phase": ph, "item": item, "notes": args.notes, "at": now()}
    save_json(STATE, state)
    print(f"ledger: recorded {args.verdict} for phase {ph}" + (f" item {item} ({step or 'final'})" if item else ""))
    return 0


def cmd_status(args) -> int:
    state = load_json(STATE)
    if not state:
        print("ledger: not initialised (no .ledger/state.json). Next: phase 0 setup.")
        return 0
    names = {0: "setup", 1: "measure", 2: "prioritise", 3: "fix", 4: "prevent", 5: "report"}
    print(f"Started: {state.get('started')}")
    if config().get("roadmap"):
        print(f"Roadmap: {config()['roadmap']}")
    queue = load_json(QUEUE, []) or []
    for i in range(6):
        label = state.get("phases", {}).get(str(i), "pending")
        if i == 3 and queue:
            done = sum(q["status"] in ("done", "skipped") for q in queue)
            label = f"{done}/{len(queue)} items finished"
        print(f"  phase {i} {names[i]:<10} {label}")
    for q in queue:
        print(f"    item {q['file']}: {q['status']}")
    if state.get("blocked"):
        print(f"BLOCKED: {state['blocked']}")
    nxt = state.get("current", 0)
    print(f"Next phase: {nxt} {names.get(nxt, 'complete')}")
    return 0


# ================================================================ main
def main() -> int:
    p = argparse.ArgumentParser(prog="ledger", description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("init")
    s.add_argument("--src", nargs="+")
    s.add_argument("--test-command")
    s.add_argument("--base-branch")
    s.add_argument("--protected", nargs="+")
    s.add_argument("--tool-dir", nargs="+", help="folders holding lizard/jscpd/semgrep if not on PATH")
    s.set_defaults(func=cmd_init)

    s = sub.add_parser("render-gate")
    s.add_argument("--template", required=True)
    s.set_defaults(func=cmd_render_gate)

    s = sub.add_parser("churn")
    s.add_argument("--since", default="12 months ago")
    s.set_defaults(func=cmd_churn)

    s = sub.add_parser("metrics")
    s.add_argument("--reports", default=str(REPORTS))
    s.add_argument("--ccn-limit", type=int)
    s.set_defaults(func=cmd_metrics)

    s = sub.add_parser("hotspots")
    s.add_argument("--reports", default=str(REPORTS))
    s.add_argument("--tier1", type=int)
    s.add_argument("--limit", type=int, default=0)
    g = s.add_mutually_exclusive_group()
    g.add_argument("--markdown", action="store_true")
    g.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_hotspots)

    s = sub.add_parser("gate")
    s.add_argument("--baseline", default=str(LEDGER / "baseline.json"))
    s.add_argument("--current", default=str(LEDGER / "metrics.json"))
    s.add_argument("--dup-tolerance", type=float, default=0.1)
    s.set_defaults(func=cmd_gate)

    s = sub.add_parser("snapshot-baseline")
    s.set_defaults(func=cmd_snapshot_baseline)

    s = sub.add_parser("queue")
    s.add_argument("--order", nargs="+", help="reorder the existing queue (estimated cost, security first)")
    s.set_defaults(func=cmd_queue)

    s = sub.add_parser("raise-baseline")
    s.set_defaults(func=cmd_raise_baseline)

    s = sub.add_parser("start-item")
    s.add_argument("file")
    s.set_defaults(func=cmd_start_item)

    s = sub.add_parser("skip-item")
    s.add_argument("file")
    s.add_argument("--reason", required=True)
    s.set_defaults(func=cmd_skip_item)

    s = sub.add_parser("verify")
    s.add_argument("--phase", required=True, choices=["0", "1", "2", "3", "4", "5"])
    s.add_argument("--item")
    s.add_argument("--step", choices=["plan", "final"], default="final")
    s.set_defaults(func=cmd_verify)

    s = sub.add_parser("record")
    s.add_argument("--phase", required=True, choices=["0", "1", "2", "3", "4", "5"])
    s.add_argument("--item")
    s.add_argument("--step", choices=["plan", "final"], default="final")
    s.add_argument("--verdict", required=True, choices=["APPROVED", "REJECTED", "BLOCKED"])
    s.add_argument("--by", default="ledger-auditor")
    s.add_argument("--attempt", type=int, default=1)
    s.add_argument("--notes", default="")
    s.set_defaults(func=cmd_record)

    s = sub.add_parser("status")
    s.set_defaults(func=cmd_status)

    args = p.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
