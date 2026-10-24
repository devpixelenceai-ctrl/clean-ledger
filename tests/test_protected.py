"""Protected paths are checked by verify in every phase (fix #3)."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import commit_all, git, ledger, make_repo, write_config

FILES = {"src/app.py": "x = 1\n", "vendor/dep.js": "v\n", "lib/core.js": "c\n",
         "library.js": "l\n", ".gitignore": ".ledger/verify/\n.ledger/reports/\n"}


def work_repo() -> Path:
    repo = make_repo(FILES)
    write_config(repo, protected_paths=["vendor", "lib"])
    commit_all(repo, "config")
    git(repo, "switch", "-q", "-c", "clean-ledger")
    return repo


def check(out: str, name: str) -> str:
    for line in out.splitlines():
        if name in line:
            return line.strip()
    return ""


class ProtectedPathsEveryPhase(unittest.TestCase):
    def test_flags_protected_change_in_phases_0_2_4_5(self):
        repo = work_repo()
        (repo / "vendor" / "dep.js").write_text("changed\n")
        commit_all(repo, "touch vendor")
        for phase in ("0", "2", "4", "5"):
            with self.subTest(phase=phase):
                out = ledger(repo, "verify", "--phase", phase).stdout
                self.assertTrue(check(out, "no protected paths changed").startswith("FAIL"), out)
                self.assertIn("vendor/dep.js", out)

    def test_passes_when_only_unprotected_files_change(self):
        repo = work_repo()
        (repo / "library.js").write_text("changed\n")  # starts with "lib" but is not lib/
        commit_all(repo, "touch library.js")
        out = ledger(repo, "verify", "--phase", "2").stdout
        self.assertTrue(check(out, "no protected paths changed").startswith("PASS"), out)

    def test_phase3_item_does_not_confuse_prefixes(self):
        repo = work_repo()
        start = git(repo, "rev-parse", "HEAD")
        items = repo / ".ledger" / "items"
        items.mkdir(parents=True)
        before = {"max_ccn": 0, "complex_functions": 0, "duplicated_lines": 0,
                  "sec_high": 0, "sec_medium": 0, "nloc": 0}
        (items / "src-app-py.json").write_text(json.dumps(
            {"file": "src/app.py", "start_commit": start, "before": before}))
        commit_all(repo, "start item")
        (repo / "library.js").write_text("changed\n")
        commit_all(repo, "touch library.js")
        out = ledger(repo, "verify", "--phase", "3", "--item", "src/app.py").stdout
        self.assertTrue(check(out, "no protected paths").startswith("PASS"), out)


if __name__ == "__main__":
    unittest.main()
