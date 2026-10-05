"""Phone/desktop notifications: device subscriptions and agent events (question asked, work finished)."""
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time

from . import webpush
from .backups import write_private
from .dependencies import require

try:
    import locales
except ModuleNotFoundError:
    locales = None

SUBJECT = 'https://github.com/matacoder/agent-deck'
AGENT_LABELS = {'claude': 'Claude', 'codex': 'Codex', 'claude-kimi': 'Claude · Kimi', 'kimi': 'Kimi Code', 'pi': 'Pi'}
MAX_DEVICES = 20
IDLE_LOCAL, IDLE_REMOTE, MIN_BUSY = 8, 25, 20


class Push:
    def __init__(self, directory, sessions, questions, sender=None, clock=time.monotonic):
        self.path = Path(directory) / 'push.json'
        self.sessions, self.questions = sessions, questions
        self.sender = sender or webpush.send
        self.clock = clock
        self.lock = threading.RLock()
        self.activity = {}   # (deck, name) -> [activity, changed_at, busy_since or None]
        self.seen = {}       # question fingerprint -> last time it was present
        self.started = False
        self.warm = False  # The first pass after a restart only learns what is already pending.
        try:
            self.config = json.loads(self.path.read_text())
        except (OSError, ValueError):
            self.config = {}
        self.config.setdefault('subscriptions', [])
        self.config.setdefault('events', {'questions': True, 'finished': True})

    def save(self):
        write_private(self.path, json.dumps(self.config).encode())

    def vapid(self):
        require()
        with self.lock:
            if not self.config.get('vapid'):
                self.config['vapid'] = webpush.b64url(webpush.private_bytes(webpush.private_key()))
                self.save()
            return webpush.private_key(webpush.unb64url(self.config['vapid']))

    def status(self):
        from .dependencies import status as dependency_status
        state = dependency_status()
        with self.lock:
            devices = [{k: s[k] for k in ('id', 'label', 'created')} for s in self.config['subscriptions']]
            public = webpush.b64url(webpush.public_bytes(self.vapid())) if state['ready'] else None
            return {'available': state['ready'], 'error': state['error'], 'public_key': public,
                    'devices': devices, 'events': dict(self.config['events'])}

    def subscribe(self, data):
        require()
        subscription = data.get('subscription') if isinstance(data.get('subscription'), dict) else {}
        endpoint, keys = subscription.get('endpoint'), subscription.get('keys') or {}
        if not webpush.allowed_endpoint(endpoint):
            raise ValueError('Этот браузер использует неизвестный сервис уведомлений')
        try:
            p256dh, auth = webpush.unb64url(str(keys.get('p256dh', ''))), webpush.unb64url(str(keys.get('auth', '')))
            from cryptography.hazmat.primitives.asymmetric import ec
            ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), p256dh)
        except (ValueError, TypeError):
            raise ValueError('Неверная подписка на уведомления') from None
        if len(auth) != 16:
            raise ValueError('Неверная подписка на уведомления')
        language = data.get('language') if isinstance(data.get('language'), str) and re.fullmatch(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})?', data.get('language', '')) else 'en'
        label = str(data.get('label') or 'Browser')[:60]
        with self.lock:
            others = [s for s in self.config['subscriptions'] if s['endpoint'] != endpoint]
            if len(others) >= MAX_DEVICES:
                raise ValueError('Слишком много устройств с уведомлениями; отключите лишние')
            item = {'id': secrets.token_hex(8), 'endpoint': endpoint, 'keys': {'p256dh': keys['p256dh'], 'auth': keys['auth']},
                    'label': label, 'language': language, 'created': int(time.time())}
            self.config['subscriptions'] = others + [item]
            self.save()
        self.start()
        return {'id': item['id']}

    def unsubscribe(self, identity):
        with self.lock:
            self.config['subscriptions'] = [s for s in self.config['subscriptions'] if s['id'] != identity]
            self.save()

    def set_events(self, events):
        with self.lock:
            for key in ('questions', 'finished'):
                if isinstance(events.get(key), bool):
                    self.config['events'][key] = events[key]
            self.save()
            return dict(self.config['events'])

    def translate(self, text, language, params=()):
        if locales is not None:
            text = locales.translate_message(text, language if language in {i['code'] for i in locales.available()} else 'en')
        return text.format(*params)

    def text(self, part, language):
        """A plain string stays as is; a (message, *params) tuple is translated; a dict adds an untranslated suffix."""
        if isinstance(part, dict):
            return self.text(part['message'], language) + part['suffix']
        return part if isinstance(part, str) else self.translate(part[0], language, part[1:])

    def deliver(self, message, only=None):
        """message: title/body keys with params, plus tag/deck/session; sent to every (or one) device."""
        key = self.vapid()
        with self.lock:
            targets = [s for s in self.config['subscriptions'] if only is None or s['id'] == only]
        gone, sent = [], 0
        for subscription in targets:
            language = subscription.get('language', 'en')
            # Short title (the session) that fits a lock-screen line; status and details go to the body.
            payload = {'title': self.text(message['title'], language),
                       'body': '\n'.join(self.text(part, language) for part in message.get('body', ())),
                       'tag': message.get('tag'), 'deck': message.get('deck', ''), 'session': message.get('session', ''),
                       'url': ('/?deck=' + message['deck'] if message.get('deck') else '/') + ('#' + message['session'] if message.get('session') else '')}
            try:
                status = self.sender(key, SUBJECT, subscription, payload, urgency=message.get('urgency', 'normal'))
            except ValueError:
                continue
            if status in (404, 410):
                gone.append(subscription['id'])  # The browser revoked this subscription.
            elif 200 <= status < 300:
                sent += 1
        if gone:
            with self.lock:
                self.config['subscriptions'] = [s for s in self.config['subscriptions'] if s['id'] not in gone]
                self.save()
        return sent

    def test(self, identity):
        if not self.deliver({'title': 'Agent Deck', 'body': [('Уведомления Agent Deck работают',),
                             ('Так будут выглядеть вопросы агентов и завершение работы.',)], 'tag': 'test'}, only=identity):
            raise ValueError('Сервис уведомлений не принял сообщение; включите уведомления заново')

    @staticmethod
    def status_line(message, agent, machine):
        # "Codex ждёт ответа · Mac Studio": the machine only appears for connected computers.
        return {'message': (message, AGENT_LABELS.get(agent, agent or 'Agent')), 'suffix': ' · ' + machine if machine else ''}

    def events(self, now=None):
        """One observation; returns notifications to send. Pure apart from its own memory, for testing."""
        now = self.clock() if now is None else now
        out, pending = [], set()
        if self.config['events'].get('questions') or self.config['events'].get('finished'):
            for q in self.questions():
                pending.add((q.deck, q.session))
                if q.fingerprint not in self.seen and self.config['events'].get('questions'):
                    out.append({'title': q.session, 'body': [self.status_line('{0} ждёт ответа', q.agent, q.origin), q.title[:240]],
                                'tag': f'q-{q.deck}-{q.session}', 'deck': q.deck,
                                'session': q.session, 'urgency': 'high'})
                self.seen[q.fingerprint] = now
        self.seen = {k: t for k, t in self.seen.items() if now - t < 30}
        if not self.warm:
            out = []
        for s in self.sessions():
            key, activity = (s.get('deck', ''), s['name']), s.get('activity')
            state = self.activity.get(key)
            if state is None:
                self.activity[key] = [activity, now, None]
                continue
            if activity != state[0]:
                state[0], state[1] = activity, now
                state[2] = state[2] if state[2] is not None else now
                continue
            idle = IDLE_REMOTE if key[0] else IDLE_LOCAL
            if state[2] is not None and now - state[1] >= idle:
                worked = now - state[2] >= MIN_BUSY
                state[2] = None
                if worked and key not in pending and s.get('agent') != 'shell' and self.config['events'].get('finished'):
                    out.append({'title': s.get('title') or s['name'],
                                'body': [self.status_line('{0} закончил работу', s.get('agent'), s.get('deck_name', ''))],
                                'tag': f'f-{key[0]}-{key[1]}',
                                'deck': key[0], 'session': key[1]})
        self.warm = True
        return out

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        threading.Thread(target=self.loop, name='agent-deck-push', daemon=True).start()

    def loop(self):
        while True:
            time.sleep(3)
            try:
                if not self.config['subscriptions']:
                    continue
                for message in self.events():
                    self.deliver(message)
            except Exception as error:  # A failed tick must not stop notifications; it retries in 3 s.
                print(f'Notification check failed: {error}', flush=True)
