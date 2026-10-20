"""LaTeX request representation with provenance for native LyX objects.

Only annotations are hidden. Objects that cannot be reconstructed losslessly
use content-addressed commands; the original native data stays on this machine.
"""
from collections import Counter, defaultdict
import hashlib
from pathlib import Path
import re

from .selection import extract_body
from .replacement import (Math, THEOREMS, REFERENCE, body_insets, formula_source,
                          math_parts, native_paragraphs, paragraph_boundaries, UNSAFE_TEX)


OBJECT = re.compile(r'\\lyxaiobject\{([0-9a-f]{24})\}')
PAR_METADATA = re.compile(r'(?m)^\\(?:paragraph_spacing|noindent|indent|leftindent|align|labelwidthstring)\b[^\n]*\n?')


def wrap(body):
    return '\\begin_body\n' + body + '\n\\end_body\n'


def kind(raw):
    return raw.split('\n', 1)[0][len('\\begin_inset '):].strip()


def contents(raw):
    start = re.search(r'(?m)^\\begin_layout ', raw)
    return raw[start.start():raw.rindex(r'\end_inset')] if start else ''


def text_of(raw):
    return extract_body(wrap('\\begin_layout Standard\n' + raw + '\n\\end_layout'), allow_empty=True).text


def marker(raw):
    canonical = re.sub(r'(?m)^status [^\n]*\n?', '', raw)
    return '\\lyxaiobject{' + hashlib.sha256(canonical.encode()).hexdigest()[:24] + '}'


def opaque(raw):
    name = kind(raw)
    if name == 'ERT' and UNSAFE_TEX.search(text_of(raw)):
        return True
    if name == 'Tabular':
        shape = re.search(r'<lyxtabular[^>]*rows="(\d+)" columns="(\d+)"', raw)
        cells = list(body_insets(raw[raw.index('\n')+1:raw.rindex(r'\end_inset')]))
        return (not shape or len(cells) != int(shape[1]) * int(shape[2])
                or bool(re.search(r'\b(?:multicolumn|multirow)="[1-9]\d*"', raw))
                or any(len(native_paragraphs(wrap(contents(cell[2])))) > 1 for cell in cells))
    if name.startswith('Flex ') and name not in ('Flex Emph', 'Flex Strong', 'Flex Noun'):
        return True
    return (name.startswith(('Note ', 'Foot', 'Marginal', 'Graphics', 'space ', 'VSpace', 'Newline '))
            or not (name in ('Formula', 'ERT', 'Text', 'Tabular', 'CommandInset label', 'CommandInset ref', 'CommandInset citation')
                    or name.startswith(('Formula ', 'Float ', 'Caption ', 'Box ', 'Flex ', 'Argument ', 'Quotes '))))


def protected_objects(native, filename=None):
    result = {}
    origin = re.search(r'(?m)^\\origin (.+)$', native)
    base = Path(origin[1].strip('"')) if origin and origin[1] != 'unavailable' else None
    if (base is None or not base.is_absolute()) and filename:
        base = Path(filename).parent
    def relocate(raw):
        if base is None or not base.is_absolute():
            return raw
        def absolute(match):
            value = Path(match[2].strip('"'))
            value = value if value.is_absolute() else base / value
            return match[1] + str(value.resolve()).replace('\\', '/')
        return re.sub(r'(?m)^([ \t]*filename[ \t]+)([^\n]+)$', absolute, raw)
    def visit(body):
        for _, _, raw in body_insets(body):
            if opaque(raw):
                result[marker(raw)] = relocate(raw)
            else:
                visit(raw[raw.index('\n') + 1:raw.rindex(r'\end_inset')])
    visit(native.split(r'\begin_body', 1)[1].split(r'\end_body', 1)[0])
    return result


