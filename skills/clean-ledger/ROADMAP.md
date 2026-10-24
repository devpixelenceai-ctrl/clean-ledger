# Clean Ledger Roadmap

Clean Ledger pays down technical debt in a software repository without a human at the keyboard. It finds the debt, ranks it by cost, fixes the most expensive parts safely, stops new debt from entering, and reports the result. Every phase must be approved by an independent auditor before the next one starts.

This file is the contract. The Builder follows it, and the Auditor judges the Builder against it.

---

## 1. Roles

| Role | Who | Does | Never does |
| --- | --- | --- | --- |
| **Builder** | The main Claude Code session | Executes each phase, commits work, asks for an audit, fixes what the Auditor rejects | Approves its own work, records verdicts, pushes or merges |
| **Auditor** | The `ledger-auditor` subagent | Runs the objective checks, reviews the work against this roadmap, records the verdict | Edits code, writes fixes, approves without evidence |
| **Owner** | The human | Configures the run, reads the final report, reviews and merges the branch | Needs to approve anything during the run |
| **Guard** | The PreToolUse hook | Hard-blocks dangerous actions in code, whatever any prompt says | Can be talked out of a block |

## 2. Golden rules

1. **Behaviour is sacred.** A refactor changes structure, never behaviour. The only allowed behaviour change is closing a security hole, and it must come with a test that proves the hole is closed.
2. **Tests before code.** No file is changed until characterization tests that lock in its current behaviour are committed and passing.
3. **Small steps.** One module per item, one idea per commit, tests run after every commit.
4. **Evidence over claims.** A phase is done when `ledger.py verify` passes and the Auditor approves. "I did it" is not evidence.
5. **Nothing leaves the branch.** All work happens on the `clean-ledger` branch. Nothing is pushed, merged, published or deployed. The Owner merges.
6. **When in doubt, stop.** Anything this roadmap does not cover, or anything the Guard blocks, is written up in `BLOCKED.md` and the run stops.

## 3. The protocol (run it for every step)

A *step* is a phase (0, 1, 2, 4, 5), the overall phase 3 sign-off, or one of the two checkpoints of a phase 3 item (`plan`, then `final`).

1. **Read** this roadmap's section for the step.
2. **Do** the tasks. Commit the work with a conventional commit message.
3. **Self-check:** run the step's `verify` command (see the table). Fix and re-run until it passes. If it still fails after 5 tries, escalate (section 6).
4. **Audit:** delegate to the `ledger-auditor` subagent with exactly this brief:
   `Audit phase <N> [item <file> step <plan|final>], attempt <k>. Builder summary: <3-6 lines: what was done, where, anything unusual>.`
5. **Verdict:** the Auditor runs the objective checks, reviews the work, records its verdict with `ledger.py record` and returns `APPROVED` or `REJECTED` with required fixes.
6. **Commit the record:** `git add -A && git commit -m "chore(ledger): audit phase <N> <verdict>"`.
7. **On REJECTED:** apply every required fix, commit, and go back to step 3 as attempt k+1. After `max_attempts_per_step` (default 3) rejections, escalate (section 6).
8. **On APPROVED:** move to the next step.

The Builder never runs `ledger.py record` itself. `record` refuses an approval unless a passing `verify` exists for the current commit.

| Step | Self-check and audit command |
| --- | --- |
| Phase 0, 1, 2, 4, 5 | `python3 .ledger/ledger.py verify --phase N` |
| Phase 3 item, plan checkpoint | `python3 .ledger/ledger.py verify --phase 3 --item <file> --step plan` |
| Phase 3 item, final checkpoint | `python3 .ledger/ledger.py verify --phase 3 --item <file>` |
| Phase 3 overall sign-off | `python3 .ledger/ledger.py verify --phase 3` |

Run `python3 .ledger/ledger.py status` at any time to see where the run is. If a run is interrupted, resume from the first step that is not approved.

## 4. Phase overview

| Phase | Goal | Main output | Audits |
| --- | --- | --- | --- |
| 0 Setup | Tools, project memory and a trusted baseline | `CLAUDE.md`, `BASELINE.md`, `.ledger/` | 1 |
| 1 Measure | Every significant debt item, with numbers | `DEBT_REGISTER.md` | 1 |
| 2 Prioritise | Debt ranked by cost; a fix queue | `.ledger/queue.json`, Tier 1 costs | 1 |
| 3 Fix | Top Tier 1 items paid down safely | Refactor commits, Done rows | 2 per item + 1 sign-off |
| 4 Prevent | New debt blocked at the door | CI gate workflow | 1 |
| 5 Report | Proof of value and hand-off | `PROGRESS.md`, `PR_DESCRIPTION.md` | 1 |

