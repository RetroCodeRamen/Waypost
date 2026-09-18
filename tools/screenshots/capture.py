"""Capture Waypost portal screenshots for README and docs.

Starts a temporary Station API with seeded demo data, opens Chromium via
Playwright, and writes PNGs under docs/screenshots/.

Usage (from repo root, venv active):

    uv pip install -r server/requirements-dev.txt
    playwright install chromium
    python -m tools.screenshots.capture

Environment:

    WAYPOST_SHOT_BASE   Override base URL (skip local server start)
    WAYPOST_SHOT_OUT    Output directory (default: docs/screenshots)
"""

from __future__ import annotations

import os
import socket
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

DEFAULT_OUT = ROOT / "docs" / "screenshots"

PAGES = [
    ("home", "/", "Home dashboard (early prototype)"),
    ("dispatch", "/dispatch.html", "Dispatch messaging prototype"),
    ("postbox", "/postbox.html", "Postbox mail prototype"),
    ("commons", "/commons.html", "Commons feed prototype"),
    ("noticeboard", "/noticeboard.html", "Noticeboard bulletins prototype"),
    ("beacon", "/beacon.html", "Beacon emergency alert prototype"),
    ("locker", "/locker.html", "Locker files prototype"),
    ("rollcall", "/rollcall.html", "Rollcall presence prototype"),
    ("signal", "/signal.html", "Signal diagnostics prototype"),
]


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return int(s.getsockname()[1])


def seed_demo(base: str) -> None:
    import httpx

    with httpx.Client(base_url=base, timeout=30.0) as client:
        for _ in range(40):
            try:
                if client.get("/api/health").status_code == 200:
                    break
            except Exception:
                time.sleep(0.15)
        else:
            raise RuntimeError("Station API did not become ready")

        client.post(
            "/api/rollcall/status",
            json={"username": "aj", "status": "Working on the north outpost"},
        )
        client.post(
            "/api/rollcall/status",
            json={"username": "bob", "status": "At the reservoir"},
        )
        client.post(
            "/api/dispatch/devices/bind",
            json={"node_id": "pocket-bob", "username": "bob"},
        )
        client.post(
            "/api/dispatch/conversations/direct",
            json={"user_a": "aj", "user_b": "bob"},
        )
        client.post(
            "/api/dispatch/messages",
            json={
                "sender": "bob",
                "peer": "aj",
                "body": "Generator fuel arrived at the shed.",
                "transport": "lora",
            },
        )
        client.post(
            "/api/dispatch/messages",
            json={
                "sender": "aj",
                "peer": "bob",
                "body": "Thanks — can you check Outpost 03 next?",
                "transport": "wifi",
            },
        )
        client.post(
            "/api/postbox/messages",
            json={
                "from_user": "bob",
                "to": "aj@waypost",
                "subject": "Trail maintenance this weekend",
                "body": "Planning a work party Saturday morning if weather holds.",
            },
        )
        client.post(
            "/api/postbox/messages",
            json={
                "from_user": "aj",
                "to": "bob@waypost",
                "subject": "Water filtration notes",
                "body": "Draft updates for the Fieldbook page — review when you can.",
                "queue_only": True,
            },
        )
        client.post(
            "/api/commons/posts",
            json={
                "author": "bob",
                "title": "Saturday work party",
                "body": "Meet at the north trailhead at 08:00 if weather holds. Bring gloves.",
            },
        )
        client.post(
            "/api/commons/posts",
            json={
                "author": "aj",
                "body": "Outpost 03 is back online after the overnight power blip.",
            },
        )
        client.post(
            "/api/noticeboard/notices",
            json={
                "author": "aj",
                "title": "Well maintenance Tuesday",
                "body": "Pump house closed 09:00–12:00. Fill jugs Monday evening if you can.",
                "priority": "high",
            },
        )
        client.post(
            "/api/noticeboard/notices",
            json={
                "author": "bob",
                "title": "Community supper Friday",
                "body": "Potluck at the commons hall from 18:00. Bring a dish to share.",
                "priority": "normal",
            },
        )
        client.post(
            "/api/beacon",
            json={
                "author": "aj",
                "title": "Storm watch — secure loose gear",
                "body": "High winds expected after dark. Check tent lines and shed doors.",
                "severity": "urgent",
            },
        )
        client.post(
            "/api/dispatch/devices/bind",
            json={"node_id": "pocket-aj", "username": "aj"},
        )
        # Seed Locker demo files via multipart
        client.post(
            "/api/locker/files",
            data={
                "owner": "bob",
                "scope": "shared",
                "note": "Print and post near the well",
            },
            files={
                "file": (
                    "well-maintenance.txt",
                    b"Pump house checklist\n1. Check oil\n2. Clear intake\n3. Log hours\n",
                    "text/plain",
                )
            },
        )
        client.post(
            "/api/locker/files",
            data={"owner": "aj", "scope": "shared", "note": "Community map draft"},
            files={
                "file": (
                    "trail-map-notes.txt",
                    b"North ridge spur is muddy after rain. Prefer lower path.\n",
                    "text/plain",
                )
            },
        )


