#!/usr/bin/env bash
# Clean Ledger end-to-end test driver (runs on the host).
#
#   ./e2e/run.sh build   build the image from the committed plugin (needs network)
#   ./e2e/run.sh smoke   free checks inside the container (no API key, no cost)
#   ./e2e/run.sh run     the paid, unattended run (needs ANTHROPIC_API_KEY or
#                        CLAUDE_CODE_OAUTH_TOKEN exported in this shell)
#   ./e2e/run.sh judge [out-dir]   check a finished run (default: the latest)
#
# Settings for `run` (environment): MAX_FIXES (1), MAX_BUDGET_USD (20),
# RUN_TIMEOUT (3h), MODEL (Claude Code's default).
set -euo pipefail

HERE="$(cd "$(dirname "$0")" && pwd)"
ROOT="$(dirname "$HERE")"
IMAGE="clean-ledger-e2e"

commit() { git -C "$ROOT" rev-parse --short HEAD; }

case "${1:-}" in
  build)
    if [ -n "$(git -C "$ROOT" status --porcelain)" ]; then
      echo "run.sh: commit your changes first; the image must match a commit" >&2
      exit 2
    fi
    docker build -f "$HERE/Dockerfile" --build-arg "PLUGIN_COMMIT=$(commit)" \
      -t "$IMAGE:$(commit)" -t "$IMAGE:latest" "$ROOT"
    ;;

  smoke)
    docker run --rm "$IMAGE:latest" e2e-smoke
    ;;

  run)
    if [ -z "${ANTHROPIC_API_KEY:-}" ] && [ -z "${CLAUDE_CODE_OAUTH_TOKEN:-}" ]; then
      echo "run.sh: export ANTHROPIC_API_KEY (or CLAUDE_CODE_OAUTH_TOKEN) in this shell first; see e2e/README.md" >&2
      exit 2
    fi
    out="$HERE/out/$(date +%Y%m%d-%H%M%S)"
    mkdir -p "$out"
    docker image inspect "$IMAGE:latest" --format '{{json .Config.Labels}}' > "$out/image-labels.json"
    # -e NAME passes the variable through without putting its value on the
    # command line; nothing from the host is mounted except the output folder.
    set +e
    docker run --rm \
      -e ANTHROPIC_API_KEY -e CLAUDE_CODE_OAUTH_TOKEN \
      -e MAX_FIXES="${MAX_FIXES:-1}" -e MAX_BUDGET_USD="${MAX_BUDGET_USD:-20}" \
      -e RUN_TIMEOUT="${RUN_TIMEOUT:-3h}" -e MODEL="${MODEL:-}" \
      --cap-drop ALL --security-opt no-new-privileges \
      -v "$out:/out" "$IMAGE:latest" e2e-run
    status=$?
    set -e
    echo "run.sh: run finished with exit $status; evidence in $out"
    python3 "$HERE/judge.py" "$out" || true
    ;;

  judge)
    out="${2:-$(ls -d "$HERE"/out/*/ 2>/dev/null | sort | tail -1)}"
    [ -n "$out" ] || { echo "run.sh: no runs in $HERE/out" >&2; exit 2; }
    python3 "$HERE/judge.py" "$out"
    ;;

  *)
    sed -n '2,12p' "$0"
    exit 2
    ;;
esac