---

## 5. Phases

### Phase 0: Setup

**Goal.** Make the repository ready: tools installed, Clean Ledger files in place, an accurate `CLAUDE.md`, a passing test suite and a recorded baseline. No application code changes.

**Tasks.**
1. Confirm git, Python 3 and Node.js are available. Confirm the working tree is clean. If it is not, escalate.
2. Detect the default branch. Create and switch to the `clean-ledger` branch from it.
3. Install missing analysis tools: `pip install lizard`, `npm install -g jscpd`, and optionally `pip install semgrep` (skip Semgrep on Windows without WSL). Prefer user-level installs.
4. Detect languages, source folders, test framework and the exact test command. Run `python3 <this skill's scripts>/ledger.py init --src <dirs> --test-command "<cmd>" --base-branch <default branch>`, adding `--protected <paths>` for generated, vendored or migration folders.
5. Install project dependencies with the project's own lockfile command (`npm ci`, `pip install -r requirements.txt`, `poetry install`, `mvn -q test-compile`, etc.).
6. Run the test suite. If it does not pass, escalate. Clean Ledger never refactors on top of a failing suite.
7. Explore the code read-only. Write `CLAUDE.md` with these headings: `## Overview`, `## Architecture`, `## Commands` (exact install, build, lint, test commands), `## Conventions`, `## Protected` (paths never to edit, matching `protected_paths`), `## Debt rules` (the golden rules in section 2).
8. Run `bash .ledger/measure.sh`. Copy `.ledger/metrics.json` to `.ledger/baseline.json`.
9. Write `BASELINE.md`: date, commit, test results, coverage if available, the metrics, and outdated dependencies from the package manager.
10. Commit: `chore(ledger): phase 0 setup`.

**Objective criteria (verify --phase 0).** On the `clean-ledger` branch; config valid and source folders exist; base branch exists; `.ledger/ledger.py` and `measure.sh` present; lizard and jscpd installed; baseline valid; `CLAUDE.md` has Commands, Protected and Debt rules sections; `BASELINE.md` exists; `.gitignore` excludes `.ledger/reports/`; no source or test files changed; the test suite passes; the working tree is clean.

**Reviewed criteria (Auditor judges).**
- The commands in `CLAUDE.md` are real: they match the project's manifests and CI, and the test command equals `test_command` in the config.
- `src_dirs` covers the real application code and excludes tests, generated and vendored code.
- `protected_paths` covers generated code, vendored code, applied migrations and anything sensitive.
- The architecture description matches the code.
- `BASELINE.md` numbers match `.ledger/baseline.json`.

### Phase 1: Measure

**Goal.** A single `DEBT_REGISTER.md` listing every significant debt item with numbers. Measurement only.

**Tasks.**
1. Run `bash .ledger/measure.sh`.
2. Run `python3 .ledger/ledger.py hotspots --markdown --limit 40`.
3. Read `.ledger/reports/lizard.csv` for functions over complexity 15, and `.ledger/reports/jscpd-report.json` for the largest duplicate blocks.
4. List outdated dependencies with the package manager. Note any that are a major version behind or have advisories.
5. Write `DEBT_REGISTER.md` with these sections, in this order:
   - `## Totals` (baseline and now: complex functions, duplication %, security findings, coverage, outdated majors)
   - `## Hotspots` (the hotspot table, plus a one-line plain-English problem note per Tier 1 row)
   - `## Dependencies`
   - `## Team input` (leave the heading and the line "To be filled in by the Owner's team.")
   - `## Done` (a table: Date, File, What changed, Before → after)
   - `## Observations` (the 5 worst hotspots with one sentence each; high-severity security items; data problems you noticed)
6. Commit: `chore(ledger): phase 1 debt register`.

**Objective criteria (verify --phase 1).** Measurement runs; the complexity report has functions; the churn report exists; the register has all six sections and the hotspot table; the top hotspots are named in it; no source or test files changed; the working tree is clean.

**Reviewed criteria.**
- The problem notes describe what is actually wrong in each file. Spot-check at least 2 Tier 1 files by reading them.
- Totals match `.ledger/metrics.json`.
- Observations are specific (file, function, number), not generic.
- Nothing in the register is invented: every number traces to a report.

### Phase 2: Prioritise

**Goal.** Debt ranked by cost, with an ordered fix queue.

