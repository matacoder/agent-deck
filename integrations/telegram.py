"""Telegram delivery and authenticated replies; no public webhook or third-party SDK."""
import hashlib
import hmac
import json
import os
from pathlib import Path
import re
import secrets
import threading
import time
import urllib.error
import urllib.request

try:
    import locales
except ModuleNotFoundError:
    locales = None

from .questions import Question
from .push import AGENT_LABELS
from .store import Store
from .private_files import write_json

TOKEN = re.compile(r"\d{5,20}:[A-Za-z0-9_-]{20,100}")
# A batch is read up to 1 MB: 100 long messages are more and would be fetched again forever.
UPDATES = 25
FREE_TEXT = re.compile(r'(?:Other\b|Type something|Другое\b|Свой ответ)', re.I)


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
                       409: 'Telegram: этот бот уже получает обновления на другом DeckAway. Отключите Telegram там и подключите тот DeckAway в «Сеть → Другие DeckAway»: его вопросы придут в этот бот',
                       429: 'Telegram: слишком много запросов'}.get(code, 'Telegram: запрос не выполнен')
            raise TelegramError(message, payload.get('parameters', {}).get('retry_after', 5)) from None
        except (OSError, ValueError):
            # Never surface urllib's exception: it can contain the token in its URL.
            raise TelegramError('Telegram: нет соединения, повторю автоматически') from None
        if not isinstance(payload, dict) or not payload.get('ok'):
            raise TelegramError('Telegram: запрос не выполнен')
        return payload.get('result')


def atomic_json(path, data):
    write_json(path, data, ensure_ascii=False, indent=2)


