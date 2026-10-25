"""Tests for hooks/guard.py (the PreToolUse safety hook)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from helpers import git, guard, make_repo, write_config, commit_all


def ledger_repo(branch: str = "clean-ledger", **cfg) -> Path:
    repo = make_repo({"src/app.py": "x = 1\n"}, branch="main")
    write_config(repo, **cfg)
    commit_all(repo, "ledger config")
    if branch != "main":
        git(repo, "switch", "-q", "-c", branch)
    return repo


def bash(cmd: str, cwd: Path, project_dir: Path | None = None):
    payload = {"tool_name": "Bash", "tool_input": {"command": cmd}, "cwd": str(cwd)}
    env = {"CLAUDE_PROJECT_DIR": str(project_dir or cwd)}
    return guard(payload, env=env, cwd=cwd)


def edit(path: Path, cwd: Path, project_dir: Path | None = None, tool: str = "Edit"):
    payload = {"tool_name": tool, "tool_input": {"file_path": str(path)}, "cwd": str(cwd)}
    env = {"CLAUDE_PROJECT_DIR": str(project_dir or cwd)}
    return guard(payload, env=env, cwd=cwd)


class GuardInLedgerRepo(unittest.TestCase):
    def setUp(self):
        self.repo = ledger_repo(protected_paths=["vendor", "index.js"])

    def test_blocks_push(self):
        self.assertEqual(bash("git push origin clean-ledger", self.repo).returncode, 2)

    def test_allows_status(self):
        self.assertEqual(bash("git status", self.repo).returncode, 0)

    def test_blocks_git_subcommands_behind_global_options(self):
        for cmd in ("git -C . push", 'git -C "a b" push origin x', "git --no-pager push",
                    "git -c user.name=x commit --amend -m y", "git -C . reset --hard HEAD~1",
                    "git --git-dir=.git merge main"):
            with self.subTest(cmd=cmd):
                self.assertEqual(bash(cmd, self.repo).returncode, 2)

    def test_allows_harmless_git_with_global_options(self):
        for cmd in ("git -C . status", "git --no-pager log --oneline -3", "git -C . diff"):
            with self.subTest(cmd=cmd):
                self.assertEqual(bash(cmd, self.repo).returncode, 0)

    def test_blocks_control_file_edit(self):
        self.assertEqual(edit(self.repo / ".ledger" / "state.json", self.repo).returncode, 2)

    def test_blocks_protected_dir_edit(self):
        self.assertEqual(edit(self.repo / "vendor" / "lib.js", self.repo).returncode, 2)

    def test_blocks_protected_file_edit(self):
        self.assertEqual(edit(self.repo / "index.js", self.repo).returncode, 2)

    def test_allows_similar_name_outside_protected_dir(self):
        self.assertEqual(edit(self.repo / "vendored.js", self.repo).returncode, 0)

    def test_blocks_commit_on_other_branch(self):
        git(self.repo, "switch", "-q", "main")
        self.assertEqual(bash("git commit -m x", self.repo).returncode, 2)

    def test_allows_commit_on_work_branch(self):
        self.assertEqual(bash("git commit -m x", self.repo).returncode, 0)


class GuardFindsRepoFromParentFolder(unittest.TestCase):
    """The session may start in a parent folder of the ledger repo (fix #1)."""

    def setUp(self):
        self.parent = Path(tempfile.mkdtemp(prefix="ledger-parent-"))
        repo = ledger_repo()
        self.repo = self.parent / "app"
        repo.rename(self.repo)

    def test_blocks_push_after_cd(self):
        r = bash('cd "app" && git push origin clean-ledger', self.parent)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_blocks_push_with_git_dash_c(self):
        r = bash(f'git -C "{self.repo}" push', self.parent)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_blocks_push_when_hook_cwd_is_repo(self):
        r = bash("git push", self.repo, project_dir=self.parent)
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_blocks_control_file_edit_by_absolute_path(self):
        r = edit(self.repo / ".ledger" / "approvals.jsonl", self.parent, tool="Write")
        self.assertEqual(r.returncode, 2, r.stderr)

    def test_blocks_control_file_shell_overwrite_after_cd(self):
        # baseline.json is writable until phase 0 is approved (see test_guard_control)
        r = bash('cd app && cp x.json .ledger/state.json', self.parent)
        self.assertEqual(r.returncode, 2, r.stderr)


class GuardOutsideLedgerRepos(unittest.TestCase):
    def test_stays_out_of_the_way(self):
        plain = make_repo({"a.txt": "a\n"})
        self.assertEqual(bash("git push origin main", plain).returncode, 0)
        self.assertEqual(edit(plain / "a.txt", plain).returncode, 0)


if __name__ == "__main__":
    unittest.main()
