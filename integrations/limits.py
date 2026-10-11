"""A subscription limit shown on an agent's screen: is the session stopped by one, and when does it lift.

Wording checked against Claude Code 2.1 ("You've hit your session limit · resets 3pm",
"Usage limit reached") and Codex 0.160 ("You've hit your usage limit. … try again at 3:15 PM.").
Spend limits and team budgets are skipped: they do not lift on their own.
"""
import re
import time

# Only at the start of a line: the same words inside a sentence are conversation, not the agent's notice.
NOTICE = re.compile(r"^[^\w\n]*(you['’]ve (?:hit|reached) your (?![^.\n]*(?:spend|budget))[^.\n]*limit|usage limit reached)",
                    re.I | re.M)
RESET = re.compile(r"(?:resets(?: at)?|try again at)\s+(.{1,60})", re.I)
CLOCK = re.compile(r"(?<![\d:])(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\b|(?<![\d:])(\d{1,2}):(\d{2})(?!\d)", re.I)
DAY = re.compile(r"\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.I)
MONTHS = ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec")
TAIL_LINES = 40
# A time without a date belongs to a window of a few hours; further ahead means it has already passed.
SOON = 6 * 3600


def local(year, month, day, hour, minute):
    try:
        return time.mktime((year, month, day, hour, minute, 0, 0, 0, -1))
    except (OverflowError, ValueError):
        return None


def reset_time(text, now):
    """Epoch of "3pm", "3:15 PM", "15:00" or "Oct 14, 9am" in the server's time zone; None when unreadable."""
    clock = CLOCK.search(text)
    if not clock:
        return None
    if clock.group(3):
        hour, minute = int(clock.group(1)), int(clock.group(2) or 0)
        if not 1 <= hour <= 12:
            return None
        hour = hour % 12 + (12 if clock.group(3).lower() == "p" else 0)
    else:
        hour, minute = int(clock.group(4)), int(clock.group(5))
    if hour > 23 or minute > 59:
        return None
    today = time.localtime(now)
    day = DAY.search(text)
    if day:
        month = MONTHS.index(day.group(1).lower()) + 1
        at = local(today.tm_year, month, int(day.group(2)), hour, minute)
        # A date months in the past is next year's: limits never reset further back than a week.
        if at is not None and at < now - 180 * 86400:
            at = local(today.tm_year + 1, month, int(day.group(2)), hour, minute)
        return at
    around = [local(today.tm_year, today.tm_mon, today.tm_mday + shift, hour, minute) for shift in (-1, 0, 1)]
    around = [at for at in around if at is not None]
    ahead = [at for at in around if now < at <= now + SOON]
    past = [at for at in around if at <= now]
    return ahead[0] if ahead else past[-1] if past else None


def detect(screen, now):
    """{'notice': the line, 'at': reset epoch or None} for a limit notice near the bottom of the screen."""
    tail = "\n".join(screen.rstrip().splitlines()[-TAIL_LINES:])
    found = None
    for found in NOTICE.finditer(tail):
        pass  # The last notice on the screen is the current one.
    if not found:
        return None
    # Codex wraps the sentence over several lines before it names the time.
    rest = re.sub(r"\s+", " ", tail[found.start(1):found.start(1) + 600])
    reset = RESET.search(rest)
    return {"notice": rest[:120].strip(), "at": reset_time(reset.group(1), now) if reset else None}
