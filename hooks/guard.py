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
    (r"\bprintenv\b|(^|[;&|(]\s*)env\s*($|[;&|)])|\bexport\s+-p\b|\bdeclare\s+-[a-zA-Z]*x|/proc/[^\s/]+/environ"
     r"|(^|[;&|(]\s*)set\s*($|[;&|)])",
     "dumping environment variables is not allowed"),
]

SECRET_PATH = re.compile(r"(^|/)(\.env(\..*)?|.*\.pem|.*\.key|id_rsa.*|credentials.*|secrets?/.*)$", re.I)
CONTROL_FILES = {".ledger/approvals.jsonl", ".ledger/state.json", ".ledger/ledger.py", ".ledger/measure.sh"}
FROZEN_AFTER_PHASE0 = {".ledger/baseline.json", ".ledger/config.json"}

SEPARATORS = {";", "&&", "||", "|", "|&", "&", "(", ")", "\n"}
REDIRECTS = {">", ">>", ">|", "&>", "&>>", "<>"}
# Commands whose path arguments they modify: all of them, or only the last.
MODIFY_ALL = {"rm", "unlink", "truncate", "shred", "tee", "touch", "mv"}
MODIFY_LAST = {"cp", "install", "ln", "rsync"}
WRAPPERS = {"command", "builtin", "nohup", "time", "env", "xargs", "exec"}
CODE_WRITE = re.compile(r"write_text|write_bytes|\.unlink\(|os\.remove|os\.rename|os\.replace|shutil\."
                        r"|open\([^)]*['\"][wax+]|writeFileSync|appendFileSync|unlinkSync")
HEREDOC = re.compile(r"<<-?\s*(['\"]?)([A-Za-z_][A-Za-z0-9_]*)\1[^\n]*\n(.*?)\n\s*\2\s*(?:\n|$)", re.S)


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


def control_paths(root: Path) -> set[str]:
    """Files only `ledger.py` may change; baseline and config join them once
    phase 0 is approved."""
    paths = set(CONTROL_FILES)
    try:
        state = json.loads((root / ".ledger" / "state.json").read_text(encoding="utf-8"))
        if state.get("phases", {}).get("0") == "approved":
            paths |= FROZEN_AFTER_PHASE0
    except (FileNotFoundError, json.JSONDecodeError):
        pass
    return paths


def norm_target(target: str, here: Path, root: Path) -> str:
    p = Path(os.path.expanduser(target))
    p = p if p.is_absolute() else here / p
    try:
        return Path(os.path.realpath(p)).relative_to(os.path.realpath(root)).as_posix()
    except ValueError:
        return p.as_posix()


def simple_commands(tokens: list[str]) -> list[list[str]]:
    out, cur = [], []
    for t in tokens:
        if t in SEPARATORS:
            if cur:
                out.append(cur)
            cur = []
        else:
            cur.append(t)
    if cur:
        out.append(cur)
    return out


def written_paths(cmd: str, cwd: Path, root: Path) -> list[str] | None:
    """Repo-relative paths a shell command writes, as far as can be told.
    None means the command could not be parsed."""
    code_chunks = [m.group(3) for m in HEREDOC.finditer(cmd)]
    body_free = HEREDOC.sub(lambda m: m.group(0).split("\n", 1)[0] + "\n", cmd)
    try:
        lex = shlex.shlex(body_free, posix=True, punctuation_chars=";&|()<>")
        lex.whitespace_split = True
        lex.whitespace = " \t\r"
        tokens = list(lex)
    except ValueError:
        return None
    written: list[str] = []
    here = cwd
    for words in simple_commands(tokens):
        args, i = [], 0
        while i < len(words):
            w = words[i]
            if w in REDIRECTS and i + 1 < len(words):
                target = words[i + 1]
                if not (target.startswith("&") or target == "/dev/null" or target.isdigit()):
                    written.append(norm_target(target, here, root))
                i += 2
                continue
            if w in (">&", "<&", "<", "<<", "<<<", "<<-"):
                i += 2
                continue
            if w.isdigit() and i + 1 < len(words) and words[i + 1] in REDIRECTS | {">&"}:
                i += 1
                continue
            args.append(w)
            i += 1
        while args and (re.match(r"^[A-Za-z_][A-Za-z0-9_]*=", args[0]) or args[0] in WRAPPERS):
            args = args[1:]
        if not args:
            continue
        name, rest = os.path.basename(args[0]), args[1:]
        paths = [a for a in rest if not a.startswith("-")]
        if name == "cd":
            here = Path(os.path.expanduser(paths[0])) if paths and Path(paths[0]).is_absolute() \
                else here / (paths[0] if paths else str(Path.home()))
        elif name in MODIFY_ALL:
            written += [norm_target(a, here, root) for a in paths]
        elif name in MODIFY_LAST and paths:
            written.append(norm_target(paths[-1], here, root))
        elif name in ("sed", "perl") and any(a.startswith("-i") or a.startswith("-pi") for a in rest):
            written += [norm_target(a, here, root) for a in paths]
        elif name == "dd":
            written += [norm_target(a[3:], here, root) for a in rest if a.startswith("of=")]
        elif name == "git" and set(rest) & {"checkout", "restore", "rm", "mv"}:
            written += [norm_target(a, here, root) for a in paths
                        if a not in ("checkout", "restore", "rm", "mv")]
        elif re.match(r"^(python[\d.]*|node|perl|ruby)$", name):
            code_chunks += rest
    for code in code_chunks:
        if CODE_WRITE.search(code):
            written += [norm_target(m, here, root)
                        for m in re.findall(r"[\w./-]*\.ledger/[\w.-]+|(?<![\w/])(?:state|approvals|baseline|config)"
                                            r"\.json[l]?", code)]
    return written


def find_ledger(dirs: list[Path]) -> tuple[Path, str] | None:
    """Return (repo root, config text) for the first ledger repo found. A
    `.ledger/` folder without a config counts too, so the Guard is active from
    the start of a run, before `ledger.py init` writes the config."""
    for d in dirs:
        for p in (d, *d.parents):
            cfg = p / ".ledger" / "config.json"
            if cfg.is_file():
                return p, cfg.read_text(encoding="utf-8")
            if (p / ".ledger").is_dir() and (p / ".git").exists():
                return p, "{}"
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
        controls = control_paths(root)
        cwd = Path(data.get("cwd") or os.getcwd())
        written = written_paths(cmd, cwd, root)
        if written is None:
            # Unparseable: fall back to refusing any mention of a control file.
            if any(c in cmd or Path(c).name in cmd for c in controls):
                block("could not parse this command and it mentions a ledger control file")
        else:
            hit = sorted({w for w in written if w in controls})
            if hit:
                block(f"{', '.join(hit)} change only through ledger.py (`record`, `snapshot-baseline`)")
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
        if path in FROZEN_AFTER_PHASE0 and path in control_paths(root):
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
