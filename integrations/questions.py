"""Normalize active terminal questions without treating ordinary output as a prompt."""
from dataclasses import dataclass
import hashlib
import json
import re
from pathlib import Path


@dataclass(frozen=True)
class Question:
    session: str
    agent: str
    instance: str
    title: str
    options: tuple
    selected: int
    progress: str = ""
    request_id: str = ""

    @property
    def fingerprint(self):
        # Cursor movement does not create a new question; a new pane/conversation does.
        data = [self.session, self.agent, self.instance, self.title, self.options, self.progress, self.request_id]
        return hashlib.sha256(json.dumps(data, ensure_ascii=False).encode()).hexdigest()


OPTION = re.compile(r"^\s*([›❯>●]?)\s*(\d{1,2})[.)]\s+(.+)$")
FOOTER = re.compile(r"(?:enter|return|⏎)\s+(?:to\s+)?(?:submit(?: (?:answer|all))?|select|confirm|continue|proceed)\b", re.I)


class QuestionNotReady(ValueError):
    retryable = True


def parse_question(session, agent, instance, screen):
    if agent not in ("codex", "claude", "claude-kimi", "kimi"):
        return None
    screen = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", screen)
    lines = [line.strip().strip("│┃").strip() for line in screen.splitlines()[-120:]]
    footers = [i for i, line in enumerate(lines) if FOOTER.search(line)]
    if not footers:
        return None
    end = footers[-1]
    # A historical picker above a new composer must never receive an answer.
    if any(re.match(r"^[›❯>]\s+\S", line) and not OPTION.match(line) for line in lines[end + 1:]):
        return None
    if any("to clear notes" in line.lower() for line in lines[max(0, end - 2):end + 2]):
        return None  # Notes focus requires a different adapter, never send selection keys there.
    start = max(0, end - 60)
    headers = [i for i in range(start, end) if re.match(r"^Question \d+/\d+", lines[i])]
    queued = [i for i in range(start, end) if 'Queued follow-up inputs' in lines[i]]
    async_form = bool(queued and re.search(r'shift\+\s*→\s+main prompt', lines[end], re.I))
    progress = ""
    if headers:
        start = headers[-1] + 1
        progress = re.match(r"Question \d+/\d+", lines[headers[-1]])[0]
    elif async_form:
        start = queued[-1] + 1
    rows = [(i, OPTION.match(lines[i])) for i in range(start, end) if OPTION.match(lines[i])]
    if not rows or not any(match[1] for _, match in rows):
        return None
    # Keep only the final contiguous numbered menu (not a numbered list in the question).
    restart = max((j for j, (_, match) in enumerate(rows) if match[2] == "1"), default=-1)
    if restart < 0:
        return None
    rows = rows[restart:]
    if [int(match[2]) for _, match in rows] != list(range(1, len(rows) + 1)) or len(rows) > 9:
        return None
    marked = [j for j, (_, match) in enumerate(rows) if match[1]]
    if len(marked) != 1:
        return None
    first = rows[0][0]
    if not headers and not async_form:
        # Separators bound the dialog and keep preceding conversation out of notifications.
        separators = [i for i in range(start, first) if re.match(r"^[─━═╌┄╭╰┌└][─━═╌┄╭╰┌└┐┘╮╯\s]*$", lines[i])]
        if separators:
            start = separators[-1] + 1
        else:
            start = max(start, first - 6)
    title = "\n".join(line for line in lines[start:first] if line).strip()
    if not title:
        return None
    if not headers and not async_form and not re.search(r"\?|would you|do you|allow|proceed|choose|выберите|разрешить", title, re.I):
        return None
    options = tuple(match[3].strip() for _, match in rows)
    if any(re.match(r'\[[ xX✓]\]', label) for label in options) or any('space to toggle' in line.lower() for line in lines[start:end + 2]):
        return None
    return Question(session, agent, instance, title[:1600], options, marked[0], progress)


