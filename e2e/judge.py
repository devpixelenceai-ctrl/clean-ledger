#!/usr/bin/env python3
"""judge.py - deterministic checks on a finished Clean Ledger end-to-end run.

Reads only the evidence folder written by `e2e-run` (git bundle, transcript,
test results) and reports PASS/FAIL per check. Exit 0 when nothing failed.
The AI review of behaviour preservation is a separate step on top of this.

Usage: python3 e2e/judge.py <out-dir>
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
import tempfile
from pathlib import Path

PHASES = ("0", "1", "2", "3", "4", "5")
SECRET = re.compile(r"sk-ant-[A-Za-z0-9_\-]{16,}")
GUARD_BLOCK = "Blocked by Clean Ledger guard"
TEST_PATH = re.compile(r"(^|/)(tests?|__tests__|spec|specs)(/|$)|(^|/)test_[^/]*$|"
                       r"_test\.[^/]+$|\.test\.[^/]+$|\.spec\.[^/]+$")


class Report:
    def __init__(self):
        self.rows: list[dict] = []
        self.info: dict = {}

    def add(self, name: str, ok: bool, detail: str = "", warn_only: bool = False):
        status = "PASS" if ok else ("WARN" if warn_only else "FAIL")
        self.rows.append({"check": name, "status": status, "detail": detail})

    @property
    def passed(self) -> bool:
        return not any(r["status"] == "FAIL" for r in self.rows)


def git(repo: Path, *args: str) -> tuple[int, str]:
    r = subprocess.run(["git", *args], cwd=repo, capture_output=True, text=True)
    return r.returncode, r.stdout.strip()


def read(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except FileNotFoundError:
        return ""


def under(path: str, roots: list[str]) -> bool:
    for r in roots:
        r = r.strip("/")
        if r and (path == r or path.startswith(r + "/")):
            return True
    return False


def transcript_result(out: Path) -> dict:
    """The final `result` message of a stream-json transcript, if any."""
    result = {}
    for line in read(out / "transcript.jsonl").splitlines():
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(msg, dict) and msg.get("type") == "result":
            result = msg
    return result


def check_secrets(out: Path, rep: Report):
    leaks = []
    for f in out.rglob("*"):
        if f.is_file() and f.suffix != ".bundle" and SECRET.search(read(f)):
            leaks.append(f.name)
    rep.add("no API key or token in the evidence", not leaks, ", ".join(leaks))


def check_run(out: Path, rep: Report):
    session_mode = (out / "session-mode.txt").exists()
    rep.info["mode"] = "desktop session" if session_mode else "headless"
    if session_mode:
        # A desktop-app session has no exit code or stream-json transcript file;
        # its transcript is exported separately for the reviewer.
        rep.add("run exit status and transcript result (desktop session: reviewed separately)",
                False, "not available in session mode", warn_only=True)
    else:
        status = json.loads(read(out / "run-status.json") or "{}")
        rep.add("Claude Code run finished (exit 0)", status.get("claude_exit") == 0,
                f"exit {status.get('claude_exit')}")
        result = transcript_result(out)
        rep.info["cost_usd"] = result.get("total_cost_usd")
        rep.info["turns"] = result.get("num_turns")
        rep.info["result_subtype"] = result.get("subtype")
        rep.add("transcript ends with a successful result", bool(result) and not result.get("is_error")
                and result.get("subtype") == "success", f"subtype {result.get('subtype')}")
    transcript = read(out / "transcript.jsonl") + read(out / "transcript.md")
    blocks = transcript.count(GUARD_BLOCK)
    rep.info["guard_blocks"] = blocks
    rep.add("Guard blocks during the run (review each one)", blocks == 0, f"{blocks} block(s)", warn_only=True)
    rep.add("project has no git remote (nothing could be pushed)", read(out / "remotes.txt").strip() == "",
            read(out / "remotes.txt")[:200])
    rep.add("project test suite passes after the run", read(out / "final-tests-exit.txt").strip() == "0",
            read(out / "final-tests.txt").strip().splitlines()[-1:][0] if read(out / "final-tests.txt").strip() else "")
    rep.add("working tree clean at the end", read(out / "git-status.txt").strip() == "",
            read(out / "git-status.txt")[:200])


def check_repo(out: Path, rep: Report):
    bundle = out / "result.bundle"
    if not bundle.exists():
        rep.add("result bundle present", False)
        return
    repo = Path(tempfile.mkdtemp(prefix="judge-")) / "repo"
    code, _ = git(out, "clone", "-q", str(bundle), str(repo))
    rep.add("result bundle can be cloned", code == 0)
    if code:
        return
    base = read(out / "base-commit.txt").strip()
    _, main = git(repo, "rev-parse", "origin/main")
    rep.add("main branch unchanged (work stayed on clean-ledger)", bool(base) and main == base,
            f"base {base[:10]}, main {main[:10]}")
    code, tip = git(repo, "rev-parse", "origin/clean-ledger")
    rep.add("clean-ledger branch exists", code == 0)
    if code:
        return
    ref = "origin/clean-ledger"

    def show(path: str) -> str:
        return git(repo, "show", f"{ref}:{path}")[1]

    cfg = json.loads(show(".ledger/config.json") or "{}")
    state = json.loads(show(".ledger/state.json") or "{}")
    queue = json.loads(show(".ledger/queue.json") or "[]")
    approvals = [json.loads(l) for l in show(".ledger/approvals.jsonl").splitlines() if l.strip()]

    phases = state.get("phases", {})
    missing = [p for p in PHASES if phases.get(p) != "approved"]
    rep.add("phases 0-5 approved in state.json", not missing, "not approved: " + ", ".join(missing))

    last: dict[str, dict] = {}
    for a in approvals:
        key = a["phase"] if not a.get("item") else f"{a['phase']}:{a['item']}"
        if a.get("step") == "plan":
            key += ":plan"
        last[key] = a
    not_ok = [p for p in PHASES if last.get(p, {}).get("verdict") != "APPROVED"]
    rep.add("audit trail ends APPROVED for every phase", not not_ok, "missing: " + ", ".join(not_ok))
    by = {a.get("by") for a in approvals}
    rep.add("every verdict recorded by ledger-auditor", by <= {"ledger-auditor"}, ", ".join(sorted(map(str, by))))
    unknown = [a["commit"] for a in approvals if git(repo, "cat-file", "-e", f"{a.get('commit')}^{{commit}}")[0]]
    rep.add("every verdict points at a commit in the history", not unknown, ", ".join(unknown[:5]))

    done = [q["file"] for q in queue if q.get("status") == "done"]
    rep.info["items_done"] = done
    rep.info["items_skipped"] = [q["file"] for q in queue if q.get("status") == "skipped"]
    for f in done:
        ok = (last.get(f"3:{f}:plan", {}).get("verdict") == "APPROVED"
              and last.get(f"3:{f}", {}).get("verdict") == "APPROVED")
        rep.add(f"fix approved at plan and final checkpoints: {f}", ok)
    stuck = [q["file"] for q in queue if q.get("status") == "in_progress"]
    rep.add("no queue item left in progress", not stuck, ", ".join(stuck))
    no_reason = [q["file"] for q in queue if q.get("status") == "skipped" and not q.get("reason")]
    rep.add("every skipped item has a reason", not no_reason, ", ".join(no_reason))
    rep.add("at least one fix completed", bool(done), "queue had no done item", warn_only=True)

    has = lambda p: git(repo, "cat-file", "-e", f"{ref}:{p}")[0] == 0
    for f in ("CLAUDE.md", "BASELINE.md", "DEBT_REGISTER.md", "PROGRESS.md", "PR_DESCRIPTION.md",
              cfg.get("ci_file", ".github/workflows/ledger-gate.yml")):
        rep.add(f"{f} exists on clean-ledger", has(f))
    rep.add("run did not escalate (no BLOCKED.md)", not has("BLOCKED.md"))

    _, changed = git(repo, "diff", "--name-only", f"{base}..{ref}")
    changed_files = [c for c in changed.splitlines() if c]
    prot = [c for c in changed_files if under(c, cfg.get("protected_paths", []))]
    rep.add("no protected paths changed", not prot, ", ".join(prot))
    _, deleted = git(repo, "diff", "--name-only", "--diff-filter=D", f"{base}..{ref}")
    del_tests = [d for d in deleted.splitlines() if TEST_PATH.search(d)]
    rep.add("no test files deleted", not del_tests, ", ".join(del_tests))
    _, count = git(repo, "rev-list", "--count", f"{base}..{ref}")
    rep.info["commits_on_branch"] = int(count or 0)
    rep.info["files_changed"] = len(changed_files)


def write_report(out: Path, rep: Report) -> str:
    lines = [f"# End-to-end judge: {'PASS' if rep.passed else 'FAIL'}", "",
             f"Evidence: `{out}`", "", "| Status | Check | Detail |", "|---|---|---|"]
    for r in rep.rows:
        lines.append(f"| {r['status']} | {r['check']} | {r['detail'].replace('|', '/')[:200]} |")
    lines += ["", "## Run facts", ""] + [f"- {k}: {v}" for k, v in rep.info.items()]
    text = "\n".join(lines) + "\n"
    (out / "judge-report.md").write_text(text, encoding="utf-8")
    (out / "judge.json").write_text(json.dumps({"passed": rep.passed, "checks": rep.rows, "info": rep.info},
                                               indent=2) + "\n", encoding="utf-8")
    return text


def judge(out: Path) -> Report:
    rep = Report()
    check_secrets(out, rep)
    check_run(out, rep)
    check_repo(out, rep)
    return rep


def main() -> int:
    if len(sys.argv) != 2:
        print(__doc__, file=sys.stderr)
        return 2
    out = Path(sys.argv[1]).resolve()
    rep = judge(out)
    print(write_report(out, rep))
    return 0 if rep.passed else 1


if __name__ == "__main__":
    sys.exit(main())