**Tasks.**
1. Run `python3 .ledger/ledger.py queue`. This writes `.ledger/queue.json` with Tier 1 items (high-severity security findings, plus the top-scoring complex hotspots).
2. Estimate a monthly cost for each Tier 1 item: hours lost per month × `hourly_cost` from the config. If `hourly_cost` is not set, use 75 and say so. Base the hours on change frequency, number of authors and complexity, and show the assumption.
3. In `## Hotspots`, add a "Tier 1 queue" table: order, file, why, estimated monthly cost. Label every money figure as an estimate.
4. If the queue is empty, write "No Tier 1 items" and the reason in the register; phase 3 will then be signed off with no items.
5. Commit: `chore(ledger): phase 2 prioritise`.

**Objective criteria (verify --phase 2).** `queue.json` exists; every queued file exists and is named in the register; the register contains monthly cost estimates (or explains an empty queue); no source or test files changed; the working tree is clean.

**Reviewed criteria.**
- The order makes sense: security first, then the highest cost.
- Cost estimates show their assumptions and are labelled as estimates.
- No item that should be Tier 3 (complex but untouched) is in the queue without a reason.

### Phase 3: Fix

**Goal.** Pay down the top Tier 1 items, at most `max_fixes_per_run` per run (default 3), each one safely.

Work through `queue.json` in order, skipping items marked `done` or `skipped`. For each item:

**3a. Start.** Run `python3 .ledger/ledger.py start-item <file>`. Commit the snapshot: `chore(ledger): start <file>`.

**3b. Understand.** Read the file, its callers and its tests. Identify public interfaces, hidden business rules and side effects.

**3c. Protect.** Write characterization tests that lock in current behaviour: every branch you can reach, edge cases, error paths, and odd current behaviour. Mark any existing bug with a comment and keep its current behaviour. Golden-master or snapshot tests are fine for complex output. Run the tests against the unchanged code; they must pass. Commit: `test(<module>): characterization tests for <file>`.

**3d. Plan.** Write `.ledger/items/<slug>-plan.md` (the slug is printed by start-item, e.g. `src-billing-py`). It contains numbered steps, each with the change, its risk (low/medium/high) and how it will be verified. It also states the public interfaces that must not change. Commit: `docs(ledger): refactor plan for <file>`.

**3e. Plan checkpoint.** Run the protocol with `--step plan`. Do not change the target file until the plan is approved.

**3f. Refactor.** Carry out the approved plan one step at a time. After each step, run the tests and commit as `refactor(<module>): <step>` (or `fix(<module>): <security fix>`). If a step breaks tests and the fix is not obvious, revert that step with `git revert` and adjust the plan in a new commit.

**3g. Record.** Add a row to `## Done` in `DEBT_REGISTER.md`: date, file, what changed, before → after numbers from `bash .ledger/measure.sh`. Commit: `docs(ledger): record fix for <file>`.

**3h. Final checkpoint.** Run the protocol for the item (no `--step`).

**If an item is rejected `max_attempts_per_step` times:** revert all of the item's commits to the target and tests with `git revert` (never reset), then run `python3 .ledger/ledger.py skip-item <file> --reason "<why>"`, commit, add the item to `BLOCKED.md` under "Skipped items", and continue with the next item. Do not stop the whole run for one item.

**Objective criteria, plan checkpoint.** Characterization tests committed; target file and all source code unchanged; plan file written and covering steps and risks; tests pass; tree clean.

**Objective criteria, final checkpoint.** Plan approved before refactoring; tests committed before the first change to the target; at least 2 commits including a `refactor(` or `fix(` commit; tests added or updated and none deleted; no protected paths or ledger control files touched; tests pass; no metric for the file got worse and at least one improved; the whole-repo gate versus baseline passes; the item is in `## Done`; tree clean.

**Reviewed criteria, plan checkpoint.**
- The tests are real characterization tests: they call the target's public functions with varied inputs and assert on results. Reject tests that assert nothing meaningful, only check that code runs, or mock away the logic under test.
- The tests cover the branches that the refactor will touch.
- The plan is small-step, keeps public interfaces, and its risks are honest.

**Reviewed criteria, final checkpoint.**
- Behaviour is preserved: read the full diff of the target (`git diff <start_commit> HEAD -- <file>`). Every logic change must be a pure restructuring. Any real behaviour change must be a documented security fix with a test.
- Public signatures are unchanged unless the plan said otherwise and gave a reason.
- No test was weakened: no assertions removed, loosened or skipped.
- The code follows `CLAUDE.md` conventions and is easier to read than before.
- The Done row's numbers match the measurements.

