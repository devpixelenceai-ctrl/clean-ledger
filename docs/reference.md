# Reference

## Slash commands

| Command | What it does |
|---|---|
| `/clean-ledger:run [max fixes]` | Runs the whole roadmap, or resumes it from the first step not yet approved. The number caps how many Tier 1 items are fixed (default 3). |
| `/clean-ledger:status` | Shows phases, items, recent verdicts, and whether the run is blocked. Changes nothing. |
| `/clean-ledger:review [base]` | Read-only review of the current branch for newly added debt. Useful before opening any pull request, not just Clean Ledger ones. |

## `ledger.py` subcommands

Run from the repository root. After `init`, the script lives at `.ledger/ledger.py`.

| Subcommand | Purpose |
|---|---|
| `init --src <dirs or files> --test-command "<cmd>" --base-branch <branch> [--protected <paths>] [--tool-dir <dirs>]` | Creates `.ledger/`, copies `ledger.py` and `measure.sh` into it, writes `config.json` (including the roadmap path), and updates `.gitignore`. |
| `churn [--since "12 months ago"]` | Commits and distinct authors per file, as CSV. |
| `metrics [--reports <dir>]` | Summarises the reports into JSON: functions, complex functions, max/average complexity, duplication, security counts and tool versions. |
| `hotspots [--markdown \| --json] [--limit N]` | Ranks files into Tiers 1–3. |
| `snapshot-baseline` | Phase 0: copies `metrics.json` to `baseline.json`. Refused after Phase 0 approval. |
| `queue` | Writes `.ledger/queue.json` with the Tier 1 items. |
| `start-item <file>` | Snapshots a file's metrics and the start commit before fixing it. |
| `skip-item <file> --reason "<why>"` | Marks a reverted item as skipped. |
| `verify --phase N [--item <file>] [--step plan\|final]` | Runs the objective checks. Exits 1 on any FAIL, and saves the result in `.ledger/verify/`. |
| `record --phase N [--item <file>] [--step plan] --verdict APPROVED\|REJECTED\|BLOCKED --attempt K --notes "…"` | **Auditor only.** Appends a verdict to `approvals.jsonl` and updates `state.json`. Refuses an approval without a passing `verify` at the current commit. |
| `render-gate --template <assets/ledger-gate.yml>` | Writes the CI gate workflow, with tool versions pinned to those installed. |
| `gate [--baseline f] [--current f] [--dup-tolerance 0.1]` | Compares current metrics with the baseline. Exits 1 if debt grew. |
| `status` | Prints the run's progress and the roadmap path. |

`bash .ledger/measure.sh` runs lizard, jscpd, Semgrep (if installed) and churn the same way locally and in CI. It writes `.ledger/reports/` and `.ledger/metrics.json`.

## Configuration (`.ledger/config.json`)

Written by Phase 0, and frozen once Phase 0 is approved.

| Key | Default | Meaning |
|---|---|---|
| `branch` | `clean-ledger` | Work branch; commits anywhere else are blocked |
| `base_branch` | `main` | Branch the work starts from |
| `src_dirs` | `["src"]` | Folders **or files** to analyse and fix |
| `test_command` | set by `init` | Command that must pass at every checkpoint |
| `test_timeout_seconds` | `1800` | Time limit per test run |
| `test_attempts` | `2` | Runs per check. A pass after a failure adds a "flaky" warning |
| `protected_paths` | `[]` | Paths never to edit (matched by path segment) |
| `tool_dirs` | `[]` | Folders holding lizard, jscpd or Semgrep when they are not on `PATH` |
| `roadmap` | set by `init` | Absolute path to `ROADMAP.md`, for the Auditor |
| `hourly_cost` | `null` ($75 assumed) | Rate used for monthly cost estimates |
| `currency` | `USD` | Currency label for estimates |
| `max_fixes_per_run` | `3` | Fix budget per run |
| `max_attempts_per_step` | `3` | Rejections before an item is skipped or a phase escalated |
| `tier1_size` | `10` | Top hotspots that can become Tier 1 |
| `ccn_limit` | `15` | A function counts as complex above this cyclomatic complexity |
| `ci_file` | `.github/workflows/ledger-gate.yml` | Path of the CI gate workflow |
| `autopilot` | `true` | The Guard enforces its limits while this is true |

## Files Clean Ledger adds to your repository

```
.ledger/
  config.json          configuration (frozen after phase 0)
  baseline.json        metrics at the start (frozen after phase 0)
  state.json           phase and item status (written only by ledger.py)
  approvals.jsonl      the audit trail: every verdict with its commit
  queue.json           the Tier 1 fix queue
  items/               per-item snapshot (<slug>.json) and refactor plan (<slug>-plan.md)
  ledger.py, measure.sh  the engine (also used by CI)
  reports/ metrics.json verify/   generated, git-ignored
CLAUDE.md              project memory: overview, architecture, commands, conventions, protected paths, debt rules
BASELINE.md            the starting point, in words
DEBT_REGISTER.md       totals, hotspots, dependencies, team input, done, observations
PROGRESS.md            plain-English results (at most 300 words)
PR_DESCRIPTION.md      a ready-made pull-request description
BLOCKED.md             only if the run stopped and needs you
.github/workflows/ledger-gate.yml   the CI gate
```

## Plugin layout

```
.claude-plugin/        plugin.json, marketplace.json
skills/clean-ledger/   SKILL.md (the Builder's instructions), ROADMAP.md (the contract),
                       scripts/ (ledger.py, measure.sh), assets/ (gate template, settings templates)
agents/ledger-auditor.md   the Auditor subagent
hooks/                 hooks.json, guard.py
commands/              run.md, status.md, review.md
tests/                 the test suite (Python standard library only)
e2e/                   the end-to-end harness: Docker image, local runner, judge
runner/                the fleet runner (clean_ledger_fleet.py), its Docker image and an example fleet file
```
