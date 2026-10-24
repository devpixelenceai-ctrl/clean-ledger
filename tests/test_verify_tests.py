"""Tests for how `ledger.py verify` runs the project's test suite (fix #2)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import commit_all, git, ledger, make_repo, write_config


def repo_with_test_command(cmd: str, **cfg) -> Path:
    repo = make_repo({"src/app.py": "x = 1\n", ".gitignore": ".ledger/verify/\n"})
    write_config(repo, test_command=cmd, **cfg)
    commit_all(repo, "config")
    git(repo, "switch", "-q", "-c", "clean-ledger")
    return repo


def check_lines(out: str) -> list[str]:
    return [l for l in out.splitlines() if "test suite" in l]


class VerifyTestRuns(unittest.TestCase):
    def test_passing_suite(self):
        repo = repo_with_test_command("echo all good")
        out = ledger(repo, "verify", "--phase", "5").stdout
        self.assertIn("PASS  test suite passes", out)
        self.assertNotIn("WARN  test suite is stable", out)

    def test_flaky_suite_passes_with_a_visible_warning(self):
        counter = Path(tempfile.mkdtemp()) / "count"
        cmd = (f'n=$(cat "{counter}" 2>/dev/null || echo 0); n=$((n+1)); echo $n > "{counter}"; '
               f'if [ $n -eq 1 ]; then echo "1) flaky test failing: got 403"; exit 1; fi; echo ok')
        repo = repo_with_test_command(cmd)
        out = ledger(repo, "verify", "--phase", "5").stdout
        self.assertIn("PASS  test suite passes", out)
        self.assertIn("WARN  test suite is stable", out)
        self.assertIn("passed on attempt 2", out)
        self.assertIn("flaky test failing: got 403", out)

    def test_failing_suite_fails_and_keeps_the_full_log(self):
        noise = "x" * 2000
        cmd = f'echo "2) important test failing: expected 1 got 2"; echo "{noise}"; exit 1'
        repo = repo_with_test_command(cmd)
        out = ledger(repo, "verify", "--phase", "5").stdout
        self.assertIn("FAIL  test suite passes", out)
        # the failing test is named even though 2,000 characters follow it
        self.assertIn("important test failing", out)
        logs = list((repo / ".ledger" / "verify").glob("tests-attempt*.log"))
        self.assertEqual(len(logs), 2, logs)
        self.assertIn(noise, logs[0].read_text())

    def test_names_mocha_failures(self):
        cmd = ("printf '  1290 passing\\n  1 failing\\n\\n  1) req.ip\\n       should return the remote address:\\n"
               "     Error: expected 200 \"OK\", got 403\\n'; exit 1")
        repo = repo_with_test_command(cmd, test_attempts=1)
        out = ledger(repo, "verify", "--phase", "5").stdout
        self.assertIn("1) req.ip", out)
        self.assertIn("got 403", out)

    def test_attempts_are_configurable(self):
        repo = repo_with_test_command("exit 1", test_attempts=1)
        out = ledger(repo, "verify", "--phase", "5").stdout
        self.assertIn("FAIL  test suite passes", out)
        logs = list((repo / ".ledger" / "verify").glob("tests-attempt*.log"))
        self.assertEqual(len(logs), 1)


if __name__ == "__main__":
    unittest.main()
