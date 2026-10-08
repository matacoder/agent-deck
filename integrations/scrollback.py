"""Search in a session's whole terminal output (tmux scrollback), newest match first.

The query is a plain case-insensitive substring, never a regular expression, so a pasted pattern cannot
make the panel spin. Results are capped; each match carries a few lines around it.
"""
MAX_QUERY = 200
MAX_MATCHES = 200
CONTEXT = 2
MAX_LINE = 2000  # tmux joins wrapped rows: one minified file can be a multi-megabyte line.


def clip(line, at=0):
    """A window of a long line, around the match when there is one."""
    if len(line) <= MAX_LINE:
        return line
    start = max(0, min(at - MAX_LINE // 4, len(line) - MAX_LINE))
    return ('…' if start else '') + line[start:start + MAX_LINE] + ('…' if start + MAX_LINE < len(line) else '')


def search(text, query, limit=MAX_MATCHES, context=CONTEXT):
    if not isinstance(query, str) or not query.strip() or len(query) > MAX_QUERY:
        raise ValueError('Введите текст для поиска, до 200 символов')
    needle = query.strip().casefold()
    lines = text.split('\n')
    while lines and not lines[-1].strip():
        lines.pop()  # The empty rows under the prompt are not output.
    matches, total = [], 0
    for index in range(len(lines) - 1, -1, -1):
        if needle not in lines[index].casefold():
            continue
        total += 1
        if len(matches) < limit:
            matches.append({'line': index + 1, 'text': clip(lines[index], lines[index].casefold().find(needle)),
                            'before': [clip(line) for line in lines[max(0, index - context):index]],
                            'after': [clip(line) for line in lines[index + 1:index + 1 + context]]})
    return {'query': query.strip(), 'lines': len(lines), 'total': total, 'matches': matches}
