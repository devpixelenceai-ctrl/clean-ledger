# How it works

This page goes through a run in detail: the protocol every step follows, then each phase's tasks, its objective checks and what the Auditor reviews. The authoritative text is [ROADMAP.md](../skills/clean-ledger/ROADMAP.md); this page explains it.

## The protocol: every step, the same way

A *step* is one of:
- a phase (0, 1, 2, 4 or 5);
- one of the two checkpoints of a Phase 3 item (`plan`, then `final`);
- the Phase 3 sign-off.

Every step follows the same seven moves:

1. **Read** the roadmap section for the step.
2. **Do** the tasks, and commit the work.
3. **Self-check.** Run `python3 .ledger/ledger.py verify --phase N` (plus `--item <file> [--step plan]` in Phase 3) and fix problems until it passes. After five failed tries, escalate.
4. **Audit.** Delegate to the `ledger-auditor` subagent with a fixed brief:
   ```
   Audit phase <N> [item <file> step <plan|final>], attempt <k>.
   Builder summary: <what was done>. Refusals: <none, or each Guard/sandbox refusal>.
   ```
5. **Verdict.** The Auditor runs `verify` itself, reviews the work and records `APPROVED`, `REJECTED` or `BLOCKED` with `ledger.py record`. `record` refuses an approval unless a passing `verify` exists for the current commit.
6. **Commit the record:** `chore(ledger): audit phase <N> <verdict>`.
7. **Act on the verdict.**
   - On `REJECTED`, apply every required fix and go back to move 3. After three rejections, an item is reverted and skipped; a phase is escalated.
   - On `APPROVED`, move to the next step.

The Builder never runs `ledger.py record` itself.

## Phase 0: Setup

**Goal:** a repository that is ready, with a trusted baseline. No application code changes.

**Tasks:**
1. Run `mkdir -p .ledger`, which switches the Guard on.
2. Check that git, Python and Node are available, and that the working tree is clean.
3. Create the `clean-ledger` branch from the default branch.
4. Install the analysis tools if they are missing.
5. Run `ledger.py init`. It takes:
   - the source folders or files;
   - the exact test command;
   - the base branch;
   - the protected paths;
   - the tool folders, if the tools aren't on `PATH`.
6. Install the project's dependencies and run the tests. **If they fail, the run stops.**
7. Write `CLAUDE.md`, with these sections:
   - Overview;
   - Architecture;
   - Commands;
   - Conventions;
   - Protected;
   - Debt rules.
8. Run `bash .ledger/measure.sh`, then `ledger.py snapshot-baseline`.
9. Write `BASELINE.md`, including a "Not checked" list.

**Objective checks:**
- right branch;
- valid config, and the source paths exist;
- tools installed;
- valid baseline;
- the required `CLAUDE.md` sections;
- `.gitignore` entries;
- no source, test or protected files changed;
- tests pass;
- clean tree.

**The Auditor reviews:**
- Are the commands real, matching the manifests and CI?
- Do the source paths cover the real code, and only that?
- Do the protected paths cover generated, vendored and sensitive files?
- Does the architecture description match the code?
- Does `BASELINE.md` match `baseline.json`?

## Phase 1: Measure

**Goal:** one `DEBT_REGISTER.md` listing every significant debt item, with numbers. Measurement only.

**How measurement works.** `measure.sh` runs the same tools the same way, locally and in CI:

| Measures | Tool | Writes |
|---|---|---|
| Complexity per function | lizard | `.ledger/reports/lizard.csv` |
| Duplicated blocks | jscpd | `.ledger/reports/jscpd-report.json` |
| Security and smells | Semgrep `p/default` (optional) | `.ledger/reports/semgrep.json` |
| Churn: commits and authors per file over 12 months | git log | `.ledger/reports/churn.csv` |

It then summarises everything into `.ledger/metrics.json`.

**The hotspot table.** `ledger.py hotspots` ranks files:

> score = churn percentile × complexity percentile × (1 + security weight)

A file is **Tier 1** if it has a high-severity security finding, or if it is in the top 10 and has at least one complex function (complexity over 15). A file is **Tier 2** if it is complex and changes. Everything else is **Tier 3**.

**The register's sections:**
- Totals;
- Hotspots, with a plain-English problem note per Tier 1 file;
- Dependencies;
- Team input;
- Done;
- Observations.

**The Auditor reviews:**
- Do the problem notes describe what is really wrong? It spot-checks Tier 1 files by reading them.
- Do the totals match `metrics.json`?
- Are the observations specific?
- Does every number trace back to a report?

