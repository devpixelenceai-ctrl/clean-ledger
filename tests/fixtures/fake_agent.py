#!/usr/bin/env python3
"""Stand-in for a Clean Ledger run, used by test_fleet.py.

usage: fake_agent.py <project> <mode>   mode = pass | touch-main | blocked
Simulates the files a finished run leaves on the clean-ledger branch.
"""

import json
import subprocess
import sys
from pathlib import Path

project, mode = Path(sys.argv[1]), sys.argv[2]


def git(*args):
    subprocess.run(["git", *args], cwd=project, check=True, capture_output=True)


base = subprocess.run(["git", "rev-parse", "HEAD"], cwd=project, capture_output=True, text=True).stdout.strip()
if mode == "touch-main":
    (project / "app.py").write_text("changed on main\n")
    git("commit", "-qam", "commit on main")
git("switch", "-q", "-c", "clean-ledger")
led = project / ".ledger"
led.mkdir(exist_ok=True)
files = {
    ".gitignore": ".ledger/metrics.json\n.ledger/reports/\n",
    ".ledger/config.json": json.dumps({"test_command": "true", "protected_paths": [],
                                       "ci_file": ".github/workflows/ledger-gate.yml"}),
    ".ledger/state.json": json.dumps({"phases": {p: "approved" for p in "012345"},
                                      **({"blocked": {"phase": "3"}} if mode == "blocked" else {})}),
    ".ledger/queue.json": json.dumps([{"file": "app.py", "status": "done", "reason": ""}]),
    ".ledger/baseline.json": json.dumps({"complex_functions": 3, "max_ccn": 22, "duplication_pct": 1.5}),
    ".ledger/approvals.jsonl": "".join(json.dumps({"phase": p, "item": i, "step": s, "verdict": "APPROVED",
                                                   "by": "ledger-auditor", "commit": base[:8]}) + "\n"
                                       for p, i, s in [*[(p, None, None) for p in "012345"],
                                                       ("3", "app.py", "plan"), ("3", "app.py", None)]),
    ".github/workflows/ledger-gate.yml": "run: python3 .ledger/ledger.py gate\n",
    "app.py": "def f():\n    return 1  # refactored\n",
}
for name in ("CLAUDE.md", "BASELINE.md", "DEBT_REGISTER.md", "PROGRESS.md", "PR_DESCRIPTION.md"):
    files[name] = "# doc\n"
if mode == "blocked":
    files["BLOCKED.md"] = "# blocked\n"
for name, text in files.items():
    p = project / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)
git("add", "-A")
git("commit", "-qm", "simulated clean ledger run")
(led / "metrics.json").write_text(json.dumps({"complex_functions": 2, "max_ccn": 16, "duplication_pct": 1.2}))
# Claude Code's stream-json ends with a result message.
print(json.dumps({"type": "result", "subtype": "success", "is_error": False, "total_cost_usd": 0, "num_turns": 1}))
