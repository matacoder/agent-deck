import base64
import io
import json
from pathlib import Path
import sys
import tarfile
import tempfile
import unittest
from unittest.mock import patch
import unittest.mock

from support import ROOT, PanelCase, require_crypto
sys.path.insert(0, str(ROOT))
from integrations import backups as B


def machine(test, name='alpha'):
    tmp = tempfile.TemporaryDirectory(dir='/tmp')
    test.addCleanup(tmp.cleanup)
    home = Path(tmp.name)
    (home / '.config/cc-panel/integrations').mkdir(parents=True)
    (home / '.config/cc-panel/kimi.json').write_text('{"key":"kimi-secret"}')
    (home / '.config/cc-panel/integrations/telegram.json').write_text('{"token":"tg"}')
    (home / '.codex').mkdir()
    (home / '.codex/auth.json').write_text('{"tokens":"codex"}')
    (home / '.config/cc-panel/env').write_text('PANEL_PASSWORD=never-backed-up\n')
    return B.Backups(home, lambda: '1.5.0', lambda: name)


class CryptoTests(unittest.TestCase):
    def setUp(self):
        require_crypto(self)

    def test_recovery_code_round_trips_and_rejects_typos(self):
        key = bytes(range(32))
        code = B.encode_code(key)
        self.assertTrue(code.startswith('AD1-'))
        self.assertEqual(B.decode_code(code.lower().replace('-', ' ')), key)
        broken = code[:-1] + ('A' if code[-1] != 'A' else 'B')
        for bad in (broken, 'AD1-XXXX', '', None):
            with self.assertRaises(ValueError):
                B.decode_code(bad)

    def test_sealed_backup_hides_content_and_detects_tampering_or_wrong_key(self):
        key, other = bytes(32), bytes([1]) * 32
        blob = B.seal(key, {'origin': 'a' * 24, 'created': 1, 'name': 'alpha'}, b'kimi-secret' * 20)
        self.assertNotIn(b'kimi-secret', blob)
        self.assertEqual(B.unseal(key, blob)[1], b'kimi-secret' * 20)
        meta, offset = B.read_meta(blob)
        self.assertEqual((meta['origin'], meta['key_id']), ('a' * 24, B.key_id(key)))
        for position in (offset + 30, len(blob) - 1, len(B.MAGIC) + 8):
            tampered = bytearray(blob); tampered[position] ^= 1
            with self.assertRaises(ValueError):
                B.unseal(key, bytes(tampered))
        with self.assertRaisesRegex(ValueError, 'другим кодом'):
            B.unseal(other, blob)
        with self.assertRaises(ValueError):
            B.read_meta(b'not a backup')
        self.assertTrue(blob.startswith(b'ADBK2\n'))

    def test_backups_written_by_1_5_0_still_restore(self):
        key = bytes(range(32))
        header = json.dumps({'origin': 'a' * 24, 'created': 1, 'name': 'old', 'key_id': B.key_id(key)},
                            sort_keys=True, separators=(',', ':')).encode()
        nonce, data = bytes(24), b'legacy settings'
        signed = B.LEGACY_MAGIC + len(header).to_bytes(4, 'big') + header + nonce + B._keystream_xor(B._derive(key, b'adbk-enc'), nonce, data)
        legacy = signed + B.hashlib.blake2b(signed, key=B._derive(key, b'adbk-mac'), digest_size=32).digest()
        self.assertEqual(B.unseal(key, legacy)[1], data)
        with self.assertRaisesRegex(ValueError, 'изменён'):
            B.unseal(key, legacy[:-1] + bytes([legacy[-1] ^ 1]))