class Telegram:
    def __init__(self, directory, scan, answer, api=None, prompt=None):
        self.path = Path(directory) / 'telegram.json'
        self.directory = Path(directory)
        self.directory.mkdir(mode=0o700, parents=True, exist_ok=True)
        if self.directory.is_symlink():
            raise ValueError('Integration directory must not be a symlink')
        self.directory.chmod(0o700)
        self.scan, self.answer = scan, answer
        self.prompt = prompt  # prompt(deck, session, session_created, text): a reply to "finished" goes to that session.
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
        except (ValueError, OSError):
            self.config = None
        if not isinstance(self.config, dict):
            # A broken file must not block the panel or the «clear» action that rewrites it.
            self.config = {}
            self.error = (f'Telegram settings file {self.path} is unreadable or corrupt; '
                          'save the Telegram settings again or disconnect Telegram to reset it')
        self.started = False
        self.seen = {}

    def language(self):
        language = self.config.get('language', os.environ.get('PANEL_LANGUAGE', 'en'))
        if locales is not None and language not in {item['code'] for item in locales.available()}:
            language = 'en'
        return language

    def translate(self, text):
        return text if locales is None else locales.translate_message(text, self.language())

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
                    'account': c.get('account', ''), 'error': self.error, 'finished': c.get('finished', True),
                    'pair_url': f"https://t.me/{c['bot']}?start=deck_{self.pair_code}"
                    if self.pair_code and time.time() < self.pair_deadline else None}

    def save(self, data):
        if (not isinstance(data.get('token', ''), str) or not isinstance(data.get('enabled', True), bool)
                or not isinstance(data.get('finished', True), bool)):
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
        # Telegram is asked outside the lock: status polls and button taps must not wait for it.
        bot = self.api.call(token, 'getMe')
        webhook = self.api.call(token, 'getWebhookInfo')
        if webhook.get('url'):
            raise ValueError('У бота уже настроен webhook. Используйте отдельного бота или отключите webhook самостоятельно.')
        if not bot.get('is_bot') or not re.fullmatch(r'[A-Za-z0-9_]{5,32}', bot.get('username', '')):
            raise ValueError('Telegram не вернул имя бота')
        with self.lock:
            language = data.get('language', self.config.get('language', os.environ.get('PANEL_LANGUAGE', 'en')))
            if locales is not None and language not in {item['code'] for item in locales.available()}:
                raise ValueError('Invalid language')
            changed = token != self.config.get('token')
            if changed:
                self.config = {}
                self.pair_code = None
                self.database().reset()
            self.config.update(language=language)
            self.config.update(token=token, bot=bot['username'], enabled=data.get('enabled', True),
                               finished=data.get('finished', self.config.get('finished', True)))
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

    def asks_questions(self):
        """Whether an agent's question reaches its owner here, with buttons to answer it."""
        with self.lock:
            return self.eligible(self.config)

    def poll_loop(self):
        while not self.stop.is_set():
            with self.lock:
                c = self.config.copy()
            if not c.get('token') or not (self.eligible(c) or time.time() < c.get('pair_deadline', 0)):
                self.stop.wait(1)
                continue
            try:
                updates = self.api.call(c['token'], 'getUpdates', offset=self.database().offset(),
                                       timeout=20, limit=UPDATES, allowed_updates=['message', 'callback_query'])
                problem = ''
                for update in updates:
                    with self.lock:
                        if c.get('token') != self.config.get('token'):
                            break
                    # Not under the lock: an answer to a connected computer takes seconds, and status
                    # and settings requests must not wait for it.
                    try:
                        problem = self.handle(update) or problem
                    except TelegramError as error:
                        problem = str(error)
                    except Exception:
                        problem = 'Telegram: не удалось обработать обновление'
                    # Always advance: a failing update would otherwise be re-fetched forever.
                    # Dropping it is safe because claim-before-input prevents double answers.
                    self.database().offset(update['update_id'] + 1)
                with self.lock:
                    self.error = problem
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
        # Connected DeckAway scans take network time; never hold the lock that answers button taps.
        questions = self.scan()
        with self.lock:
            if not self.eligible(self.config):
                return
            db = self.database()
            now = time.monotonic()
            self.seen.update({q.fingerprint: now for q in questions})
            self.seen = {key: at for key, at in self.seen.items() if now - at < 6}
            # Open rows get a 6 s grace for redraw flicker. Closed rows retire after ~2 missed scans
            # (scans run every 2 s), so one flickering scan never re-sends an answered prompt.
            recent = {key for key, at in self.seen.items() if now - at < 3}
            token, chat = self.config['token'], self.config['chat_id']
            closed = [old['message_id'] for old in db.expire(set(self.seen), recent) if old['message_id']]
            waiting = [(row['id'], q) for row, q in ((db.remember(q), q) for q in questions) if row['status'] == 'pending']
        # Sent outside the lock, like the scan: a slow Telegram must not hold button taps and status polls.
        for message_id in closed:
            self.api.call(token, 'editMessageReplyMarkup', chat_id=chat, message_id=message_id,
                          reply_markup={'inline_keyboard': []})
        for row_id, q in waiting:
            options = [f'{i + 1}. {label[:180]}' for i, label in enumerate(q.options)]
            keyboard = [[{'text': f'{i + 1}. {label[:90]}', 'callback_data': f"q:{row_id}:{i}"}]
                        for i, label in enumerate(q.options)
                        if not FREE_TEXT.match(label)]
            hint = ('\n\n' + self.translate('Свой ответ: ответьте на это сообщение текстом')
                    if any(FREE_TEXT.match(label) for label in q.options) else '')
            result = self.api.call(token, 'sendMessage', chat_id=chat,
                # The chat list shows only the first words: the question, then where it comes from.
                text=f'{q.title}\n\n' + '\n'.join(options) + '\n\n' + ' · '.join(filter(None, (q.label or q.session, q.origin, q.agent))) + hint,
                reply_markup={'inline_keyboard': keyboard})
            with self.lock:
                if self.config.get('token') == token:  # Not a bot that was replaced meanwhile.
                    self.database().set_status(row_id, 'sent', result['message_id'])

    def wants_finished(self):
        with self.lock:
            return self.eligible(self.config) and self.config.get('finished', True)

    def finished(self, message):
        """Says that a session finished working; a reply to this message is the next prompt for that session."""
        with self.lock:
            c = self.config.copy()
        if not self.eligible(c) or not c.get('finished', True):
            return
        label = AGENT_LABELS.get(message.get('agent'), message.get('agent') or 'Agent')
        # What was done, in the session's own summary, when a model of its provider could write one.
        summary = (message.get('summaries') or {}).get(self.language()) or {}
        told = summary.get('done') or summary.get('line') or self.translate('{0} закончил работу').format(label)
        # Short enough to read in the chat list: what happened, then where. That a reply is the next prompt
        # is said once, in Settings, not under every message.
        text = told + '\n\n' + ' · '.join(filter(None, (summary.get('title') or message['title'], message.get('origin'), label)))
        try:
            result = self.api.call(c['token'], 'sendMessage', chat_id=c['chat_id'], text=text)
            self.database().notice(result['message_id'], message.get('deck', ''), message['session'],
                                   int(message.get('created') or 0))
        except (TelegramError, KeyError, TypeError) as error:
            with self.lock:  # Shown in Settings; the next finished session tries again.
                self.error = str(error) if isinstance(error, TelegramError) else 'Telegram: не удалось обработать обновление'

    def handle(self, update):
        message = update.get('message', {})
        chat = message.get('chat', {})
        actor = message.get('from', {})
        text = message.get('text', '')
        if (chat.get('type') == 'private' and isinstance(actor.get('id'), int) and actor['id'] > 0
                and not actor.get('is_bot') and chat.get('id') == actor.get('id') and text.startswith('/start deck_')):
            with self.lock:  # Pairing changes the owner: nothing else may read the config meanwhile.
                return self.handle_pairing(chat, actor, text)
        # Answers use a snapshot: the owner checked here is the one the answer is bound to; the
        # database claim, not the lock, is what prevents a second answer.
        with self.lock:
            c = self.config.copy()
        if message.get('reply_to_message') and text:
            return self.handle_reply(c, message, chat, actor, text)
        return self.handle_callback(c, update.get('callback_query'))

    def handle_pairing(self, chat, actor, text):
        c = self.config
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
                          text=self.translate('DeckAway подключён. Вопросы агентов придут сюда с кнопками ответа.'))

    def handle_callback(self, c, callback):
        if not callback:
            return
        msg = callback.get('message', {})
        trusted = (self.eligible(c) and callback.get('from', {}).get('id') == c.get('user_id')
                   and msg.get('chat', {}).get('id') == c.get('chat_id')
                   and msg.get('chat', {}).get('type') == 'private')
        result_text = 'Эта кнопка недоступна'
        problem = ''
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
                        problem = self.notify(c['token'], 'editMessageReplyMarkup', chat_id=c['chat_id'],
                                              message_id=msg['message_id'], reply_markup={'inline_keyboard': []})
        return self.notify(c['token'], 'answerCallbackQuery', callback_query_id=callback['id'],
                           text=self.translate(result_text)[:180],
                           show_alert=result_text != 'Ответ передан агенту') or problem

    def handle_reply(self, c, message, chat, actor, text):
        """A reply to a question message answers its "Other / Type something" option with that text."""
        if not (self.eligible(c) and chat.get('type') == 'private' and actor.get('id') == c.get('user_id')
                and chat.get('id') == c.get('chat_id')) or text.startswith('/'):
            return
        notice = self.database().notice_by_message(message['reply_to_message'].get('message_id'))
        if notice:
            return self.notify(c['token'], 'sendMessage', chat_id=c['chat_id'], text=self.translate(self.send_prompt(notice, text)),
                               reply_to_message_id=message.get('message_id'))
        row = self.database().by_message(message['reply_to_message'].get('message_id'))
        reply = 'Этот вопрос не найден или уже закрыт'
        if row and row['status'] == 'sent':
            payload = json.loads(row['payload'])
            q = Question(**{**payload, 'options': tuple(payload['options'])})
            index = next((i for i, label in enumerate(q.options) if FREE_TEXT.match(label)), None)
            if index is None:
                reply = 'У этого вопроса нет варианта для своего ответа; нажмите кнопку'
            elif len(text) > 4000:
                reply = 'Ответ длиннее 4000 символов'
            elif self.database().claim(row['id']):
                reply = self.answer_claimed(row, q, index, text)
                if self.database().get(row['id'])['status'] != 'sent' and row['message_id']:
                    self.notify(c['token'], 'editMessageReplyMarkup', chat_id=c['chat_id'], message_id=row['message_id'],
                                reply_markup={'inline_keyboard': []})
        return self.notify(c['token'], 'sendMessage', chat_id=c['chat_id'], text=self.translate(reply),
                           reply_to_message_id=message.get('message_id'))

    def send_prompt(self, notice, text):
        # Each Telegram update is handled once, so an unknown failure is reported and never typed again.
        if self.prompt is None:
            return 'Отправка сообщений из Telegram недоступна'
        if len(text) > 4000:
            return 'Сообщение длиннее 4000 символов'
        try:
            self.prompt(notice['deck'], notice['session'], notice['session_created'], text)
        except ValueError as error:
            return str(error)
        except Exception:
            return 'Проверьте сессию в панели: повторная отправка отключена'
        return 'Сообщение передано агенту'

    def answer_claimed(self, row, q, index, text=None):
        # Same outcomes as a button: retryable errors reopen, others close; unknown failures never replay.
        try:
            self.answer(q, index, text) if text is not None else self.answer(q, index)
        except ValueError as error:
            self.database().set_status(row['id'], 'sent' if getattr(error, 'retryable', False) else 'expired')
            return str(error)
        except Exception:
            self.database().set_status(row['id'], 'uncertain')
            return 'Проверьте ответ в панели: повторная отправка отключена'
        self.database().set_status(row['id'], 'answered')
        return 'Ответ передан агенту'

    def notify(self, token, method, **data):
        # Cosmetic UI calls: the answer state is already final, so a failure is reported, not raised.
        try:
            self.api.call(token, method, **data)
        except TelegramError as error:
            return str(error)
        return ''
