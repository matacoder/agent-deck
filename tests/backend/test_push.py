import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

from support import ROOT, PanelCase, require_crypto
sys.path.insert(0, str(ROOT))
from integrations import webpush as W
from integrations.push import Push
from integrations.questions import Question

ENDPOINT = 'https://web.push.apple.com/QGuUj3dB-test'


def device_keys():
    receiver = W.private_key()
    return receiver, {'p256dh': W.b64url(W.public_bytes(receiver)), 'auth': W.b64url(b'0123456789abcdef')}


class WebPushTests(unittest.TestCase):
    def setUp(self):
        require_crypto(self)

    def test_rfc8291_example_encrypts_byte_for_byte(self):
        u = W.unb64url
        sender = W.private_key(u('yfWPiYE-n46HLnH0KqZOF1fJJU3MYrct3AELtAQ-oRw'))
        receiver_public = u('BCVxsr7N_eNgVRqvHtD0zTZsEc6-VV-JvLexhqUzORcxaOzi6-AYWXvTBHm4bjyPjs7Vd8pZGH6SRpkNtoIAiw4')
        body = W.encrypt(u('V2hlbiBJIGdyb3cgdXAsIEkgd2FudCB0byBiZSBhIHdhdGVybWVsb24'), receiver_public,
                         u('BTBZMqHH6r4Tts7J_aSIgg'), sender=sender, salt=u('DGv6ra1nlYgDCS1FRnbzlw'))
        self.assertEqual(W.b64url(body), 'DGv6ra1nlYgDCS1FRnbzlwAAEABBBP4z9KsN6nGRTbVYI_c7VJSPQTBtkgcy27mlmlMoZIIgDll6e3vCYLocInmYWAmS6TlzAC8wEqKK6PBru3jl7A_yl95bQpu6cVPTpK4Mqgkf1CXztLVBSt2Ks3oZwbuwXPXLWyouBWLVWGNWQexSgSxsj_Qulcy4a-fN')

    def test_off_curve_device_key_is_rejected(self):
        bad = b'\x04' + bytes(64)
        with self.assertRaises(ValueError):
            W.encrypt(b'x', bad, bytes(16))

    def test_vapid_token_is_a_valid_es256_signature_for_the_push_origin(self):
        from cryptography.hazmat.primitives import hashes
        from cryptography.hazmat.primitives.asymmetric import ec
        from cryptography.hazmat.primitives.asymmetric.utils import encode_dss_signature
        key = W.private_key()
        header = W.vapid_header(key, ENDPOINT, 'https://example.test', now=1000)
        token, public = header.removeprefix('vapid t=').split(', k=')
        signing, signature = token.rsplit('.', 1)
        raw = W.unb64url(signature)
        der = encode_dss_signature(int.from_bytes(raw[:32], 'big'), int.from_bytes(raw[32:], 'big'))
        ec.EllipticCurvePublicKey.from_encoded_point(ec.SECP256R1(), W.unb64url(public)).verify(der, signing.encode(), ec.ECDSA(hashes.SHA256()))
        claims = json.loads(W.unb64url(signing.split('.')[1]))
        self.assertEqual(claims, {'aud': 'https://web.push.apple.com', 'exp': 1000 + 12 * 3600, 'sub': 'https://example.test'})

    def test_only_known_push_services_are_contacted(self):
        for url in (ENDPOINT, 'https://fcm.googleapis.com/fcm/send/x', 'https://updates.push.services.mozilla.com/wpush/v2/x',
                    'https://db5p.notify.windows.com/w/?token=x'):
            self.assertTrue(W.allowed_endpoint(url), url)
        for url in ('http://web.push.apple.com/x', 'https://evil.example/x', 'https://push.apple.com.evil.example/x',
                    'https://user:pw@web.push.apple.com/x', 'https://web.push.apple.com:8443/x', 'https://127.0.0.1/x', None):
            self.assertFalse(W.allowed_endpoint(url), url)

    def test_send_posts_encrypted_payload_with_vapid_and_reports_status(self):
        _, keys = device_keys()
        captured = []

        class Response:
            status = 201
            def __enter__(self): return self
            def __exit__(self, *args): return False
        def opener(request, timeout):
            captured.append(request)
            return Response()
        status = W.send(W.private_key(), 'https://example.test', {'endpoint': ENDPOINT, 'keys': keys},
                        {'title': 'secret question'}, urgency='high', opener=opener)
        self.assertEqual(status, 201)
        request = captured[0]
        self.assertEqual(request.get_header('Content-encoding'), 'aes128gcm')
        self.assertEqual(request.get_header('Urgency'), 'high')
        self.assertTrue(request.get_header('Authorization').startswith('vapid t='))
        self.assertNotIn(b'secret question', request.data)
        with self.assertRaises(ValueError):
            W.send(W.private_key(), 'x', {'endpoint': 'https://evil.example/x', 'keys': keys}, {}, opener=opener)


