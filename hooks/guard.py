#!/usr/bin/env python3
"""Clean Ledger safety guard (Claude Code PreToolUse hook).

Active only in repositories that contain .ledger/config.json. It blocks actions
an autonomous run must never take, whatever any prompt says. Exit code 2 blocks
the tool call and shows the reason to Claude; exit 0 allows it.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import sys
from pathlib import Path

BLOCKED_COMMANDS = [
    (r"\bgit\s+push\b", "pushing is reserved for the human owner"),
    (r"\bgit\s+merge\b", "merging is reserved for the human owner"),
    (r"\bgit\s+rebase\b", "rebasing rewrites history"),
    (r"\bgit\s+reset\s+--hard\b", "hard reset can destroy work; use git revert"),
    (r"\bgit\s+clean\s+-[a-z]*f", "git clean deletes untracked files"),
    (r"\bgit\s+branch\s+-D\b", "force-deleting branches is not allowed"),
    (r"\bgit\s+(commit|tag)\b.*--no-verify\b", "skipping git hooks is not allowed"),
    (r"\bgit\s+commit\b.*--amend\b", "amending rewrites history; make a new commit"),
    (r"\bgit\s+(filter-branch|filter-repo|update-ref)\b", "history rewriting is not allowed"),
    (r"\brm\s+-[a-z]*r[a-z]*f|\brm\s+-[a-z]*f[a-z]*r", "recursive force delete is not allowed"),
    (r"\bsudo\b", "sudo is not allowed"),
    (r"\b(curl|wget)\b[^|]*\|\s*(ba|z)?sh\b", "piping downloads into a shell is not allowed"),
    (r"\b(ssh|scp|rsync)\b", "remote access is not allowed"),
    (r"\b(npm|yarn|pnpm)\s+publish\b|\btwine\s+upload\b|\bcargo\s+publish\b|\bgem\s+push\b",
     "publishing packages is not allowed"),
    (r"\bdocker\s+push\b|\bkubectl\b|\bhelm\b|\bterraform\s+(apply|destroy)\b",
     "deploying or changing infrastructure is not allowed"),
    (r"\b(aws|gcloud|az)\s", "cloud CLIs are not allowed"),
    (r"\bgh\s+(pr\s+merge|release|repo\s+delete|secret)\b", "this GitHub action is reserved for the owner"),
    (r"(^|[;&|\s])(cat|less|more|head|tail|grep)\s[^;&|]*\.env\b", "reading secret files is not allowed"),
    (r"\bprintenv\b|(^|[;&|]\s*)env\s*($|[;&|])", "dumping environment variables is not allowed"),
]

SECRET_PATH = re.compile(r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|id_rsa.*|credentials.*|secrets?/.*)$", re.I)
CONTROL_FILES = {".ledger/approvals.jsonl", ".ledger/state.json", ".ledger/ledger.py", ".ledger/measure.sh"}


def block(reason: str) -> None:
    print(f"Blocked by Clean Ledger guard: {reason}. If this is truly needed, stop and "
          f"write it up in BLOCKED.md for the human owner.", file=sys.stderr)
    sys.exit(2)


def rel(root: Path, file_path: str) -> str:
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(file_path).as_posix()


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    root = Path(os.environ.get("CLAUDE_PROJECT_DIR") or data.get("cwd") or os.getcwd())
    cfg_path = root / ".ledger" / "config.json"
    if cfg_path.exists():
        raw = cfg_path.read_text(encoding="utf-8")
    else:
        # Switching to another branch must not switch the guard off: read the
        # config from the work branch if this repository has one.
        r = subprocess.run(["git", "show", "clean-ledger:.ledger/config.json"], cwd=root,
                           capture_output=True, text=True)
        if r.returncode != 0:
            sys.exit(0)  # not a Clean Ledger repository: stay out of the way
        raw = r.stdout
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        cfg = {}
    if not cfg.get("autopilot", True):
        sys.exit(0)

    tool = data.get("tool_name", "")
    tin = data.get("tool_input", {}) or {}

    if tool == "Bash":
        cmd = tin.get("command", "")
        for pattern, reason in BLOCKED_COMMANDS:
            if re.search(pattern, cmd, re.I):
                block(reason)
        if re.search(r"\.ledger/(approvals\.jsonl|state\.json|baseline\.json|ledger\.py|measure\.sh)", cmd) and \
                re.search(r">|\btee\b|\bsed\s+-i|\b(mv|cp|rm|truncate|dd)\b|open\(|write", cmd):
            block("ledger control files change only through `ledger.py record`")
        if re.search(r"\bgit\s+commit\b", cmd):
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
                                    capture_output=True, text=True).stdout.strip()
            work = cfg.get("branch", "clean-ledger")
            if branch and branch != work:
                block(f"commits are only allowed on the '{work}' branch (currently on '{branch}')")
        sys.exit(0)

    if tool in ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read"):
        path = rel(root, tin.get("file_path") or tin.get("notebook_path") or "")
        if SECRET_PATH.search(path):
            block(f"secret files are off limits ({path})")
        if tool == "Read":
            sys.exit(0)
        if path in CONTROL_FILES:
            block(f"{path} is a Clean Ledger control file")
        if path in (".ledger/baseline.json", ".ledger/config.json"):
            state = root / ".ledger" / "state.json"
            approved = False
            if state.exists():
                try:
                    approved = json.loads(state.read_text()).get("phases", {}).get("0") == "approved"
                except json.JSONDecodeError:
                    pass
            if approved:
                block(f"{path} is frozen after phase 0 approval")
        for p in cfg.get("protected_paths", []):
            p = p.strip("/")
            if p and (path == p or path.startswith(p + "/")):
                block(f"{path} is in a protected path ({p})")
        ci_file = cfg.get("ci_file", ".github/workflows/ledger-gate.yml")
        if path.startswith(".github/workflows/") and path != ci_file:
            block("only the Clean Ledger gate workflow may be added or changed")
    sys.exit(0)


if __name__ == "__main__":
    main()