def transcript_model(path, agent):
    """Model of the latest turn, so a /model switch shows up without asking the agent."""
    model = None
    with Path(path).open('rb') as stream:
        if Path(path).stat().st_size > 256 * 1024:
            stream.seek(-256 * 1024, 2)
            stream.readline()
        for line in stream:
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if not isinstance(record, dict):
                continue
            kind, body = ('turn_context', record.get('payload')) if agent == 'codex' else ('assistant', record.get('message'))
            value = body.get('model') if record.get('type') == kind and isinstance(body, dict) else None
            # Claude marks locally generated error turns as <synthetic>.
            if isinstance(value, str) and 0 < len(value) <= 120 and value.isprintable() and not value.startswith('<'):
                model = value
    return model


def transcript_questions(path, session, agent, instance):
    """Read only pending question tools from the agent's own conversation, not its output."""
    pending = {}
    with Path(path).open('rb') as stream:
        if Path(path).stat().st_size > 2 * 1024 * 1024:
            stream.seek(-2 * 1024 * 1024, 2)
            stream.readline()
        for line in stream:
            try:
                record = json.loads(line)
            except (ValueError, UnicodeError):
                continue
            if agent == 'codex':
                if record.get('type') != 'response_item':
                    continue
                item = record.get('payload', {})
                if item.get('type') == 'message' and item.get('role') == 'user':
                    pending.clear()  # A direct answer/new instruction supersedes previous async questions.
                if item.get('type') == 'function_call' and item.get('name', '').split('.')[-1] in ('request_user_input', 'request_user_input_async'):
                    try:
                        args = json.loads(item.get('arguments', '{}'))
                    except ValueError:
                        continue
                    pending[item['call_id']] = args.get('questions', [])
                elif item.get('type') == 'function_call_output':
                    try:
                        output = json.loads(item.get('output', '{}'))
                    except (ValueError, TypeError):
                        output = {}
                    if not isinstance(output, dict) or not output.get('accepted'):
                        pending.pop(item.get('call_id'), None)
            else:
                message = record.get('message', {})
                content = message.get('content', [])
                if not isinstance(content, list):
                    if record.get('type') == 'user':
                        pending.clear()
                    continue
                if record.get('type') == 'user' and any(part.get('type') == 'text' for part in content):
                    pending.clear()
                for part in content:
                    if part.get('type') == 'tool_use' and part.get('name') == 'AskUserQuestion':
                        pending[part['id']] = part.get('input', {}).get('questions', [])
                    elif part.get('type') == 'tool_result':
                        pending.pop(part.get('tool_use_id'), None)
    result = []
    for identity, questions in pending.items():
        for index, data in enumerate(questions):
            title = data.get('question') or data.get('title')
            options = data.get('options')
            if not isinstance(title, str) or not isinstance(options, list) or not 1 <= len(options) <= 9:
                continue
            if data.get('is_secret') or data.get('isSecret') or data.get('multiSelect'):
                continue
            labels = tuple(option if isinstance(option, str) else option.get('label', '') for option in options)
            if not all(isinstance(label, str) and label for label in labels):
                continue
            result.append(Question(session, agent, instance, title[:1600], labels, 0,
                                   f'Question {index + 1}/{len(questions)}', f'{identity}:{index}'))
    return result


def matches_screen(structured, visible):
    """Transcript labels omit terminal descriptions and the UI's implicit Other option."""
    if not visible or structured.instance != visible.instance or structured.session != visible.session:
        return False
    if structured.progress and visible.progress and structured.progress != visible.progress:
        return False
    normalize = lambda value: ' '.join(value.split()).casefold()
    if normalize(structured.title) not in normalize(visible.title):
        return False
    return len(visible.options) >= len(structured.options) and all(
        normalize(actual).startswith(normalize(expected)) for expected, actual in zip(structured.options, visible.options))
