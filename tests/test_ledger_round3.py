"""ledger.py fixes from the node-semver end-to-end run: queue ordering and raising the baseline."""

from __future__ import annotations

import json
import unittest
from pathlib import Path

from helpers import commit_all, git, ledger, make_repo, write_config


def repo() -> Path:
    r = make_repo({"src/a.js": "1\n", "src/b.js": "2\n", "src/c.js": "3\n", ".gitignore": ".ledger/reports/\n"})
    write_config(r)
    commit_all(r, "config")
    git(r, "switch", "-q", "-c", "clean-ledger")
    return r


def write_queue(r: Path, items: list[tuple[str, int]]):
    q = [{"file": f, "score": 1.0, "max_ccn": 20, "sec_high": h, "status": "todo", "reason": ""} for f, h in items]
    (r / ".ledger" / "queue.json").write_text(json.dumps(q))


def queue_files(r: Path) -> list[str]:
    return [q["file"] for q in json.loads((r / ".ledger" / "queue.json").read_text())]


class QueueOrder(unittest.TestCase):
    def test_reorders_by_the_given_cost_order(self):
        r = repo()
        write_queue(r, [("src/a.js", 0), ("src/b.js", 0), ("src/c.js", 0)])
        res = ledger(r, "queue", "--order", "src/c.js", "src/a.js", "src/b.js")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(queue_files(r), ["src/c.js", "src/a.js", "src/b.js"])

    def test_security_items_must_stay_first(self):
        r = repo()
        write_queue(r, [("src/a.js", 1), ("src/b.js", 0), ("src/c.js", 0)])
        res = ledger(r, "queue", "--order", "src/b.js", "src/a.js", "src/c.js")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("security", res.stderr)
        self.assertEqual(queue_files(r), ["src/a.js", "src/b.js", "src/c.js"])

    def test_order_must_name_exactly_the_queued_files(self):
        r = repo()
        write_queue(r, [("src/a.js", 0), ("src/b.js", 0)])
        for order in (["src/a.js"], ["src/a.js", "src/b.js", "src/x.js"], ["src/a.js", "src/a.js"]):
            with self.subTest(order=order):
                self.assertNotEqual(ledger(r, "queue", "--order", *order).returncode, 0)
        self.assertEqual(queue_files(r), ["src/a.js", "src/b.js"])

    def test_keeps_item_status(self):
        r = repo()
        write_queue(r, [("src/a.js", 0), ("src/b.js", 0)])
        q = json.loads((r / ".ledger" / "queue.json").read_text())
        q[0]["status"] = "done"
        (r / ".ledger" / "queue.json").write_text(json.dumps(q))
        ledger(r, "queue", "--order", "src/b.js", "src/a.js")
        q = json.loads((r / ".ledger" / "queue.json").read_text())
        self.assertEqual([(x["file"], x["status"]) for x in q], [("src/b.js", "todo"), ("src/a.js", "done")])


class RaiseBaseline(unittest.TestCase):
    def setUp(self):
        self.r = repo()
        (self.r / ".ledger" / "baseline.json").write_text(json.dumps(
            {"complex_functions": 5, "duplication_pct": 2.0, "security": {"high": 0, "medium": 2, "low": 1}}))
        (self.r / ".ledger" / "state.json").write_text(json.dumps({"phases": {p: "approved" for p in "012345"}}))

    def metrics(self, **m):
        base = {"complex_functions": 5, "duplication_pct": 2.0, "security": {"high": 0, "medium": 2, "low": 1}}
        base.update(m)
        (self.r / ".ledger" / "metrics.json").write_text(json.dumps(base))

    def baseline(self) -> dict:
        return json.loads((self.r / ".ledger" / "baseline.json").read_text())

    def test_raises_when_nothing_got_worse(self):
        self.metrics(complex_functions=3, duplication_pct=1.5)
        res = ledger(self.r, "raise-baseline")
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertEqual(self.baseline()["complex_functions"], 3)

    def test_refuses_to_loosen_the_gate(self):
        for worse in ({"complex_functions": 6}, {"duplication_pct": 2.01},
                      {"security": {"high": 0, "medium": 3, "low": 1}}):
            with self.subTest(worse=worse):
                self.metrics(**worse)
                self.assertNotEqual(ledger(self.r, "raise-baseline").returncode, 0)
                self.assertEqual(self.baseline()["complex_functions"], 5)

    def test_refuses_during_a_run(self):
        (self.r / ".ledger" / "state.json").write_text(json.dumps({"phases": {"0": "approved"}}))
        self.metrics(complex_functions=3)
        res = ledger(self.r, "raise-baseline")
        self.assertNotEqual(res.returncode, 0)
        self.assertIn("phase 5", res.stderr)


if __name__ == "__main__":
    unittest.main()
