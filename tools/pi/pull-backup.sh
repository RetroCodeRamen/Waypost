#!/usr/bin/env bash
# Pull a Station backup from the Pi to this machine (outside git — never commit).
#
#   ./tools/pi/pull-backup.sh
#   ./tools/pi/pull-backup.sh aj@waypost.local
#
# Uses ~/.ssh/waypost_pi_deploy when present. Destination: ~/Waypost-backups/
set -euo pipefail

PI="${1:-aj@waypost.local}"
KEY="${WAYPOST_PI_SSH_KEY:-$HOME/.ssh/waypost_pi_deploy}"
DEST="${WAYPOST_BACKUP_DIR:-$HOME/Waypost-backups}"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
SSH=(ssh -o BatchMode=yes)
SCP=(scp -o BatchMode=yes)
[[ -f $KEY ]] && SSH+=(-i "$KEY") && SCP+=(-i "$KEY")

mkdir -p "$DEST"

# Prefer a fresh tarball from /var/lib/waypost/backups if readable.
REMOTE_ARCHIVE="$("${SSH[@]}" "$PI" \
	'ls -1t /var/lib/waypost/backups/waypost-*.tar.gz 2>/dev/null | head -1' || true)"

if [[ -n $REMOTE_ARCHIVE ]]; then
	LOCAL="$DEST/waypost-$STAMP-from-pi.tar.gz"
	"${SCP[@]}" "$PI:$REMOTE_ARCHIVE" "$LOCAL"
	echo "pulled: $LOCAL"
	exit 0
fi

# Fallback: the import copy in the admin home (post-migration snapshot).
IMPORT="$("${SSH[@]}" "$PI" 'test -d ~/waypost-import && echo ~/waypost-import' || true)"
if [[ -z $IMPORT ]]; then
	echo "No readable backup on $PI (need sudo waypost-backup or ~/waypost-import)" >&2
	exit 1
fi

LOCAL_DIR="$DEST/waypost-import-$STAMP"
mkdir -p "$LOCAL_DIR"
"${SCP[@]}" -r "$PI:waypost-import/*" "$LOCAL_DIR/"
echo "pulled: $LOCAL_DIR (from ~/waypost-import — refresh with sudo waypost-backup on Pi when possible)"