def question(session='api', deck='', title='Proceed?', origin=''):
    return Question(session, 'claude', '%1', title, ('Yes', 'No'), 0, deck=deck, origin=origin)


class PushServiceTests(unittest.TestCase):
    def setUp(self):
        require_crypto(self)
        tmp = tempfile.TemporaryDirectory(dir='/tmp')
        self.addCleanup(tmp.cleanup)
        self.sessions, self.questions = [], []
        self.sent = []
        self.status = 201
        def sender(key, subject, subscription, payload, urgency='normal'):
            self.sent.append((subscription['id'], payload, urgency))
            return self.status
        self.push = Push(Path(tmp.name), lambda: self.sessions, lambda: self.questions, sender=sender)

    def subscribe(self, endpoint=ENDPOINT, language='en'):
        _, keys = device_keys()
        return self.push.subscribe({'subscription': {'endpoint': endpoint, 'keys': keys}, 'label': 'iPhone', 'language': language})['id']

    def test_subscriptions_are_validated_private_and_deduplicated_by_endpoint(self):
        first = self.subscribe()
        second = self.subscribe()
        self.assertEqual([d['id'] for d in self.push.status()['devices']], [second])
        self.assertNotEqual(first, second)
        self.assertEqual(self.push.path.stat().st_mode & 0o777, 0o600)
        self.assertNotIn('endpoint', json.dumps(self.push.status()))
        for bad in ({'endpoint': 'https://evil.example/x', 'keys': device_keys()[1]},
                    {'endpoint': ENDPOINT, 'keys': {'p256dh': W.b64url(b'\x04' + bytes(64)), 'auth': W.b64url(bytes(16))}},
                    {'endpoint': ENDPOINT, 'keys': {'p256dh': device_keys()[1]['p256dh'], 'auth': 'short'}}):
            with self.assertRaises(ValueError):
                self.push.subscribe({'subscription': bad})

    def test_question_is_announced_once_after_warm_up_and_names_the_machine(self):
        self.questions = [question('old')]
        self.assertEqual(self.push.events(now=0), [])  # Pending before a restart: not re-announced.
        self.questions = [question('old'), question('api', deck='a' * 24, origin='Mac Studio')]
        [message] = self.push.events(now=3)
        self.assertEqual(message['title'], 'api')
        self.assertEqual(message['body'][1], 'Proceed?')
        self.assertEqual((message['deck'], message['urgency']), ('a' * 24, 'high'))
        self.assertEqual(self.push.events(now=6), [])

    def test_a_renamed_session_is_announced_by_its_new_name_without_a_new_fingerprint(self):
        from dataclasses import replace
        self.push.events(now=0)
        original = question('api')
        renamed = replace(original, label='Billing API')
        self.assertEqual(renamed.fingerprint, original.fingerprint)  # Renaming never re-announces a question.
        self.questions = [renamed]
        [message] = self.push.events(now=3)
        self.assertEqual(message['title'], 'Billing API')
        self.assertEqual(message['session'], 'api')  # Opening the notification still finds the tmux session.

    def test_finished_needs_real_work_then_quiet_and_skips_shells_and_pending_questions(self):
        self.push.events(now=0)
        def tick(now, activity, **extra):
            self.sessions = [{'name': 'api', 'title': 'API', 'agent': 'claude', 'activity': activity, **extra}]
            return self.push.events(now=now)
        tick(0, 1)
        tick(3, 2)          # Burst starts.
        self.assertEqual(tick(12, 2), [])  # Quiet but worked only 3 s.
        tick(20, 3); tick(45, 4)
        [done] = tick(54, 4)
        self.assertEqual(done['title'], 'API')
        tick(60, 5); tick(90, 6)
        self.questions = [question('api')]
        self.push.seen[self.questions[0].fingerprint] = 90
        self.assertEqual(tick(100, 6), [])  # A pending question already says it is waiting.
        self.questions = []
        self.sessions = [{'name': 'sh', 'agent': 'shell', 'activity': 1}]
        self.push.events(now=100)
        self.sessions = [{'name': 'sh', 'agent': 'shell', 'activity': 2}]; self.push.events(now=101)
        self.sessions = [{'name': 'sh', 'agent': 'shell', 'activity': 3}]; self.push.events(now=130)
        self.assertEqual(self.push.events(now=140), [])

    def test_remote_sessions_wait_longer_before_finished(self):
        self.push.events(now=0)
        remote = lambda activity: [{'name': 'ml', 'deck': 'b' * 24, 'deck_name': 'Mac', 'agent': 'codex', 'activity': activity}]
        self.sessions = remote(1); self.push.events(now=0)
        self.sessions = remote(2); self.push.events(now=1)
        self.sessions = remote(3); self.push.events(now=30)
        self.assertEqual(self.push.events(now=40), [])
        [done] = self.push.events(now=56)
        self.assertEqual(done['title'], 'ml')

    def test_delivery_translates_per_device_and_forgets_revoked_devices(self):
        ru, en = self.subscribe(language='ru'), self.subscribe(endpoint=ENDPOINT + '2', language='en')
        self.push.deliver({'title': 'api-tests', 'body': [self.push.status_line('{0} ждёт ответа', 'codex', 'Mac Studio'), 'Run tests?'],
                           'session': 'api', 'deck': 'a' * 24})
        payloads = {identity: payload for identity, payload, _ in self.sent}
        # The title is just the session so it fits; status and question go to the body.
        self.assertEqual(payloads[ru]['title'], 'api-tests')
        self.assertEqual(payloads[ru]['body'], 'Codex ждёт ответа · Mac Studio\nRun tests?')
        self.assertEqual(payloads[en]['body'], 'Codex is waiting for an answer · Mac Studio\nRun tests?')
        self.assertEqual(payloads[en]['url'], '/?deck=' + 'a' * 24 + '#api')
        self.status = 410
        self.push.deliver({'title': 'api'})
        self.assertEqual(self.push.status()['devices'], [])

    def test_a_message_waits_while_encryption_is_not_ready_and_failures_do_not_drop_others(self):
        self.subscribe()
        ready = [False]
        vapid = self.push.vapid
        def gated():
            if not ready[0]:
                raise ValueError('Компоненты шифрования ещё не установлены')
            return vapid()
        self.push.vapid = gated
        self.push.send_all([{'title': 'api'}, {'title': 'web'}], now=0)
        self.assertEqual(self.sent, [])
        ready[0] = True
        self.push.send_all([], now=60)
        self.assertEqual([payload['title'] for _, payload, _ in self.sent], ['api', 'web'])
        ready[0] = False
        self.push.send_all([{'title': 'late'}], now=100)
        ready[0] = True
        self.push.send_all([], now=100 + 601)  # Too old to be useful: dropped.
        self.assertEqual(len(self.sent), 2)

    def test_events_can_be_turned_off(self):
        self.push.set_events({'questions': False, 'finished': 'nope'})
        self.assertEqual(self.push.status()['events'], {'questions': False, 'finished': True})
        self.push.events(now=0)
        self.questions = [question()]
        self.assertEqual(self.push.events(now=3), [])


class PanelPushTests(PanelCase):
    def test_service_worker_is_public_javascript_and_settings_require_login(self):
        import threading
        from unittest.mock import patch
        self.enterContext(patch.object(self.panel.Handler, 'log_message'))
        server = self.panel.ThreadingHTTPServer(('127.0.0.1', 0), self.panel.Handler)
        threading.Thread(target=server.serve_forever, daemon=True).start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        import http.client
        def get(path):
            connection = http.client.HTTPConnection(*server.server_address, timeout=5)
            connection.request('GET', path)
            response = connection.getresponse()
            body = response.read(); connection.close()
            return response.status, response.getheader('Content-Type'), body
        status, ctype, body = get('/sw.js')
        self.assertEqual(status, 200)
        self.assertTrue(ctype.startswith('application/javascript'))
        self.assertIn(b"addEventListener('push'", body)
        self.assertEqual(get('/api/push')[0], 401)
