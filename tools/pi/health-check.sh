#!/usr/bin/env bash
# Read-only health check for a Pi Station (no sudo required).
#
#   ./tools/pi/health-check.sh
#   ./tools/pi/health-check.sh aj@10.0.0.193
set -euo pipefail

PI="${1:-aj@waypost.local}"
KEY="${WAYPOST_PI_SSH_KEY:-$HOME/.ssh/waypost_pi_deploy}"
SSH=(ssh -o BatchMode=yes -o ConnectTimeout=8)
[[ -f $KEY ]] && SSH+=(-i "$KEY")

echo "=== Waypost Pi health: $PI ==="

"${SSH[@]}" "$PI" bash -s <<'REMOTE'
set -euo pipefail
echo "-- hostname --"
hostname -f 2>/dev/null || hostname
echo "-- services --"
for u in waypost-api caddy hostapd dnsmasq waypost-uplink.timer; do
	printf '%-22s %s\n' "$u" "$(systemctl is-active "$u" 2>/dev/null || echo '?')"
done
echo "-- api --"
curl -sf http://127.0.0.1:8000/api/health | head -c 400 || echo FAIL
echo
echo "-- radio device --"
ls -l /dev/waypost-lora 2>/dev/null || echo "(no /dev/waypost-lora)"
echo "-- uplink --"
cat /run/waypost-uplink.state 2>/dev/null || echo "(unknown)"
REMOTE

echo "=== done ==="
