"""Real tmux integration on a private socket; no agents or live sessions are started."""
from pathlib import Path
import json
import shlex
import shutil
import subprocess
import time
import unittest
from unittest.mock import patch

from support import PanelCase

REAL_RUN = subprocess.run
REAL_POPEN = subprocess.Popen


@unittest.skipUnless(shutil.which("tmux"), "install tmux to run private-socket integration tests")
class TmuxIntegration(PanelCase):
    def setUp(self):
        super().setUp()
        socket = str(self.home / "tmux.sock")
        def run(args, **kwargs):
            if args[0] != "tmux":
                raise AssertionError("only isolated tmux commands are allowed")
            return REAL_RUN(["tmux", "-S", socket, "-f", "/dev/null", *args[1:]], **kwargs)
        self.enterContext(patch.object(self.panel.subprocess, "run", side_effect=run))
        self.enterContext(patch.object(self.panel.subprocess, "Popen", REAL_POPEN))
        def tmux(*args, check=True):
            result = run(["tmux", *args], capture_output=True, text=True, timeout=5)
            if check and result.returncode:
                raise RuntimeError(result.stderr)
            return result.stdout
        self.panel.tmux = tmux
        self.addCleanup(lambda: tmux("kill-server", check=False))
        self.input_file = self.home / "input.bin"
        ready = self.home / "ready"
        script = self.home / "read_input.py"
        script.write_text("import os,sys,tty\nfrom pathlib import Path\ntty.setraw(0)\n"
                          "Path(sys.argv[2]).touch()\n"
                          "with open(sys.argv[1], 'ab', buffering=0) as f:\n"
                          " while True:\n"
                          "  data=os.read(0,4096)\n"
                          "  if not data: break\n"
                          "  f.write(data)\n")
        command = " ".join(shlex.quote(str(part)) for part in ("python3", script, self.input_file, ready))
        tmux("new-session", "-d", "-s", "cc-demo", "-x", "200", "-y", "50", command)
        tmux("set-option", "-t", "=cc-demo:", "@cc_agent", "codex")
        deadline = time.monotonic() + 5
        while not ready.exists() and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertTrue(ready.exists(), "isolated input reader did not start")

    def test_restart_resets_mouse_modes_and_preserves_launch_arguments_and_directory(self):
        project = self.home / "project with spaces"
        project.mkdir()
        old = self.home / "mouse.py"
        old.write_text("import time\nprint('\\x1b[?1003h\\x1b[?1006h', end='', flush=True)\ntime.sleep(60)\n")
        self.panel.tmux("new-session", "-d", "-s", "cc-restart", "-c", str(project),
                        shlex.join(["python3", str(old)]))
        self.panel.tmux("set-option", "-t", "=cc-restart:", "@cc_agent", "codex")
        def modes():
            return self.panel.tmux("display-message", "-p", "-t", "=cc-restart:",
                                   "#{mouse_any_flag}/#{mouse_sgr_flag}").strip()
        deadline = time.monotonic() + 5
        while modes() != "1/1" and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(modes(), "1/1")
        result = self.home / "launched.json"
        stub = self.home / "agent.py"
        stub.write_text("import json,os,sys\nfrom pathlib import Path\n"
                        + "Path(" + repr(str(result)) + ").write_text(json.dumps([sys.argv[1:],os.getcwd()]))\n")
        command = shlex.join(["python3", str(stub), "--no-alt-screen"])
        with patch.object(self.panel, "agent_cmd", return_value=command), patch.object(self.panel, "stop_children"):
            self.panel.action_restart({"name": "restart", "mode": "new"})
        deadline = time.monotonic() + 5
        while not result.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertTrue(result.exists(), "restarted agent did not launch")
        self.assertEqual(json.loads(result.read_text()), [["--no-alt-screen"], str(project)])
        self.assertEqual(modes(), "0/0")

    def test_screen_capture_includes_output_older_than_two_hundred_lines(self):
        script = self.home / 'long_output.py'
        script.write_text("import time\nfor i in range(700): print('history-line-%04d' % i, flush=True)\ntime.sleep(60)\n")
        self.panel.tmux('new-session', '-d', '-s', 'cc-history', '-x', '100', '-y', '30',
                        shlex.join(['python3', '-u', str(script)]))
        deadline = time.monotonic() + 5
        preview = ''
        while time.monotonic() < deadline:
            preview = next(s for s in self.panel.list_sessions('history') if s['name'] == 'history')['preview']
            if 'history-line-0699' in preview:
                break
            time.sleep(.02)
        self.assertIn('history-line-0000', preview)
        self.assertIn('history-line-0699', preview)

    def test_literal_dash_semicolon_backslash_unicode_and_multiline_reach_tmux_intact(self):
        expected = b""
        for text in ("-x", "a;", "b\\;", "- список\n- вторая строка"):
            self.panel.action_send({"name": "demo", "text": text})
            expected += ("\x1b[200~" + text + "\x1b[201~\r").encode()
        deadline = time.monotonic() + 5
        while (not self.input_file.exists() or self.input_file.stat().st_size < len(expected)) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.input_file.read_bytes(), expected)

    def test_shell_input_is_literal_without_agent_bracket_markers(self):
        self.panel.tmux("set-option", "-t", "=cc-demo:", "@cc_agent", "shell")
        self.panel.action_send({"name": "demo", "text": "printf hello;"})
        deadline = time.monotonic() + 5
        while (not self.input_file.exists() or self.input_file.stat().st_size < 14) and time.monotonic() < deadline:
            time.sleep(0.01)
        self.assertEqual(self.input_file.read_bytes(), b"printf hello;\r")

    def test_panel_answer_button_selects_the_shown_option_and_rejects_stale_ids(self):
        emulator = self.home / 'menu.py'
        answer = self.home / 'menu-answer.txt'
        emulator.write_text("""import os,sys,tty,time
from pathlib import Path
tty.setraw(0)
selected=0
labels=['Allow once','Allow always','Type something else']
def render():
 print('\\x1b[2J\\x1b[H────────\\r\\nDo you want to run this command?\\r\\n',end='')
 for i,label in enumerate(labels):
  print(('❯' if selected==i else ' ')+' '+str(i+1)+'. '+label+'\\r')
 print('Enter to confirm\\r',flush=True)
render()
while True:
 data=os.read(0,4096)
 if b'B' in data: selected=min(2,selected+1);render()
 if b'A' in data: selected=max(0,selected-1);render()
 if b'\\r' in data:
  Path(sys.argv[1]).write_text(str(selected))
  print('\\x1b[2J\\x1b[HAnswered\\r',flush=True)
  while True:time.sleep(1)
""")
        command = shlex.join(['python3', '-u', str(emulator), str(answer)])
        self.panel.tmux('new-session', '-d', '-s', 'cc-menu', '-x', '100', '-y', '35', command)
        self.panel.tmux('set-option', '-t', '=cc-menu:', '@cc_agent', 'claude')
        deadline = time.monotonic() + 5
        question = None
        while not question and time.monotonic() < deadline:
            question = self.panel.session_question('menu')
            time.sleep(.02)
        self.assertIsNotNone(question)
        payload = self.panel.question_payload(question)
        self.assertEqual([o['label'] for o in payload['options']], ['Allow once', 'Allow always', 'Type something else'])
        self.assertEqual([o['text'] for o in payload['options']], [False, False, True])
        with self.assertRaises(ValueError):
            self.panel.action_answer({'name': 'menu', 'id': 'stale', 'index': 1})
        with self.assertRaises(ValueError):
            self.panel.action_answer({'name': 'menu', 'id': payload['id'], 'index': 2})
        with self.assertRaises(ValueError):
            self.panel.action_answer({'name': 'menu', 'id': payload['id'], 'index': True})
        self.assertFalse(answer.exists())
        self.panel.action_answer({'name': 'menu', 'id': payload['id'], 'index': 1})
        deadline = time.monotonic() + 5
        while not answer.exists() and time.monotonic() < deadline:
            time.sleep(.02)
        self.assertEqual(answer.read_text(), '1')
        self.assertIsNone(self.panel.session_question('../menu'))

    def test_telegram_button_selects_a_real_terminal_question_once(self):
        from integrations.telegram import Telegram
        from test_telegram import FakeAPI, TOKEN
        emulator = self.home / 'question.py'
        answer = self.home / 'answer.txt'
        emulator.write_text("""import os,sys,tty,time
from pathlib import Path
tty.setraw(0)
selected=0
def render():
 print('\\x1b[2J\\x1b[H• Queued follow-up inputs\\r\\nChoose an installation?\\r\\n',end='')
 for i,label in enumerate(['Homebrew','Manual']):
  print(('›' if selected==i else ' ')+' '+str(i+1)+'. '+label+'\\r')
 print('enter submit   ctrl+] skip   shift+→ main prompt\\r',flush=True)
render()
while True:
 data=os.read(0,4096)
 if b'B' in data: selected=min(1,selected+1);render()
 if b'A' in data: selected=max(0,selected-1);render()
 if b'\\r' in data:
  Path(sys.argv[1]).write_text(str(selected))
  print('\\x1b[2J\\x1b[HAnswered\\r',flush=True)
  while True:time.sleep(1)
""")
        command=shlex.join(['python3','-u',str(emulator),str(answer)])
        self.panel.tmux('new-session','-d','-s','cc-question','-x','100','-y','35',command)
        self.panel.tmux('set-option','-t','=cc-question:','@cc_agent','codex')
        deadline=time.monotonic()+5
        q=None
        while not q and time.monotonic()<deadline:
            q=self.panel.current_question('question')
            time.sleep(.02)
        self.assertIsNotNone(q)
        transport=FakeAPI()
        integration=Telegram(self.home/'integrations',lambda:[q],self.panel.answer_question,transport)
        integration.start=lambda:None
        integration.save({'token':TOKEN})
        code=integration.pair()['pair_url'].split('?start=deck_',1)[1]
        integration.handle({'message':{'text':'/start deck_'+code,'chat':{'id':100,'type':'private'},'from':{'id':100}}})
        integration.deliver()
        row=integration.database().pending()[0]
        callback={'callback_query':{'id':'test','from':{'id':100},'message':{'message_id':row['message_id'],'chat':{'id':100,'type':'private'}},'data':f"q:{row['id']}:1"}}
        integration.handle(callback)
        integration.handle(callback)
        deadline=time.monotonic()+5
        while not answer.exists() and time.monotonic()<deadline:time.sleep(.02)
        self.assertEqual(answer.read_text(),'1')
        self.assertEqual(integration.database().get(row['id'])['status'],'answered')
