---
description: Run Clean Ledger end to end (or resume) - measure, rank and safely fix technical debt, with an auditor approving every phase
argument-hint: "[optional: max fixes this run, e.g. 3]"
---

Use the clean-ledger skill to run the Clean Ledger roadmap in this repository, end to end and without asking me for approvals. The ledger-auditor subagent approves each step and the guard hook enforces the hard limits.

Optional maximum number of Tier 1 fixes for this run: $ARGUMENTS
If a number is given and phase 0 is not yet approved, write it as `max_fixes_per_run` in `.ledger/config.json` during phase 0. Otherwise use the configured value.

If a previous run exists, resume from the first step that is not approved.
