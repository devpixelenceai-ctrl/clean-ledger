# Security policy

Clean Ledger lets an AI agent change code without a person approving each step, so its safety controls are part of the product. This page explains how to report a vulnerability, what counts as one, and how this repository is protected.

## Supported versions

| Version | Supported |
|---|---|
| 1.3.x (latest) | Yes |
| Earlier than 1.3 | No. Please upgrade |

Security fixes are released as a new patch or minor version and listed in the [changelog](CHANGELOG.md).

## Reporting a vulnerability

**Please do not open a public issue, discussion or pull request for a security problem.**

Report it privately through GitHub:
1. Go to the repository's **Security** tab.
2. Choose **Report a vulnerability**. This opens a private advisory that only the maintainers can see.

Please include:
- the version of Clean Ledger, and of Claude Code if relevant;
- what you did, step by step, and what happened;
- the impact you expect (for example, "the Guard allows a push");
- a minimal example or proof of concept, if you have one, **with any real secrets removed**.

What to expect:
- We aim to acknowledge reports within 7 days, and to agree a fix and a disclosure date with you.
- We will credit you in the advisory and the changelog unless you ask us not to.

## What counts as a vulnerability

**In scope:**
- **Guard bypasses:** a command or file edit that the [Guard](hooks/guard.py) should block but does not. Examples: pushing, merging, rewriting history, editing `.ledger/approvals.jsonl` or `state.json`, reading secrets, dumping environment variables, or editing protected paths.
- **Audit integrity:** a way to record an approval without a passing `ledger.py verify` at the current commit, or to make `verify` pass when a criterion is not met.
- **Leaks:** credentials, tokens or private data written into reports, transcripts, evidence folders or commits by the plugin or the end-to-end harness.
- **Supply chain:** the gate workflow template, or this repository's workflows, allowing code injection or unpinned third-party code to run with write access.

**Out of scope** (please report these upstream):
- vulnerabilities in Claude Code itself (report to Anthropic), or in lizard, jscpd, Semgrep, Python, Node or GitHub Actions;
- findings that need an attacker who already controls your machine or your Claude Code session.

Known limitations, such as "the Auditor runs in the same session as the Builder", are described in [docs/safety.md](docs/safety.md). They are not vulnerabilities in themselves, but a practical way to exploit one is.

## Using Clean Ledger safely

The full guide is in [docs/safety.md](docs/safety.md). In short:
- **Isolate the run.** Run unattended only in a sandbox or a container holding a clone **without push credentials**. Never bypass permissions on your own machine.
- **Protect what matters.** Give the run a protected-paths list that covers generated, vendored and sensitive files.
- **Review before merging.** Review the branch and `.ledger/approvals.jsonl` yourself. The plugin never merges for you.

## How this repository is protected

- **Account:** maintainer accounts use two-factor authentication.
- **The default branch (`main`)** is protected against force pushes and deletion.
- **Secret scanning with push protection** blocks commits that contain known credential formats.
- **Dependabot** alerts and security updates are on, and keeps the GitHub Actions pins current.
- **Workflows:**
  - run with read-only `GITHUB_TOKEN` permissions;
  - pin every action to a full commit hash;
  - do not persist checkout credentials;
  - never use `pull_request_target`.
- **Private vulnerability reporting** is enabled, as described above.
- **Commit identity:** commits use a GitHub no-reply address, so no personal email is published.
