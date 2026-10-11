"""Prompts that wait for their moment, and continuing by itself after a subscription limit.

A prompt is sent at a time, when the session is free, or when the limit that stopped the session resets.
Every prompt is removed from the file before it is typed: a crash in between loses it, never sends it twice.
"""
import json
from pathlib import Path
import secrets
import threading
import time

from .backups import write_private
from .limits import detect

TRIGGERS = ("time", "idle", "limit")
MAX_TEXT, MAX_PER_SESSION, MAX_AHEAD = 20000, 20, 30 * 86400
IDLE = 8            # Seconds without screen activity before a session counts as free.
AFTER_RESET = 60    # The limit lifts a little after the minute the agent names.
GONE_AFTER = 600    # A restart closes the session for a moment; a session gone this long is closed.
CONTINUE = "continue"


class Schedule:
    def __init__(self, directory, sessions, screen, blocked, send, window_reset=None, clock=time.time):
        self.path = Path(directory) / "schedule.json"
        self.sessions, self.screen, self.blocked, self.send = sessions, screen, blocked, send
        self.window_reset = window_reset or (lambda agent: None)
        self.clock = clock
        self.lock = threading.RLock()
        self.activity = {}   # session -> [activity, changed_at]
        self.missing = {}    # session -> first time it was not found
        self.resumed = {}    # session -> reset time already acted on
        self.limits = {}     # session -> {'notice', 'at'} while a limit notice is on its screen
        self.errors = {}     # session -> why the last prompt was not sent
        self.started = False
        try:
            saved = json.loads(self.path.read_text())
        except (OSError, ValueError):
            saved = {}
        saved = saved if isinstance(saved, dict) else {}
        self.prompts = [p for p in saved.get("prompts", []) if self.valid(p)]
        self.auto = {name for name in saved.get("auto_resume", []) if isinstance(name, str)}

    @staticmethod
    def valid(prompt):
        return (isinstance(prompt, dict) and isinstance(prompt.get("id"), str) and isinstance(prompt.get("session"), str)
                and isinstance(prompt.get("text"), str) and prompt.get("trigger") in TRIGGERS
                and isinstance(prompt.get("at", 0), (int, float)))

    def save(self):
        write_private(self.path, json.dumps({"prompts": self.prompts, "auto_resume": sorted(self.auto)},
                                            ensure_ascii=False).encode())

    def status(self, name):
        with self.lock:
            return {"prompts": [{k: p[k] for k in ("id", "text", "trigger", "at", "created")}
                                for p in self.prompts if p["session"] == name],
                    "auto_resume": name in self.auto, "limit": self.limits.get(name), "error": self.errors.get(name, "")}

    def session(self, name):
        found = next((s for s in self.sessions() if s["name"] == name), None) if isinstance(name, str) else None
        if not found:
            raise ValueError("нет такой сессии")
        return found

    def add(self, name, text, trigger, at=None):
        session = self.session(name)
        if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT:
            raise ValueError("Введите сообщение (до 20000 символов)")
        if trigger not in TRIGGERS:
            raise ValueError("Выберите, когда отправить сообщение")
        if trigger == "limit" and session.get("agent") == "shell":
            raise ValueError("У терминала нет лимитов подписки")
        now = self.clock()
        if trigger == "time":
            if isinstance(at, bool) or not isinstance(at, (int, float)) or not now - 60 <= at <= now + MAX_AHEAD:
                raise ValueError("Укажите время в ближайшие 30 дней")
        with self.lock:
            if sum(p["session"] == name for p in self.prompts) >= MAX_PER_SESSION:
                raise ValueError("Слишком много отложенных сообщений в этой сессии; удалите лишние")
            prompt = {"id": secrets.token_hex(8), "session": name, "text": text, "trigger": trigger,
                      "at": int(at) if trigger == "time" else 0, "created": int(now)}
            self.prompts.append(prompt)
            self.errors.pop(name, None)
            self.save()
        self.start()
        return self.status(name)

    def remove(self, identity):
        with self.lock:
            kept = [p for p in self.prompts if p["id"] != identity]
            if len(kept) != len(self.prompts):
                self.prompts = kept
                self.save()

    def set_auto(self, name, enabled):
        session = self.session(name)
        if not isinstance(enabled, bool):
            raise ValueError("Автопродолжение можно только включить или выключить")
        if enabled and session.get("agent") == "shell":
            raise ValueError("У терминала нет лимитов подписки")
        with self.lock:
            (self.auto.add if enabled else self.auto.discard)(name)
            self.save()
        self.start()
        return self.status(name)

    def forget(self, name):
        with self.lock:
            kept = [p for p in self.prompts if p["session"] != name]
            changed = len(kept) != len(self.prompts) or name in self.auto
            self.prompts = kept
            self.auto.discard(name)
            for memory in (self.activity, self.missing, self.resumed, self.limits, self.errors):
                memory.pop(name, None)
            if changed:
                self.save()

    def idle(self, session, now):
        state = self.activity.get(session["name"])
        if state is None or state[0] != session.get("activity"):
            self.activity[session["name"]] = [session.get("activity"), now]
            return False
        return now - state[1] >= IDLE

    def limit(self, session, now):
        """The limit notice on an idle screen, with the reset time from the screen or the provider's counters."""
        name = session["name"]
        found = detect(self.screen(name), now)
        with self.lock:
            known = self.limits.get(name)
        if found and found["at"] is None:
            # Once the window resets the counters no longer name it, so the time learned earlier is kept.
            found["at"] = (self.window_reset(session.get("agent"))
                           or (known["at"] if known and known["notice"] == found["notice"] else None))
        with self.lock:
            if found:
                self.limits[name] = found
            else:
                self.limits.pop(name, None)
        return found

    def due(self, session, now):
        """Texts to type into this session now, oldest first; their prompts are already removed from the file."""
        name, free = session["name"], self.idle(session, now)
        with self.lock:
            mine = [p for p in self.prompts if p["session"] == name]
            waits_for_limit = name in self.auto or any(p["trigger"] == "limit" for p in mine)
        lifted = None
        if free and waits_for_limit and session.get("running"):
            found = self.limit(session, now)
            if found and found["at"] and now >= found["at"] + AFTER_RESET and self.resumed.get(name) != found["at"]:
                lifted = found["at"]
        chosen = [p for p in mine if p["trigger"] == "time" and now >= p["at"]]
        if lifted:
            chosen += [p for p in mine if p["trigger"] == "limit"]
        if free and not chosen:
            chosen = [p for p in mine if p["trigger"] == "idle"][:1]  # One at a time: the next waits for this one.
        texts = [p["text"] for p in sorted(chosen, key=lambda p: p["created"])]
        if lifted and not any(p["trigger"] == "limit" for p in chosen):
            texts.append(CONTINUE)
        if not texts or not session.get("running") or self.blocked(name):
            return []  # A question on the screen would take the text as its answer; wait for the user.
        with self.lock:
            gone = {p["id"] for p in chosen}
            self.prompts = [p for p in self.prompts if p["id"] not in gone]
            if lifted:
                self.resumed[name] = lifted
            if gone:
                self.save()
        return texts

    def tick(self, now=None):
        now = self.clock() if now is None else now
        with self.lock:
            wanted = {p["session"] for p in self.prompts} | self.auto
        if not wanted:
            return
        sessions = {s["name"]: s for s in self.sessions()}
        for name in wanted:
            session = sessions.get(name)
            if session is None:
                if now - self.missing.setdefault(name, now) >= GONE_AFTER:
                    self.forget(name)
                continue
            self.missing.pop(name, None)
            for text in self.due(session, now):
                try:
                    self.send(name, text)
                    self.errors.pop(name, None)
                except Exception as error:  # Never retried: part of the text may already be typed.
                    self.errors[name] = str(error) if isinstance(error, ValueError) else type(error).__name__
                    break
                self.activity[name] = [session.get("activity"), now]

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        threading.Thread(target=self.loop, name="agent-deck-schedule", daemon=True).start()

    def loop(self):
        while True:
            time.sleep(5)
            try:
                self.tick()
            except Exception as error:  # A failed pass must not stop later prompts; it runs again in 5 s.
                print(f"Scheduled prompts check failed: {type(error).__name__}", flush=True)
