# Waypost brand assets

Source masters live in `/image` at the repo root. Web-optimized copies used by the portal are under `web/portal/static/brand/`.

## Primary lockup

| File | Use |
|------|-----|
| `image/Logo-no_background.png` | Master transparent logo (icon + wordmark) |
| `static/brand/waypost-logo.png` | Trimmed master for light surfaces |
| `static/brand/waypost-logo-480.png` | Compact horizontal lockup |
| `static/brand/waypost-logo-on-white.png` | From `logo-white_backgroung.png` — print / light cards |

## Mark (icon only)

Cropped from the transparent lockup for sidebar, favicon, and small UI chrome:

- `waypost-mark-256.png`
- `waypost-mark-64.png` — sidebar
- `waypost-mark-32.png` — favicon

## Atmosphere / campaign stills

From `logo1`–`logo4` — optional splash / Waygate / marketing backgrounds. Keep usage subtle in the app shell.

| File | Mood |
|------|------|
| `waypost-atmosphere-1.jpg` | Map / expedition flat-lay |
| `waypost-atmosphere-2.jpg` | Night valley + mesh network |
| `waypost-atmosphere-3.jpg` | Topo map texture |
| `waypost-atmosphere-4.jpg` | Sunrise ridge (used lightly on Home) |

## Current product usage

- **Sidebar:** tree mark + “Waypost” wordmark (light type on dark green chrome)
- **Favicon / apple-touch:** mark PNGs via `shell.js`
- **Home:** soft atmosphere-4 strip under the greeting (desktop)

Avoid putting the dark wordmark on the dark sidebar without a light plate — contrast will fail.
