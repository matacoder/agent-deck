# Agent gallery

Pictures agents make show under the line that names them, but only while that path is in the session's
recent output: once it scrolls away, Claude redraws the screen, or the agent writes a new picture to the
same `/tmp/shot.png`, the picture is gone. Goal: every picture a session showed stays viewable.

## Collecting
- A background thread looks at each session whose screen changed (every 5 s), finds picture paths with the
  same rules as the Screen view (absolute, `~/…`, relative to the agent's folder, a bare name searched in the
  project, paths wrapped across lines).
- A picture is kept only under the existing rule: its path is on that session's screen, it is PNG, JPEG,
  WebP or GIF by content (never SVG), up to 25 MB.
- Kept as a private copy (`~/.cache/agent-deck/gallery/<session>/`, 0700/0600), one per distinct content:
  a file the agent overwrites gives a new picture, the same content again does not.
- Limits per session: 200 pictures and 300 MB, oldest dropped first; copies older than 30 days are deleted.
  A session that is gone keeps its gallery until then (a session restored under the same name sees it).

## Showing
- Fifth tab in the project panel, "Галерея": square thumbnails three per row, newest first, the count on top.
  A tap opens the existing full-screen viewer; swipe or ←/→ walks through the whole gallery.
- The Screen view keeps its thumbnails: when a path is no longer on screen (or the file was deleted or
  replaced), the panel answers with the kept copy instead of nothing.
- Connected computers: the gateway passes gallery pictures like screenshots; a computer without this
  version says it needs an update.
- Reloaded while the tab is open and the page visible.

## Out of scope
- Videos, SVG, pictures the agent never printed a path for, sharing outside the panel.
