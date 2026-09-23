#!/usr/bin/env bash
# Waypost Station installer — Raspberry Pi OS Lite 64-bit (Debian Bookworm/Trixie).
#
# Safe to re-run: code and configs are refreshed, but secrets (session key,
# Wi-Fi PSK), the database and the TLS CA are created once and kept.
#
#   sudo ./deploy/raspberry-pi/install.sh                # Station + HTTPS; AP staged, not switched on
#   sudo ./deploy/raspberry-pi/install.sh --enable-ap    # also turn wlan0 into the WAYPOST access point
#
# Switching wlan0 to AP mode drops any Wi-Fi client connection on wlan0, so
# --enable-ap refuses to run from an SSH session that arrives over wlan0.
# Use Ethernet (or the console) for that step.
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
PREFIX=/opt/waypost
DATA=/var/lib/waypost
ETC=/etc/waypost
CADDY_ROOT_CRT=/var/lib/caddy/.local/share/caddy/pki/authorities/local/root.crt

SSID=WAYPOST
COUNTRY=US
CHANNEL=6
FREQUENCY=""
TRANSPORT=reticulum
ENABLE_AP=0
FORCE_AP=0
SKIP_APT=0
NO_START=0

usage() {
	sed -n '2,13p' "$0" | sed 's/^# \{0,1\}//'
	cat <<'EOF'

Options:
  --enable-ap          Switch wlan0 to the WAYPOST access point (hostapd + dnsmasq)
  --force-ap           Allow --enable-ap even when SSH arrives over wlan0
  --ssid NAME          Access point SSID (default WAYPOST)
  --country CC         Wi-Fi regulatory country, e.g. US, GB, DE (default US)
  --channel N          2.4 GHz channel (default 6)
  --frequency HZ       LoRa frequency; required outside US/CA/MX/AU/NZ/BR
  --transport KIND     reticulum (default, RNode on /dev/waypost-lora) or mock (no radio)
  --skip-apt           Do not install OS packages (already installed)
  --no-start           Install files only; do not enable/start services
  -h, --help           Show this help
EOF
}

while [[ $# -gt 0 ]]; do
	case "$1" in
		--enable-ap) ENABLE_AP=1 ;;
		--force-ap) FORCE_AP=1 ;;
		--ssid) SSID="$2"; shift ;;
		--country) COUNTRY="${2^^}"; shift ;;
		--channel) CHANNEL="$2"; shift ;;
		--frequency) FREQUENCY="$2"; shift ;;
		--transport) TRANSPORT="$2"; shift ;;
		--skip-apt) SKIP_APT=1 ;;
		--no-start) NO_START=1 ;;
		-h|--help) usage; exit 0 ;;
		*) echo "Unknown option: $1" >&2; usage >&2; exit 2 ;;
	esac
	shift
done

step() { printf '\n==> %s\n' "$*"; }
note() { printf '    %s\n' "$*"; }
die() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ $EUID -eq 0 ]] || die "run as root (sudo $0)"
[[ -f "$REPO_DIR/server/api/main.py" ]] || die "cannot find the Waypost repo at $REPO_DIR"
[[ "$TRANSPORT" == reticulum || "$TRANSPORT" == mock ]] || die "--transport must be reticulum or mock"
[[ "$SSID" =~ ^[A-Za-z0-9_.-]{1,32}$ ]] || die "--ssid must be 1-32 chars of A-Z a-z 0-9 _ . -"
[[ "$COUNTRY" =~ ^[A-Z]{2}$ ]] || die "--country must be a two-letter code"
[[ "$CHANNEL" =~ ^([1-9]|1[0-3])$ ]] || die "--channel must be 1-13"

if [[ -z "$FREQUENCY" ]]; then
	case "$COUNTRY" in
		US|CA|MX|AU|NZ|BR) FREQUENCY=915000000 ;;
		*) [[ "$TRANSPORT" == mock ]] || die "pass --frequency for LoRa in $COUNTRY (e.g. 868100000 in the EU)" ;;
	esac
