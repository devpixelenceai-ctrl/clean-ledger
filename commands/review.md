---
description: Review the current branch for newly added technical debt before a pull request (read-only)
argument-hint: "[base branch, default main]"
---

Review the current branch against base branch: $ARGUMENTS (default: the repository's default branch). Do not change any files.

1. Run `git diff --stat <base>...HEAD` and read the full diff.
2. If `.ledger/measure.sh` exists, run `bash .ledger/measure.sh` and `python3 .ledger/ledger.py gate`.
3. Report by severity, each with file, line, why it matters and a concrete fix: new or grown functions over complexity 15; new duplicated blocks; new security findings; changed logic without new or updated tests; breaks of CLAUDE.md conventions.
4. End with a verdict: ready, ready with small fixes, or needs work.
