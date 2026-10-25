# Clean Ledger

**Audited technical-debt paydown for Claude Code.**

Clean Ledger is a Claude Code plugin that pays down technical debt in a code repository by itself, under strict rules. It:
1. measures the debt with free tools;
2. ranks it by what it costs your team;
3. refactors the worst parts behind tests that prove behaviour did not change;
4. adds a CI gate so the debt does not come back;
5. writes a report.

An independent **Auditor** subagent approves every step, and a **Guard** hook blocks dangerous actions. You start it with one command and come back to a branch that is ready for review. Nothing is ever pushed or merged without you.

```
/clean-ledger:run 3
```

## Why

Technical debt (code that is complex, duplicated or untested) slows down every change and causes bugs. Paying it down is valuable but tedious, and an AI agent let loose on a codebase can do real damage. Clean Ledger makes the paydown **safe and verifiable**:
- every change is pinned by tests first;
- every step is checked by scripts and by an independent auditor;
- everything is recorded in an audit trail you can read.

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
   │ blocks push,     │                     │ objective checks,  │
   │ merge, secrets…  │                     │ audit trail        │
   └──────────────────┘                     └────────────────────┘
```

| Phase | What happens | Output |
|---|---|---|
| 0 Setup | Checks tools and tests, writes project memory, records a baseline | `CLAUDE.md`, `BASELINE.md`, `.ledger/` |
| 1 Measure | Complexity, duplication, security findings and change history for every file | `DEBT_REGISTER.md` |
| 2 Prioritise | Ranks hotspots (changed often × complex × insecure) and estimates their monthly cost | Tier 1 fix queue |
| 3 Fix | For each item: characterization tests → plan → **plan audit** → small refactor steps → **final audit** | Refactor commits |
| 4 Prevent | Adds a free CI gate that fails pull requests which add debt | `.github/workflows/ledger-gate.yml` |
| 5 Report | Writes a plain-English summary and a pull-request description | `PROGRESS.md`, `PR_DESCRIPTION.md` |

## Results so far

The latest unattended end-to-end run (version 1.2.2), on the Python library [prettytable](https://github.com/prettytable/prettytable), was **approved at every step on the first attempt**.
- **The worst function:** complexity went from 35 to 28.
- **Tests:** 145 characterization tests were added, and all 483 tests pass.
- **Behaviour:** no change, confirmed by an independent reviewer who read the full diff.

An earlier run failed review, and its failures shaped versions 1.2 and 1.3. Every run is written up in [docs/testing-and-results.md](docs/testing-and-results.md).

## Documentation

| Read this | To learn |
|---|---|
| [What is Clean Ledger?](docs/what-is-clean-ledger.md) | The idea, the roles and a walk-through of a real run, step by step |
| [Getting started](docs/getting-started.md) | How to install it and run it on your repository, step by step |
| [How it works](docs/how-it-works.md) | Each phase in detail: tasks, checks and what the Auditor looks for |
| [Safety](docs/safety.md) | The Guard, the Auditor, sandboxing, hard limits and honest limitations |
| [Reference](docs/reference.md) | Commands, `ledger.py` subcommands, configuration and the files it adds |
| [Troubleshooting](docs/troubleshooting.md) | What to do when a run stops with `BLOCKED.md` |
| [Testing and results](docs/testing-and-results.md) | The test suite, the end-to-end harness and real run results |
| [Changelog](CHANGELOG.md) | What changed in each version, and why |

## Quick start

1. **Install the plugin** in Claude Code:
   ```
   /plugin marketplace add devpixelenceai-ctrl/clean-ledger
   /plugin install clean-ledger@clean-ledger-marketplace
   ```
2. **Install the free analysis tools:**
   ```bash
   pip install lizard semgrep
   npm install -g jscpd
   ```
3. **Open a repository whose tests pass** and start a run:
   ```
   /clean-ledger:run 1
   ```
4. **Review the `clean-ledger` branch**, starting with `PR_DESCRIPTION.md`, and merge it if you are happy.

[Getting started](docs/getting-started.md) has the full version, including how to run it unattended and safely.

## Requirements

- [Claude Code](https://docs.claude.com/en/docs/claude-code/overview).
- Git, Python 3.9 or later, and Node.js 18 or later.
- A repository whose test suite passes. Clean Ledger refuses to refactor on top of failing tests.

## Status

Version 1.3.0, lightly field-tested:
- one manual run on Express (JavaScript);
- three unattended runs on prettytable (Python): the last passed, one failed review, and one stopped correctly on an environment problem;
- 83 automated tests.

Run it on a small, non-critical repository first, and read its audit trail before trusting it with important code.

## Development

```bash
./tests/run_tests.sh          # unit and integration tests (Python standard library only)
claude plugin validate .      # check the plugin manifests
```

See [docs/testing-and-results.md](docs/testing-and-results.md) for the end-to-end harness.

## License

MIT. See [LICENSE](LICENSE).
