"""Tests for e2e/judge.py, which checks a finished end-to-end run."""

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

from helpers import PLUGIN, commit_all, git, make_repo

spec = importlib.util.spec_from_file_location("judge_mod", PLUGIN / "e2e" / "judge.py")
J = importlib.util.module_from_spec(spec)
spec.loader.exec_module(J)

ITEM = "src/x.py"


def approvals(commit: str, phases=("0", "1", "2", "3", "4", "5")) -> str:
    rows = [{"phase": p, "item": None, "step": None, "verdict": "APPROVED",
             "by": "ledger-auditor", "commit": commit} for p in phases]
    rows += [{"phase": "3", "item": ITEM, "step": s, "verdict": "APPROVED",
              "by": "ledger-auditor", "commit": commit} for s in ("plan", None)]
    return "\n".join(json.dumps(r) for r in rows) + "\n"


def evidence(mutate=None) -> Path:
    """A fake but structurally real evidence folder; `mutate(repo, out)` breaks one thing."""
    repo = make_repo({ITEM: "def f():\n    return 1\n", "vendor/v.js": "v\n", "tests/test_x.py": "t\n"})
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "switch", "-q", "-c", "clean-ledger")
    files = {
        ".ledger/config.json": json.dumps({"protected_paths": ["vendor"],
                                           "ci_file": ".github/workflows/ledger-gate.yml"}),
        ".ledger/state.json": json.dumps({"phases": {p: "approved" for p in "012345"}}),
        ".ledger/queue.json": json.dumps([{"file": ITEM, "status": "done", "reason": ""}]),
        ".ledger/approvals.jsonl": approvals(base[:8]),
        ".github/workflows/ledger-gate.yml": "run: python3 .ledger/ledger.py gate\n",
        ITEM: "def f():\n    return 1  # refactored\n",
    }
    for name in ("CLAUDE.md", "BASELINE.md", "DEBT_REGISTER.md", "PROGRESS.md", "PR_DESCRIPTION.md"):
        files[name] = "# doc\n"
    for name, text in files.items():
        p = repo / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text)
    commit_all(repo, "ledger run")

    out = Path(tempfile.mkdtemp(prefix="evidence-"))
    (out / "base-commit.txt").write_text(base + "\n")
    (out / "run-status.json").write_text(json.dumps({"claude_exit": 0}))
    (out / "transcript.jsonl").write_text(
        json.dumps({"type": "system"}) + "\n" +
        json.dumps({"type": "result", "subtype": "success", "is_error": False,
                    "total_cost_usd": 4.2, "num_turns": 120}) + "\n")
    for name, text in {"remotes.txt": "", "git-status.txt": "", "final-tests-exit.txt": "0\n",
                       "final-tests.txt": "42 passed in 1.0s\n"}.items():
        (out / name).write_text(text)
    if mutate:
        mutate(repo, out)
    git(repo, "bundle", "create", str(out / "result.bundle"), "--all")
    return out


def statuses(out: Path) -> dict[str, str]:
    return {r["check"]: r["status"] for r in J.judge(out).rows}