**3i. Phase 3 sign-off.** When the budget is used up or the queue is finished, run the protocol for phase 3 with no item.

**Objective criteria, sign-off (verify --phase 3).** No item in progress; every done item approved; every skipped item has a reason and is fully reverted; the fix budget was respected or the queue finished; the gate passes; tests pass; tree clean.

**Reviewed criteria, sign-off.** `BLOCKED.md` lists any skipped items with honest reasons; nothing unfinished is hidden.

### Phase 4: Prevent

**Goal.** Make debt that has been paid stay paid, using free CI.

**Tasks.**
1. Detect the CI system. For GitHub, copy this skill's `assets/ledger-gate.yml` to `.github/workflows/ledger-gate.yml`. For another CI system, write the equivalent at the path in `ci_file` (update the config only during phase 0; otherwise use the default path).
2. If Semgrep is not installed locally, remove the Semgrep install line from the workflow so CI measures the same things as the baseline.
3. If the repository has no Dependabot or Renovate config, add `.github/dependabot.yml` for the project's package ecosystems with a weekly schedule and a limit of 5 open pull requests.
4. Add a short `## Quality gate` section to `CLAUDE.md` explaining the gate and how to raise the baseline after a reviewed paydown.
5. Commit: `ci(ledger): add technical debt gate`.

**Objective criteria (verify --phase 4).** The CI workflow exists and runs `ledger.py gate`; measurement runs; the gate passes locally; tests pass; tree clean.

**Reviewed criteria.**
- The workflow is valid for the detected CI system, checks out full history, and installs the same tools used for the baseline.
- No other workflow was changed.
- The Dependabot or Renovate config matches the real package ecosystems.

### Phase 5: Report

**Goal.** Prove the value and hand the branch to the Owner.

**Tasks.**
1. Run `bash .ledger/measure.sh` and update `## Totals` in the register.
2. Write `PROGRESS.md` for non-technical readers, at most 300 words. Cover what was fixed; a before → after table of the totals; estimated monthly time and money saved (labelled as estimates, with assumptions); skipped items and why; and recommended next steps, including the remaining Tier 1 and Tier 2 work.
3. Write `PR_DESCRIPTION.md`: summary, list of changes per item, how behaviour was protected, test results, metrics before → after, risks, and a checklist for the Owner's review.
4. If any item was skipped or any phase escalated, make sure `BLOCKED.md` is accurate.
5. Commit: `docs(ledger): phase 5 report`.

**Objective criteria (verify --phase 5).** `PROGRESS.md` and `PR_DESCRIPTION.md` exist; phases 0–4 are approved; every done item is approved and none is in progress; tests pass; tree clean.

**Reviewed criteria.**
- Every number in `PROGRESS.md` matches the metrics and the register.
- Savings are clearly labelled as estimates and show their assumptions.
- Skipped items and limitations are reported honestly, not hidden.
- `PR_DESCRIPTION.md` gives a reviewer everything needed to review the branch.

After phase 5 is approved, the run is complete. The Builder ends with a final message to the Owner: the branch name, the approved phases, the items fixed and skipped, the headline numbers, and the instruction to review `PR_DESCRIPTION.md` and merge if satisfied.

---

## 6. Escalation

Escalate when a phase (not a single item) is rejected `max_attempts_per_step` times, when the self-check fails 5 times, when the Guard blocks something the roadmap needs, when the test suite fails in phase 0, or when anything happens that this roadmap does not cover.

To escalate:
1. Stop working on the step. Do not try to get around the problem.
2. Write `BLOCKED.md`: the phase and step, what was attempted, the last verify output, the Auditor's last required fixes, what you think is needed from the Owner, and how to resume.
3. Have the Auditor record it: delegate `Record BLOCKED for phase <N>: <one line>`.
4. Commit: `chore(ledger): blocked at phase <N>`.
5. End the run with a short message to the Owner pointing to `BLOCKED.md`.

## 7. Hard limits (enforced by the Guard)

Never push, merge, rebase, hard-reset, amend, force-delete branches or skip git hooks. Never delete files recursively, use sudo, pipe downloads into a shell, use remote shells, publish packages, deploy, or use cloud CLIs. Never read or write `.env` files, keys or credentials. Never edit `.ledger/approvals.jsonl`, `.ledger/state.json`, `.ledger/ledger.py` or `.ledger/measure.sh` directly. Never edit `.ledger/baseline.json` or `.ledger/config.json` after phase 0 is approved. Never edit protected paths or any CI workflow other than the gate. Never commit outside the `clean-ledger` branch.