## Phase 2: Prioritise

**Goal:** debt ranked by cost, and an ordered fix queue.

**Tasks:**
1. Run `ledger.py queue`, which writes `.ledger/queue.json` with the Tier 1 items.
2. Estimate each item's monthly cost: hours lost per month × hourly rate. The default rate is $75, and the assumptions are shown.
3. Add a "Tier 1 queue" table to the register.

**The Auditor reviews:**
- Is the order sensible, with security first, then cost?
- Are the estimates labelled as estimates, with their assumptions?
- Has anything that should be Tier 3 been queued without a reason?

## Phase 3: Fix

**Goal:** pay down up to `max_fixes_per_run` items, each one safely. For each item in queue order:

1. **Start.** Run `ledger.py start-item <file>`, which snapshots the file's metrics and the start commit.
2. **Understand.** Read the file, its callers and its tests. Find the public interfaces, the hidden rules and the side effects.
3. **Protect.** Write **characterization tests** that lock in the current behaviour:
   - every reachable branch;
   - edge cases and error paths;
   - odd behaviour.

   Existing bugs are kept and marked with a comment, not fixed. The tests must pass on the unchanged code, and are committed before any change.
4. **Plan.** Write `.ledger/items/<slug>-plan.md`: numbered steps, each with the change, its risk and how it will be verified, plus the public interfaces that must not change.
5. **Plan checkpoint audit.** The target file must not change until this is approved.
6. **Refactor.** Carry out the plan one step at a time.
   - **Tests:** run them after each step, then commit as `refactor(<module>): step N - …`.
   - **Planned steps only:** anything not in the plan needs a plan amendment commit first.
   - **No metric-gaming:** never reshape code only to move a metric.
7. **Record.** Add a row to the register's `## Done` table, with the before → after numbers.
8. **Final checkpoint audit.**

**Objective checks at the final checkpoint:**
- the plan was approved before refactoring;
- tests were committed before the first change to the target;
- at least two commits, including a `refactor(`/`fix(` one;
- tests added, none deleted;
- no protected or control files touched;
- tests pass;
- **no metric for the file got worse, and at least one improved**;
- the whole-repo gate against the baseline passes;
- the item is in `## Done`.

**The Auditor reviews:**
- It reads the full diff of the target, and every hunk must be a behaviour-preserving restructure.
- Public signatures are unchanged.
- No assertion was removed or loosened.
- Every commit maps to a plan step.
- The code is easier to read.
- The Done numbers match the measurements.

**What happens to items that fail:**
- **Three rejections:** the item's commits are reverted with `git revert` (never a reset), the item is skipped with a reason and listed in `BLOCKED.md`, and the run continues.
- **The sign-off:** when the budget is used up or the queue is empty, a final Phase 3 audit checks that nothing is half-finished.

## Phase 4: Prevent

**Goal:** debt that has been paid stays paid.

1. `ledger.py render-gate --template <skill>/assets/ledger-gate.yml` writes `.github/workflows/ledger-gate.yml`. It has read-only permissions, does not persist checkout credentials, and pins lizard, jscpd and Semgrep to **the versions recorded in the baseline**.
2. Dependabot or Renovate is added if the repository has neither.
3. A `## Quality gate` section is added to `CLAUDE.md`.

On every pull request, the workflow runs `measure.sh` and then `ledger.py gate`. It fails if any of these rose above the baseline:
- complex functions;
- duplication, beyond a 0.1-point tolerance;
- high- or medium-severity findings.

## Phase 5: Report

1. Re-measure, and update the register's totals.
2. Write `PROGRESS.md`, at most 300 words, for non-technical readers. It covers:
   - what was fixed;
   - a before → after table;
   - estimated savings, labelled with their assumptions;
   - skipped items;
   - what was not checked;
   - next steps.
3. Write `PR_DESCRIPTION.md` for the reviewer.

After the final approval, the Builder hands over: the branch, the approved phases, the items fixed and skipped, the headline numbers, and "review `PR_DESCRIPTION.md` and merge if satisfied".

## When things go wrong: escalation

The run **stops** and writes `BLOCKED.md` when:
- a phase is rejected three times;
- a self-check fails five times;
- the Guard or a sandbox refuses something the roadmap needs;
- the tests fail in Phase 0;
- anything happens that the roadmap does not cover.

It never works around a refusal: no switching tools, no changing certificates, caches or environment variables. You fix the cause and run `/clean-ledger:run` again to resume.

## Next

- [Safety](safety.md): the layers that protect your repository.
- [Reference](reference.md): every command and setting.
