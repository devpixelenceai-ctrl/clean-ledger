#!/usr/bin/env bash
# measure.sh - run every free analysis tool the same way, locally and in CI.
# Source folders come from .ledger/config.json (src_dirs) or $LEDGER_SRC.
set -euo pipefail
cd "$(git rev-parse --show-toplevel)"

SRC="${LEDGER_SRC:-$(python3 -c 'import json;print(" ".join(json.load(open(".ledger/config.json")).get("src_dirs",["src"])))' 2>/dev/null || echo src)}"
# User-level tool installs (tool_dirs in the config) come first on PATH.
TOOL_DIRS="$(python3 -c 'import json,os;print(os.pathsep.join(os.path.expanduser(d) for d in json.load(open(".ledger/config.json")).get("tool_dirs",[])))' 2>/dev/null || true)"
if [ -n "$TOOL_DIRS" ]; then export PATH="$TOOL_DIRS:$PATH"; fi
OUT=.ledger/reports
mkdir -p "$OUT"
IGNORE_GLOBS="**/node_modules/**,**/vendor/**,**/dist/**,**/build/**,**/test/**,**/tests/**,**/__tests__/**,**/*.min.js"
echo "ledger measure: source folders = $SRC"

# 1. Complexity
# shellcheck disable=SC2086
lizard -x "*/node_modules/*" -x "*/vendor/*" -x "*/dist/*" -x "*/build/*" \
       -x "*/test/*" -x "*/tests/*" -x "*/__tests__/*" --csv $SRC > "$OUT/lizard.csv"

# 2. Duplication
rm -f "$OUT/jscpd-report.json"
# shellcheck disable=SC2086
jscpd $SRC --absolute --reporters json --output "$OUT" --ignore "$IGNORE_GLOBS" --silent >/dev/null 2>&1 \
  || echo "ledger measure: jscpd failed, duplication not measured"

# 3. Security (optional)
rm -f "$OUT/semgrep.json"
if command -v semgrep >/dev/null 2>&1; then
  # shellcheck disable=SC2086
  semgrep scan --config p/default --metrics=off --json --quiet -o "$OUT/semgrep.json" $SRC \
    || echo "ledger measure: semgrep failed, security not measured"
else
  echo "ledger measure: semgrep not installed, security not measured"
fi

# 4. Churn (CI must check out with fetch-depth: 0)
python3 .ledger/ledger.py churn --since "${LEDGER_SINCE:-12 months ago}" > "$OUT/churn.csv"

# 5. Summary
python3 .ledger/ledger.py metrics --reports "$OUT" > .ledger/metrics.json
echo "ledger measure: wrote .ledger/metrics.json"