fi

HAVE_SYSTEMD=0
[[ -d /run/systemd/system ]] && HAVE_SYSTEMD=1
if [[ $HAVE_SYSTEMD -eq 0 && $NO_START -eq 0 ]]; then
	note "systemd is not running (container?) — installing files without starting services"
	NO_START=1
fi

ssh_over_wlan0() {
	local client
	client="${SSH_CONNECTION%% *}"
	[[ -n "${SSH_CONNECTION:-}" && -n "$client" ]] || return 1
	ip route get "$client" 2>/dev/null | grep -q ' dev wlan0 '
}

if [[ $ENABLE_AP -eq 1 && $FORCE_AP -eq 0 ]] && ssh_over_wlan0; then
	die "your SSH session is on wlan0; enabling the AP would cut it off. Reconnect over Ethernet, or pass --force-ap"
fi

# ---------------------------------------------------------------------------
step "OS packages"
if [[ $SKIP_APT -eq 1 ]]; then
	note "skipped (--skip-apt)"
else
	export DEBIAN_FRONTEND=noninteractive
	apt-get update -qq
	apt-get install -y -qq --no-install-recommends \
		python3 python3-venv python3-pip rsync openssl ca-certificates curl gpg \
		hostapd dnsmasq rfkill iw iproute2 sqlite3 >/dev/null
	# Debian ships Caddy 2.6, which cannot lengthen the local CA intermediate
	# (needed for clock-drift tolerance) — use Caddy's official repo instead.
	CADDY_KEYRING=/usr/share/keyrings/caddy-stable-archive-keyring.gpg
	if [[ ! -f "$CADDY_KEYRING" ]]; then
		curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/gpg.key | gpg --dearmor -o "$CADDY_KEYRING"
		curl -1sLf https://dl.cloudsmith.io/public/caddy/stable/debian.deb.txt \
			> /etc/apt/sources.list.d/caddy-stable.list
		chmod o+r "$CADDY_KEYRING" /etc/apt/sources.list.d/caddy-stable.list
		apt-get update -qq
	fi
	apt-get install -y -qq caddy >/dev/null
	note "installed (Caddy $(caddy version | cut -d' ' -f1))"
fi
if [[ $ENABLE_AP -eq 0 && $NO_START -eq 0 ]]; then
	# Debian starts dnsmasq on install; never let it answer on the home LAN before the AP exists
	systemctl disable --now dnsmasq >/dev/null 2>&1 || true
fi

# ---------------------------------------------------------------------------
step "Service user"
if ! id waypost >/dev/null 2>&1; then
	useradd --system --home-dir "$DATA" --no-create-home --shell /usr/sbin/nologin waypost
	note "created user waypost"
fi
usermod -a -G dialout waypost

# ---------------------------------------------------------------------------
step "Code → $PREFIX"
install -d -m 0755 "$PREFIX"
rsync -a --delete \
	--exclude '.git/' --exclude '.venv/' --exclude 'data/' --exclude '__pycache__/' \
	--exclude '.pytest_cache/' --exclude '.pio/' --exclude '.env' --exclude '.tmp/' \
	"$REPO_DIR/" "$PREFIX/"
chown -R root:root "$PREFIX"
chmod -R go-w "$PREFIX"
note "synced from $REPO_DIR"

step "Python environment"
[[ -x "$PREFIX/.venv/bin/python" ]] || python3 -m venv "$PREFIX/.venv"
"$PREFIX/.venv/bin/pip" install -q --disable-pip-version-check -r "$PREFIX/server/requirements.txt"
note "$("$PREFIX/.venv/bin/python" --version) with $(wc -l < "$PREFIX/server/requirements.txt") requirements"

# ---------------------------------------------------------------------------
step "Data + config directories"
install -d -o waypost -g waypost -m 0750 "$DATA" "$DATA/data" "$DATA/reticulum" "$DATA/backups"
install -d -o root -g waypost -m 0750 "$ETC"
install -d -o root -g root -m 0755 "$ETC/public"