def escape(text):
    saved = []
    def protect(match):
        saved.append(match[0])
        return f'LYXAIREF{len(saved)-1}END'
    text = REFERENCE.sub(protect, text)
    text = re.sub(r'([&%#_{}])', r'\\\1', text)
    text = text.replace('~', r'\textasciitilde{}').replace('^', r'\textasciicircum{}')
    for i, ref in enumerate(saved):
        text = text.replace(f'LYXAIREF{i}END', ref)
    return text


def render_body(body):
    saved = []
    for start, end, raw in reversed(list(body_insets(body))):
        saved.append(render_inset(raw))
        body = body[:start] + f'LYXAIINSET{len(saved)-1}END' + body[end:]
    text = text_of(body)
    text = ''.join(formula_source(p) if isinstance(p, Math) else escape(p) for p in math_parts(text))
    for i, value in enumerate(saved):
        text = text.replace(f'LYXAIINSET{i}END', value)
    return text


def dimension(value):
    value = value.strip('"')
    match = re.fullmatch(r'([\d.]+)(text|col|line|page)%', value)
    if match:
        unit = {'text': 'textwidth', 'col': 'columnwidth', 'line': 'linewidth', 'page': 'paperwidth'}[match[2]]
        return f'{float(match[1])/100:g}\\{unit}'
    return value if re.fullmatch(r'[\d.]+(?:pt|em|ex|cm|mm|in|bp)', value) else r'\linewidth'


def render_inset(raw):
    name = kind(raw)
    if opaque(raw):
        # No annotation contents are sent. Unknown objects expose their readable
        # content in a comment, while the token retains their full native data.
        description = '' if name.startswith(('Note ', 'Foot', 'Marginal')) else text_of(raw).replace('\n', ' ')
        return marker(raw) + ('% LyX ' + name + ': ' + description + '\n' if description else '')
    if name in ('ERT', 'Formula', 'CommandInset label', 'CommandInset ref', 'CommandInset citation') or name.startswith(('Formula ', 'Quotes ')):
        return text_of(raw)
    if name == 'Tabular':
        cells = list(body_insets(raw[raw.index('\n')+1:raw.rindex(r'\end_inset')]))
        shape = re.search(r'<lyxtabular[^>]*rows="(\d+)" columns="(\d+)"', raw)
        cols = int(shape[2])
        aligns = re.findall(r'<column[^>]* alignment="(\w+)"', raw)
        spec = ''.join({'left': 'l', 'right': 'r', 'center': 'c'}.get(a, 'l') for a in aligns) or 'l' * cols
        rows = [' & '.join(render_inset(cell[2]) for cell in cells[i:i+cols]) for i in range(0, len(cells), cols)]
        return '\\begin{tabular}{' + spec + '}\n' + '\\\\\n'.join(rows) + '\n\\end{tabular}'
    body = contents(raw)
    short = ''
    if name.startswith('Caption '):
        for start, end, argument in reversed(list(body_insets(body))):
            if kind(argument) == 'Argument 1':
                short = render_paragraphs(wrap(contents(argument)))
                body = body[:start] + body[end:]
    inner = render_paragraphs(wrap(body))
    if name.startswith('Float '):
        env = name.split(' ', 1)[1] + ('*' if '\nwide true' in raw else '')
        placement = re.search(r'(?m)^placement ([a-z!]+)$', raw)
        return '\\begin{' + env + '}' + ('['+placement[1]+']' if placement else '') + '\n' + inner + '\n\\end{' + env + '}'
    if name.startswith('Caption '):
        return '\\caption' + ('[{' + short + '}]' if short else '') + '{' + inner + '}'
    if name.startswith('Box '):
        width = re.search(r'(?m)^width (.+)$', raw)
        return '\\begin{minipage}{' + (dimension(width[1]) if width else r'\linewidth') + '}\n' + inner + '\n\\end{minipage}'
    if name.startswith('Flex '):
        command = {'Emph': 'emph', 'Strong': 'textbf', 'Noun': 'textsc'}.get(name.split(' ', 1)[1])
        if command:
            return '\\' + command + '{' + inner + '}'
        return marker(raw) + '% LyX ' + name + ': ' + text_of(raw).replace('\n', ' ') + '\n'
    return inner


