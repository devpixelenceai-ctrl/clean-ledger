# Changelog

Each release after 1.0.0 came out of a real run of Clean Ledger, checked by an automated judge and an independent reviewer. See [docs/testing-and-results.md](docs/testing-and-results.md) for those runs.

## 1.5.0

Fixes from the first full run of the plugin installed from GitHub, on node-semver (JavaScript). Every phase was approved, and `ranges/subset.js` went from complexity 84 to 12 with all 8,756 assertions still passing. The run also exposed these gaps:

- **New `ledger.py queue --order <files>`.** Phase 2 now sets the fix order with a command instead of hand-editing `queue.json`. It refuses a list that drops, adds or repeats a file, or puts a non-security item before a security one.
- **New `ledger.py raise-baseline`** for the Owner after a reviewed paydown. It works only after Phase 5 is approved, and refuses if any metric is worse than the baseline, so it can only tighten the gate. The getting-started guide and the Phase 4 `## Quality gate` text now use it.
- **Guard:** read-only git plumbing with similar names, such as `git merge-base`, is no longer blocked as a `git merge`.
- **Roadmap golden rule 8:** scratch files stay under `.ledger/reports/`, never outside the repository. The run had written a helper script to the session's scratchpad.
- **Roadmap Phase 3c:** mutation checks run only in a throwaway worktree under `.ledger/reports/`. The target file is never edited before the plan is approved, not even temporarily.
- **E2E judge:** a credential-looking URL found only in the project's own test output (node-semver's fixtures contain `user:password@` URLs) is a warning, not a failure. Anywhere else it still fails.
- **Skill:** lists the control files by name, and treats a permission-rule denial like any other refusal: escalate, never re-run a trimmed command.
- **E2E judge:** also warns about shell commands that write outside the project (`cp`, `mv`, `tee`, redirects to absolute or `$VAR/` paths). `judge.py --help` works.
- **E2E harness:** `local_run.py --collect` runs the project's configured test command instead of assuming Python.

## 1.4.1

Fixes from the first test of the plugin installed from GitHub, run on node-semver. The run stopped correctly at phase 0 with `BLOCKED.md`.

- **`settings.sandboxed.json` blocked the plugin from reading its own files.** It denied all of `~/.claude`, but a plugin installed from a GitHub marketplace lives in `~/.claude/plugins/cache/`, so the Builder could not read `ROADMAP.md`. The template now blocks only the sensitive parts:
  - transcripts and project memory;
  - sessions, history and file history;
  - settings;
  - credentials.

  It now also blocks `~/.claude.json`, which it missed before.
- **The sandbox template allows `registry.npmjs.org`,** so JavaScript projects can install their dependencies.
- **Guard:** a commit in the same command that first switches to the work branch is allowed, for example `git switch -c clean-ledger && git commit …`. Previously it was blocked, because the hook runs while HEAD is still on the old branch.
- **E2E harness:** `local_run.py` takes any repository (`--repo`, `--ref`, `--setup`) and can install the plugin from a marketplace (`--plugin-source owner/repo`), just as a user would.

## 1.4.0

- **Fleet runner** (`runner/clean_ledger_fleet.py`, [docs/fleet.md](docs/fleet.md)):
  - Runs Clean Ledger on many repositories in parallel. Each one gets a fresh clone, pinned to a ref, with no git remote.
  - Executors: `docker` (a throwaway container per repository, from `runner/Dockerfile`), `local` (headless and sandboxed) or `command`.
  - Every repository is judged with the e2e judge, and the results go into `fleet-report.md` and `fleet-summary.json`.
  - A free `plan` mode checks every repository and the executor without calling Claude.
- **Security policy** ([SECURITY.md](SECURITY.md)): private vulnerability reporting, scope, and how the repository is protected.
- **This repository:**
  - a GitHub Actions test workflow (read-only token, actions pinned to full commit hashes) and Dependabot for the pins;
  - published with a clean history and a no-reply commit email;
  - secret scanning with push protection, Dependabot alerts, a protected `main` branch, and GitHub-owned, hash-pinned actions only.