if [[ -f "$ETC/waypost.env" ]]; then
	note "kept existing $ETC/waypost.env"
else
	umask 027
	cat > "$ETC/waypost.env" <<EOF
# Waypost Station — generated by install.sh $(date -u +%Y-%m-%d). Edit, then: systemctl restart waypost-api
WAYPOST_ENV=production
WAYPOST_DATA_DIR=$DATA/data
WAYPOST_SQLITE_PATH=$DATA/data/waypost.db
WAYPOST_SECRET_KEY=$(openssl rand -hex 32)
WAYPOST_SSID=$SSID
WAYPOST_RADIO_REGION=$COUNTRY
WAYPOST_TRANSPORT=$TRANSPORT
WAYPOST_LORA_DEVICE=/dev/waypost-lora
WAYPOST_RNS_INTERFACE=rnode
WAYPOST_RNS_CONFIG=$DATA/reticulum
WAYPOST_RNS_FREQUENCY=${FREQUENCY:-915000000}
# Must match every radio on the mesh (see docs/radio-dev.md):
# WAYPOST_RNS_BANDWIDTH=125000
# WAYPOST_RNS_TXPOWER=14
# WAYPOST_RNS_SF=8
# WAYPOST_RNS_CR=5
EOF
	umask 022
	chown root:waypost "$ETC/waypost.env"
	chmod 0640 "$ETC/waypost.env"
	note "wrote $ETC/waypost.env (secret key generated)"
fi

# ---------------------------------------------------------------------------
step "Radio device rule"
install -d -m 0755 /etc/udev/rules.d
install -m 0644 "$SCRIPT_DIR/udev/99-waypost-station-lora.rules" /etc/udev/rules.d/
if [[ $NO_START -eq 0 ]]; then
	udevadm control --reload-rules && udevadm trigger --subsystem-match=tty
fi
if [[ -e /dev/waypost-lora ]]; then
	note "/dev/waypost-lora → $(readlink -f /dev/waypost-lora)"
else
	note "no radio found yet; plug in the RNode and it appears as /dev/waypost-lora"
fi

# ---------------------------------------------------------------------------
step "Station API service"
install -d -m 0755 /etc/systemd/system
install -m 0644 "$SCRIPT_DIR/systemd/waypost-api.service" /etc/systemd/system/
if [[ $NO_START -eq 0 ]]; then
	systemctl daemon-reload
	systemctl enable waypost-api >/dev/null 2>&1
	systemctl restart waypost-api
	for _ in $(seq 1 30); do
		curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 && break
		sleep 1
	done
	curl -fsS http://127.0.0.1:8000/api/health >/dev/null 2>&1 \
		&& note "API healthy on 127.0.0.1:8000" \
		|| note "API not answering yet — check: journalctl -u waypost-api -e"
fi

# ---------------------------------------------------------------------------
step "HTTPS (Caddy, offline local CA)"
install -d -m 0755 /etc/caddy
install -m 0644 "$SCRIPT_DIR/caddy/Caddyfile" /etc/caddy/Caddyfile
if command -v caddy >/dev/null 2>&1; then
	CADDY_VER="$(caddy version | sed -E 's/^v?([0-9]+)\.([0-9]+).*/\1 \2/')"
	read -r CADDY_MAJ CADDY_MIN <<< "$CADDY_VER"
	(( CADDY_MAJ > 2 || (CADDY_MAJ == 2 && CADDY_MIN >= 8) )) \
		|| die "Caddy $(caddy version | cut -d' ' -f1) is too old (need 2.8+); re-run without --skip-apt"
	caddy validate --config /etc/caddy/Caddyfile --adapter caddyfile >/dev/null 2>&1 \
		|| die "Caddyfile failed validation: caddy validate --config /etc/caddy/Caddyfile"
	note "Caddyfile valid ($(caddy version | cut -d' ' -f1))"
