# Running Clean Ledger on many repositories (the fleet runner)

`runner/clean_ledger_fleet.py` runs Clean Ledger on a list of repositories in parallel. Each repository is isolated, judged with the same checks as the end-to-end tests, and summarised in one fleet report. It uses only the Python standard library.

## How it works

```
fleet.json ──▶ plan ──▶ for each repo, in parallel (max_parallel):
                          fresh clone at the ref, on a local branch, git remote removed
                          ──▶ executor runs /clean-ledger:run N  (container, local or command)
                          ──▶ collect evidence (git bundle, transcript, test results)
                          ──▶ judge (e2e/judge.py)
              ──▶ fleet-report.md + fleet-summary.json
```

**Safety by design:**
- **No push possible.** Every clone has its git remote removed. Each run also has the plugin's Guard and Auditor.
- **One repository can't break another.** A failing or erroring repository does not stop the others.
- **Untrusted code stays in the container.** With the Docker executor, the project's own tests run inside the container, never on your machine.
- **Keys are passed by name only** (`-e ANTHROPIC_API_KEY`). The judge fails a repository if anything that looks like a key, a token or `user:password@` appears in its evidence.

## Step by step

**1. Write a fleet file.** Start from [`runner/fleet.example.json`](../runner/fleet.example.json):

```json
{
  "executor": "docker",
  "image": "clean-ledger-runner:latest",
  "max_parallel": 2,
  "runs_dir": "fleet-runs",
  "defaults": { "max_fixes": 1, "budget_usd": 20, "timeout_min": 180 },
  "repos": [
    { "name": "prettytable", "url": "https://github.com/prettytable/prettytable.git", "ref": "3.18.0" },
    { "name": "node-semver", "url": "https://github.com/npm/node-semver.git", "ref": "v7.6.3", "max_fixes": 2 }
  ]
}
```

Keep this file, and `runs_dir`, **outside** any repository you care about.

**2. Plan (free).** This clones every repository, pins it, removes its remote, detects its languages, and checks that the executor is ready. It makes no Claude calls.

```bash
python3 /path/to/clean-ledger/runner/clean_ledger_fleet.py plan fleet.json
```

```
planned  prettytable: 819 commits, Python
planned  node-semver: 501 commits, JavaScript
not ready: no ANTHROPIC_API_KEY or CLAUDE_CODE_OAUTH_TOKEN in the environment
```

**3. Build the runner image** (Docker executor). Run this once, from the plugin repository:

```bash
docker build -f runner/Dockerfile --build-arg PLUGIN_COMMIT=$(git rev-parse --short HEAD) -t clean-ledger-runner:latest .
```

**4. Provide credentials** in the terminal where you will start the run. Use an API key, or a token from `claude setup-token`, and keep it out of files and shell history:

```bash
read -rs ANTHROPIC_API_KEY && export ANTHROPIC_API_KEY      # or CLAUDE_CODE_OAUTH_TOKEN
```

**5. Run.** This plans again into a new folder, then runs every repository:

```bash
python3 /path/to/clean-ledger/runner/clean_ledger_fleet.py run fleet.json
```

The run refuses to start if the executor is not ready. Each repository's spending is capped by `budget_usd`, through `--max-budget-usd`, and its time by `timeout_min`.

**6. Read the report:** `<runs_dir>/<stamp>/fleet-report.md`.

| Repository | Verdict | Phases approved | Fixed | Complex fns | Max CCN | Duplication % | Guard blocks |
|---|---|---|---|---|---|---|---|
| prettytable | PASS | 6/6 | 1 | 9 → 9 | 35 → 28 | 2.99 → 3.0 | 0 |

The example row above uses the figures from the real end-to-end run. The report is followed by any failed checks for each repository. The full evidence is in `<repo>/out/`:
- `judge-report.md`;
- `transcript.jsonl`;
- `result.bundle`;
- the test output.

To rebuild the report:

```bash
python3 runner/clean_ledger_fleet.py report <runs_dir>/<stamp>
```

**7. Review and merge** each repository's work:

```bash
git clone <runs_dir>/<stamp>/<repo>/out/result.bundle review && cd review && git log clean-ledger
```

**A PASS from the judge is necessary, not sufficient.** Review each branch as described in [Getting started](getting-started.md), step 9, then apply it to the real repository yourself, for example by adding the bundle as a remote and opening a pull request.

## Executors

| Executor | Where the run happens | Needs | Isolation |
|---|---|---|---|
| `docker` (recommended) | A throwaway container per repository: non-root, all capabilities dropped, only the clone and its evidence folder mounted | Docker, the runner image, and `ANTHROPIC_API_KEY` or `CLAUDE_CODE_OAUTH_TOKEN` | Strong |
| `local` | Headless `claude -p` on this machine: plugin loaded per run (`--plugin-dir`), [sandboxed settings](../skills/clean-ledger/assets/settings.sandboxed.json), `dontAsk` permissions, no user settings or MCP servers | The `claude` CLI signed in with an account that can run headless, plus lizard and jscpd (add `"tool_dirs"` if they are not on `PATH`) | Medium: the Claude Code sandbox, on your machine |
| `command` | Any program you name, with `{project}`, `{out}`, `{max_fixes}` and `{name}` placeholders | The program | Up to you (used by the test suite) |

## Fleet file reference

| Key | Default | Meaning |
|---|---|---|
| `executor` | `docker` | `docker`, `local` or `command` |
| `image` | `clean-ledger-runner:latest` | Docker image for the `docker` executor |
| `command` | – | Argument list for the `command` executor |
| `max_parallel` | `2` | Repositories run at the same time |
| `runs_dir` | `fleet-runs` | Where run folders go (relative to the fleet file) |
| `tool_dirs` | `[]` | Extra folders for lizard, jscpd and Semgrep (`local` executor) |
| `defaults` | `max_fixes` 1, `budget_usd` 20, `timeout_min` 180, `model` "" | Per-repository settings, each overridable per repo |
| `repos[]` | – | `url` (required), plus `name`, `ref`, `base_branch` (`main`), `max_fixes`, `budget_usd`, `timeout_min` and `model` |

## Limits

- **Languages.** The runner image contains Python and Node. Repositories in other ecosystems (Java, Go, Ruby and so on) need their toolchain added to `runner/Dockerfile`; otherwise their runs stop with `BLOCKED.md` in Phase 0.
- **Linux hosts.** The container user (uid 1000) must be able to write the mounted clone. On Docker Desktop this is automatic; on Linux, run as a matching user or adjust ownership.
- **Credentials.** The runner needs a credential that works without a person: an API key or a `claude setup-token` token for Docker, or a headless-capable CLI login for `local`. A desktop-app login cannot be scripted.
- **Testing so far.** The orchestration has 7 automated tests, run with a stand-in agent, and real `plan` runs against GitHub. The full paid fleet run has not yet been run end to end with a real key: the single-repository runs in [testing-and-results.md](testing-and-results.md) used the same plugin, judge and evidence format.
