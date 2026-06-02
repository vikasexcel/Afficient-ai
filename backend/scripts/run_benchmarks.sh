#!/usr/bin/env bash
# Run the latency + performance benchmark suite and emit
# tests/reports/{latency_report.json,performance_report.html}.
#
# Usage:
#   ./scripts/run_benchmarks.sh                  # hermetic (fakes only)
#   RUN_EXTERNAL_BENCH=1 ./scripts/run_benchmarks.sh   # live providers too

set -euo pipefail

# cd to backend/ (this script's parent's parent).
HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${HERE}/.."

if [[ -d venv && -z "${VIRTUAL_ENV:-}" ]]; then
  # shellcheck disable=SC1091
  source venv/bin/activate
fi

mkdir -p tests/reports

# -p no:cacheprovider keeps CI runs deterministic; -ra surfaces skips.
pytest \
  -ra \
  -p no:cacheprovider \
  -m "performance or latency" \
  tests/performance tests/latency "$@"

echo
echo "Reports:"
echo "  - $(pwd)/tests/reports/latency_report.json"
echo "  - $(pwd)/tests/reports/performance_report.html"
