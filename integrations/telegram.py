"""Telegram delivery and authenticated replies; no public webhook or third-party SDK."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import tempfile
import threading
import time
import urllib.error
import urllib.request

try:
    import locales
except ModuleNotFoundError:
    locales = None

from .questions import Question
from .store import Store

TOKEN = re.compile(r"\d{5,20}:[A-Za-z0-9_-]{20,100}")


class TelegramError(RuntimeError):
    def __init__(self, message, delay=5):
        super().__init__(message)
        self.delay = min(120, max(1, delay))


class API:
    def call(self, token, method, **data):
        request = urllib.request.Request(f'https://api.telegram.org/bot{token}/{method}',
            json.dumps(data).encode(), {'Content-Type': 'application/json'})
        try:
            with urllib.request.urlopen(request, timeout=data.get('timeout', 0) + 10) as response:
                payload = json.loads(response.read(1024 * 1024))
        except urllib.error.HTTPError as error:
            try:
                payload = json.loads(error.read(65536))
            except (ValueError, OSError):
                payload = {}
            finally:
                error.close()
            code = error.code
            message = {401: 'Telegram: неверный токен', 403: 'Telegram: откройте чат с ботом и нажмите Start',
                       409: 'Telegram: бот уже используется другим получателем обновлений',
                       429: 'Telegram: слишком много запросов'}.get(code, 'Telegram: запрос не выполнен')
            raise TelegramError(message, payload.get('parameters', {}).get('retry_after', 5)) from None
        except (OSError, ValueError):
            # Never surface urllib's exception: it can contain the token in its URL.
            raise TelegramError('Telegram: нет соединения, повторю автоматически') from None
        if not isinstance(payload, dict) or not payload.get('ok'):
            raise TelegramError('Telegram: запрос не выполнен')
        return payload.get('result')


def atomic_json(path, data):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise ValueError('Integration settings must not be a symlink')
    fd, temporary = tempfile.mkstemp(dir=path.parent)
    try:
        with os.fdopen(fd, 'w') as stream:
            json.dump(data, stream, ensure_ascii=False, indent=2)
        os.replace(temporary, path)
        path.chmod(0o600)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


class Telegram:
    def __init__(self, directory, scan, answer, api=None):
        self.path = Path(directory) / 'telegram.json'
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError('Integration directory must not be a symlink')
        self.directory.chmod(0o700)
        self.scan, self.answer = scan, answer
        self.api = api or API()
        self.lock = threading.RLock()
        self.stop = threading.Event()
        self.error = ''
        self.pair_code = None
        self.pair_deadline = 0
        self.store = None  # SQLite is created only when an integration is configured.
        try:
            self.config = json.loads(self.path.read_text())
        except FileNotFoundError:
            self.config = {}
        self.started = False
        self.seen = {}

    def translate(self, text):
        if locales is None:
            return text
        language = self.config.get('language', os.environ.get('PANEL_LANGUAGE', 'en'))
        if language not in {item['code'] for item in locales.available()}:
            language = 'en'
        return locales.translate_message(text, language)

    def database(self):
        with self.lock:
            if self.store is None:
                self.store = Store(self.directory / 'questions.sqlite3')
            return self.store

    def status(self):
        with self.lock:
            c = self.config
            return {'available': True, 'configured': bool(c.get('token')), 'enabled': c.get('enabled', False),
                    'paired': bool(c.get('user_id')), 'bot': c.get('bot', ''),
                    'account': c.get('account', ''), 'error': self.error,
                    'pair_url': f"https://t.me/{c['bot']}?start=deck_{self.pair_code}"
                    if self.pair_code and time.time() < self.pair_deadline else None}

    def save(self, data):
        if not isinstance(data.get('token', ''), str) or not isinstance(data.get('enabled', True), bool):
            raise ValueError('Неверные настройки Telegram')
        with self.lock:
            if data.get('clear'):
                self.config = {}
                self.pair_code = None
                self.error = ''
                atomic_json(self.path, self.config)
                self.database().reset()
                return self.status()
            token = data.get('token', '').strip() or self.config.get('token', '')
            if not TOKEN.fullmatch(token):
                raise ValueError('Вставьте токен бота из @BotFather')
            bot = self.api.call(token, 'getMe')
            webhook = self.api.call(token, 'getWebhookInfo')
            if webhook.get('url'):
                raise ValueError('У бота уже настроен webhook. Используйте отдельного бота или отключите webhook самостоятельно.')
            if not bot.get('is_bot') or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', bot.get('username', '')):
                raise ValueError('Telegram не вернул имя бота')
            language = data.get('language', self.config.get('language', os.environ.get('PANEL_LANGUAGE', 'en')))
            if locales is not None and language not in {item['code'] for item in locales.available()}:
                raise ValueError('Invalid language')
            changed = token != self.config.get('token')
            if changed:
                self.config = {}
                self.pair_code = None
                self.database().reset()
            self.config.update(language=language)
            self.config.update(token=token, bot=bot['username'], enabled=data.get('enabled', True))
            atomic_json(self.path, self.config)
            self.error = ''
        self.start()
        return self.status()

    def pair(self):
        with self.lock:
            if not self.config.get('token'):
                raise ValueError('Сначала сохраните токен Telegram-бота')
            self.pair_code = secrets.token_urlsafe(24)
            self.pair_deadline = time.time() + 600
            self.config.update(pair_hash=hashlib.sha256(self.pair_code.encode()).hexdigest(),
                               pair_deadline=self.pair_deadline)
            atomic_json(self.path, self.config)
        self.start()
        return self.status()

    def start(self):
        with self.lock:
            if self.started:
                return
            self.started = True
        for worker in (self.poll_loop, self.scan_loop):
            threading.Thread(target=worker, name='agent-deck-telegram', daemon=True).start()

    def eligible(self, c):
        return bool(c.get('token') and c.get('enabled') and c.get('user_id'))

    def poll_loop(self):
        while not self.stop.is_set():
            with self.lock:
                c = self.config.copy()
            if not c.get('token') or not (self.eligible(c) or time.time() < c.get('pair_deadline', 0)):
                self.stop.wait(1)
                continue
            try:
                updates = self.api.call(c['token'], 'getUpdates', offset=self.database().offset(),
                                       timeout=20, allowed_updates=['message', 'callback_query'])
                for update in updates:
                    with self.lock:
                        if c.get('token') != self.config.get('token'):
                            break
                        self.handle(update)
                        self.database().offset(update['update_id'] + 1)
                with self.lock:
                    self.error = ''
            except TelegramError as error:
                with self.lock:
                    self.error = str(error)
                self.stop.wait(error.delay)
            except Exception:
                with self.lock:
                    self.error = 'Telegram: не удалось обработать обновление'
                self.stop.wait(5)

    def scan_loop(self):
        while not self.stop.is_set():
            try:
                self.deliver()
            except TelegramError as error:
                with self.lock:
                    self.error = str(error)
                self.stop.wait(error.delay)
            except Exception:
                with self.lock:
                    self.error = 'Не удалось проверить вопросы агентов; повторю автоматически'
            self.stop.wait(2)

    def deliver(self):
        with self.lock:
            if not self.eligible(self.config):
                return
            questions = self.scan()
            db = self.database()
            now = time.monotonic()
            self.seen.update({q.fingerprint: now for q in questions})
            self.seen = {key: at for key, at in self.seen.items() if now - at < 6}
            for old in db.expire(set(self.seen)):
                if old['message_id']:
                    self.api.call(self.config['token'], 'editMessageReplyMarkup',
                                  chat_id=self.config['chat_id'], message_id=old['message_id'],
                                  reply_markup={'inline_keyboard': []})
            for q in questions:
                row = db.remember(q)
                if row['status'] != 'pending':
                    continue
                options = [f'{i + 1}. {label[:180]}' for i, label in enumerate(q.options)]
                keyboard = [[{'text': f'{i + 1}. {label[:90]}', 'callback_data': f"q:{row['id']}:{i}"}]
                            for i, label in enumerate(q.options)
                            if not re.match(r'(?:Other\b|Type something|Другое\b|Свой ответ)', label, re.I)]
                result = self.api.call(self.config['token'], 'sendMessage', chat_id=self.config['chat_id'],
                    text=f'{q.agent} · {q.session}\n\n{q.title}\n\n' + '\n'.join(options),
                    reply_markup={'inline_keyboard': keyboard})
                db.set_status(row['id'], 'sent', result['message_id'])

    def handle(self, update):
        # Caller holds the integration lock: token/owner cannot change during an answer.
        c = self.config
        message = update.get('message', {})
        chat = message.get('chat', {})
        actor = message.get('from', {})
        text = message.get('text', '')
        if (chat.get('type') == 'private' and isinstance(actor.get('id'), int) and actor['id'] > 0
                and not actor.get('is_bot') and chat.get('id') == actor.get('id') and text.startswith('/start deck_')):
            candidate = text.split(' ', 1)[1].removeprefix('deck_')
            valid = time.time() < c.get('pair_deadline', 0) and hmac.compare_digest(
                hashlib.sha256(candidate.encode()).hexdigest(), c.get('pair_hash', ''))
            if valid:
                self.database().reset()
                c.update(chat_id=chat['id'], user_id=actor['id'], enabled=True,
                         account=actor.get('username') or actor.get('first_name', 'Telegram'),
                         pair_hash='', pair_deadline=0)
                self.pair_code = None
                atomic_json(self.path, c)
                self.api.call(c['token'], 'sendMessage', chat_id=chat['id'],
                              text=self.translate('Agent Deck подключён. Вопросы агентов придут сюда с кнопками ответа.'))
            return
        callback = update.get('callback_query')
        if not callback:
            return
        msg = callback.get('message', {})
        trusted = (self.eligible(c) and callback.get('from', {}).get('id') == c.get('user_id')
                   and msg.get('chat', {}).get('id') == c.get('chat_id')
                   and msg.get('chat', {}).get('type') == 'private')
        result_text = 'Эта кнопка недоступна'
        match = re.fullmatch(r'q:([a-f0-9]{24}):([0-8])', callback.get('data', ''))
        if trusted and match:
            row = self.database().get(match[1])
            if row and row['message_id'] == msg.get('message_id'):
                if row['status'] != 'sent':
                    result_text = 'На этот вопрос уже ответили или он закрыт'
                elif self.database().claim(row['id']):
                    try:
                        q = Question(**{**json.loads(row['payload']), 'options': tuple(json.loads(row['payload'])['options'])})
                        index = int(match[2])
                        if index >= len(q.options):
                            raise ValueError('Неверный вариант ответа')
                        self.answer(q, index)
                    except ValueError as error:
                        self.database().set_status(row['id'], 'sent' if getattr(error, 'retryable', False) else 'expired')
                        result_text = str(error)
                    except Exception:
                        self.database().set_status(row['id'], 'uncertain')
                        result_text = 'Проверьте ответ в панели: повторная отправка отключена'
                    else:
                        self.database().set_status(row['id'], 'answered')
                        result_text = 'Ответ передан агенту'
                    if self.database().get(row['id'])['status'] != 'sent':
                        self.api.call(c['token'], 'editMessageReplyMarkup', chat_id=c['chat_id'],
                                      message_id=msg['message_id'], reply_markup={'inline_keyboard': []})
        self.api.call(c['token'], 'answerCallbackQuery', callback_query_id=callback['id'],
                      text=self.translate(result_text)[:180], show_alert=result_text != 'Ответ передан агенту')
