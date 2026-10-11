"""Prompts the user saved to send with one tap; one list for every computer, kept on the gateway."""
import json
from pathlib import Path
import threading

from .backups import write_private

MAX_PROMPTS, MAX_LABEL, MAX_TEXT = 24, 30, 4000


class QuickPrompts:
    def __init__(self, directory):
        self.path = Path(directory) / "quick-prompts.json"
        self.lock = threading.Lock()

    def list(self):
        with self.lock:
            try:
                return self.clean(json.loads(self.path.read_text()))
            except (OSError, ValueError):
                return []  # A missing or damaged file is an empty list; saving rewrites it.

    @staticmethod
    def clean(items):
        if not isinstance(items, list) or len(items) > MAX_PROMPTS:
            raise ValueError("Быстрых сообщений может быть не больше 24")
        result = []
        for item in items:
            text = item.get("text") if isinstance(item, dict) else None
            label = item.get("label", "") if isinstance(item, dict) else None
            if not isinstance(text, str) or not text.strip() or len(text) > MAX_TEXT or not isinstance(label, str):
                raise ValueError("Быстрое сообщение: введите текст до 4000 символов")
            label = " ".join(label.split())[:MAX_LABEL] or " ".join(text.split())[:MAX_LABEL]
            result.append({"label": label, "text": text})
        return result

    def save(self, items):
        prompts = self.clean(items)
        with self.lock:
            write_private(self.path, json.dumps(prompts, ensure_ascii=False).encode())
        return prompts
