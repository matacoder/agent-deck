import json
from pathlib import Path
import re
import sys
import tempfile
import unittest
from unittest.mock import patch
from support import ROOT
sys.path.insert(0, str(ROOT))
import locales


class LocaleTests(unittest.TestCase):
    def test_partial_additional_catalog_inherits_english_and_escapes_html(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            for tag in ('en', 'ru'):
                (root / (tag + '.json')).write_bytes((ROOT / 'locales' / (tag + '.json')).read_bytes())
            (root / 'es.json').write_text(json.dumps({'name':'Español','messages':{'Настройки':'Ajustes <script>'}}))
            locales.catalog.cache_clear()
            try:
                with patch.object(locales, 'DIRECTORY', root):
                    self.assertEqual({x['code'] for x in locales.available()}, {'en','ru','es'})
                    self.assertEqual(locales.translate('Пароль','es'), 'Password')
                    html = locales.render_html('<html lang="ru"><h3>Настройки</h3><script>const x=__PANEL_I18N__;</script>', 'es')
                    self.assertIn('Ajustes &lt;script&gt;', html)
                    self.assertNotIn('Ajustes <script>', html)
                    self.assertIn('\\u003cscript>', html)
            finally:
                locales.catalog.cache_clear()

    def test_catalogs_match_placeholders_and_cover_all_static_ui_strings(self):
        english = locales.catalog('en')['messages']
        russian = locales.catalog('ru')['messages']
        self.assertEqual(english.keys(), russian.keys())
        for item in locales.available():
            data = locales.catalog(item['code'])
            locales.validate(data)
            self.assertEqual(data['messages'].keys(), english.keys(), item['code'])
            for source, translated in data['messages'].items():
                self.assertTrue(translated.strip(), (item['code'], source))
                self.assertEqual(len(source) - len(source.lstrip()), len(translated) - len(translated.lstrip()), (item['code'], source))
                self.assertEqual(len(source) - len(source.rstrip()), len(translated) - len(translated.rstrip()), (item['code'], source))
        page = (ROOT/'panel/index.html').read_text()
        for match in re.finditer(r'(?<![\w])tr\(("(?:\\.|[^"\\])*")', page):
            self.assertIn(json.loads(match.group(1)), english)
        with self.assertRaises(ValueError):
            locales.validate({'name':'Test','messages':{'Value {0}':'Value {1}'}})
        with self.assertRaises(ValueError):
            locales.catalog('../outside')

    def test_full_language_pack_is_discovered_with_native_names(self):
        expected = {'en','ru','es','pt-BR','de','fr','zh-CN','ja','ko','id','tr','it','pl','uk','hi','zh-TW'}
        languages = locales.available()
        self.assertTrue(expected <= {item['code'] for item in languages})
        self.assertEqual(len({item['name'] for item in languages}),len(languages))
        english = locales.catalog('en')['messages']
        for code in expected - {'en', 'ru'}:
            messages = locales.catalog(code)['messages']
            for key, value in messages.items():
                self.assertEqual(re.findall(r'--[a-z][a-z-]+',english[key]),re.findall(r'--[a-z][a-z-]+',value),(code,key))
                if code != 'uk':
                    self.assertIsNone(re.search(r'[\u0400-\u04ff]',value),(code,key))

    def test_response_localizes_errors_and_jobs_but_preserves_user_data(self):
        data={'error':'неверное имя сессии','job':{'message':'Панель обновлена до v0.8.0'},
              'sessions':[{'preview':'неверное имя сессии','name':'Пароль'}], 'question':{'title':'Пароль','options':['Настройки']}}
        result=locales.response(data,'en')
        self.assertEqual(result['error'],'invalid session name')
        self.assertEqual(result['job']['message'],'Panel updated to v0.8.0')
        self.assertEqual(result['sessions'],data['sessions'])
        self.assertEqual(result['question'],data['question'])