def _prime_page(page, slug: str) -> None:
    """Open seeded rows so screenshots show conversation/mail detail."""
    if slug == "dispatch":
        page.wait_for_selector("#conv-list button", timeout=10000)
        page.click("#conv-list button")
        page.wait_for_selector("#messages li", timeout=10000)
    elif slug == "postbox":
        page.wait_for_selector("#mail-list button", timeout=10000)
        page.click("#mail-list button")
        page.wait_for_selector("#detail:not([hidden])", timeout=10000)
    elif slug == "noticeboard":
        page.wait_for_selector("#notice-list button", timeout=10000)
        page.wait_for_selector("#detail:not([hidden])", timeout=10000)


def capture(base: str, out_dir: Path) -> list[Path]:
    from playwright.sync_api import sync_playwright

    out_dir.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            viewport={"width": 1440, "height": 900},
            device_scale_factor=1,
        )
        page = context.new_page()

        for slug, path, _caption in PAGES:
            page.goto(base.rstrip("/") + path, wait_until="networkidle")
            # Shell mounts via JS; give it a beat
            page.wait_for_selector(".wp-sidebar", timeout=10000)
            _prime_page(page, slug)
            page.wait_for_timeout(350)
            dest = out_dir / f"{slug}.png"
            page.screenshot(path=str(dest), full_page=False)
            written.append(dest)
            try:
                print(f"wrote {dest.relative_to(ROOT)}")
            except ValueError:
                print(f"wrote {dest}")

        # Mobile home shot for responsive docs
        mobile = browser.new_context(
            viewport={"width": 390, "height": 844},
            device_scale_factor=2,
            is_mobile=True,
        )
        mpage = mobile.new_page()
        mpage.goto(base.rstrip("/") + "/", wait_until="networkidle")
        mpage.wait_for_selector(".wp-menu-btn", timeout=10000)
        mpage.wait_for_timeout(400)
        dest = out_dir / "home-mobile.png"
        mpage.screenshot(path=str(dest), full_page=False)
        written.append(dest)
        try:
            print(f"wrote {dest.relative_to(ROOT)}")
        except ValueError:
            print(f"wrote {dest}")
        mobile.close()

        browser.close()

    return written


def write_manifest(out_dir: Path) -> None:
    lines = [
        "# Portal screenshots",
        "",
        "Early-alpha UI captures generated by `python -m tools.screenshots.capture`.",
        "These show **prototype** screens, not a finished product.",
        "",
        "Regenerate:",
        "",
        "```bash",
        "uv pip install -r server/requirements-dev.txt",
        "playwright install chromium",
        "python -m tools.screenshots.capture",
        "pytest server/tests/test_screenshots.py -q",
        "# Optional full regenerator smoke:",
        "WAYPOST_SHOT_LIVE=1 pytest server/tests/test_screenshots.py::test_capture_regenerates -q",
        "```",
        "",
    ]
    for slug, _path, caption in PAGES:
        lines.append(f"## {caption}")
        lines.append("")
        lines.append(f"![ {caption} ]({slug}.png)")
        lines.append("")
    lines.extend(
        [
            "## Home (mobile width)",
            "",
            "![Home mobile](home-mobile.png)",
            "",
        ]
    )
    (out_dir / "README.md").write_text("\n".join(lines), encoding="utf-8")
    try:
        print(f"wrote {(out_dir / 'README.md').relative_to(ROOT)}")
    except ValueError:
        print(f"wrote {out_dir / 'README.md'}")


def main() -> int:
    out_dir = Path(os.environ.get("WAYPOST_SHOT_OUT", DEFAULT_OUT))
    external = os.environ.get("WAYPOST_SHOT_BASE")
    proc = None
    data_dir = ROOT / "data" / "screenshots-run"
    data_dir.mkdir(parents=True, exist_ok=True)
    db_path = data_dir / "waypost.db"
    if db_path.exists():
        db_path.unlink()

    try:
        if external:
            base = external.rstrip("/")
            print(f"using existing server {base}")
        else:
            port = _free_port()
            base = f"http://127.0.0.1:{port}"
            env = os.environ.copy()
            env.update(
                {
                    "WAYPOST_ENV": "development",
                    "WAYPOST_TRANSPORT": "mock",
                    "WAYPOST_DATA_DIR": str(data_dir),
                    "WAYPOST_SQLITE_PATH": str(db_path),
                    "PYTHONPATH": str(ROOT),
                }
            )
            proc = subprocess.Popen(
                [
                    sys.executable,
                    "-m",
                    "uvicorn",
                    "server.api.main:app",
                    "--host",
                    "127.0.0.1",
                    "--port",
                    str(port),
                ],
                cwd=str(ROOT),
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
            print(f"started Station API on {base} (pid {proc.pid})")

        seed_demo(base)
        capture(base, out_dir)
        write_manifest(out_dir)
        return 0
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()


if __name__ == "__main__":
    raise SystemExit(main())
