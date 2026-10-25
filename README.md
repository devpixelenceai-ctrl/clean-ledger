# Clean Ledger

**Autonomous, audited technical-debt paydown for Claude Code.**

Technical debt is the cost of past shortcuts: complex, duplicated, untested code that makes every change slower and riskier. It is the largest single cost of poor software quality. Clean Ledger lets Claude Code pay it down on its own. It finds the debt, ranks it by what it costs, fixes the most expensive parts behind tests, adds a CI gate so the debt doesn't come back, and writes up the results.

You start it with one command. You come back to a branch ready for review.

## How it works

```
        You (Owner)                  configure once, review and merge at the end
            │
            ▼
   ┌──────────────────┐   "Audit phase N"   ┌────────────────────┐
   │     Builder      │ ──────────────────▶ │  ledger-auditor    │
   │ (Claude Code)    │ ◀────────────────── │  (subagent)        │
   │ does the work    │  APPROVED/REJECTED  │  checks evidence,  │
   └────────┬─────────┘   + required fixes  │  records verdict   │
            │                               └─────────┬──────────┘
            │ every tool call                         │ runs
            ▼                                         ▼
   ┌──────────────────┐                     ┌────────────────────┐
   │   Guard hook     │                     │    ledger.py       │
   │ hard-blocks push,│                     │ objective checks,  │
   │ merge, secrets…  │                     │ tamper-resistant   │
   └──────────────────┘                     │ approval records   │
                                            └────────────────────┘
```

There are four roles:

- **Builder.** Your main Claude Code session. It follows `ROADMAP.md` and does the work.
- **Auditor.** The `ledger-auditor` subagent. It runs objective checks, reviews the work against the roadmap, and approves or rejects each step. It never edits code, and it is the only one that records verdicts.
- **ledger.py.** A deterministic script with dozens of objective acceptance checks. It refuses to record an approval unless a passing verification exists for the current commit.
- **Guard.** A hook that blocks dangerous actions in code, whatever any prompt says.

The run goes through six phases, each gated by the Auditor:

| Phase | What happens | Audits |
| --- | --- | --- |
| 0 Setup | Installs free tools, writes CLAUDE.md, checks tests pass, records a baseline | 1 |
| 1 Measure | Builds `DEBT_REGISTER.md`: complexity, duplication, security, churn, dependencies | 1 |
| 2 Prioritise | Ranks hotspots (change frequency × complexity × security) and estimates monthly cost | 1 |
| 3 Fix | For each Tier 1 item: tests first → plan → **plan audit** → small refactor steps → **final audit** | 2 per item + sign-off |
| 4 Prevent | Adds a free CI gate that fails pull requests which add debt | 1 |
| 5 Report | Writes `PROGRESS.md` for managers and `PR_DESCRIPTION.md` for reviewers | 1 |

When the Auditor rejects work, the Builder fixes it and tries again, up to 3 attempts. If a single fix keeps failing, it is reverted and skipped, and the run moves on. If a whole phase keeps failing, the run stops and explains why in `BLOCKED.md`.

## What it catches

These were tested by simulation. The objective checks reject:

- Refactoring before the plan is approved.
- Writing tests *after* changing the code, which would lock in new behaviour instead of protecting old behaviour.
- Fixes that don't improve the target file, or that make any metric worse.
- Fixes that make the whole repository worse than the baseline.
- Deleted test files, touched protected paths, and edited control files.
- Failing tests, uncommitted work, and work on the wrong branch.
- Approvals with no passing evidence at the current commit.

The Auditor's reviewed criteria add human-style judgement on top. Are the tests meaningful? Is every change behaviour-preserving? Were any assertions weakened? Are the cost estimates honest?

## Requirements

- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview). It needs a paid Claude plan or API credits; everything else here is free.
- Git, Python 3.9+, Node.js 18+.
- A repository whose test suite passes. Clean Ledger refuses to refactor on top of failing tests.

The free analysis tools (lizard, jscpd, and Semgrep Community Edition, which is optional) are installed by phase 0.

## Install

Push this folder to a GitHub repository, then in Claude Code:

```
/plugin marketplace add YOUR_GITHUB_USER/clean-ledger
/plugin install clean-ledger@clean-ledger-marketplace
```

To try it before publishing, use a local path:

```
/plugin marketplace add /path/to/clean-ledger
/plugin install clean-ledger@clean-ledger-marketplace
```

