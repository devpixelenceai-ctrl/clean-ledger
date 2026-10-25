# What is Clean Ledger?

This page explains Clean Ledger from the ground up: the problem it solves, the people and programs involved, and what happens, step by step, when it runs on a real project.

## 1. The problem: technical debt

Every codebase collects shortcuts:
- a function that grew to 200 lines;
- the same logic copied into three places;
- code nobody dares to touch because nothing tests it.

This is **technical debt**. Like financial debt, it charges interest: every change to that code takes longer and is more likely to break something.

Paying it down means **refactoring**: changing the structure of the code without changing what it does. It is valuable work, but it is slow, it is easy to postpone, and it is risky. A refactor that accidentally changes behaviour is a new bug.

## 2. The idea: let an AI agent do it, under audit

Claude Code can read, test and refactor code. Letting it loose on a repository unsupervised is risky, though. It might:
- "fix" behaviour that users depend on;
- skip tests;
- report success when it failed;
- run a command that destroys work.

Clean Ledger wraps Claude Code in a **contract and a set of checks**, so its work can be trusted without a person approving every step:

- **A contract**, [ROADMAP.md](../skills/clean-ledger/ROADMAP.md). Six phases, with the exact tasks, the objective criteria and the review criteria for each.
- **Golden rules.** Behaviour is sacred. Tests come before code. Steps are small. Evidence beats claims. Nothing leaves the branch. When in doubt, stop.
- **Objective checks.** `ledger.py verify` runs dozens of pass/fail checks for each phase. Examples:
  - the tests pass;
  - characterization tests were committed before the code changed;
  - no metric got worse;
  - protected files are untouched.
- **An independent Auditor.** A separate subagent re-runs the checks, reads the code and approves or rejects each step. It is the only one allowed to record verdicts.
- **A Guard.** A hook that inspects every command before it runs and blocks dangerous ones. Examples: pushing, merging, rewriting history, editing the audit trail, reading secrets.

## 3. The four roles

| Role | Who | Does | Never does |
|---|---|---|---|
| **Owner** | You | Starts the run, reads the report, reviews and merges the branch | Needs to approve anything during the run |
| **Builder** | Your Claude Code session | Does each phase's work and commits it | Approves its own work, records verdicts, pushes or merges |
| **Auditor** | The `ledger-auditor` subagent | Runs the checks, reviews the work, records APPROVED or REJECTED | Edits code or fixes problems itself |
| **Guard** | A PreToolUse hook (`hooks/guard.py`) | Blocks dangerous actions, whatever any prompt says | Can be talked out of a block |

## 4. The six phases at a glance

| # | Phase | Question it answers | You get |
|---|---|---|---|
| 0 | Setup | Is this repository ready, and where are we starting from? | `CLAUDE.md`, `BASELINE.md` |
| 1 | Measure | Where is the debt, in numbers? | `DEBT_REGISTER.md` |
| 2 | Prioritise | Which debt costs the most? | A Tier 1 fix queue with monthly cost estimates |
| 3 | Fix | Can we pay down the worst items without changing behaviour? | Characterization tests and small refactor commits |
| 4 | Prevent | How do we stop new debt? | A CI gate workflow |
| 5 | Report | What did we gain? | `PROGRESS.md` and `PR_DESCRIPTION.md` |

Each phase ends with an audit. A rejection sends the Builder back to fix what the Auditor found and try again, up to three times. Phase 3 has two audits per item: one for the plan before any code changes, and one for the finished refactor.

## 5. A real run, step by step

This is what actually happened when Clean Ledger 1.2.2 ran unattended on [prettytable](https://github.com/prettytable/prettytable) 3.18.0, a Python library that prints tables. The run started from a single command, `/clean-ledger:run 1`, which allows one fix.

**Step 1: Setup (phase 0).**
1. Created `.ledger/`, which switches the Guard on, then created the `clean-ledger` branch.
2. Initialised the ledger, configured the source folder and test command, and installed the project's dependencies.
3. Ran the test suite: **338 tests passed**.
4. Measured the baseline:
   - 206 functions;
   - **9 functions over complexity 15**, the worst at **35**;
   - 2.99% duplicated code;
   - 0 security findings.
5. Wrote `CLAUDE.md` and `BASELINE.md`, then asked the Auditor. **Approved**: 20 of 20 objective checks passed.

**Step 2: Measure (phase 1).** Wrote `DEBT_REGISTER.md`, which contains:
- totals;
- a hotspot table that ranks each file by how often it changes and how complex it is;
- outdated dependencies;
- observations.

**Approved.** The Auditor checked that every number traced back to a report.

**Step 3: Prioritise (phase 2).**
- **The fix queue:** one Tier 1 item, `src/prettytable/prettytable.py`. It is the library's main file: changed 34 times by 9 authors in a year, with the most complex function in the project.
- **The cost estimate:** about **$319 a month** in extra effort, clearly labelled as an estimate with its assumptions.

**Approved.**

**Step 4: Fix (phase 3).**
1. Snapshotted the file's metrics.
2. Wrote **145 characterization tests** that pin the current behaviour, including odd behaviour and three existing bugs, which it kept and documented rather than "fixing".
3. Committed the tests, wrote a step-by-step refactor plan, and asked for the **plan audit**: **approved** before the file was touched.
4. Carried out the plan in small commits, running the tests after each. Three tangled sections became small named helpers.
5. Recorded the result:
   - worst complexity **35 → 28**;
   - the three refactored functions went from 35, 31 and 27 down to 25, 18 and 23.
6. **Final audit.** The Auditor read the whole diff and confirmed every change was behaviour-preserving. **Approved.**

**Step 5: Prevent (phase 4).** Generated a GitHub Actions workflow that re-measures every pull request and fails it if the debt grows. The tool versions are pinned to the ones used for the baseline. **Approved.**

**Step 6: Report (phase 5).** Wrote:
- `PROGRESS.md` for non-technical readers;
- `PR_DESCRIPTION.md` for the reviewer. Its contents:
  - changes;
  - how behaviour was protected;
  - test results (**483 passing**);
  - before → after metrics;
  - risks;
  - a review checklist.

**Approved.**

**The result:**
- **Branch:** a `clean-ledger` branch with 22 commits, each phase approved on the first attempt.
- **Git:** `main` untouched, and nothing pushed.
- **Audit trail:** every verdict is in `.ledger/approvals.jsonl`.

An independent reviewer and an automated judge then checked the whole run. See [testing-and-results.md](testing-and-results.md).

## 6. What Clean Ledger is not

- **It does not prove correctness.** It proves behaviour was *preserved as far as the tests can see*. Characterization tests help a lot, but code with heavy input/output, timing or external services is harder to pin down.
- **It is not tamper-proof security.** The Auditor runs inside the same Claude Code session as the Builder. The Guard and `ledger.py` make cheating hard and visible, but your review before merging is the final control.
- **It is not a full security audit.** Semgrep's default rules are a starting point.

## Next

- [Getting started](getting-started.md): install it and run it yourself.
- [How it works](how-it-works.md): every phase in detail.
