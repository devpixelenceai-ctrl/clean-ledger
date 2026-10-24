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
import shlex
import subprocess
import sys
from pathlib import Path

# `git` followed by any global options (-C <dir>, -c k=v, --no-pager, ...) before
# the subcommand, so `git -C repo push` is caught like `git push`.
_ARG = r"""(?:"[^"]*"|'[^']*'|\S+)"""
GIT = r"\bgit(?:\s+-[Cc]\s+" + _ARG + r"|\s+--[\w-]+(?:=" + _ARG + r")?|\s+-[A-Za-z])*\s+"

BLOCKED_COMMANDS = [
    (GIT + r"push\b", "pushing is reserved for the human owner"),
    (GIT + r"merge\b", "merging is reserved for the human owner"),
    (GIT + r"rebase\b", "rebasing rewrites history"),
    (GIT + r"reset\s+--hard\b", "hard reset can destroy work; use git revert"),
    (GIT + r"clean\s+-[a-z]*f", "git clean deletes untracked files"),
    (GIT + r"branch\s+-D\b", "force-deleting branches is not allowed"),
    (GIT + r"(commit|tag)\b.*--no-verify\b", "skipping git hooks is not allowed"),
    (GIT + r"commit\b.*--amend\b", "amending rewrites history; make a new commit"),
    (GIT + r"(filter-branch|filter-repo|update-ref)\b", "history rewriting is not allowed"),
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


FILE_TOOLS = ("Edit", "Write", "MultiEdit", "NotebookEdit", "Read")


def rel(root: Path, file_path: str) -> str:
    try:
        return Path(file_path).resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return Path(file_path).as_posix()


def command_dirs(cmd: str, cwd: Path) -> list[Path]:
    """Folders a shell command works in: each `cd <dir>` and `git -C <dir>`."""
    try:
        tokens = shlex.split(cmd)
    except ValueError:
        tokens = cmd.split()
    dirs, here = [], cwd
    for i, tok in enumerate(tokens[:-1]):
        nxt = Path(os.path.expanduser(tokens[i + 1]))
        if tok == "cd":
            here = nxt if nxt.is_absolute() else here / nxt
            dirs.append(here)
        elif tok == "-C" and i > 0 and tokens[i - 1] == "git":
            dirs.append(nxt if nxt.is_absolute() else here / nxt)
    return dirs


def candidate_dirs(data: dict, tool: str, tin: dict) -> list[Path]:
    """Where to look for the ledger repo, most specific first."""
    cwd = Path(data.get("cwd") or os.getcwd())
    out: list[Path] = []
    if tool in FILE_TOOLS:
        fp = tin.get("file_path") or tin.get("notebook_path") or ""
        if fp:
            p = Path(fp)
            out.append((p if p.is_absolute() else cwd / p).parent)
    if tool == "Bash":
        out += command_dirs(tin.get("command", ""), cwd)
    out.append(cwd)
    if os.environ.get("CLAUDE_PROJECT_DIR"):
        out.append(Path(os.environ["CLAUDE_PROJECT_DIR"]))
    return out


def find_ledger(dirs: list[Path]) -> tuple[Path, str] | None:
    """Return (repo root, config text) for the first ledger repo found."""
    for d in dirs:
        for p in (d, *d.parents):
            cfg = p / ".ledger" / "config.json"
            if cfg.is_file():
                return p, cfg.read_text(encoding="utf-8")
    for d in dirs:
        if not d.is_dir():
            continue
        top = subprocess.run(["git", "rev-parse", "--show-toplevel"], cwd=d,
                             capture_output=True, text=True)
        if top.returncode != 0:
            continue
        # Switching to another branch must not switch the guard off: read the
        # config from the work branch if this repository has one.
        r = subprocess.run(["git", "show", "clean-ledger:.ledger/config.json"], cwd=top.stdout.strip(),
                           capture_output=True, text=True)
        if r.returncode == 0:
            return Path(top.stdout.strip()), r.stdout
    return None


def main() -> None:
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError:
        sys.exit(0)
    tool = data.get("tool_name", "")
    tin = data.get("tool_input", {}) or {}
    found = find_ledger(candidate_dirs(data, tool, tin))
    if not found:
        sys.exit(0)  # not a Clean Ledger repository: stay out of the way
    root, raw = found
    try:
        cfg = json.loads(raw)
    except json.JSONDecodeError:
        cfg = {}
    if not cfg.get("autopilot", True):
        sys.exit(0)

    if tool == "Bash":
        cmd = tin.get("command", "")
        for pattern, reason in BLOCKED_COMMANDS:
            if re.search(pattern, cmd, re.I):
                block(reason)
        if re.search(r"\.ledger/(approvals\.jsonl|state\.json|baseline\.json|ledger\.py|measure\.sh)", cmd) and \
                re.search(r">|\btee\b|\bsed\s+-i|\b(mv|cp|rm|truncate|dd)\b|open\(|write", cmd):
            block("ledger control files change only through `ledger.py record`")
        if re.search(GIT + r"commit\b", cmd):
            branch = subprocess.run(["git", "rev-parse", "--abbrev-ref", "HEAD"], cwd=root,
                                    capture_output=True, text=True).stdout.strip()
            work = cfg.get("branch", "clean-ledger")
            if branch and branch != work:
                block(f"commits are only allowed on the '{work}' branch (currently on '{branch}')")
        sys.exit(0)

    if tool in FILE_TOOLS:
        raw_path = Path(tin.get("file_path") or tin.get("notebook_path") or "")
        if not raw_path.is_absolute():
            raw_path = Path(data.get("cwd") or os.getcwd()) / raw_path
        path = rel(root, str(raw_path))
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
