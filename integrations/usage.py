"""Subscription limits of Claude, Codex and Kimi, normalized to windows the panel shows.

Network access and credentials come from the caller, so this module stays free of side effects.
"""
from datetime import datetime
import json
import math
import time
import urllib.error


def epoch(iso):
    # Python 3.10 parses only 3- or 6-digit fractions; an unexpected format loses the reset time, not the card.
    try:
        return int(datetime.fromisoformat(iso.replace("Z", "+00:00")).timestamp()) if iso else None
    except (ValueError, TypeError, AttributeError):
        return None


def claude(credentials, http_json):
    o = credentials.get("claudeAiOauth") or {}
    if not o.get("accessToken"):
        return {"error": "Войдите в Claude Code для просмотра лимитов"}
    if (o.get("expiresAt") or 0) / 1000 < time.time():
        # never refresh here: Claude rotates refresh tokens, a second refresher would log it out
        return {"plan": o.get("subscriptionType"), "error": "токен истёк — запустите Claude, он обновит его"}
    d = http_json("https://api.anthropic.com/api/oauth/usage",
                  {"Authorization": "Bearer " + o["accessToken"], "anthropic-beta": "oauth-2025-04-20"})
    windows = []
    week = 7 * 86400
    for key, label, secs in (("seven_day", "неделя", week),
                             ("seven_day_opus", "неделя Opus", week), ("seven_day_sonnet", "неделя Sonnet", week)):
        w = d.get(key)
        if w and w.get("utilization") is not None:
            windows.append({"label": label, "percent": w["utilization"], "resets_at": epoch(w.get("resets_at")),
                            "secs": secs})
    return {"plan": o.get("subscriptionType"), "windows": windows}


def codex(http_json, auth_path):
    with open(auth_path) as stream:
        t = json.load(stream).get("tokens") or {}
    if not t.get("access_token"):
        return {"error": "Codex вошёл по API-ключу: лимитов подписки нет"}
    d = http_json("https://chatgpt.com/backend-api/wham/usage",
                  {"Authorization": "Bearer " + t["access_token"], "ChatGPT-Account-Id": t.get("account_id", "")})
    windows = []
    for w in ((d.get("rate_limit") or {}).get("primary_window"), (d.get("rate_limit") or {}).get("secondary_window")):
        if not w:
            continue
        secs = w.get("limit_window_seconds") or 0
        label = {18000: "5 ч", 604800: "неделя"}.get(secs, f"{round(secs / 3600)} ч")
        windows.append({"label": label, "percent": w.get("used_percent"), "resets_at": w.get("reset_at"), "secs": secs})
    windows.sort(key=lambda w: w["secs"])
    return {"plan": d.get("plan_type"), "windows": windows}


def kimi(key, http_json):
    if not key:
        return {"error": "Сохраните ключ Kimi в настройках панели"}
    try:
        data = http_json("https://api.kimi.com/coding/v1/usages", {"Authorization": "Bearer " + key, "Accept": "application/json"})
    except urllib.error.HTTPError as error:
        error.close()
        return {"error": "Kimi: проверьте ключ" if error.code in (401, 403) else "Kimi: лимиты временно недоступны"}
    except (OSError, ValueError):
        return {"error": "Kimi: лимиты временно недоступны"}
    windows = []
    authoritative = set()
    # The counters in limits are authoritative. The legacy usages.limit_5h can
    # incorrectly report zero even while the service rejects calls at 100/100.
    for limit in data.get("limits") or []:
        if not isinstance(limit, dict):
            continue
        window, detail = limit.get("window") or {}, limit.get("detail") or {}
        try:
            multiplier = {"TIME_UNIT_SECOND": 1, "TIME_UNIT_MINUTE": 60,
                          "TIME_UNIT_HOUR": 3600, "TIME_UNIT_DAY": 86400}[window["timeUnit"]]
            secs = float(window["duration"]) * multiplier
            if not math.isfinite(secs) or secs <= 0:
                continue
            authoritative.add(secs)
            total, used = float(detail["limit"]), float(detail["used"])
            if not all(map(math.isfinite, (total, used))) or total <= 0 or used < 0:
                continue
            reset = epoch(detail.get("resetTime"))
            label = {18000: "5 часов", 604800: "неделя"}.get(secs, f"{secs / 3600:g} ч")
            windows.append({"label": label, "percent": used / total * 100,
                            "resets_at": reset, "secs": secs, "period": "hours"})
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
    for name, label, secs, period in (
            ("limit_month_total", "Общий · месяц", 0, "month"),
            ("limit_month_code", "Kimi Code · месяц", 0, "month"),
            ("limit_5h", "5 часов", 18000, "hours"),
            ("limit_7d", "неделя", 604800, "week")):
        if secs and secs in authoritative:
            continue
        value = (data.get("usages") or {}).get(name)
        if not isinstance(value, dict):
            continue
        try:
            ratio = float(value["used_ratio"])
            if not math.isfinite(ratio) or ratio < 0:
                continue
            reset = epoch(value.get("reset_time"))
        except (ValueError, TypeError, KeyError, OverflowError):
            continue
        # Calendar months vary in length. Do not invent a 30-day pace/forecast.
        windows.append({"label": label, "percent": ratio * 100, "resets_at": reset, "secs": secs, "period": period})
    return {"windows": windows} if windows else {"error": "Kimi не вернул данные о квотах"}