class BackupTests(unittest.TestCase):
    def setUp(self):
        require_crypto(self)

    def test_setup_once_creates_private_key_and_returns_code_only_then(self):
        alpha = machine(self)
        result = alpha.setup()
        self.assertIn('code', result)
        self.assertEqual(alpha.key_path.stat().st_mode & 0o777, 0o600)
        with self.assertRaises(ValueError):
            alpha.setup()
        self.assertNotIn('code', json.dumps(alpha.status()))
        beta = machine(self, 'beta')
        self.assertEqual(beta.setup(result['code'])['key_id'], result['key_id'])

    def test_backup_contains_whitelisted_files_only_and_skips_symlinks(self):
        alpha = machine(self)
        alpha.setup()
        (alpha.home / '.config/gh').mkdir(parents=True)
        (alpha.home / '.config/gh/hosts.yml').symlink_to(alpha.home / '.config/cc-panel/env')
        blob = alpha.create()
        files = B.unpack(B.unseal(alpha.key(), blob)[1])
        self.assertEqual(set(files), {'deck/kimi.json', 'deck/telegram.json', 'agents/codex-auth.json', 'deck/instance-id'})
        self.assertNotIn(b'never-backed-up', b''.join(files.values()))
        stored = alpha.store_dir / B.read_meta(blob)[0]['origin']
        self.assertEqual(stored.stat().st_mode & 0o777, 0o700)
        self.assertTrue(all(p.stat().st_mode & 0o777 == 0o600 for p in stored.iterdir()))

    def test_retention_keeps_the_newest_copies_per_machine(self):
        alpha = machine(self); alpha.setup()
        for created in range(B.KEEP + 3):
            with patch.object(B.time, 'time', return_value=1000 + created):
                alpha.create()
        names = sorted(p.name for p in (alpha.store_dir / alpha.instance_id()).iterdir())
        self.assertEqual(len(names), B.KEEP)
        self.assertEqual(names[0], f'{1000 + 3}.adbk')

    def test_restore_on_a_new_machine_writes_only_known_destinations_and_keeps_identity(self):
        alpha = machine(self); code = alpha.setup()['code']
        blob = alpha.create()
        fresh = machine(self, 'fresh')
        (fresh.home / '.codex/auth.json').unlink()
        with self.assertRaisesRegex(ValueError, 'код восстановления'):
            fresh.restore(blob)
        result = fresh.restore(blob, code)
        self.assertIn('agents/codex-auth.json', result['files'])
        self.assertEqual((fresh.home / '.codex/auth.json').read_text(), '{"tokens":"codex"}')
        self.assertEqual((fresh.home / '.codex/auth.json').stat().st_mode & 0o777, 0o600)
        self.assertEqual(fresh.instance_id(), alpha.instance_id())
        self.assertEqual(fresh.key(), alpha.key())

    def test_restore_first_backs_up_the_state_it_replaces(self):
        alpha = machine(self); alpha.setup()
        blob = alpha.create()
        (alpha.home / '.config/cc-panel/kimi.json').write_text('{"key":"newer"}')
        with patch.object(B.time, 'time', return_value=4_000_000_000):
            alpha.restore(blob)
        safety = B.unpack(B.unseal(alpha.key(), alpha.read(alpha.instance_id(), 4_000_000_000))[1])
        self.assertEqual(safety['deck/kimi.json'], b'{"key":"newer"}')
        self.assertEqual((alpha.home / '.config/cc-panel/kimi.json').read_text(), '{"key":"kimi-secret"}')

    def test_archive_with_unexpected_paths_is_rejected_even_with_a_valid_tag(self):
        alpha = machine(self); alpha.setup()
        buffer = io.BytesIO()
        with tarfile.open(fileobj=buffer, mode='w:gz') as archive:
            info = tarfile.TarInfo('../../.bashrc'); data = b'evil'; info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
        blob = B.seal(alpha.key(), {'origin': 'b' * 24, 'created': 5, 'name': 'x'}, buffer.getvalue())
        with self.assertRaisesRegex(ValueError, 'неожиданный файл'):
            alpha.restore(blob)
        self.assertFalse((alpha.home.parent / '.bashrc').exists() and (alpha.home.parent / '.bashrc').read_bytes() == b'evil')

    def test_storage_is_bounded_in_machines(self):
        alpha = machine(self); alpha.setup()
        with patch.object(B, 'MAX_ORIGINS', 2):
            for origin in ('1' * 24, '2' * 24):
                alpha.store(B.seal(alpha.key(), {'origin': origin, 'created': 1, 'name': 'x'}, b''))
            alpha.store(B.seal(alpha.key(), {'origin': '1' * 24, 'created': 2, 'name': 'x'}, b''))
            with self.assertRaisesRegex(ValueError, 'Слишком много'):
                alpha.store(B.seal(alpha.key(), {'origin': '3' * 24, 'created': 1, 'name': 'x'}, b''))

    def test_reading_and_storing_validate_identifiers_and_format(self):
        alpha = machine(self); alpha.setup()
        for origin, created in (('../x', 1), ('a' * 24, '1'), ('A' * 24, 1)):
            with self.assertRaises(ValueError):
                alpha.read(origin, created)
        with self.assertRaises(ValueError):
            alpha.store(b'garbage')


