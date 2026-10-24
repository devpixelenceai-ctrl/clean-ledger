"""Single files in src_dirs (fix #4) and jscpd path / duplicate counting (fix #7)."""

from __future__ import annotations

import importlib.util
import json
import os
import tempfile
import unittest
from pathlib import Path

from helpers import LEDGER_PY, commit_all, git, ledger, make_repo, write_config

spec = importlib.util.spec_from_file_location("ledger_mod", LEDGER_PY)
L = importlib.util.module_from_spec(spec)
spec.loader.exec_module(L)


def check(out: str, name: str) -> str:
    return next((l.strip() for l in out.splitlines() if name in l), "")


class SourceFiles(unittest.TestCase):
    def setUp(self):
        self.repo = make_repo({"index.js": "module.exports = 1\n", "lib/a.js": "a\n",
                               ".gitignore": ".ledger/verify/\n"})
        write_config(self.repo, src_dirs=["index.js", "lib"])
        commit_all(self.repo, "config")
        git(self.repo, "switch", "-q", "-c", "clean-ledger")

    def test_phase0_accepts_a_file_in_src_dirs(self):
        out = ledger(self.repo, "verify", "--phase", "0").stdout
        self.assertTrue(check(out, "src_dirs exist").startswith("PASS"), out)

    def test_change_to_a_source_file_is_detected(self):
        (self.repo / "index.js").write_text("module.exports = 2\n")
        commit_all(self.repo, "edit entry point")
        out = ledger(self.repo, "verify", "--phase", "2").stdout
        line = check(out, "source code and tests unchanged")
        self.assertTrue(line.startswith("FAIL"), out)
        self.assertIn("index.js", line)


class JscpdReading(unittest.TestCase):
    def setUp(self):
        self.root = Path(tempfile.mkdtemp(prefix="jscpd-"))
        self.reports = self.root / ".ledger" / "reports"
        self.reports.mkdir(parents=True)
        self.old = os.getcwd()
        os.chdir(self.root)

    def tearDown(self):
        os.chdir(self.old)

    def write_report(self, dups):
        side = lambda name, s, e: {"name": name, "start": s, "end": e}
        report = {"statistics": {"total": {"percentage": 1.5, "duplicatedLines": 9}},
                  "duplicates": [{"lines": e1 - s1 + 1, "firstFile": side(n1, s1, e1),
                                  "secondFile": side(n2, s2, e2)} for (n1, s1, e1, n2, s2, e2) in dups]}
        (self.reports / "jscpd-report.json").write_text(json.dumps(report))

    def test_absolute_names_become_repo_relative(self):
        a = str(self.root / "src" / "a" / "index.js")
        b = str(self.root / "src" / "b" / "util.js")
        self.write_report([(a, 1, 5, b, 10, 14)])
        per_file = L.read_jscpd(self.reports)["per_file"]
        self.assertEqual(per_file, {"src/a/index.js": 5, "src/b/util.js": 5})

    def test_short_name_is_not_credited_to_every_file_with_that_basename(self):
        # jscpd without --absolute can report just "index.js"; two files share that name
        for d in ("a", "b"):
            (self.root / "src" / d).mkdir(parents=True)
            (self.root / "src" / d / "index.js").write_text("x\n")
        self.write_report([("index.js", 1, 5, "other.js", 1, 5)])
        per_file = L.read_jscpd(self.reports)["per_file"]
        self.assertEqual(L.match_dup("src/a/index.js", per_file), 0)
        self.assertEqual(L.match_dup("src/b/index.js", per_file), 0)

    def test_short_name_resolved_when_it_is_unambiguous(self):
        (self.root / "src").mkdir()
        (self.root / "src" / "response.js").write_text("x\n")
        (self.root / ".ledger" / "config.json").write_text(json.dumps({"src_dirs": ["src"]}))
        self.write_report([("response.js", 236, 242, "response.js", 264, 270)])
        self.assertEqual(L.read_jscpd(self.reports)["per_file"], {"src/response.js": 14})

    def test_overlapping_clones_count_each_line_once(self):
        self.write_report([("src/x.js", 1, 10, "src/y.js", 1, 10),
                           ("src/x.js", 5, 12, "src/z.js", 1, 8)])
        per_file = L.read_jscpd(self.reports)["per_file"]
        self.assertEqual(per_file["src/x.js"], 12)  # lines 1-12, not 10 + 8

    def test_clone_within_one_file_counts_both_copies(self):
        self.write_report([("src/x.js", 236, 242, "src/x.js", 264, 270)])
        self.assertEqual(L.read_jscpd(self.reports)["per_file"], {"src/x.js": 14})

    def test_totals_still_come_from_jscpd(self):
        self.write_report([("src/x.js", 1, 3, "src/y.js", 1, 3)])
        dup = L.read_jscpd(self.reports)
        self.assertEqual((dup["percentage"], dup["duplicated_lines"]), (1.5, 9))


class MeasureScript(unittest.TestCase):
    def test_measure_asks_jscpd_for_absolute_paths(self):
        text = (LEDGER_PY.parent / "measure.sh").read_text()
        self.assertIn("--absolute", text)


if __name__ == "__main__":
    unittest.main()
