"""Rules from AGENTS.md that a reader can break without noticing, checked on the source itself."""
import ast
import contextlib
import importlib.util
import io
import tempfile
from pathlib import Path
from types import SimpleNamespace
import unittest

from support import PanelCase, ROOT

SOURCES = sorted([*ROOT.glob('panel/*.py'), *ROOT.glob('integrations/*.py')])


def calls(tree, attribute):
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute) and node.func.attr == attribute \
                and isinstance(node.func.value, ast.Name) and node.func.value.id == 'subprocess':
            yield node


class SourceRulesTests(unittest.TestCase):
    def trees(self):
        for path in SOURCES:
            yield path.relative_to(ROOT), ast.parse(path.read_text(), str(path))

    def test_child_processes_never_use_a_shell_and_never_inherit_stdin(self):
        # A child that inherits the panel's stdin can wait for input that never comes (gh, git prompts).
        problems = []
        for path, tree in self.trees():
            for node in calls(tree, 'run'):
                names = {keyword.arg for keyword in node.keywords}
                if None in names:
                    continue  # **options: the caller's own check applies
                if 'shell' in names:
                    problems.append(f'{path}:{node.lineno} shell=')
                if not names & {'input', 'stdin'}:
                    problems.append(f'{path}:{node.lineno} no input')
        self.assertEqual(problems, [])

    def test_integrations_never_import_the_panel(self):
        # Services get their collaborators passed in; importing panel back would make a cycle.
        problems = []
        for path, tree in self.trees():
            if path.parts[0] != 'integrations':
                continue
            for node in ast.walk(tree):
                names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else \
                    [node.module or ''] if isinstance(node, ast.ImportFrom) else []
                problems += [f'{path}:{node.lineno}' for name in names if name.split('.')[0] == 'panel']
        self.assertEqual(problems, [])


class BundleRulesTests(unittest.TestCase):
    def build(self):
        spec = importlib.util.spec_from_file_location('build_panel', ROOT / 'scripts/build-panel.py')
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module

    def test_bundle_rejects_a_file_left_out_and_a_name_declared_twice(self):
        build = self.build()
        with tempfile.TemporaryDirectory(dir='/tmp') as directory:
            source = Path(directory)
            for name in (*build.SCRIPTS, 'app.js'):
                (source / name).write_text(f'function only_{name.replace(".", "_").replace("-", "_")}(){{}}\n')
            build.check_scripts(source)
            (source / 'hub.js').write_text('let sessions=[];\n')
            (source / 'app.js').write_text('let sessions=[];\n')
            with self.assertRaisesRegex(SystemExit, 'sessions is declared at top level in both hub.js and app.js'):
                build.check_scripts(source)
            (source / 'app.js').write_text('\n')
            (source / 'new.js').write_text('\n')
            with self.assertRaisesRegex(SystemExit, 'new.js'):
                build.check_scripts(source)


class FailureLogTests(PanelCase):
    def test_an_unexpected_error_is_logged_by_place_without_its_text(self):
        def broken():
            raise KeyError('secret-token-123')
        request = SimpleNamespace(command='POST', path='/deck/x/c/signed-path/t/ws?token=abc')
        stderr = io.StringIO()
        try:
            broken()
        except KeyError as error:
            with contextlib.redirect_stderr(stderr):
                self.panel.Handler.log_failure(request, error)
        line = stderr.getvalue()
        self.assertIn('500 POST /deck/x/c/***/t/ws: KeyError at test_code_rules.py:', line)
        self.assertIn(' broken', line)
        for secret in ('secret-token-123', 'signed-path', 'token=abc'):
            self.assertNotIn(secret, line)


if __name__ == '__main__':
    unittest.main()