class FakeDecks:
    """Connected machines answering the backup API like a remote panel would."""
    def __init__(self, test, **machines):
        self.machines = machines
        self.ids = {name: (str(i) * 24)[:24] for i, name in enumerate(machines, 1)}
        self.calls = []

    def status(self):
        return {'decks': [{'id': self.ids[n], 'name': n} for n in self.machines]}

    def request(self, deck, method, path, body=None, timeout=30):
        name = next(n for n, i in self.ids.items() if i == deck)
        target = self.machines[name]
        self.calls.append((name, method, path))
        if target is None:
            return 404, {}, b'{"error":"not found"}'
        data = json.loads(body) if body else {}
        try:
            if path == '/api/backups':
                result = target.status()
            elif path == '/api/backup_setup':
                result = target.setup(data['code'])
            elif path == '/api/backup_now':
                result = {'blob': base64.b64encode(target.create()).decode()}
            elif path == '/api/backup_store':
                result = {'meta': target.store(base64.b64decode(data['blob']))}
            else:
                return 404, {}, b'{}'
        except ValueError as error:
            return 400, {}, json.dumps({'error': str(error)}).encode()
        return 200, {}, json.dumps(result).encode()


class ReplicationTests(unittest.TestCase):
    def setUp(self):
        require_crypto(self)

    def test_gateway_shares_its_key_and_every_machine_holds_every_other_backup(self):
        gateway, mac, server = machine(self, 'gw'), machine(self, 'mac'), machine(self, 'server')
        gateway.setup()
        report = B.replicate(gateway, FakeDecks(self, mac=mac, server=server))
        self.assertTrue(all(m['ok'] for m in report['machines']), report)
        everyone = {gateway.instance_id(), mac.instance_id(), server.instance_id()}
        for each in (gateway, mac, server):
            self.assertEqual({m['origin'] for m in each.stored()}, everyone)
            self.assertEqual(each.key(), gateway.key())

    def test_machine_with_another_key_or_old_release_is_reported_not_overwritten(self):
        gateway, other = machine(self, 'gw'), machine(self, 'other')
        gateway.setup(); other.setup()
        other_key = other.key()
        report = B.replicate(gateway, FakeDecks(self, other=other, old=None))
        errors = {m['name']: m.get('error', '') for m in report['machines']}
        self.assertIn('другим кодом', errors['other'])
        self.assertIn('Обновите', errors['old'])
        self.assertEqual(other.key(), other_key)
        self.assertEqual([m['origin'] for m in gateway.stored()], [gateway.instance_id()])
        self.assertEqual(gateway.status()['report']['machines'][0]['ok'], False)


