#!/usr/bin/env bash
# Run the Clean Ledger test suite (Python standard library only).
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m unittest discover -s tests -p "test_*.py" -v "$@"
