"""Tests for runner/clean_ledger_fleet.py, the multi-repo runner."""

from __future__ import annotations

import importlib.util
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from helpers import PLUGIN, git, make_repo

spec = importlib.util.spec_from_file_location("fleet", PLUGIN / "runner" / "clean_ledger_fleet.py")
F = importlib.util.module_from_spec(spec)
spec.loader.exec_module(F)
FAKE = Path(__file__).resolve().parent / "fixtures" / "fake_agent.py"


def write_cfg(repos: list[dict], **extra) -> Path:
    d = Path(tempfile.mkdtemp(prefix="fleet-"))
    cfg = {"executor": "command", "command": [sys.executable, str(FAKE), "{project}", "pass"],
           "runs_dir": "runs", "max_parallel": 2, "repos": repos, **extra}
    p = d / "fleet.json"
    p.write_text(json.dumps(cfg))
    return p


def source_repo() -> Path:
    r = make_repo({"app.py": "def f():\n    return 1\n", "lib/util.js": "module.exports = 1\n"})
    git(r, "remote", "add", "origin", "https://example.invalid/x.git")
    return r


class Config(unittest.TestCase):
    def test_rejects_bad_configs(self):
        cases = [({"repos": []}, "non-empty"), ({"executor": "ssh", "repos": [{"url": "x"}]}, "unknown executor"),
                 ({"repos": [{"name": "a b", "url": "x"}]}, "invalid name"),
                 ({"repos": [{"url": "x/a"}, {"url": "y/a"}]}, "duplicate"),
                 ({"executor": "command", "repos": [{"url": "x"}]}, "command")]
        for body, msg in cases:
            with self.subTest(msg=msg):
                p = Path(tempfile.mkdtemp()) / "f.json"
                p.write_text(json.dumps(body))
                with self.assertRaises(F.FleetError) as cm:
                    F.load_config(p)
                self.assertIn(msg, str(cm.exception))

    def test_defaults_and_names(self):
        cfg = F.load_config(write_cfg([{"url": "https://github.com/org/proj.git"},
                                       {"name": "two", "url": "x", "max_fixes": 3}]))
        self.assertEqual([r["name"] for r in cfg["repos"]], ["proj", "two"])
        self.assertEqual([r["max_fixes"] for r in cfg["repos"]], [1, 3])
        self.assertTrue(cfg["runs_dir"].is_absolute())


class Plan(unittest.TestCase):
    def test_clones_pins_and_removes_remotes(self):
        src = source_repo()
        cfg = F.load_config(write_cfg([{"name": "one", "url": str(src), "ref": "main"}]))
        run_dir = F.plan(cfg, "t1")
        project = run_dir / "one" / "project"
        self.assertEqual(git(project, "remote"), "")
        self.assertEqual(git(project, "branch", "--show-current"), "main")
        info = json.loads((run_dir / "one" / "out" / "plan.json").read_text())
        self.assertEqual(info["base_commit"], git(src, "rev-parse", "HEAD"))
        self.assertEqual(set(info["languages"]), {"Python", "JavaScript"})
        plan = json.loads((run_dir / "fleet-plan.json").read_text())
        self.assertEqual(plan["executor_problems"], [])

    def test_a_bad_repo_does_not_stop_the_plan(self):
        cfg = F.load_config(write_cfg([{"name": "good", "url": str(source_repo())},
                                       {"name": "bad", "url": "/nonexistent/repo"}]))
        plan = json.loads((F.plan(cfg, "t2") / "fleet-plan.json").read_text())
        status = {r["name"]: r["status"] for r in plan["repos"]}
        self.assertEqual(status, {"good": "planned", "bad": "error"})


class Run(unittest.TestCase):
    def test_runs_judges_and_reports_each_repo(self):
        repos = [{"name": n, "url": str(source_repo())} for n in ("alpha", "beta", "gamma")]
        cfg_path = write_cfg(repos)
        cfg = F.load_config(cfg_path)
        cfg["repos"][1]["_mode"] = "touch-main"
        cfg["command"] = [sys.executable, str(FAKE), "{project}", "{mode}"]
        modes = {"alpha": "pass", "beta": "touch-main", "gamma": "blocked"}
        real_execute = F.execute

        def execute(c, repo, folder):
            c = {**c, "command": [p.replace("{mode}", modes[repo["name"]]) for p in c["command"]]}
            return real_execute(c, repo, folder)

        with mock.patch.object(F, "execute", execute):
            run_dir = F.run(cfg, "t3")
        summary = json.loads((run_dir / "fleet-summary.json").read_text())
        verdicts = {r["name"]: r["verdict"] for r in summary["repos"]}
        self.assertEqual(verdicts, {"alpha": "PASS", "beta": "FAIL", "gamma": "FAIL"})
        alpha = next(r for r in summary["repos"] if r["name"] == "alpha")
        self.assertEqual((alpha["complex_before"], alpha["complex_after"]), (3, 2))
        self.assertEqual((alpha["max_ccn_before"], alpha["max_ccn_after"]), (22, 16))
        self.assertEqual(alpha["phases_approved"], 6)
        report = (run_dir / "fleet-report.md").read_text()
        self.assertIn("1/3 repositories passed", report)
        self.assertIn("main branch unchanged", report)
        self.assertIn("(BLOCKED)", report)
        # the project's test command ran (command executor runs it on the host)
        self.assertEqual((run_dir / "alpha" / "out" / "final-tests-exit.txt").read_text().strip(), "0")

    def test_refuses_to_run_when_the_executor_is_not_ready(self):
        cfg = F.load_config(write_cfg([{"url": str(source_repo())}], executor="docker",
                                      image="clean-ledger-runner:does-not-exist"))
        env = {k: v for k, v in os.environ.items() if k not in F.KEY_VARS}
        with mock.patch.dict(os.environ, env, clear=True):
            with self.assertRaises(F.FleetError) as cm:
                F.run(cfg, "t4")
        self.assertIn("ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN", str(cm.exception))
        self.assertFalse((cfg["runs_dir"] / "t4").exists())

    def test_report_can_be_rebuilt(self):
        cfg = F.load_config(write_cfg([{"name": "solo", "url": str(source_repo())}]))
        run_dir = F.run(cfg, "t5")
        first = (run_dir / "fleet-report.md").read_text()
        F.report(run_dir)
        self.assertEqual((run_dir / "fleet-report.md").read_text(), first)
        self.assertIn("1/1 repositories passed", first)


if __name__ == "__main__":
    unittest.main()