class PanelBackupTests(PanelCase):
    def setUp(self):
        super().setUp()
        require_crypto(self)

    def test_a_machine_refuses_to_store_a_foreign_copy_of_itself_and_restore_restarts(self):
        alpha = machine(self)
        alpha.setup()
        blob = alpha.create()
        with patch.object(self.panel, 'backup_service', return_value=alpha), \
             patch.object(self.panel, 'restart_soon') as restart:
            with self.assertRaisesRegex(ValueError, 'сама хранит'):
                self.panel.action_backup_store({'blob': base64.b64encode(blob).decode()})
            meta = B.read_meta(blob)[0]
            result = self.panel.action_backup_restore({'origin': meta['origin'], 'created': meta['created']})
            self.assertIn('deck/kimi.json', result['restored']['files'])
            restart.assert_called_once()

    def test_cycle_replicates_only_when_other_machines_are_connected(self):
        with patch.object(self.panel, 'backup_service') as service, \
             patch('integrations.backups.replicate', return_value={'machines': []}) as replicate, \
             patch.object(self.panel, 'remote_decks') as decks:
            decks.status.return_value = {'decks': []}
            self.panel.run_backups()
            service.return_value.create.assert_called_once()
            replicate.assert_not_called()
            decks.status.return_value = {'decks': [{'id': 'a' * 24}]}
            self.panel.run_backups()
            replicate.assert_called_once()


class MacKeychainTests(unittest.TestCase):
    def setUp(self):
        require_crypto(self)

    def mac(self, name, stored=b'{"claudeAiOauth":{"accessToken":"keychain-secret"}}', writes=None, ok=True):
        base = machine(self, name)
        writes = writes if writes is not None else []
        def write(data):
            writes.append(data)
            return ok
        return B.Backups(base.home, lambda: '1.9.0', lambda: name, platform='darwin', keychain=(lambda: stored, write)), writes

    def test_mac_backup_takes_the_claude_login_from_the_keychain(self):
        alpha, _ = self.mac('alpha')
        alpha.setup()
        files = B.unpack(B.unseal(alpha.key(), alpha.create())[1])
        self.assertEqual(files['agents/claude-credentials.json'], b'{"claudeAiOauth":{"accessToken":"keychain-secret"}}')

    def test_mac_restore_returns_the_login_to_the_keychain_without_a_plaintext_file(self):
        alpha, _ = self.mac('alpha')
        code = alpha.setup()['code']
        blob = alpha.create()
        fresh, writes = self.mac('fresh', stored=None)
        result = fresh.restore(blob, code)
        self.assertEqual(writes, [b'{"claudeAiOauth":{"accessToken":"keychain-secret"}}'])
        self.assertFalse((fresh.home / '.claude/.credentials.json').exists())
        self.assertEqual(result['warnings'], [])
        broken, _ = self.mac('broken', stored=None, ok=False)
        self.assertIn('Claude', broken.restore(blob, code)['warnings'][0])

    def test_linux_restore_of_a_mac_backup_writes_the_credentials_file(self):
        alpha, _ = self.mac('alpha')
        code = alpha.setup()['code']
        linux = machine(self, 'linux')
        linux.restore(alpha.create(), code)
        self.assertEqual((linux.home / '.claude/.credentials.json').stat().st_mode & 0o777, 0o600)

    def test_keychain_commands_keep_the_secret_out_of_argv(self):
        seen = []
        run = lambda args, **kw: seen.append((args, kw.get('input'))) or unittest.mock.Mock(returncode=0, stdout=b'secret\n')
        self.assertEqual(B.keychain_read(run=run), b'secret')
        self.assertTrue(B.keychain_write(b'{"t":"secret"}', run=run, account='dev'))
        args, stdin = seen[-1]
        self.assertEqual(args, ['security', '-i'])
        self.assertNotIn(b'secret', b' '.join(a.encode() for a in args))
        self.assertIn(b'-X ' + b'{"t":"secret"}'.hex().encode(), stdin)
        self.assertFalse(B.keychain_write(b'x', run=run, account='bad name; rm'))
