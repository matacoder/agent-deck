"""Small durable outbox, separate from panel settings and agent session history."""
import json
import os
from pathlib import Path
import secrets
import sqlite3
import time
from contextlib import contextmanager


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, mode=0o700, exist_ok=True)
        if self.path.is_symlink():
            raise ValueError("Integration database must not be a symlink")
        fd = os.open(self.path, os.O_CREAT | os.O_RDWR, 0o600)
        os.close(fd)
        self.path.chmod(0o600)
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS questions (
                    id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, session TEXT NOT NULL,
                    payload TEXT NOT NULL, message_id INTEGER, status TEXT NOT NULL,
                    created REAL NOT NULL);
                CREATE UNIQUE INDEX IF NOT EXISTS question_open ON questions(fingerprint)
                    WHERE status IN ('pending', 'sent', 'answering');
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            ''')
            # Never replay an answer after a crash between terminal input and acknowledgement.
            db.execute("UPDATE questions SET status='uncertain' WHERE status='answering'")

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            with db:
                yield db
        finally:
            db.close()

    def remember(self, question):
        with self.connect() as db:
            row = db.execute("SELECT * FROM questions WHERE fingerprint=? AND status!='retired' ORDER BY created DESC LIMIT 1",
                             (question.fingerprint,)).fetchone()
            if row:
                return dict(row)
            identity = secrets.token_hex(12)
            db.execute("INSERT INTO questions VALUES(?,?,?,?,NULL,'pending',?)",
                       (identity, question.fingerprint, question.session,
                        json.dumps(question.__dict__, ensure_ascii=False), time.time()))
            return dict(db.execute("SELECT * FROM questions WHERE id=?", (identity,)).fetchone())

    def get(self, identity):
        with self.connect() as db:
            row = db.execute("SELECT * FROM questions WHERE id=?", (identity,)).fetchone()
            return dict(row) if row else None

    def claim(self, identity):
        with self.connect() as db:
            return db.execute("UPDATE questions SET status='answering' WHERE id=? AND status='sent'",
                              (identity,)).rowcount == 1

    def set_status(self, identity, status, message_id=None):
        with self.connect() as db:
            db.execute("UPDATE questions SET status=?, message_id=COALESCE(?,message_id) WHERE id=?",
                       (status, message_id, identity))

    def pending(self):
        with self.connect() as db:
            return [dict(row) for row in db.execute("SELECT * FROM questions WHERE status IN ('pending','sent')")]

    def expire(self, fingerprints):
        stale = []
        with self.connect() as db:
            for row in db.execute("SELECT * FROM questions WHERE status IN ('pending','sent')"):
                if row['fingerprint'] not in fingerprints:
                    stale.append(dict(row))
            db.executemany("UPDATE questions SET status='expired' WHERE id=?", [(r['id'],) for r in stale])
            rows = db.execute("SELECT id,fingerprint FROM questions WHERE status IN ('answered','expired','uncertain')").fetchall()
            db.executemany("UPDATE questions SET status='retired' WHERE id=?",
                           [(r['id'],) for r in rows if r['fingerprint'] not in fingerprints])
            db.execute("DELETE FROM questions WHERE created < ? AND status NOT IN ('pending','sent')",
                       (time.time() - 7 * 86400,))
        return stale

    def offset(self, value=None):
        with self.connect() as db:
            if value is not None:
                db.execute("INSERT OR REPLACE INTO metadata VALUES('telegram_offset',?)", (str(value),))
            row = db.execute("SELECT value FROM metadata WHERE key='telegram_offset'").fetchone()
            return int(row[0]) if row else 0

    def reset(self):
        with self.connect() as db:
            db.execute("UPDATE questions SET status='retired'")
            db.execute("DELETE FROM metadata WHERE key='telegram_offset'")