fi
if [[ $NO_START -eq 0 ]]; then
	systemctl enable caddy >/dev/null 2>&1
	systemctl restart caddy
	for _ in $(seq 1 30); do [[ -f "$CADDY_ROOT_CRT" ]] && break; sleep 1; done
fi
if [[ -f "$CADDY_ROOT_CRT" ]]; then
	install -m 0644 "$CADDY_ROOT_CRT" "$ETC/public/waypost-ca.crt"
	openssl x509 -in "$ETC/public/waypost-ca.crt" -noout -fingerprint -sha256 \
		| cut -d= -f2 > "$ETC/public/waypost-ca.sha256"
	chmod 0644 "$ETC/public/waypost-ca.sha256"
	note "CA published at http://<station>/waypost-ca.crt"
	note "fingerprint $(cat "$ETC/public/waypost-ca.sha256")"
else
	note "CA not created yet (Caddy not started); re-run after first boot to publish it"
fi

# ---------------------------------------------------------------------------
step "Wi-Fi access point ($SSID)"
if [[ ! -f "$ETC/wifi-psk" ]]; then
	umask 077
	# 20 chars from an unambiguous alphabet — easy to read aloud at camp
	# (finite input: tr reading /dev/urandom into head would die of SIGPIPE under pipefail)
	PSK="$(head -c 4096 /dev/urandom | LC_ALL=C tr -dc 'abcdefghjkmnpqrstuvwxyz23456789')"
	printf '%s' "${PSK:0:20}" > "$ETC/wifi-psk"
	unset PSK
	umask 022
	note "generated Wi-Fi password in $ETC/wifi-psk"
fi
chmod 0600 "$ETC/wifi-psk"

install -d -m 0755 /etc/hostapd
PSK="$(cat "$ETC/wifi-psk")"
umask 077
sed -e "s|@SSID@|$SSID|" -e "s|@COUNTRY@|$COUNTRY|" -e "s|@CHANNEL@|$CHANNEL|" -e "s|@PSK@|$PSK|" \
	"$SCRIPT_DIR/hostapd/hostapd.conf" > /etc/hostapd/hostapd.conf
umask 022
unset PSK
chmod 0600 /etc/hostapd/hostapd.conf
install -m 0644 "$SCRIPT_DIR/systemd/waypost-wlan0.service" /etc/systemd/system/

if [[ $ENABLE_AP -eq 1 ]]; then
	install -d -m 0755 /etc/dnsmasq.d /etc/NetworkManager/conf.d
	install -m 0644 "$SCRIPT_DIR/dnsmasq/waypost.conf" /etc/dnsmasq.d/waypost.conf
	printf '[keyfile]\nunmanaged-devices=interface-name:wlan0\n' \
		> /etc/NetworkManager/conf.d/99-waypost-unmanaged-wlan0.conf
	if [[ $NO_START -eq 0 ]]; then
		command -v raspi-config >/dev/null 2>&1 && raspi-config nonint do_wifi_country "$COUNTRY" || true
		rfkill unblock wlan || true
		systemctl reload NetworkManager 2>/dev/null || true
		systemctl daemon-reload
		systemctl unmask hostapd >/dev/null 2>&1 || true
		systemctl enable waypost-wlan0 hostapd dnsmasq >/dev/null 2>&1
		systemctl restart waypost-wlan0 hostapd dnsmasq
		note "AP up: SSID $SSID on 10.42.0.1 (password: sudo cat $ETC/wifi-psk)"
	else
		note "AP configs installed; services start on next boot"
	fi
else
	note "staged only (hostapd config + wlan0 unit). Run again with --enable-ap from Ethernet to switch it on"
fi

# ---------------------------------------------------------------------------
step "Done"
note "Portal (after joining $SSID):  https://waypost.home.arpa/"
note "First visit on a new device:   http://waypost.home.arpa/  → trust page → install certificate"
note "Logs: journalctl -u waypost-api -u caddy -f"
