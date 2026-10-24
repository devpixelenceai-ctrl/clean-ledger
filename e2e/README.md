# End-to-end test

Runs the installed Clean Ledger plugin, unattended, on a real project inside a
Docker container, then judges the result.

- **Test project:** [prettytable](https://github.com/prettytable/prettytable) 3.18.0 (Python, BSD-3-Clause).
- **Image:** Debian + Node 22 + Python, Claude Code 2.1.302, lizard 1.24.2, jscpd 5.4.2, Semgrep 1.182.1,
  the plugin installed from this repository's current commit, and the project cloned with its
  git remote removed (nothing can be pushed).
- **Isolation:** runs as a non-root user with all Linux capabilities dropped; nothing from your Mac
  is mounted except the output folder. The container has network access (Claude's API, Semgrep rules).

## Steps

```bash
./e2e/run.sh build    # build the image (downloads packages, clones the project)
./e2e/run.sh smoke    # free checks: tools, plugin installed, project tests pass, Guard blocks a push
./e2e/run.sh run      # the paid run (see "API key" below)
./e2e/run.sh judge    # re-check the latest run
```

`run` writes everything to `e2e/out/<timestamp>/`: the transcript, a git bundle of the result,
test output, and `judge-report.md`.

Settings (environment variables for `run`):

| Variable | Default | Meaning |
|---|---|---|
| `MAX_BUDGET_USD` | `20` | Hard spending cap passed to `claude --max-budget-usd` |
| `MAX_FIXES` | `1` | Tier 1 fixes allowed in the run |
| `RUN_TIMEOUT` | `3h` | Wall-clock limit |
| `MODEL` | Claude Code default | Model for the run |

## API key

The run needs **either** an Anthropic API key **or** a Claude subscription token. Keep it out of
chat, files and shell history:

1. Get one:
   - API key: create it at console.anthropic.com → API keys (billed to that account), or
   - subscription token: run `claude setup-token` in your terminal and copy the token it prints.
2. In the terminal where you will start the run, type (the value is not shown or saved in history):

   ```bash
   read -rs ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY
   ```

   For a subscription token use `CLAUDE_CODE_OAUTH_TOKEN` instead of `ANTHROPIC_API_KEY`.
3. Start the run in that same terminal: `./e2e/run.sh run`
4. Afterwards: `unset ANTHROPIC_API_KEY CLAUDE_CODE_OAUTH_TOKEN`. If you created a key just for
   this test, you can delete it in the console.

`run.sh` passes the variable into the container by name (`-e ANTHROPIC_API_KEY`), so its value never
appears on a command line, in the image or in the output. The judge fails the run if anything that
looks like an Anthropic key or token appears in the evidence.

## What the judge checks

`judge.py` (deterministic): the run ended successfully; phases 0–5 are approved and every verdict
was recorded by `ledger-auditor` against a real commit; each finished fix was approved at its plan
and final checkpoints; nothing is left in progress; `main` is unchanged and the project has no
remote; protected paths and test files are intact; the project's tests pass; all deliverables exist;
no `BLOCKED.md`; no secrets in the evidence. Guard blocks are listed for review.

After that, an independent reviewer reads the transcript and the code diff to judge whether
behaviour was preserved and the audits were honest.
