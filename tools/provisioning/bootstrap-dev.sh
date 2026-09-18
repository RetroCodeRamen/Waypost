#!/usr/bin/env bash
# Minimal Waypost Station bootstrap stub (Phase 1).
# Safe to run on a developer machine for directory layout only.
# Full hostapd/dnsmasq/openNDS install is intended for Raspberry Pi OS.

set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DATA_ROOT="${WAYPOST_DATA_ROOT:-$ROOT/data}"

mkdir -p \
  "$DATA_ROOT" \
  "$DATA_ROOT/mail" \
  "$DATA_ROOT/fieldbook" \
  "$DATA_ROOT/commons" \
  "$DATA_ROOT/locker" \
  "$DATA_ROOT/archive" \
  "$DATA_ROOT/reticulum" \
  "$DATA_ROOT/backups"

if [[ ! -f "$ROOT/.env" ]]; then
  cp "$ROOT/.env.example" "$ROOT/.env"
  echo "Created .env from .env.example"
fi

echo "Waypost data directories ready under $DATA_ROOT"
echo "Next (dev): uv venv .venv && source .venv/bin/activate && uv pip install -r server/requirements.txt"
echo "Next (dev): uvicorn server.api.main:app --reload --port 8000"
