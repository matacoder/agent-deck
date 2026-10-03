"""File-backed gettext-style catalogs shared by the panel and optional integrations."""
from functools import lru_cache
from html import escape, unescape
import json
from pathlib import Path
import re

DIRECTORY = Path(__file__).parent
TAG = re.compile(r'[a-z]{2,3}(?:-[A-Za-z0-9]{2,8})*\Z')


def validate(data):
    if (not isinstance(data, dict) or not isinstance(data.get('name'), str)
            or not 1 <= len(data['name']) <= 80 or not isinstance(data.get('messages'), dict)
            or len(data['messages']) > 3000):
        raise ValueError('Invalid locale catalog')
    for key, value in data['messages'].items():
        if (not isinstance(key, str) or not isinstance(value, str)
                or len(key) > 10000 or len(value) > 10000
                or sorted(re.findall(r'\{\d+\}', key)) != sorted(re.findall(r'\{\d+\}', value))):
            raise ValueError('Invalid locale translation or placeholders')
    return data


@lru_cache(maxsize=32)
def catalog(language):
    if not TAG.fullmatch(language):
        raise ValueError('Invalid language tag')
    path = DIRECTORY / (language + '.json')
    if path.stat().st_size > 1024 * 1024 or path.is_symlink():
        raise ValueError('Invalid locale file')
    return validate(json.loads(path.read_text(encoding='utf-8')))


def available():
    languages = []
    for path in sorted(DIRECTORY.glob('*.json')):
        try:
            languages.append({'code': path.stem, 'name': catalog(path.stem)['name']})
        except (OSError, ValueError):
            continue
    return languages


def messages(language):
    # Partial community catalogs inherit English; Russian remains the source language.
    result = dict(catalog('en')['messages'])
    result.update(catalog(language)['messages'])
    return result


def translate(text, language):
    return messages(language).get(text, text)


def render_html(page, language):
    head, separator, script = page.partition('<script>')
    translations = messages(language)
    def replace(match):
        if match.group(1) is not None:
            text = match.group(1)
            return '>' + escape(unescape(translations[text]), quote=False) + '<' if text in translations else match.group()
        attr, text = match.group(2), match.group(3)
        return attr + '="' + escape(translations[text], quote=True) + '"' if text in translations else match.group()
    head = re.sub(r'>([^<>]+)<|(title|placeholder|aria-label)="([^"]*)"', replace, head)
    head = re.sub(r'<html lang="[^"]*"', '<html lang="' + language + '"', head, count=1)
    # JSON lives in JavaScript, never interpolate translations as executable code.
    bootstrap = json.dumps({'language': language, 'messages': translations}, ensure_ascii=False).replace('<', '\\u003c').replace('\u2028', '\\u2028').replace('\u2029', '\\u2029')
    return head + separator + script.replace('__PANEL_I18N__', bootstrap)


def translate_message(text, language):
    translations = messages(language)
    if text in translations:
        return translations[text]
    for source, target in translations.items():
        if not re.search(r'\{\d+\}', source):
            continue
        parts = re.split(r'(\{\d+\})', source)
        pattern = ''.join('(.*?)' if re.fullmatch(r'\{\d+\}', part) else re.escape(part) for part in parts)
        match = re.fullmatch(pattern, text, re.S)
        if match:
            values = {part: value for part, value in zip(parts[1::2], match.groups())}
            return re.sub(r'\{\d+\}', lambda m: values[m.group()], target)
    return text


def response(data, language):
    if isinstance(data, list):
        return [response(item, language) for item in data]
    if isinstance(data, dict):
        return {key: translate_message(value, language) if key in ('error', 'message') and isinstance(value, str)
                else response(value, language) for key, value in data.items()}
    return data
