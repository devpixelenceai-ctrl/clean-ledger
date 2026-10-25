# Changelog

Each release after 1.0.0 came out of a real run of Clean Ledger, checked by an automated judge and an independent reviewer. See [docs/testing-and-results.md](docs/testing-and-results.md) for those runs.

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
