"""What the gateway asks its connected Agent Decks: questions, session lists and Telegram state.

Computers are asked in parallel, so an offline one costs one timeout instead of one per computer.
A computer that fails keeps its last answer for a while: a network blip must not look like its
questions were answered (Telegram would retire and later re-send them, notifications would fire
twice) or like every session finished.
"""
from concurrent.futures import ThreadPoolExecutor
import json
import threading
import time

from .decks import POLL_LIMIT
from .questions import Question

FAILURES = (ValueError, KeyError, TypeError, AttributeError, OSError, RuntimeError)
QUESTIONS_STALE_FOR = 300
QUESTION_BACKOFF = 30
SESSIONS_EVERY = 10


def get_json(decks, identity, path, timeout=5, method='GET', body=None):
    """One call to a connected computer -> (status, dict); anything but a JSON object raises ValueError."""
    args = () if body is None else (body,)
    status, _, raw = decks.request(identity, method, path, *args, timeout=timeout, limit=POLL_LIMIT)
    try:
        data = json.loads(raw)
    except ValueError:
        raise ValueError('Remote Agent Deck returned invalid JSON') from None
    if not isinstance(data, dict):
        raise ValueError('Remote Agent Deck returned an unexpected answer')
    return status, data


def each(decks, fetch):
    """Runs fetch(deck) for every computer in parallel -> [(deck, result, error)]."""
    if not decks:
        return []
    with ThreadPoolExecutor(max_workers=min(8, len(decks))) as pool:
        futures = [(deck, pool.submit(fetch, deck)) for deck in decks]
    results = []
    for deck, future in futures:
        try:
            results.append((deck, future.result(), None))
        except FAILURES as error:
            results.append((deck, None, error))
    return results


class Gateway:
    def __init__(self, decks, clock=time.monotonic):
        self.decks = decks  # Callable returning the connected-decks service, which the panel may replace.
        self.clock = clock
        self.lock = threading.Lock()
        self.backoff = {}     # deck id -> monotonic time before which questions are not asked again
        self.snapshot = {}    # deck id -> (asked_at, questions)
        self.sessions_at = None
        self.session_items = []
        self.sessions_lock = threading.Lock()  # One refresh at a time; network calls stay outside self.lock.

    def connected(self):
        return [deck for deck in self.decks().status().get('decks', []) if deck.get('id')]

    def fetch_questions(self, deck):
        status, data = get_json(self.decks(), deck['id'], '/api/questions')
        if status != 200:
            raise ValueError('questions unavailable')  # Older releases have no /api/questions.
        # The remote fingerprint travels as `instance`: it is what the remote checks on answer.
        return [Question(item['session'], item['agent'], item['id'], item['title'],
                         tuple(o['label'] for o in item['options']), item['selected'],
                         item.get('progress', ''), deck=deck['id'], origin=deck.get('name', ''),
                         label=str(item.get('label') or ''))
                for item in data.get('questions', [])]

    def questions(self):
        """Questions of connected Agent Decks, so one Telegram bot on the gateway serves every machine."""
        decks, now = self.connected(), self.clock()
        with self.lock:
            due = [deck for deck in decks if self.backoff.get(deck['id'], 0) <= now]
        for deck, items, error in each(due, self.fetch_questions):
            with self.lock:
                if error:
                    self.backoff[deck['id']] = self.clock() + QUESTION_BACKOFF
                else:
                    self.snapshot[deck['id']] = (self.clock(), items)
        result = []
        with self.lock:
            present = {deck['id'] for deck in decks}
            for identity in list(self.snapshot):
                at, items = self.snapshot[identity]
                if identity not in present or self.clock() - at >= QUESTIONS_STALE_FOR:
                    del self.snapshot[identity]  # Removed computers and answers too old to trust.
                else:
                    result.extend(items)
            self.backoff = {key: until for key, until in self.backoff.items() if key in present}
        return result

    def fetch_sessions(self, deck):
        status, data = get_json(self.decks(), deck['id'], '/api/sessions')
        if status != 200:
            raise ValueError('sessions unavailable')
        sessions = data.get('sessions', [])
        # One malformed entry must not stop notifications for every computer.
        return [{**s, 'deck': deck['id'], 'deck_name': deck.get('name', '')} for s in sessions
                if isinstance(s, dict) and isinstance(s.get('name'), str)]

    def sessions(self):
        """Connected computers' session lists for notification events, refreshed every 10 s."""
        with self.sessions_lock:
            return self.refresh_sessions()

    def refresh_sessions(self):
        if self.sessions_at is None or self.clock() - self.sessions_at > SESSIONS_EVERY:
            previous = {}
            for item in self.session_items:
                previous.setdefault(item['deck'], []).append(item)
            remote = []
            for deck, items, error in each(self.connected(), self.fetch_sessions):
                remote += previous.get(deck['id'], []) if error else items
            self.session_items, self.sessions_at = remote, self.clock()
        return list(self.session_items)

    def telegram_states(self):
        """(computer id, name, its Telegram status) for every connected computer that answered."""
        def fetch(deck):
            status, data = get_json(self.decks(), deck['id'], '/api/integrations', timeout=3)
            return data.get('telegram', {}) if status == 200 else {}
        return [(deck['id'], deck.get('name', ''), state) for deck, state, error in each(self.connected(), fetch)
                if not error and isinstance(state, dict)]

    def answer(self, question, index, text=None):
        request = {'name': question.session, 'id': question.instance, 'index': index}
        if text is not None:
            request['text'] = text
        try:
            status, _, payload = self.decks().request(question.deck, 'POST', '/api/answer',
                                                      json.dumps(request).encode(), timeout=15)
        except Exception:
            # Transport failure after sending is ambiguous: report it, never resend.
            raise RuntimeError('Remote Agent Deck did not confirm the answer') from None
        if status == 200:
            return
        try:
            message = json.loads(payload).get('error')
        except (ValueError, AttributeError):
            message = None
        if 400 <= status < 500 and message:
            raise ValueError(message)
        raise RuntimeError('Remote Agent Deck did not confirm the answer')
