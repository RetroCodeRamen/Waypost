# Vendored browser libraries (Outpost Wi-Fi page)

Served by the Outpost from flash (gzipped into `src/web_assets.h` by
`tools/make_web_assets.py`) — the Outpost has no Internet, and a phone on its
plain-HTTP page has no WebCrypto, so signing and key derivation run in these.

| File | Package | License | Checked |
|---|---|---|---|
| `nacl-fast.min.js` | tweetnacl 1.0.3 (Ed25519 signatures) | Unlicense (`LICENSE-tweetnacl`) | npm tarball sha512 matched the registry's `dist.integrity`, 2026-10-05 |
| `scrypt.js` | scrypt-js 3.0.1 (key from username + password) | MIT (`LICENSE-scrypt-js`) | same |

Update only by re-downloading the exact npm tarball and re-checking its integrity.