## 1.3.0

Fixes for the minor issues found by the second prettytable end-to-end run. That run passed: the judge returned PASS and the review returned PASS WITH ISSUES.

- **Roadmap:**
  - Every refactor commit names its plan step.
  - Anything unplanned needs a plan-amendment commit first.
  - No change may exist only to move a metric.
  - The Auditor maps each commit to a plan step.
- **Roadmap:** the built-in Semgrep CA-bundle fallback is named as the only sanctioned certificate exception.
- **Disclosure:** `BASELINE.md` and `PROGRESS.md` must list the checks that were not run and the metrics that were not measured.
- **Auditor:** scratch output, such as coverage data, stays under `.ledger/reports/`.
- **E2E judge:**
  - Fails on file writes outside the project.
  - Warns on reads outside the project and on use of the desktop app's side-session notes.

## 1.2.2

- **Semgrep in sandboxes that hide the OS certificate store:** `measure.sh` and the tool-version check retry once with Python's CA bundle, and log that they did. This was reproduced and verified under a macOS sandbox profile that blocks the certificate service.

## 1.2.1

- **Semgrep's own files:** `measure.sh` keeps Semgrep's settings, log and version cache in `.ledger/reports/semgrep-home/` unless they are already set. Semgrep can then run in sandboxes that forbid writing to `~/.semgrep`.

## 1.2.0

Fixes from the first prettytable end-to-end run, which the independent review failed on process grounds.

- **Guard: only real writes to control files are blocked.** Covered forms:
  - redirect targets;
  - `cp`, `mv`, `tee`, `rm`, `sed -i`, `ln` and `dd` destinations;
  - `git checkout --`;
  - inline Python or Node writes.

  The first run had 19 false blocks; the same commands now produce 0. Three real-write forms the old Guard missed are now caught.
- **Guard: active earlier.** It is active as soon as `.ledger/` exists, and blocks more forms of environment dump.
- **Shell and file tools agree:** `baseline.json` and `config.json` are writable until phase 0 is approved, then frozen.
- **New command, recorded path:** `ledger.py snapshot-baseline` for phase 0. `init` records the roadmap path for the Auditor.
- **Roadmap:**
  - Never route a refused action through another tool.
  - Record tools that cannot run as "not measured".
  - Never dump environment variables.
  - Every refusal is listed in the audit brief, and the Auditor rejects workarounds.
- **Honest numbers:** tool versions are read only from a successful `--version`; unmeasured security is shown as "n/a".
- **E2E judge:**
  - Reads exported sessions and counts real Guard blocks.
  - Fails on credential URLs and on tool-switch workarounds.

## 1.1.0

Fixes for problems found by running 1.0.0 by hand on Express.

- **Guard: finding the repository.** It finds the ledger repository even when the session starts in a parent folder.
- **Guard: git global options.** It blocks `git -C <dir> push`, `git --no-pager push` and similar forms.
- **`verify`: flaky test suites.**
  - A failing test suite is re-run once (`test_attempts`).
  - A pass after a failure is flagged as a warning.
  - The full log of every run is kept, and the failing tests are named.
- **`verify`: protected paths.** They are checked in every phase and matched by path segment, so `lib` no longer matches `library.js`.
- **Sources and duplicates:**
  - `src_dirs` may contain files as well as folders.
  - Duplicates are matched by exact path (`jscpd --absolute`) and counted per distinct line.
- **`tool_dirs` / `--tool-dir`:** for user-level tool installs. Metrics record the tool versions.
- **`ledger.py render-gate`:** writes a CI gate with pinned tool versions, read-only permissions and no persisted credentials. Phase 4 checks the pins.
- **Roadmap:** covers installs without a lockfile, and the new commands and checks.

## 1.0.0

- First version: roadmap, `ledger.py`, `measure.sh`, the Auditor subagent, the Guard hook, commands and the CI gate template.
