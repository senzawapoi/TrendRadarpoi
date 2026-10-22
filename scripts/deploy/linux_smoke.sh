#!/usr/bin/env bash
set -Eeuo pipefail

# Read-only target checks. Run as an operator with access to the reference
# layout; this script never enables, starts, stops, or migrates a service.
current="${TRENDRADAR_CURRENT_LINK:-/opt/trendradar/current}"
config="${CONFIG_PATH:-/etc/trendradar/config.yaml}"
units=(deploy/systemd/*.service deploy/systemd/*.timer deploy/systemd/*.slice)

command -v systemd-analyze >/dev/null || { echo "systemd-analyze is required" >&2; exit 2; }
systemd-analyze verify "${units[@]}"
test -x "$current/venv/bin/python"
test -r "$config"
test -d "${TRENDRADAR_RUNTIME_ROOT:-/var/lib/trendradar}"
test -d "${TRENDRADAR_CONTROL_DIR:-/var/lib/trendradar/control}"
test -d "${TRENDRADAR_LOCK_DIR:-/run/trendradar}"
systemctl show trendradar.slice \
  -p MemoryHigh -p MemoryMax -p TasksMax --no-pager
for unit in trendradar-bot.service trendradar-worker.service; do
  systemctl show "$unit" -p User -p Group -p ExecStart -p Slice --no-pager
done
echo "Linux package and unit checks passed; no lifecycle or provider calls were made."
