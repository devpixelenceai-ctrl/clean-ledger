# Safety

Clean Ledger lets an AI agent change your code without you approving each step. This page describes every layer that keeps that safe, and is honest about what those layers cannot do.

Found a way around one of these layers? Please report it privately, as described in the [security policy](../SECURITY.md).

## Layer 1: Golden rules

The roadmap's rules apply to every step:

1. **Behaviour is sacred.** A refactor changes structure, never behaviour. The only allowed behaviour change is closing a security hole, and it must come with a test that proves it.
2. **Tests before code.** No file changes until characterization tests that lock in its behaviour are committed and passing.
3. **Small steps.** One module per item, one idea per commit, and the tests run after every commit.
4. **Evidence over claims.** A step is done when `verify` passes and the Auditor approves.
5. **Nothing leaves the branch.** No push, merge, publish or deploy. You merge.
6. **When in doubt, stop.** A refusal by the Guard or a sandbox, or anything the roadmap doesn't cover, means writing `BLOCKED.md` and stopping. A refused action is never re-routed through another tool or a changed environment.
7. **Measure honestly.** A tool that cannot run is recorded as "not measured". Tools are never installed, uninstalled or reconfigured to make a number appear, and environment variables are never dumped.

## Layer 2: Objective checks (`ledger.py verify`)

Deterministic pass/fail checks run before every audit. Examples:
- **Git and files:** on the right branch; working tree clean; no source or test files changed during measurement phases; no protected paths changed, in any phase.
- **Test discipline:** tests committed before the first change to the target; tests pass; no test files deleted.
- **Metrics:** no file metric got worse, and the whole-repo gate against the baseline passes.
- **Audit trail:** the plan was approved before refactoring.

A flaky test suite is retried once. A pass after a failure still passes, but shows up as a warning that names the first failure, so the Auditor can see it.

## Layer 3: The independent Auditor

The `ledger-auditor` subagent is skeptical by default:
- it **re-runs** the objective checks itself;
- it reads the actual diff and tests;
- it **rejects** when evidence is missing. There is no "approved with conditions".

It specifically checks:
- **Behaviour:** every hunk of the target's diff is a pure restructuring.
- **Tests:** no assertion was removed, loosened or skipped.
- **The plan:** every refactor commit maps to a plan step.
- **Honesty:**
  - unmeasured metrics are not reported as zero;
  - money figures are labelled as estimates.
- **Conduct:** a refusal listed in the brief that was followed by a workaround means REJECTED.

It is the only one that writes verdicts, through `ledger.py record`, and `record` refuses an approval without a passing verification at the current commit. Every verdict is appended to `.ledger/approvals.jsonl` with its commit.

## Layer 4: The Guard

`hooks/guard.py` is a PreToolUse hook. It inspects every Bash command and every file edit before it runs, and blocks:

| Category | Examples |
|---|---|
| Publishing and history | `git push`, `merge`, `rebase`, `reset --hard`, `commit --amend`, `--no-verify`, `filter-branch`, force branch delete. Also written with global options, such as `git -C dir push` |
| Destruction | Recursive force delete, `git clean -f` |
| Privilege and remote access | `sudo`, `ssh`, `scp`, `rsync`, piping a download into a shell |
| Release and infrastructure | `npm`/`cargo`/`gem` publish, `twine upload`, `kubectl`, `helm`, `terraform apply`, cloud CLIs |
| Secrets | Reading `.env` files, keys and credentials; dumping environment variables (`env`, `printenv`, `export -p`, `/proc/*/environ`) |
| Control files | Writing `.ledger/approvals.jsonl`, `state.json`, `ledger.py` or `measure.sh`; writing `baseline.json` or `config.json` after Phase 0 approval |
| Scope | Editing protected paths or any CI workflow other than the gate; committing outside the work branch |

**How it decides.** For control files, the Guard **parses** the command:
- heredocs;
- redirects;
- `cd`;
- `cp`, `mv`, `tee`, `rm`, `sed -i`, `ln`, `dd` and `git checkout --`;
- inline Python or Node writes.

It blocks only paths that would actually be written, so `2>&1`, `awk '$2>15'` or a note that merely mentions a ledger file are allowed. An unparseable command that mentions a control file is blocked.

**When it is active.** In any repository containing `.ledger/`. A run creates `.ledger/` first, so the Guard is on before anything else happens. It finds the repository from the edited file, any `cd` or `git -C` in the command, or the working folder.

## Layer 5: Your sandbox (recommended)

For unattended runs, add isolation that does not depend on Clean Ledger at all. Either:
- **Claude Code's Bash sandbox,** using [`assets/settings.sandboxed.json`](../skills/clean-ledger/assets/settings.sandboxed.json). It confines writes to the repository, limits network access, and makes credential folders unreadable. Together with `dontAsk` or allow-list permissions, anything not allowed is refused rather than prompted.
- **A container or VM** holding only a clone with no push credentials. [`e2e/Dockerfile`](../e2e/Dockerfile) is an example.

Never bypass permissions on your own machine, or in a clone that has push credentials.

## Layer 6: You

Your review before merging is the final control. `PR_DESCRIPTION.md` gives you a checklist, and `.ledger/approvals.jsonl` gives you the audit trail.

## Honest limitations

- **Not tamper-proof.** The Auditor runs in the same Claude Code session as the Builder. The Guard and `ledger.py` make cheating hard and visible, but cannot make it impossible.
- **The Guard reads commands, not intent.** A command assembled in a way it cannot parse, for example through a script file or variables, can get past it. That is why the sandbox and your review matter.
- **Tests define safety.** Behaviour that no test exercises cannot be proven preserved. Code with heavy input/output, timing or external services is hard to pin down.
- **Semgrep's default rules are a starting point,** not a full security audit.
- **One sanctioned certificate exception.** When a sandbox hides the OS certificate store, `measure.sh` and `ledger.py` retry Semgrep once with Python's CA bundle, and log it. Nothing else may touch certificates.