def render_paragraphs(native):
    _, paragraphs, _ = paragraph_boundaries(native_paragraphs(native))
    result, active = [], None
    for p in paragraphs:
        env = p.layout.lower() if p.layout.lower() in THEOREMS else None
        title = ''
        body = p.body
        for start, end, raw in reversed(list(body_insets(body))):
            if kind(raw) == 'Argument 1' and env:
                title = render_paragraphs(wrap(contents(raw)))
                body = body[:start] + body[end:]
        if active != env or title:
            if active:
                result.append('\\end{' + active + '}')
            if env:
                result.append('\\begin{' + env + '}' + ('[{' + title + '}]' if title else ''))
            active = env
        text = render_body(body)
        heading = {'Section': 'section', 'Subsection': 'subsection', 'Subsubsection': 'subsubsection', 'Paragraph': 'paragraph'}.get(p.layout)
        if heading:
            text = '\\' + heading + '{' + text + '}'
        spacing = re.search(r'(?m)^\\paragraph_spacing (\w+)(?: ([\d.]+))?', body)
        if spacing:
            factor = spacing[2] or {'single': '1', 'onehalf': '1.5', 'double': '2'}.get(spacing[1], '1')
            text = '\\begin{spacing}{' + factor + '}' + text + '\\end{spacing}'
        if re.search(r'(?m)^\\noindent\s*$', body):
            text = r'\noindent ' + text
        result.append(text)
    if active:
        result.append('\\end{' + active + '}')
    return '\n\n'.join(result)


def selection_latex(native):
    from .replacement import source_destination
    if source_destination(native):
        return extract_body(native, allow_empty=True).text
    paragraphs = native_paragraphs(native)
    if all(p.layout == 'Standard' for p in paragraphs) and r'\begin_inset' not in native and not PAR_METADATA.search(native):
        return None
    return render_paragraphs(native)


def restore_objects(native, objects):
    """Replace only complete generated ERT nodes, never arbitrary native text."""
    def visit(body):
        for start, end, raw in reversed(list(body_insets(body))):
            value = text_of(raw).strip() if kind(raw) == 'ERT' else ''
            if value in objects:
                replacement = objects[value]
            else:
                split = raw.index('\n') + 1
                replacement = raw[:split] + visit(raw[split:raw.rindex(r'\end_inset')]) + '\\end_inset'
            body = body[:start] + replacement + body[end:]
        return body
    head, body = native.split(r'\begin_body', 1)
    return head + r'\begin_body' + visit(body)


