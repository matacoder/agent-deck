#!/usr/bin/env python3
"""Bundle panel sources into the HTML supported by installed release updaters."""
import argparse
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when generated HTML is stale")
    args = parser.parse_args()
    source = ROOT / "frontend"
    page = (source / "index.html").read_text()
    for marker, name in (("__PANEL_STYLE__", "style.css"), ("__PANEL_SCRIPT__", "app.js")):
        if page.count(marker) != 1:
            raise SystemExit(f"Expected one {marker} in the panel template")
        content = (source / name).read_text()
        if name == "app.js":
            parts = ("logic.js", "settings.js", "decks.js", "questions.js", "backups.js", "notifications.js", "images.js", "fleet.js", "inbox.js", "screen.js", "gestures.js", "files.js", "git.js")
            content = "".join((source / part).read_text() for part in parts) + content
        page = page.replace(marker, content)
    target = ROOT / "panel/index.html"
    if args.check:
        if target.read_text() != page:
            raise SystemExit("Panel HTML is stale; run python3 scripts/build-panel.py")
    else:
        target.write_text(page)


if __name__ == "__main__":
    main()
