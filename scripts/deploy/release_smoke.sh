#!/usr/bin/env bash
set -Eeuo pipefail

python_bin="${1:?path to release venv python is required}"
release_root="${2:?release root is required}"
database="${INTELLIGENCE_DB_PATH:-$release_root/runtime/missing/intelligence.db}"
cd /tmp
unset PYTHONPATH
"$python_bin" -c 'import trendradar, mcp_server'
"$python_bin" -m trendradar.integrations.lark --help >/dev/null
if INTELLIGENCE_DB_PATH="$database" "$python_bin" -m trendradar.ops health \
    --config "$release_root/config/config.yaml" --readiness --json >/dev/null 2>&1; then
  echo "unexpected readiness success without a prepared database" >&2
  exit 1
fi
test ! -e "$database" || {
  echo "smoke test database path unexpectedly exists: $database" >&2
  exit 1
}
echo "release import and offline smoke passed"
