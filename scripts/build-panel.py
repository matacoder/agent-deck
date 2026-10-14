#!/usr/bin/env python3
"""Bundle panel sources into the HTML supported by installed release updaters."""
import argparse
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]
# Every file shares one script scope, so order matters: a file may use at top level only what came before it.
SCRIPTS = (
    "agents.js",
    "logic.js",
    "settings.js",
    "decks.js",
    "questions.js",
    "backups.js",
    "notifications.js",
    "images.js",
    "fleet.js",
    "inbox.js",
    "screen.js",
    "gestures.js",
    "files.js",
    "gallery.js",
    "git.js",
    "session-info.js",
    "quotas.js",
    "hotkeys.js",
    "schedule.js",
    "project.js",
    "resize.js",
    "markdown.js",
    "search.js",
    "hub.js",
    "hub-cards.js",
    "hub-models.js",
    "containers.js",
    "lan.js",
    "drop.js",
    "providers.js",
    "here.js",
    "remember.js",
    "richpaste.js",
    "voice-audio.js",
    "voice.js",
)
TOP_LEVEL = re.compile(r"^(?:async\s+)?(?:function\*?|const|let|var|class)\s+([A-Za-z_$][\w$]*)", re.M)


def check_scripts(source):
    """A file missing from SCRIPTS would be dropped silently; a name declared twice would break the page."""
    files = {path.name for path in source.glob("*.js")} - {"app.js"}
    if files != set(SCRIPTS):
        raise SystemExit(f"frontend/*.js and SCRIPTS differ: {sorted(files ^ set(SCRIPTS))}")
    owners = {}
    for name in (*SCRIPTS, "app.js"):
        for declared in TOP_LEVEL.findall((source / name).read_text()):
            if declared in owners:
                raise SystemExit(f"{declared} is declared at top level in both {owners[declared]} and {name}")
            owners[declared] = name


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check", action="store_true", help="fail when generated HTML is stale")
    args = parser.parse_args()
    source = ROOT / "frontend"
    check_scripts(source)
    page = (source / "index.html").read_text()
    for marker, name in (("__PANEL_STYLE__", "style.css"), ("__PANEL_SCRIPT__", "app.js")):
        if page.count(marker) != 1:
            raise SystemExit(f"Expected one {marker} in the panel template")
        content = (source / name).read_text()
        if name == "app.js":
            content = "".join((source / part).read_text() for part in SCRIPTS) + content
        page = page.replace(marker, content)
    target = ROOT / "panel/index.html"
    if args.check:
        if target.read_text() != page:
            raise SystemExit("Panel HTML is stale; run python3 scripts/build-panel.py")
    else:
        target.write_text(page)


if __name__ == "__main__":
    main()
