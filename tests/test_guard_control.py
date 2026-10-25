"""Guard: control files are blocked only on real writes (fix round 2).

The cases marked "from the e2e run" are commands the old rule blocked even
though they changed no control file.
"""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import commit_all, git, guard, make_repo, write_config


def ledger_repo(phase0_approved: bool = False) -> Path:
    repo = make_repo({"src/app.py": "x = 1\n"})
    write_config(repo)
    state = {"phases": {"0": "approved"}} if phase0_approved else {"phases": {}}
    (repo / ".ledger" / "state.json").write_text(json.dumps(state))
    commit_all(repo, "ledger")
    git(repo, "switch", "-q", "-c", "clean-ledger")
    return repo


def bash(cmd: str, cwd: Path) -> int:
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
    return guard(payload, env={"CLAUDE_PROJECT_DIR": str(cwd)}, cwd=cwd).returncode


ALLOWED = [
    # from the e2e run
    "python3 .ledger/ledger.py hotspots --markdown --limit 40; echo; awk -F, '$2>15' .ledger/reports/lizard.csv",
    "pip uninstall -y -q semgrep 2>&1 | tail -2; bash .ledger/measure.sh 2>/dev/null; cat .ledger/metrics.json",
    'git commit -q -m "chore(ledger): audit phase 4 APPROVED" && bash .ledger/measure.sh && pytest -q 2>&1 | tail -1',
    "cat >> CLAUDE.md <<'EOF'\n## Quality gate\nRun `bash .ledger/measure.sh`, then "
    "`cp .ledger/metrics.json .ledger/baseline.json` after review.\nEOF",
    'python3 .ledger/ledger.py record --phase 1 --verdict APPROVED --attempt 2 --notes "a > b; cp and write ok"',
    # ordinary reads and redirects elsewhere
    "cat .ledger/state.json | python3 -m json.tool > /tmp/state-pretty.json",
    "bash .ledger/measure.sh > .ledger/reports/measure.log 2>&1",
    "cp .ledger/approvals.jsonl /tmp/approvals-copy.jsonl",
    "git show HEAD:.ledger/state.json",
    "python3 -c \"import json; print(json.load(open('.ledger/state.json')))\"",
]

BLOCKED = [
    "echo '{}' > .ledger/state.json",
    "echo x>>.ledger/approvals.jsonl",
    "printf 'x' | tee -a .ledger/approvals.jsonl",
    "sed -i '' 's/REJECTED/APPROVED/' .ledger/approvals.jsonl",
    "rm .ledger/ledger.py",
    "mv .ledger/measure.sh /tmp/measure.sh",
    "cp /tmp/evil.py .ledger/ledger.py",
    "truncate -s 0 .ledger/approvals.jsonl",
    "git checkout -- .ledger/approvals.jsonl",
    "cd .ledger && echo '{}' > state.json",
    "python3 -c \"open('.ledger/state.json','w').write('{}')\"",
    "python3 - <<'EOF'\nimport pathlib\npathlib.Path('.ledger/approvals.jsonl').write_text('')\nEOF",
    "ln -sf /tmp/x .ledger/state.json",
]


class ControlFiles(unittest.TestCase):
    def setUp(self):
        self.repo = ledger_repo()

    def test_harmless_commands_are_allowed(self):
        for cmd in ALLOWED:
            with self.subTest(cmd=cmd):
                self.assertEqual(bash(cmd, self.repo), 0)

    def test_real_writes_are_blocked(self):
        for cmd in BLOCKED:
            with self.subTest(cmd=cmd):
                self.assertEqual(bash(cmd, self.repo), 2)

    def test_baseline_copy_allowed_before_phase0_approval(self):
        self.assertEqual(bash("cp .ledger/metrics.json .ledger/baseline.json", self.repo), 0)

    def test_baseline_copy_blocked_after_phase0_approval(self):
        repo = ledger_repo(phase0_approved=True)
        self.assertEqual(bash("cp .ledger/metrics.json .ledger/baseline.json", repo), 2)
        self.assertEqual(bash("echo '{}' > .ledger/config.json", repo), 2)

    def test_unparseable_command_mentioning_a_control_file_is_blocked(self):
        self.assertEqual(bash("echo 'unbalanced > .ledger/state.json", self.repo), 2)


class EnvironmentDumps(unittest.TestCase):
    def test_env_dumps_are_blocked(self):
        repo = ledger_repo()
        for cmd in ("env | grep -iE 'proxy|ssl'", "printenv", "export -p", "declare -x",
                    "cat /proc/self/environ"):
            with self.subTest(cmd=cmd):
                self.assertEqual(bash(cmd, repo), 2)

    def test_env_used_to_run_a_command_is_allowed(self):
        repo = ledger_repo()
        self.assertEqual(bash("env PYTHONDONTWRITEBYTECODE=1 python3 -m pytest -q", repo), 0)


class ActiveFromRunStart(unittest.TestCase):
    """`/clean-ledger:run` creates .ledger/ first, so the Guard is on before init."""

    def setUp(self):
        self.repo = make_repo({"src/app.py": "x = 1\n"})
        (self.repo / ".ledger").mkdir()

    def test_blocks_before_config_exists(self):
        self.assertEqual(bash("env | grep -i proxy", self.repo), 2)
        self.assertEqual(bash("git push origin main", self.repo), 2)

    def test_allows_setup_before_config_exists(self):
        self.assertEqual(bash("python3 --version && git status", self.repo), 0)

    def test_repo_without_ledger_folder_is_ignored(self):
        plain = make_repo({"a.txt": "a\n"})
        self.assertEqual(bash("env | grep -i proxy", plain), 0)


if __name__ == "__main__":
    unittest.main()