Restart Claude Code afterwards. Type `/` to see the commands; plugin commands may be namespaced, for example `/clean-ledger:run`. Plugin and permission syntax can change between Claude Code versions, so check the [Claude Code docs](https://docs.claude.com/en/docs/claude-code/overview) if a step fails.

## Run it autonomously

Clean Ledger is designed to run without you approving each command. The Auditor approves the work, and the Guard enforces the hard limits. Choose one of these setups.

**Option A: allow-list (recommended).** Copy the permission template into the repository you want to clean, then run:

```
mkdir -p .claude
cp /path/to/clean-ledger/skills/clean-ledger/assets/settings.json .claude/settings.local.json
claude
> /clean-ledger:run 3
```

Commands on the allow-list run without prompting. Anything unusual still asks you, and the deny-list plus the Guard block the dangerous ones.

**Option B: fully hands-off, inside a container.** Run Claude Code in a dev container or VM that holds only a clone of the repository and no credentials. Then start it with permission checks bypassed. The Guard hook still runs and blocks pushes, merges, secrets and deletions. Never bypass permissions on your own machine or in a clone that has push credentials.

The number after `run` caps how many Tier 1 fixes are made in one run (default 3). This controls both risk and Claude usage.

## Commands

| Command | What it does |
| --- | --- |
| `/clean-ledger:run [max fixes]` | Runs or resumes the whole roadmap |
| `/clean-ledger:status` | Shows phases, items, recent verdicts and blocks |
| `/clean-ledger:review [base]` | Read-only review of any branch for new debt |

## Configuration

Phase 0 writes `.ledger/config.json`. It is frozen once phase 0 is approved.

| Key | Default | Meaning |
| --- | --- | --- |
| `branch` | `clean-ledger` | Work branch; commits are blocked anywhere else |
| `base_branch` | `main` | Branch the work starts from |
| `src_dirs` | `["src"]` | Folders or files to analyse and fix |
| `test_command` | detected | Command that must pass at every checkpoint |
| `test_attempts` | `2` | Runs of the test suite per check; a pass after a failure adds a "flaky" warning |
| `tool_dirs` | `[]` | Folders holding lizard, jscpd and Semgrep when they are not on `PATH` |
| `protected_paths` | `[]` | Paths that may never be edited |
| `max_fixes_per_run` | `3` | Fix budget per run |
| `max_attempts_per_step` | `3` | Rejections before skip or escalate |
| `hourly_cost` | `null` (75 assumed) | For monthly cost estimates |
| `tier1_size` | `10` | Top hotspots eligible for Tier 1 |
| `ccn_limit` | `15` | Complexity above which a function counts as complex |

## What it adds to your repository

```
.ledger/            config, baseline, fix queue, item snapshots and plans,
                    approvals.jsonl (the audit trail), state.json,
                    ledger.py + measure.sh (also used by CI)
CLAUDE.md           project memory
BASELINE.md         starting point
DEBT_REGISTER.md    ranked debt and everything fixed
PROGRESS.md         plain-English results
PR_DESCRIPTION.md   ready-made pull request description
BLOCKED.md          only if something needs you
.github/workflows/ledger-gate.yml   the CI gate
```

## Safety limits (Guard)

No push, merge, rebase, hard reset, amend, history rewrite, force branch delete or `--no-verify`. No recursive force delete, sudo, piping downloads into a shell, remote shells, package publishing, deploys or cloud CLIs. No reading `.env` files, keys or credentials. No direct edits to the audit trail or the control scripts. The baseline and config are frozen after phase 0. No edits to protected paths or other CI workflows, and no commits outside the work branch. The Guard is only active in repositories that contain a Clean Ledger config.

## Honest limitations

- **It is a strong process control, not tamper-proof security.** The Auditor runs in the same Claude Code session as the Builder. The Guard and `ledger.py` make cheating hard and visible, and every verdict is logged with its commit in `.ledger/approvals.jsonl`. They cannot make it impossible. Your review before merging is the final control.
- **Tests define safety.** If behaviour isn't covered by tests, the system can't prove it was preserved. Characterization tests help a lot, but areas with heavy I/O, timing or external services are harder to lock down.
- **Monorepos and exotic stacks** may need `src_dirs`, `test_command` and `protected_paths` adjusted by hand before the run.
- **Semgrep's default rules are a starting point**, not a full security audit.
- **Lightly field-tested.** Version 1.0.0's engine and roadmap were run by hand on one real project (Express, JavaScript): all six phases, one Tier 1 fix, with the Auditor rejecting and then approving phase 0. Version 1.1.0 fixes the problems that run exposed and has an automated test suite, but it has not yet been run end to end as an installed plugin, or on other languages. Run it on a small, non-critical repository first and read its audit trail before trusting it on important code.
- **The Guard reads commands, not intent.** It finds the repository from the edited file, any `cd` or `git -C` in the command, and the working folder, and it catches git subcommands written after global options. A command built in ways it does not parse (for example through a script file or variables) can still get past it.

## Development

The tests use only the Python standard library and create throwaway git repositories:

```bash
./tests/run_tests.sh
```

## Changelog

**1.2.0** (fixes from the first end-to-end run, on prettytable, which an independent review failed on process grounds)
- Guard: blocks only real writes to control files (redirect targets, cp/mv/tee/rm/sed -i/ln/dd destinations, `git checkout --`, inline Python/Node writes). 19 false blocks in the first run became 0; three real-write forms it used to miss are now caught. It is active as soon as `.ledger/` exists and blocks more environment dumps.
- Shell and file tools agree: `baseline.json` and `config.json` are writable until phase 0 is approved, then frozen.
- `ledger.py snapshot-baseline` for phase 0; `init` records the roadmap path for the Auditor.
- Roadmap: never route a refused action through another tool; record tools that cannot run as "not measured"; never dump environment variables; refusals are listed in every audit brief and workarounds are rejected.
- Honest numbers: tool versions only from a successful `--version`; unmeasured security shows as "n/a".
- E2E judge: reads exported sessions, counts real Guard blocks, and fails on credential URLs and tool-switch workarounds.

**1.1.0**
- Guard: finds the ledger repository even when the session starts in a parent folder, and blocks `git -C <dir> push`, `git --no-pager push` and similar forms.
- verify: re-runs a failing test suite once (`test_attempts`), flags a pass-after-failure as a warning, keeps every run's full log, and names the failing tests.
- verify: checks protected paths in every phase, matching by path segment (`lib` no longer matches `library.js`).
- `src_dirs` may contain files; duplicates are matched by exact path (`jscpd --absolute`) and counted per distinct line.
- `tool_dirs` / `--tool-dir` for user-level tool installs; metrics record tool versions.
- `ledger.py render-gate` writes a CI gate with pinned tool versions, read-only permissions and no persisted credentials; phase 4 checks the pins.
- Roadmap: no-lockfile installs, the new commands and checks.

## License

MIT
