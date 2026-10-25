"""ledger.py fixes from the prettytable e2e review."""

from __future__ import annotations

import json
import stat
import tempfile
import unittest
from pathlib import Path

from helpers import LEDGER_PY, commit_all, git, ledger, make_repo, write_config


def repo() -> Path:
    r = make_repo({"src/app.py": "def f():\n    return 1\n", ".gitignore": ".ledger/reports/\n"})
    write_config(r)
    commit_all(r, "config")
    git(r, "switch", "-q", "-c", "clean-ledger")
    return r


class SnapshotBaseline(unittest.TestCase):
    def test_copies_metrics_before_phase0_approval(self):
        r = repo()
        (r / ".ledger" / "metrics.json").write_text('{"complex_functions": 2}\n')
        res = ledger(r, "snapshot-baseline")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(json.loads((r / ".ledger" / "baseline.json").read_text()), {"complex_functions": 2})

    def test_refuses_after_phase0_approval(self):
        r = repo()
        (r / ".ledger" / "metrics.json").write_text('{"complex_functions": 2}\n')
        (r / ".ledger" / "state.json").write_text(json.dumps({"phases": {"0": "approved"}}))
        self.assertNotEqual(ledger(r, "snapshot-baseline").returncode, 0)
        self.assertFalse((r / ".ledger" / "baseline.json").exists())

    def test_refuses_without_metrics(self):
        self.assertNotEqual(ledger(repo(), "snapshot-baseline").returncode, 0)


class RoadmapPath(unittest.TestCase):
    def test_init_records_the_roadmap_path(self):
        r = make_repo({"src/a.py": "a\n"})
        ledger(r, "init", "--src", "src", "--test-command", "true", "--base-branch", "main")
        cfg = json.loads((r / ".ledger" / "config.json").read_text())
        self.assertEqual(Path(cfg["roadmap"]), (LEDGER_PY.parent.parent / "ROADMAP.md").resolve())
        self.assertIn("ROADMAP.md", ledger(r, "status").stdout)


class ToolVersions(unittest.TestCase):
    def test_ignores_version_text_from_a_failing_tool(self):
        tools = Path(tempfile.mkdtemp())
        bad = tools / "semgrep"
        bad.write_text("#!/bin/sh\necho 'Traceback: python 3.12.12 broke' >&2\nexit 1\n")
        bad.chmod(bad.stat().st_mode | stat.S_IEXEC)
        r = repo()
        cfg = json.loads((r / ".ledger" / "config.json").read_text())
        cfg["tool_dirs"] = [str(tools)]
        (r / ".ledger" / "config.json").write_text(json.dumps(cfg))
        reports = r / ".ledger" / "reports"
        reports.mkdir(parents=True)
        m = json.loads(ledger(r, "metrics", "--reports", str(reports), env={"PATH": "/usr/bin:/bin"}).stdout)
        self.assertIsNone(m["tools"]["semgrep"])


class ToolVersionCaFallback(unittest.TestCase):
    def test_retries_with_a_ca_bundle(self):
        tools = Path(tempfile.mkdtemp())
        sg = tools / "semgrep"
        sg.write_text('#!/bin/sh\nif [ -z "$SSL_CERT_FILE" ]; then echo "ca-certs: empty trust anchors" >&2; exit 2; fi\n'
                      'echo 1.182.1\n')
        sg.chmod(sg.stat().st_mode | stat.S_IEXEC)
        r = repo()
        cfg = json.loads((r / ".ledger" / "config.json").read_text())
        cfg["tool_dirs"] = [str(tools)]
        (r / ".ledger" / "config.json").write_text(json.dumps(cfg))
        reports = r / ".ledger" / "reports"
        reports.mkdir(parents=True)
        res = ledger(r, "metrics", "--reports", str(reports), env={"PATH": "/usr/bin:/bin", "SSL_CERT_FILE": ""})
        m = json.loads(res.stdout)
        import importlib.util
        has_ca = any(importlib.util.find_spec(n) for n in ("certifi", "pip"))
        self.assertEqual(m["tools"]["semgrep"], "1.182.1" if has_ca else None)


class UnmeasuredSecurity(unittest.TestCase):
    def hotspots(self, with_semgrep: bool) -> str:
        r = repo()
        reports = r / ".ledger" / "reports"
        reports.mkdir(parents=True)
        (reports / "lizard.csv").write_text('3,2,10,0,3,"f@1-3@src/app.py","src/app.py","f","f()",1,3\n')
        (reports / "churn.csv").write_text("file,changes,authors\nsrc/app.py,4,2\n")
        if with_semgrep:
            (reports / "semgrep.json").write_text('{"results": []}')
        return ledger(r, "hotspots", "--markdown").stdout

    def test_shows_na_when_semgrep_did_not_run(self):
        row = [l for l in self.hotspots(False).splitlines() if "src/app.py" in l][0]
        self.assertIn("n/a", row)
        self.assertNotIn("0/0/0", row)

    def test_shows_counts_when_semgrep_ran(self):
        row = [l for l in self.hotspots(True).splitlines() if "src/app.py" in l][0]
        self.assertIn("0/0/0", row)


if __name__ == "__main__":
    unittest.main()
