# Troubleshooting

When something goes wrong, a run stops and writes `BLOCKED.md` instead of guessing. Read that file first: it says what was attempted, the last check output, and what is needed from you. Fix the cause, delete `BLOCKED.md`, and run `/clean-ledger:run` again to resume.

## "lizard / jscpd installed" fails in Phase 0

**Cause:** the tools are not on the session's `PATH`.

**Fix:** either install them where the session can find them, or put them in a folder and pass it with `--tool-dir`. Inside a sandbox, environment changes such as `PATH` set in settings files may not reach the shell. Link the tools into a folder inside the repository that is git-ignored, for example the project's `.venv/bin`, and use that folder as the tool folder.

## pip cannot install anything inside the Claude Code sandbox (macOS)

**Symptom:** `SSLError(SSLCertVerificationError('OSStatus -26276'))` from pypi.org.

**Cause:** recent pip asks the macOS keychain to verify certificates, and the sandbox blocks that.

**Fix** (an Owner action, done before the run). Give pip a CA bundle through its config file. In a virtualenv, create `<venv>/pip.conf`:

```ini
[global]
cert = <path to a CA bundle, e.g. <venv>/lib/python3.X/site-packages/pip/_vendor/certifi/cacert.pem>
use-deprecated = legacy-certs
```

`cert` on its own is not enough; `legacy-certs` makes pip use it.

The Builder is not allowed to make this change itself: golden rule 6.

## Semgrep fails or reports "empty trust anchors"

**Cause:** Semgrep's engine loads the OS certificate store at start-up, which some sandboxes hide.

**What happens:** `measure.sh` retries once with Python's CA bundle and logs `semgrep needed the CA bundle fallback`. `ledger.py` does the same when it reads Semgrep's version. You do not need to do anything. This built-in fallback is the only sanctioned certificate change.

If Semgrep still cannot run, security is recorded as **not measured** ("n/a" in tables), and the run continues. Semgrep is optional.

## Semgrep cannot write `~/.semgrep`

`measure.sh` keeps Semgrep's settings, log and version cache in `.ledger/reports/semgrep-home/` unless `SEMGREP_SETTINGS_FILE`, `SEMGREP_LOG_FILE` and `SEMGREP_VERSION_CACHE_PATH` are already set.

## Tests fail in Phase 0

Clean Ledger never refactors on top of failing tests. Fix the suite, or the test command in `.ledger/config.json` (allowed until Phase 0 is approved), and resume.

## Tests fail now and then ("test suite is stable" warning)

`verify` retries a failing suite once (`test_attempts`, default 2). A pass on the retry shows as a WARN naming the first failure. Full logs are in `.ledger/verify/tests-attempt<N>.log`. Investigate real flakiness separately; it is not a Clean Ledger problem, but it makes every check less trustworthy.

## The Guard blocked a command

Read the reason in the block message.
- **A real limit** (push, merge, a secret, a control file): the run should stop and escalate. It must never retry the same thing another way.
- **A false positive:** say so in `BLOCKED.md`, and report it. Since 1.2.0 the Guard parses commands and blocks only real writes to control files. Replaying the 157 commands of a real run produced 3 blocks, all correct.

## The Auditor keeps rejecting a step

After three rejections:
- **an item** is reverted (`git revert`) and skipped with a reason, and the run continues;
- **a phase** escalates to `BLOCKED.md`.

The required fixes are in the Auditor's report and in the notes in `.ledger/approvals.jsonl`.

## The plugin list shows an old version

`claude plugin list` can show another folder's install first. The record that applies to a folder is in `~/.claude/plugins/installed_plugins.json`, under its `projectPath`. Bump the version in `.claude-plugin/plugin.json` when you change the plugin, so the cache is refreshed on install.
