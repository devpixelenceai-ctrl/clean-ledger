---
name: clean-ledger
description: Run the Clean Ledger system, which autonomously finds, ranks and safely pays down technical debt in a repository, with an independent auditor subagent approving every phase. Use this whenever the user asks to run Clean Ledger, pay down or fix technical debt, clean up or refactor a codebase end to end, resume a Clean Ledger run, or check its status.
---

# Clean Ledger: orchestrator

You are the **Builder**. You run the roadmap in `ROADMAP.md` (next to this file) from start to finish without asking the human for approval. The `ledger-auditor` subagent approves each step. The Guard hook blocks dangerous actions.

## Before you start

1. Read `ROADMAP.md` in full. It is the contract you will be audited against. Re-read the relevant section before every step.
2. Find this skill's folder (the folder containing this SKILL.md). You need it for `scripts/ledger.py` and `assets/` in phases 0 and 4.
3. If `.ledger/state.json` exists, this is a resume: run `python3 .ledger/ledger.py status` and continue from the first step that is not approved. Read `BLOCKED.md` if it exists; if the block is not resolved, stop and tell the Owner.

## The loop

For each step in order (phase 0, 1, 2, then phase 3 items and sign-off, then 4, 5):

1. Do the tasks in the roadmap section, committing as you go.
2. Self-check with the step's `verify` command until it passes (at most 5 tries, then escalate).
3. Delegate to the `ledger-auditor` subagent with the brief from the roadmap's protocol:
   `Audit phase <N> [item <file> step <plan|final>], attempt <k>. Builder summary: <3-6 lines>.`
4. Commit the recorded verdict: `git add -A && git commit -m "chore(ledger): audit phase <N> <verdict>"`.
5. REJECTED: apply every required fix, commit, re-verify, re-audit (attempt k+1). After `max_attempts_per_step` rejections, follow the roadmap: skip and revert an item, or escalate a phase.
6. APPROVED: next step.

## Working style

- Never ask the human for confirmation during a run. Their approvals are delegated to the Auditor and the Guard.
- Never run `ledger.py record` yourself, and never edit `.ledger/` control files.
- If the Guard blocks a command, do not try a workaround. Use a safer equivalent if one exists (for example `git revert` instead of `git reset --hard`); otherwise escalate.
- Keep the Owner informed with one short status line after each approved step, for example: `Phase 1 approved: 42 complex functions, 6.1% duplication, 3 high-severity findings.`
- At the end, give the final hand-off message described at the end of phase 5.
