"""Tool folders outside PATH (fix #5) and the pinned, hardened CI gate (fix #6)."""

from __future__ import annotations

import json
import os
import stat
import tempfile
import unittest
from pathlib import Path

from helpers import PLUGIN, commit_all, git, ledger, make_repo, write_config

TEMPLATE = PLUGIN / "skills" / "clean-ledger" / "assets" / "ledger-gate.yml"
MINIMAL_PATH = "/usr/bin:/bin"


def fake_tools(versions: dict[str, str]) -> Path:
    """A folder of fake tool executables that print a version."""
    d = Path(tempfile.mkdtemp(prefix="tools-"))
    for name, out in versions.items():
        p = d / name
        p.write_text(f"#!/bin/sh\necho '{out}'\n")
        p.chmod(p.stat().st_mode | stat.S_IEXEC)
    return d


def repo(**cfg) -> Path:
    r = make_repo({"src/app.py": "x = 1\n", ".gitignore": ".ledger/verify/\n.ledger/reports/\n"})
    write_config(r, **cfg)
    commit_all(r, "config")
    git(r, "switch", "-q", "-c", "clean-ledger")
    return r


def check(out: str, name: str) -> str:
    return next((l.strip() for l in out.splitlines() if name in l), "")


class ToolDirs(unittest.TestCase):
    def test_phase0_finds_tools_in_tool_dirs(self):
        tools = fake_tools({"lizard": "1.17.10", "jscpd": "4.0.5"})
        r = repo(tool_dirs=[str(tools)])
        out = ledger(r, "verify", "--phase", "0", env={"PATH": MINIMAL_PATH}).stdout
        self.assertTrue(check(out, "lizard installed").startswith("PASS"), out)
        self.assertTrue(check(out, "jscpd installed").startswith("PASS"), out)

    def test_phase0_still_fails_when_tools_are_missing(self):
        r = repo()
        out = ledger(r, "verify", "--phase", "0", env={"PATH": MINIMAL_PATH}).stdout
        self.assertTrue(check(out, "lizard installed").startswith("FAIL"), out)

    def test_init_records_tool_dirs(self):
        tools = fake_tools({"lizard": "1.0.0"})
        r = make_repo({"src/a.py": "a\n"})
        ledger(r, "init", "--src", "src", "--test-command", "true", "--base-branch", "main",
               "--tool-dir", str(tools))
        cfg = json.loads((r / ".ledger" / "config.json").read_text())
        self.assertEqual(cfg["tool_dirs"], [str(tools)])

    def test_measure_script_uses_tool_dirs(self):
        text = (PLUGIN / "skills" / "clean-ledger" / "scripts" / "measure.sh").read_text()
        self.assertIn("tool_dirs", text)

    def test_measure_script_keeps_semgrep_files_out_of_home(self):
        text = (PLUGIN / "skills" / "clean-ledger" / "scripts" / "measure.sh").read_text()
        for var in ("SEMGREP_SETTINGS_FILE", "SEMGREP_LOG_FILE", "SEMGREP_VERSION_CACHE_PATH"):
            self.assertIn(f'export {var}="${{{var}:-$PWD/$OUT/semgrep-home/', text)


class RenderGate(unittest.TestCase):
    def render(self, versions: dict[str, str]) -> str:
        tools = fake_tools(versions)
        r = repo(tool_dirs=[str(tools)])
        res = ledger(r, "render-gate", "--template", str(TEMPLATE), env={"PATH": MINIMAL_PATH})
        self.assertEqual(res.returncode, 0, res.stderr)
        return (r / ".github" / "workflows" / "ledger-gate.yml").read_text()

    def test_pins_local_tool_versions(self):
        wf = self.render({"lizard": "1.24.2", "jscpd": "jscpd 5.4.2", "semgrep": "1.182.1"})
        self.assertIn("pip install lizard==1.24.2", wf)
        self.assertIn("npm install -g jscpd@5.4.2", wf)
        self.assertIn("pip install semgrep==1.182.1", wf)
        self.assertNotIn("{{", wf)

    def test_drops_semgrep_when_not_installed_locally(self):
        wf = self.render({"lizard": "1.24.2", "jscpd": "5.4.2"})
        self.assertNotIn("semgrep", wf.lower().split("measure")[0])

    def test_workflow_is_hardened(self):
        wf = self.render({"lizard": "1.24.2", "jscpd": "5.4.2"})
        self.assertIn("permissions:\n  contents: read", wf)
        self.assertIn("persist-credentials: false", wf)
        self.assertIn("fetch-depth: 0", wf)
        self.assertIn("python3 .ledger/ledger.py gate", wf)

    def test_refuses_without_required_tools(self):
        r = repo()
        res = ledger(r, "render-gate", "--template", str(TEMPLATE), env={"PATH": MINIMAL_PATH})
        self.assertNotEqual(res.returncode, 0)


class Phase4ChecksPins(unittest.TestCase):
    def phase4(self, workflow: str, tools_in_baseline: dict) -> str:
        r = repo()
        (r / ".github" / "workflows").mkdir(parents=True)
        (r / ".github" / "workflows" / "ledger-gate.yml").write_text(workflow)
        (r / ".ledger" / "baseline.json").write_text(json.dumps(
            {"complex_functions": 0, "duplication_pct": 0.0, "tools": tools_in_baseline}))
        commit_all(r, "gate")
        return ledger(r, "verify", "--phase", "4").stdout

    def test_unpinned_workflow_fails(self):
        out = self.phase4("run: pip install lizard\nrun: python3 .ledger/ledger.py gate\n",
                          {"lizard": "1.24.2", "jscpd": "5.4.2"})
        self.assertTrue(check(out, "pins the baseline tool versions").startswith("FAIL"), out)

    def test_pinned_workflow_passes(self):
        wf = ("pip install lizard==1.24.2\nnpm install -g jscpd@5.4.2\n"
              "run: python3 .ledger/ledger.py gate\n")
        out = self.phase4(wf, {"lizard": "1.24.2", "jscpd": "5.4.2"})
        self.assertTrue(check(out, "pins the baseline tool versions").startswith("PASS"), out)


class MetricsRecordTools(unittest.TestCase):
    def test_metrics_include_tool_versions(self):
        tools = fake_tools({"lizard": "1.24.2", "jscpd": "5.4.2"})
        r = repo(tool_dirs=[str(tools)])
        reports = r / ".ledger" / "reports"
        reports.mkdir(parents=True)
        res = ledger(r, "metrics", "--reports", str(reports), env={"PATH": MINIMAL_PATH})
        m = json.loads(res.stdout)
        self.assertEqual(m["tools"], {"lizard": "1.24.2", "jscpd": "5.4.2", "semgrep": None})


if __name__ == "__main__":
    unittest.main()