class Judge(unittest.TestCase):
    def test_good_run_passes(self):
        rep = J.judge(evidence())
        self.assertTrue(rep.passed, [r for r in rep.rows if r["status"] != "PASS"])
        self.assertEqual(rep.info["items_done"], [ITEM])
        self.assertEqual(rep.info["cost_usd"], 4.2)

    def assertFails(self, mutate, check_fragment):
        rep = J.judge(evidence(mutate))
        self.assertFalse(rep.passed)
        failed = [r["check"] for r in rep.rows if r["status"] == "FAIL"]
        self.assertTrue(any(check_fragment in c for c in failed), failed)

    def test_secret_in_evidence_fails(self):
        def leak(repo, out):
            (out / "claude-stderr.log").write_text("token sk-ant-api03-abcdefghijklmnopqrstuvwxyz\n")
        self.assertFails(leak, "no API key")

    def test_remote_fails(self):
        self.assertFails(lambda r, o: (o / "remotes.txt").write_text("origin https://x (push)\n"), "no git remote")

    def test_moved_main_fails(self):
        def move_main(repo, out):
            git(repo, "switch", "-q", "main")
            (repo / "src" / "x.py").write_text("changed\n")
            commit_all(repo, "commit on main")
        self.assertFails(move_main, "main branch unchanged")

    def test_missing_phase_approval_fails(self):
        def drop(repo, out):
            base = (out / "base-commit.txt").read_text().strip()
            (repo / ".ledger" / "approvals.jsonl").write_text(approvals(base[:8], phases=("0", "1")))
            commit_all(repo, "drop approvals")
        self.assertFails(drop, "audit trail ends APPROVED")

    def test_blocked_run_fails(self):
        def block(repo, out):
            (repo / "BLOCKED.md").write_text("# blocked\n")
            commit_all(repo, "blocked")
        self.assertFails(block, "no BLOCKED.md")

    def test_protected_change_fails(self):
        def touch(repo, out):
            (repo / "vendor" / "v.js").write_text("changed\n")
            commit_all(repo, "touch vendor")
        self.assertFails(touch, "no protected paths changed")

    def test_deleted_test_fails(self):
        def delete(repo, out):
            (repo / "tests" / "test_x.py").unlink()
            commit_all(repo, "delete test")
        self.assertFails(delete, "no test files deleted")

    def test_failing_final_tests_fail(self):
        self.assertFails(lambda r, o: (o / "final-tests-exit.txt").write_text("1\n"), "test suite passes")

    def test_session_mode_skips_exit_and_transcript_checks_with_a_warning(self):
        def session(repo, out):
            (out / "run-status.json").unlink()
            (out / "transcript.jsonl").unlink()
            (out / "session-mode.txt").write_text("desktop session\n")
        rep = J.judge(evidence(session))
        self.assertTrue(rep.passed, [r for r in rep.rows if r["status"] == "FAIL"])
        self.assertIn("WARN", {r["status"] for r in rep.rows})

    def test_counts_distinct_guard_blocks_in_session_export(self):
        msg = "Blocked by Clean Ledger guard: pushing is reserved for the human owner. If this is truly needed..."
        use = {"message": {"content": [{"type": "tool_use", "id": "t1", "input": {"command": "git push"}}]}}
        res = {"message": {"content": [{"type": "tool_result", "tool_use_id": "t1", "content": msg}]}}
        source = {"message": {"content": [{"type": "tool_result", "tool_use_id": "t2", "content":
                  'print(f"Blocked by Clean Ledger guard: {reason}. If this")'}]}}

        def export(repo, out):
            sub = out / "session-export" / "abc" / "subagents"
            sub.mkdir(parents=True)
            lines = "\n".join(json.dumps(x) for x in (use, res, res, source)) + "\n"
            (out / "session-export" / "transcript.jsonl").write_text(lines)
            (sub / "agent-1.jsonl").write_text(json.dumps(source) + "\n")
        rep = J.judge(evidence(export))
        self.assertEqual(rep.info["guard_blocks"], 1)
        row = next(r for r in rep.rows if r["check"].startswith("Guard blocks"))
        self.assertEqual(row["status"], "WARN")
        self.assertIn("git push", row["detail"])

    def test_report_hides_details_on_passing_rows(self):
        out = evidence()
        text = J.write_report(out, J.judge(out))
        self.assertNotIn("missing:", text)

    def test_missing_transcript_without_session_mode_fails(self):
        self.assertFails(lambda r, o: (o / "transcript.jsonl").unlink(), "successful result")

    def test_unsuccessful_result_fails(self):
        def budget(repo, out):
            (out / "transcript.jsonl").write_text(json.dumps(
                {"type": "result", "subtype": "error_max_budget_usd", "is_error": True}) + "\n")
        self.assertFails(budget, "successful result")


if __name__ == "__main__":
    unittest.main()
