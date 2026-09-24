# openNDS / Waygate — future network-level session gating
#
# User-facing captive portal name: Waygate
#
# Shipped today (without openNDS):
#   - dnsmasq wildcard DNS → Station (deploy/raspberry-pi/dnsmasq/waypost.conf)
#   - Caddy HTTP captive redirects → web/portal/waygate.html
#   - Outpost firmware: inline Waygate splash + DNS on WAYPOST-OUTPOST
#
# openNDS still needed if we want to block LAN access until a user taps Continue
# or signs in at the network layer (store-Wi‑Fi style enforcement).
