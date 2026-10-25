# Getting started

This guide takes you from nothing to a reviewed Clean Ledger branch, one step at a time. Plan about 15 minutes of setup. The run itself takes one to a few hours, depending on the repository and the fix budget.

## Step 1: Check the prerequisites

You need:

- **Claude Code**, signed in. Clean Ledger runs inside it and uses your plan or API account.
- **Git**, **Python 3.9 or later** and **Node.js 18 or later**.
- **A repository whose test suite passes.** Clean Ledger will not refactor on top of failing tests, and Phase 0 stops if they fail.

Check:

```bash
claude --version && git --version && python3 --version && node --version
```

**Choose your first repository carefully.** Pick one that is small to medium, has a test suite that runs in a few minutes, and that you would not mind reviewing closely. A clone or a fork is ideal for a first run.

## Step 2: Install the analysis tools

Clean Ledger measures with three free tools:

| Tool | Measures | Required? |
|---|---|---|
| [lizard](https://github.com/terryyin/lizard) | Cyclomatic complexity per function | Yes |
| [jscpd](https://github.com/kucherenko/jscpd) | Duplicated code | Yes |
| [Semgrep](https://semgrep.dev) Community Edition | Security and code-smell findings | Optional (skip on Windows without WSL) |

The simplest install:

```bash
pip install lizard semgrep
npm install -g jscpd
```

**Prefer user-level installs?** Install into a folder of your own, for example:

```bash
python3 -m venv ~/.clean-ledger-tools && ~/.clean-ledger-tools/bin/pip install lizard semgrep
npm install --prefix ~/.clean-ledger-tools jscpd
```

If the tools aren't on your `PATH`, tell Clean Ledger where they are. Phase 0 passes the folders to `ledger.py init --tool-dir`, and you can mention them when you start the run.

## Step 3: Install the plugin

The complete instructions, including verification, team setup, updating and fixes, are in [installation.md](installation.md). In short:

**From GitHub** (public repository, no sign-in needed):

```
/plugin marketplace add devpixelenceai-ctrl/clean-ledger
/plugin install clean-ledger@clean-ledger-marketplace
```

**From a local folder** (a clone, or for trying changes):

```bash
claude plugin marketplace add /path/to/clean-ledger
claude plugin install clean-ledger@clean-ledger-marketplace
```

Add `--scope local` to both commands, run from inside your repository, to enable the plugin for that repository only. Restart Claude Code afterwards, then type `/` to see the commands: `/clean-ledger:run`, `/clean-ledger:status` and `/clean-ledger:review`.

Check the installation:

```bash
claude plugin list
```

## Step 4: Prepare the repository

1. **Start from a clean working tree on your default branch.** Commit or stash your changes.
2. **Make sure the tests pass now.** Run your usual test command once yourself.
3. **Decide what must never be edited.** Phase 0 proposes a list of protected paths and the Auditor checks it, but you know your repository best. Typical entries:
   - generated code;
   - vendored or third-party code;
   - applied database migrations;
   - release and CI workflows;
   - entry points;
   - anything sensitive.

   The config is frozen once Phase 0 is approved.
4. **Remove credentials from reach.** Clean Ledger never pushes, but the safest setup is a clone with no push credentials. Set it up so that nothing in the folder holds a token or key.

## Step 5: Choose how it runs

Clean Ledger is designed to run without you approving each command. Pick a setup that matches your risk appetite:

| Setup | How | When |
|---|---|---|
| **Attended** | Just run it. Claude Code asks you about anything not already allowed. | First runs, or when you want to watch |
| **Allow-list** | Copy [`assets/settings.json`](../skills/clean-ledger/assets/settings.json) to `.claude/settings.local.json` in your repository. Common commands run without prompting; dangerous ones are denied. | Day-to-day runs on your machine |
| **Allow-list + sandbox (recommended for unattended runs)** | Copy [`assets/settings.sandboxed.json`](../skills/clean-ledger/assets/settings.sandboxed.json) to `.claude/settings.local.json`. It also turns on Claude Code's Bash sandbox, which confines file writes to the repository, limits network access to package and Semgrep hosts, and makes credential folders unreadable. | Unattended runs on your own machine |
| **Container** | Run Claude Code in a dev container or VM that holds only a clone and no credentials. [`e2e/Dockerfile`](../e2e/Dockerfile) is a working example. | Fully hands-off runs |

If you copy a settings file into `.claude/`, keep it out of git. Add `.claude/settings.local.json` to `.git/info/exclude` so it doesn't make the working tree "dirty".

**Inside a sandbox,** some tools need help:
- lizard, jscpd and Semgrep must be findable. Put them in a folder that is passed with `--tool-dir`.
- pip cannot use the macOS keychain. A `pip.conf` with `cert = <CA bundle>` and `use-deprecated = legacy-certs` solves it.

Clean Ledger itself handles Semgrep's certificates and cache. See [troubleshooting](troubleshooting.md).

## Step 6: Start the run

Open Claude Code in the repository and type:

```
/clean-ledger:run 1
```

The number is the **fix budget**: how many Tier 1 items it may refactor in this run. Start with 1. The default is 3.

The Builder now works through Phase 0 to Phase 5 by itself. After each phase, it delegates to the Auditor and commits the verdict.

## Step 7: Follow along (optional)

```
/clean-ledger:status
```

This shows which phases are approved, which items are done or skipped, the latest verdicts, and whether the run is blocked. You can also read the files as they appear on the `clean-ledger` branch: `BASELINE.md`, `DEBT_REGISTER.md`, then `PROGRESS.md`.

## Step 8: If the run stops with `BLOCKED.md`

A stop is a feature, not a failure. Clean Ledger stops instead of guessing or working around a problem. Examples:
- a tool that cannot be installed;
- tests that fail before any change;
- a command the Guard refused;
- something the roadmap doesn't cover.

1. Read `BLOCKED.md`. It says what was attempted, what failed and what is needed from you.
2. Fix the cause. See [troubleshooting](troubleshooting.md).
3. Delete `BLOCKED.md` and run `/clean-ledger:run` again. It resumes from the first step that isn't approved.

## Step 9: Review the result

When the run finishes, the Builder ends with a short hand-off message. Then:

1. **Read `PR_DESCRIPTION.md`.** It lists every change, how behaviour was protected, the test results, metrics before and after, risks, and a reviewer checklist.
2. **Read the code diff yourself:**
   ```bash
   git diff main..clean-ledger -- <the refactored files>
   ```
   Every change should be a pure restructuring.
3. **Check the tests.** No existing test should be modified or deleted:
   ```bash
   git diff --name-status main..clean-ledger -- tests/
   ```
4. **Run the tests yourself.**
5. **Skim the audit trail** in `.ledger/approvals.jsonl`. Every phase, and each item's plan and final checkpoints, should end in `APPROVED`.
6. **Read `PROGRESS.md`** for the plain-English summary, including what was not checked.

## Step 10: Merge and raise the bar

If you are satisfied, merge the `clean-ledger` branch. Clean Ledger never merges for you.

Then raise the CI gate's baseline so the gains are locked in. This is an Owner action. Do it in your own terminal, not through Claude Code: the baseline is frozen for Claude once Phase 0 is approved.

```bash
bash .ledger/measure.sh
```

```bash
python3 .ledger/ledger.py raise-baseline
```

`raise-baseline` works only after Phase 5 is approved, and it refuses if any metric is worse than the current baseline, so it can only tighten the gate.

Update `BASELINE.md` to match, and commit both files in a commit you review.

From then on, the `ledger-gate` workflow fails any pull request that adds a function over the complexity limit, adds duplication beyond a small tolerance, or adds a high- or medium-severity Semgrep finding.

## Next

- [How it works](how-it-works.md): what each phase does and checks.
- [Safety](safety.md): what protects your repository during a run.