def merge_metadata(original, converted):
    """Keep existing container/cell settings when its shape still matches.

    New content and native formulas come from tex2lyx. Original table borders,
    widths, box settings, float settings and paragraph spacing stay native.
    """
    def merge(old, new):
        old_by_kind, new_by_kind = defaultdict(list), defaultdict(list)
        def group(raw):
            return 'Box' if kind(raw).startswith('Box ') else kind(raw)
        for _, _, raw in body_insets(old):
            old_by_kind[group(raw)].append(raw)
        spans = list(body_insets(new))
        for start, end, raw in spans:
            new_by_kind[group(raw)].append((start, end, raw))
        changes = []
        for name, nodes in new_by_kind.items():
            previous = old_by_kind[name]
            if len(previous) != len(nodes):
                continue
            for base, (start, end, raw) in zip(previous, nodes):
                if name in ('ERT', 'CommandInset ref', 'CommandInset citation', 'CommandInset label') and text_of(base) == text_of(raw):
                    raw = base
                elif name == 'Tabular':
                    shapes = [re.search(r'<lyxtabular[^>]*rows="(\d+)" columns="(\d+)"', v) for v in (base, raw)]
                    old_cells = list(body_insets(base[base.index('\n')+1:base.rindex(r'\end_inset')]))
                    new_cells = list(body_insets(raw[raw.index('\n')+1:raw.rindex(r'\end_inset')]))
                    if all(shapes) and shapes[0].groups() == shapes[1].groups() and len(old_cells) == len(new_cells):
                        prefix, inner = base.split('\n', 1)
                        for (a, b, old_cell), (_, _, new_cell) in reversed(list(zip(old_cells, new_cells))):
                            inner = inner[:a] + merge(old_cell, new_cell) + inner[b:]
                        raw = prefix + '\n' + inner
                elif contents(base) and contents(raw):
                    new_inner = merge(contents(base), contents(raw))
                    if name == 'Box' or name.startswith(('Float ', 'Caption ')):
                        raw = base[:base.index(r'\begin_layout ')] + new_inner + '\\end_inset'
                    else:
                        raw = raw[:raw.index(r'\begin_layout ')] + new_inner + '\\end_inset'
                changes.append((start, end, raw))
        for start, end, raw in sorted(changes, reverse=True):
            new = new[:start] + raw + new[end:]
        # Match only outer paragraphs, after nested objects have been handled.
        old_ps, new_ps = native_paragraphs(wrap(old)), native_paragraphs(wrap(new))
        if len(old_ps) == len(new_ps):
            offset = 0
            for before, after in zip(old_ps, new_ps):
                if before.layout != after.layout:
                    continue
                metadata = PAR_METADATA.findall(before.body)
                if metadata:
                    updated = ''.join(metadata) + PAR_METADATA.sub('', after.body)
                    pos = new.find(after.body, offset)
                    if pos >= 0:
                        new = new[:pos] + updated + new[pos+len(after.body):]
                        offset = pos + len(updated)
        return new
    old_body = original.split(r'\begin_body', 1)[1].split(r'\end_body', 1)[0]
    head, new_body = converted.split(r'\begin_body', 1)
    new_body, tail = new_body.split(r'\end_body', 1)
    return head + r'\begin_body' + merge(old_body, new_body) + r'\end_body' + tail


def require_preserved(original, replacement, filename=None):
    """Never silently discard selected labels, resources, or opaque objects."""
    objects = protected_objects(original, filename)
    missing = Counter()
    representation = selection_latex(original) or ''
    # Unchanged text-only edits may omit annotation markers; existing annotation
    # filtering behavior is retained. Non-annotation objects must be explicit.
    for token, raw in objects.items():
        expected = max(1, representation.count(token))
        if not kind(raw).startswith(('Note ', 'Foot', 'Marginal')) and replacement.count(token) < expected:
            # Raw TeX is also accepted for an ordinary spacing inset.
            if kind(raw).startswith(('space ', 'VSpace', 'Newline ')):
                command = kind(raw).split(' ', 1)[1].replace('{}', '')
                if command.startswith('\\') and command in replacement:
                    continue
            missing[kind(raw)] += 1
    def find_labels(body):
        labels = []
        for _, _, raw in body_insets(body):
            # Labels inside an opaque object are already retained by its token.
            if opaque(raw):
                continue
            if kind(raw) == 'CommandInset label':
                labels.extend(re.findall(r'(?m)^name "([^"\n]+)"$', raw))
            elif kind(raw) == 'ERT' or kind(raw).startswith('Formula'):
                source = re.sub(r'(?m)(?<!\\)%[^\n]*', '', text_of(raw))
                labels.extend(re.findall(r'\\label\{([^{}]+)\}', source))
            else:
                labels.extend(find_labels(raw[raw.index('\n')+1:raw.rindex(r'\end_inset')]))
        return labels
    labels = find_labels(original.split(r'\begin_body', 1)[1].split(r'\end_body', 1)[0])
    replacement = re.sub(r'(?m)(?<!\\)%[^\n]*', '', replacement)
    for name in labels:
        if '\\label{' + name + '}' not in replacement:
            missing['label: ' + name] += 1
    if missing:
        raise ValueError('修改稿缺少原选区结构，请让 AI 保留后再应用： / Revision omitted selected structures; preserve them before applying: ' + ', '.join(missing))
    return objects
