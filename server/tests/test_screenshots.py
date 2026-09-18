"""Screenshot artifact + capture smoke tests.

Default checks assert committed PNGs under docs/screenshots/ are present and
sane. The full Playwright regenerator runs when WAYPOST_SHOT_LIVE=1 (slower;
needs Chromium from `playwright install chromium`).
"""

from __future__ import annotations

import os
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SHOT_DIR = ROOT / "docs" / "screenshots"

EXPECTED = (
    "home.png",
    "dispatch.png",
    "postbox.png",
    "commons.png",
    "noticeboard.png",
    "beacon.png",
    "locker.png",
    "rollcall.png",
    "signal.png",
    "home-mobile.png",
)


def test_screenshot_artifacts_present():
    missing = [name for name in EXPECTED if not (SHOT_DIR / name).is_file()]
    assert not missing, f"missing screenshots: {missing} — run python -m tools.screenshots.capture"


def test_screenshot_png_dimensions():
    pytest.importorskip("PIL")
    from PIL import Image

    desktop = {
        "home.png",
        "dispatch.png",
        "postbox.png",
        "commons.png",
        "noticeboard.png",
        "beacon.png",
        "locker.png",
        "rollcall.png",
        "signal.png",
    }
    for name in EXPECTED:
        path = SHOT_DIR / name
        with Image.open(path) as im:
            assert im.format == "PNG"
            w, h = im.size
            assert w >= 300 and h >= 300, f"{name} too small: {w}x{h}"
            if name in desktop:
                assert (w, h) == (1440, 900), f"{name} expected 1440x900, got {w}x{h}"
            elif name == "home-mobile.png":
                assert w >= 700 and h >= 1400, f"home-mobile unexpected size {w}x{h}"


@pytest.mark.skipif(
    os.environ.get("WAYPOST_SHOT_LIVE") != "1",
    reason="set WAYPOST_SHOT_LIVE=1 to run Playwright capture",
)
def test_capture_regenerates(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    from tools.screenshots.capture import DEFAULT_OUT, PAGES, main

    assert PAGES, "PAGES catalog empty"
    out = tmp_path / "shots"
    monkeypatch.setenv("WAYPOST_SHOT_OUT", str(out))
    monkeypatch.delenv("WAYPOST_SHOT_BASE", raising=False)
    assert main() == 0
    for name in EXPECTED:
        assert (out / name).is_file(), name
    assert (out / "README.md").is_file()
    assert DEFAULT_OUT == SHOT_DIR
