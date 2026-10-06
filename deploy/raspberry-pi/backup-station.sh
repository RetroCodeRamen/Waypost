#!/usr/bin/env bash
# Snapshot Waypost Station state — run on the Pi as root (systemd timer or sudo).
#
#   sudo /usr/local/sbin/waypost-backup
#
# Writes: /var/lib/waypost/backups/waypost-YYYYMMDD-HHMMSS.tar.gz
# Keeps the 14 newest archives.
set -euo pipefail

DATA=/var/lib/waypost
DEST="$DATA/backups"
STAMP="$(date -u +%Y%m%d-%H%M%S)"
ARCHIVE="$DEST/waypost-$STAMP.tar.gz"

[[ -d $DATA/data ]] || { echo "backup: $DATA/data missing" >&2; exit 1; }
install -d -o waypost -g waypost -m 0750 "$DEST"

TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT

cp -a "$DATA/data/waypost.db" "$TMP/"
[[ -f $DATA/data/community.key ]] && cp -a "$DATA/data/community.key" "$TMP/"
[[ -f $DATA/reticulum/identity ]] && cp -a "$DATA/reticulum/identity" "$TMP/rns-identity"

tar -czf "$ARCHIVE" -C "$TMP" .
chown waypost:waypost "$ARCHIVE"
chmod 0640 "$ARCHIVE"

mapfile -t OLD < <(ls -1t "$DEST"/waypost-*.tar.gz 2>/dev/null | tail -n +15 || true)
((${#OLD[@]})) && rm -f "${OLD[@]}"

echo "backup: $ARCHIVE ($(du -h "$ARCHIVE" | awk '{print $1}'))"
