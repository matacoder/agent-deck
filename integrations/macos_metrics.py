"""Processor and memory load on macOS from its own commands, for installs without psutil (dropped from
the macOS installer: nothing is installed with pip)."""
import os
import re
import subprocess
import time

_cache = None  # (monotonic time, figures): the commands run at most once a second


def add(result):
    """Installs since psutil was dropped: the same figures from macOS's own commands."""
    global _cache
    now = time.monotonic()
    if _cache is None or now - _cache[0] >= 1:
        _cache = (now, figures())
    result.update(_cache[1])
    return result


def command(*arguments):
    try:
        return subprocess.run(list(arguments), input="", capture_output=True, text=True, timeout=3, check=True).stdout
    except (OSError, subprocess.SubprocessError):
        return None


def figures():
    figures = {}
    shares = command("ps", "-A", "-o", "%cpu=")
    try:
        # ps gives each process's recent share of one core; a decimal comma depends on the locale.
        total_share = sum(float(value.replace(",", ".")) for value in shares.split())
        figures["cpu_percent"] = round(max(0, min(100, total_share / (os.cpu_count() or 1))), 1)
    except (AttributeError, ValueError):
        pass
    total, stat = command("sysctl", "-n", "hw.memsize"), command("vm_stat")
    try:
        total = int(total)
        page = int(re.search(r"page size of (\d+) bytes", stat).group(1))
        # psutil's "available" on macOS: free plus inactive pages.
        free, inactive = (int(re.search(rf"^Pages {name}:\s+(\d+)", stat, re.M).group(1)) for name in ("free", "inactive"))
        available = (free + inactive) * page
        if total > 0:
            figures.update(memory_total=total, memory_used=max(0, min(total, total - available)))
    except (AttributeError, TypeError, ValueError):
        pass
    return figures
