import re
import tempfile
import uuid
from pathlib import Path
from unittest.mock import Mock, patch

from support import PanelCase
from integrations import agents

ROOT = Path(__file__).resolve().parents[2]


def install(home, agent):
    spec = agents.CLI[agent]
    folder = Path(home) / (spec.get('places') or ('.local/bin',))[0]
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / spec['binary']
    path.write_text('#!/bin/sh\n')
    path.chmod(0o755)
    return str(path)


class RegistryTests(PanelCase):
    def test_every_described_agent_is_known_to_the_panel_the_page_and_the_updater(self):
        page = (ROOT / 'frontend/agents.js').read_text()
        listed = dict(re.findall(r'\{id:"([\w-]+)",label:"[^"]+",glyph:"[^"]+",skip:"([^"]*)"', page))
        for agent, spec in agents.CLI.items():
            self.assertEqual(self.panel.AGENTS[agent], (spec['label'], set(spec['processes']), spec['skip']))
            self.assertEqual(self.panel.INSTALLERS[agent], spec['install'])
            self.assertEqual(self.panel.LOGINS[agent], spec['login'])
            self.assertEqual(listed[agent], spec['skip'].strip(), agent)
            self.assertIn(f'{{id:"{agent}",label:"{spec["label"]}"', page)
        self.assertEqual({a for a in listed if f'id:"{a}"' in page and re.search(rf'id:"{a}"[^}}]*cli:true', page)}, set(agents.CLI))
        self.assertTrue(set(listed) <= set(self.panel.AGENTS))

    def test_a_conversation_with_our_id_is_resumed_only_once_it_is_on_disk(self):
        sid = str(uuid.uuid4())
        with tempfile.TemporaryDirectory() as home:
            qwen = install(home, 'qwen')
            self.assertEqual(agents.command('qwen', sid, False, True, home), f'{qwen} --session-id {sid} --yolo')
            self.assertEqual(agents.command('qwen', sid, True, False, home), f'{qwen} --session-id {sid}')
            chats = Path(home) / '.qwen/projects/-home-demo-app/chats'
            chats.mkdir(parents=True)
            (chats / f'{sid}.jsonl').write_text('{}\n')
            self.assertEqual(agents.command('qwen', sid, True, False, home), f'{qwen} --resume {sid}')
            gemini = install(home, 'gemini')
            self.assertEqual(agents.command('gemini', sid, True, False, home), f'{gemini} --session-id {sid}')
            chats = Path(home) / '.gemini/tmp/app/chats'
            chats.mkdir(parents=True)
            (chats / f'session-2026-10-12T10-00-{sid[:8]}.jsonl').write_text('{}\n')
            self.assertEqual(agents.command('gemini', sid, True, True, home), f'{gemini} --resume {sid} --yolo')
            copilot = install(home, 'copilot')
            for resume in (False, True):  # One switch creates and returns: an empty conversation is not resumable.
                self.assertEqual(agents.command('copilot', sid, resume, False, home), f'{copilot} --session-id={sid}')
            for bad in (None, 'session_1', sid + '; rm -rf ~'):
                with self.assertRaisesRegex(ValueError, 'conversation ID is not saved'):
                    agents.command('qwen', bad, True, False, home)

    def test_a_program_that_makes_its_own_ids_continues_its_last_conversation(self):
        with tempfile.TemporaryDirectory() as home:
            with patch.object(agents.shutil, 'which', return_value=None), self.assertRaisesRegex(ValueError, 'Install OpenCode first'):
                agents.command('opencode', None, False, False, home)  # Said before a session opens on `command not found`.
            path = install(home, 'opencode')
            self.assertEqual(path, str(Path(home) / '.opencode/bin/opencode'))
            self.assertEqual(agents.command('opencode', None, True, True, home), f'{path} --continue --auto')
            self.assertFalse(agents.keeps_id('opencode'))
            self.assertTrue(agents.keeps_id('qwen'))
            self.assertFalse(agents.keeps_id('claude'))

    def test_sign_in_is_read_from_each_program_s_own_folder(self):
        with tempfile.TemporaryDirectory() as home:
            root = Path(home)
            self.assertEqual([agents.signed_in(a, home) for a in ('qwen', 'gemini', 'copilot', 'opencode')], [False, False, False, True])
            (root / '.qwen').mkdir()
            (root / '.qwen/settings.json').write_text('not json')
            self.assertFalse(agents.signed_in('qwen', home))
            (root / '.qwen/settings.json').write_text('{ // chosen in /auth\n "security": {"auth": {"selectedType": "openai"}} }')
            self.assertTrue(agents.signed_in('qwen', home))
            (root / '.gemini').mkdir()
            (root / '.gemini/oauth_creds.json').write_text('{}')
            self.assertTrue(agents.signed_in('gemini', home))
            (root / '.config/gh').mkdir(parents=True)
            (root / '.config/gh/hosts.yml').write_text('github.com:\n')
            self.assertTrue(agents.signed_in('copilot', home))

    def test_the_panel_builds_commands_ids_and_status_from_the_registry(self):
        sid = str(uuid.uuid4())
        with patch.object(agents, 'executable', return_value='/opt/tools/gemini'):
            self.assertEqual(self.panel.agent_cmd('gemini', sid, False, True), f'/opt/tools/gemini --session-id {sid} --yolo')
        self.assertTrue(self.panel.is_running('qwen', 'node'))
        self.assertTrue(self.panel.is_running('opencode', 'opencode'))
        self.assertFalse(self.panel.is_running('copilot', 'bash'))
        with patch.object(agents, 'executable', return_value=None):
            self.assertEqual(self.panel.agent_status('copilot'), {'installed': False, 'version': None, 'logged_in': False})

    def test_a_leading_agent_is_told_only_about_agents_that_are_ready(self):
        with tempfile.TemporaryDirectory() as home, patch.object(agents.shutil, 'which', return_value=None):
            self.assertIsNone(agents.leader_note(home))
            install(home, 'opencode')
            install(home, 'qwen')  # Installed, not signed in: not offered.
            note = agents.leader_note(home)
            self.assertIn('`opencode run "<task>"` (OpenCode)', note)
            self.assertNotIn('qwen', note)
            self.assertNotIn('Codex', note)
            (Path(home) / '.codex').mkdir()
            (Path(home) / '.codex/auth.json').write_text('{}')
            (Path(home) / '.local/bin').mkdir(parents=True, exist_ok=True)
            (Path(home) / '.local/bin/codex').write_text('')
            self.assertIn('`codex exec "<task>"` (Codex)', agents.leader_note(home))
            self.assertNotIn('Codex', agents.leader_note(home, hosts=('codex',)))

    def test_the_session_hook_never_offers_an_agent_to_itself_and_survives_a_hanging_version_check(self):
        import session_hook
        with patch.object(agents, 'leader_note', return_value='note') as note, \
                patch.object(session_hook.subprocess, 'run', return_value=Mock(stdout='codex\n')):
            self.assertEqual(session_hook.other_agents_note(session_hook.session_agent('%1')), 'note')
        note.assert_called_once_with(hosts=('codex',))
        # A program that does not answer --version is still installed; the list of agents is not held up twice.
        with tempfile.TemporaryDirectory() as home:
            binary = install(home, 'gemini')
            run = Mock(side_effect=self.panel.subprocess.TimeoutExpired('gemini', 10))
            with patch.object(agents, 'executable', return_value=str(binary)), patch.object(self.panel.subprocess, 'run', run):
                self.panel._version_cache.pop('gemini', None)
                first, second = self.panel.agent_status('gemini'), self.panel.agent_status('gemini')
            self.assertEqual((first['installed'], first['version'], second['version'], run.call_count), (True, None, None, 1))

