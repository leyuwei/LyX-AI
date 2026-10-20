"""Shared math tokenization and safe native LyX replacement serialization."""
from __future__ import annotations

from dataclasses import dataclass
import re

from markdown_it import MarkdownIt
from .selection import extract_body, reference_text


ENVIRONMENTS = r'equation\*?|displaymath|align\*?|aligned|alignat\*?|alignedat|flalign\*?|gather\*?|gathered|multline\*?|eqnarray\*?|split'
HULL = re.compile(r'\\begin\{(equation\*?|align\*?|alignat\*?|flalign\*?|gather\*?|multline\*?|eqnarray\*?)\}([\s\S]*)\\end\{\1\}')
MATH = re.compile(r'(?<!\\)(\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$(?!\$)([^\n$]+?)(?<!\\)\$|\\begin\{(' + ENVIRONMENTS + r')\}(.+?)\\end\{\6\})', re.S)
REF_COMMANDS = r'eqref|ref|pageref|vref|vpageref|nameref|prettyref|formatted|labelonly'
CITE_COMMANDS = r'cite|citep|citet|citealt|citealp|citeauthor|citeyear|citeyearpar|parencite|textcite|autocite|footcite|smartcite|supercite|Citep|Citet|Citeauthor|Parencite|Textcite|Autocite'
REFERENCE = re.compile(r'(?<!\\)\\(' + REF_COMMANDS + '|' + CITE_COMMANDS + r')(\*)?\s*(?:\[([^\[\]\r\n]*)\]\s*)?(?:\[([^\[\]\r\n]*)\]\s*)?\{([^{}\r\n]*)\}')
THEOREMS = {'theorem': 'thm', 'lemma': 'lem', 'corollary': 'cor', 'proposition': 'prop',
            'definition': 'defn', 'remark': 'rem', 'example': 'example', 'proof': 'proof',
            'claim': 'claim', 'conjecture': 'conjecture', 'fact': 'fact'}
UNSAFE_TEX = re.compile(r'\\(?:input|include|includegraphics|write\d*|openout|openin|read|catcode|csname|usepackage|documentclass|special|href|url|directlua|latelua|def|gdef|edef|xdef|let|newcommand|renewcommand)(?![A-Za-z])|\\(?:begin|end)_[A-Za-z]+|\\(?:begin|end)\{document\}', re.I)


def latex_input(text, document, user_dir=None):
    """Use LyX's own LaTeX importer for structure and text formatting commands."""
    text, fences = re.subn(r'(?m)^[ \t]*```(?:latex|tex)[ \t]*\n([\s\S]*?)^[ \t]*```[ \t]*$', r'\1', text)
    source = bool(fences)
    if source:
        text = text.strip()
    if not source and re.search(r'(?m)^\s*(?:```|~~~)', text):
        return None
    # Math and references already have a lossless native serializer. Other TeX
    # commands require the native importer, not escaped backslashes in prose.
    outside_math = ''.join(part for part in math_parts(text) if isinstance(part, str) and not part.startswith(('`', '~~~')))
    if not source and not re.search(r'(?<!\\)\\(?:[A-Za-z]+|[\\#$%&_{}~^ ,;:!])', REFERENCE.sub('', outside_math)):
        return None
    validate_tex(text)
    clean = re.sub(r'(?m)(?<!\\)%[^\n]*', '', text)
    braces = 0
    for token in re.findall(r'\\(?:[A-Za-z]+|.)|[{}]', clean):
        if token in ('{', '}'):
            braces += 1 if token == '{' else -1
            if braces < 0:
                raise ValueError('LaTeX 花括号不匹配。 / Unbalanced LaTeX braces.')
    if braces:
        raise ValueError('LaTeX 花括号不完整。 / Incomplete LaTeX braces.')
    for part in math_parts(clean):
        if isinstance(part, str) and not part.startswith(('`', '~~~')) and re.search(r'(?<!\\)\$|\\[\[\]()]', part):
            raise ValueError('公式定界符不完整。 / Incomplete math delimiter.')
    stack = []
    for token in re.finditer(r'(?<!\\)\\(begin|end)\{([\w*:-]+)\}', re.sub(r'(?m)(?<!\\)%[^\n]*', '', text)):
        if token[1] == 'begin':
            stack.append(token[2])
        elif not stack or stack.pop() != token[2]:
            raise ValueError('LaTeX 环境不匹配。 / Unbalanced LaTeX environment.')
    if stack:
        raise ValueError('LaTeX 环境不完整。 / Incomplete LaTeX environment.')
    environments = re.findall(r'\\begin\{([\w*:-]+)\}', outside_math)
    if any(env.rstrip('*') in set(THEOREMS) | set(THEOREMS.values()) for env in environments):
        document = document() if callable(document) else document
        from .latex_import import normalize_environments, layout_configuration
        layouts = layout_configuration(document, user_dir)[2]
        available = set(layouts.values()) | {name.lower() for name in layouts}
        missing = [env for env in environments if env.rstrip('*') in set(THEOREMS) | set(THEOREMS.values())
                   and env not in available and not any(THEOREMS.get(name.lower()) == env for name in layouts)]
        if missing:
            raise ValueError('当前文档缺少相应布局，请启用匹配模块（例如 AMS Theorems）。 / Enable a matching module (e.g. AMS Theorems); unavailable layout: ' + ', '.join(missing))
        text = normalize_environments(text, document, user_dir)
    # A standalone aligned/split block needs a display hull in imported LaTeX.
    return ''.join(formula_source(part) if isinstance(part, Math) else part for part in math_parts(text))


def validate_tex(text):
    if not text.strip() or len(text) > 200_000 or '\0' in text:
        raise ValueError('LaTeX is empty or too long / LaTeX 为空或过长')
    if UNSAFE_TEX.search(re.sub(r'(?m)(?<!\\)%[^\n]*', '', text)):
        raise ValueError('LaTeX 包含不支持的文件、链接、宏定义或执行命令。 / Unsupported file, link, macro definition or execution command in LaTeX.')


def source_destination(native):
    body = native.split(r'\begin_body', 1)[1].split(r'\end_body', 1)[0]
    spans = list(body_insets(body))
    outer = body
    for start, end, raw in reversed(spans):
        outer = outer[:start] + outer[end:]
    layouts = re.findall(r'\\begin_layout ([^\n]+)', outer)
    if layouts and set(layouts) == {'Plain Layout'} and r'\backslash' in outer:
        return 'interior'
    if len(layouts) == 1 and len(spans) == 1 and spans[0][2].startswith('\\begin_inset ERT\n') and not re.sub(r'(?m)^\\[^\n]*|\s+', '', outer):
        return 'object'
    return None


def source_fragment(original, replacement, destination):
    """Keep editable ERT source as source, including real TeX line breaks."""
    source = re.fullmatch(r'\s*```(?:latex|tex)\s*\n([\s\S]*?)\n```\s*', replacement)
    replacement = source[1] if source else replacement
    validate_tex(replacement)
    paragraphs = ''.join('\\begin_layout Plain Layout\n' + line.replace('\\', '\n\\backslash\n') + '\n\\end_layout\n' for line in replacement.split('\n'))
    if destination == 'object':
        paragraphs = '\\begin_layout Standard\n\\begin_inset ERT\nstatus open\n\n' + paragraphs + '\\end_inset\n\\end_layout\n'
    return original.split(r'\begin_body', 1)[0] + '\\begin_body\n' + paragraphs + '\\end_body\n\\end_document\n'


def body_insets(body):
    """Return complete outer insets, excluding their nested paragraph layouts."""
    depth = 0
    start = 0
    for match in re.finditer(r'(?m)^\\(begin_inset [^\n]+|end_inset)[ \t]*$', body):
        if match[1].startswith('begin_inset '):
            if depth == 0:
                start = match.start()
            depth += 1
        else:
            depth -= 1
            if depth < 0:
                raise ValueError('Unbalanced LyX inset')
            if depth == 0:
                yield start, match.end(), body[start:match.end()]
    if depth:
        raise ValueError('Incomplete LyX inset')


@dataclass
class NativeParagraph:
    layout: str
    body: str
    depth: int = 0


def native_paragraphs(native):
    """Read outer paragraph boundaries without confusing layouts inside ERT."""
    body = native.split(r'\begin_body', 1)[1].split(r'\end_body', 1)[0]
    list(body_insets(body))  # Validate complete inset nesting before using it.
    paragraphs, lines = [], []
    inset_depth = depth = 0
    layout = None
    for line in body.splitlines(keepends=True):
        token = line.strip()
        if token.startswith(r'\begin_inset '):
            inset_depth += 1
        elif token == r'\end_inset':
            inset_depth -= 1
            lines.append(line)
            continue
        if inset_depth:
            lines.append(line)
        elif token.startswith(r'\begin_layout '):
            if layout is not None:
                raise ValueError('Unbalanced LyX paragraph')
            layout, lines = token[len(r'\begin_layout '):], []
        elif token == r'\end_layout':
            if layout is None:
                raise ValueError('Unbalanced LyX paragraph')
            paragraphs.append(NativeParagraph(layout, ''.join(lines), depth))
            layout, lines = None, []
        elif token in (r'\begin_deeper', r'\end_deeper'):
            depth += 1 if token == r'\begin_deeper' else -1
            if not 0 <= depth <= 128:
                raise ValueError('Invalid LyX paragraph depth')
        elif layout is not None:
            lines.append(line)
    if layout is not None or depth:
        raise ValueError('Incomplete LyX paragraph structure')
    return paragraphs


def paragraph_boundaries(paragraphs):
    """Empty edge paragraphs carry unselected prefix/suffix layout on paste."""
    def empty(p):
        return r'\begin_inset' not in p.body and not re.sub(r'(?m)^\\[^\n]*|\s+', '', p.body)
    start, end = 0, len(paragraphs)
    while end - start > 1 and empty(paragraphs[start]):
        start += 1
    while end - start > 1 and empty(paragraphs[end - 1]):
        end -= 1
    return paragraphs[:start], paragraphs[start:end], paragraphs[end:]


def structured_selection(native):
    """Give AI all selected document structures, including nested objects."""
    from .structure import selection_latex
    return selection_latex(native)


def reference_inset(match):
    command, star, first, second, key = match.groups()
    citation = re.fullmatch(CITE_COMMANDS, command) is not None
    if not key.strip() or any(c in key for c in '\\"\0'):
        raise ValueError('Invalid citation or reference key / 引用标签无效')
    if not citation and (first is not None or second is not None):
        raise ValueError('Unsupported reference options / 引用选项不支持')
    if any(c in (first or '') + (second or '') for c in '\\{}"\0'):
        raise ValueError('Citation notes must be plain text / 文献引用附注须为纯文本')
    if citation:
        options = ('before "' + first + '"\nafter "' + second + '"\n') if second is not None else ('after "' + first + '"\n' if first is not None else '')
        return '\\begin_inset CommandInset citation\nLatexCommand ' + command + (star or '') + '\n' + options + 'key "' + key + '"\nliteral "true"\n\\end_inset'
    return '\\begin_inset CommandInset ref\nLatexCommand ' + command + '\nreference "' + key + '"\nnolink "' + ('true' if star else 'false') + '"\n\\end_inset'


@dataclass
class Math:
    tex: str
    display: bool


def math_parts(text):
    """Do not interpret delimiters inside Markdown code spans/fences."""
    parts = []
    for code in re.split(r'(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`)', text):
        if code.startswith(('`', '~~~')):
            parts.append(code)
            continue
        end = 0
        for match in MATH.finditer(code):
            parts.append(code[end:match.start()])
            tex = next(v for v in (match[2], match[3], match[4], match[5], match[7]) if v is not None)
            if match[6] and match[6] != 'displaymath':
                # Keep alignment, per-row numbering and labels inside the native
                # environment. Wrapping an align hull in \[...\] is invalid.
                tex = match[0]
            parts.append(Math(tex.strip(), match[2] is not None or match[3] is not None or match[7] is not None))
            end = match.end()
        parts.append(code[end:])
    return parts


def formula_source(value):
    tex = value.tex.strip()
    if value.display and HULL.fullmatch(tex):
        return tex
    if value.display:
        return '\\[\n' + tex + '\n\\]'
    return '$' + tex + '$'


def preview_tex(tex):
    # KaTeX cannot resolve document labels. Keep them in native writeback only.
    tex = re.sub(r'\\label\s*\{[^{}]*\}', '', tex)
    # KaTeX supports aligned/gathered but not the multline display environment.
    return re.sub(r'\\(begin|end)\{multline\*?\}', lambda m: '\\' + m[1] + '{gathered}', tex)


def revised_text(answer):
    matches = re.findall(r'\[REVISED\]\s*([\s\S]*?)\s*\[/REVISED\]', answer)
    return matches[0].strip() if len(matches) == 1 else ''


def replacement_fragment(original, replacement):
    if not replacement.strip() or len(replacement) > 200_000 or '\0' in replacement:
        raise ValueError('替换正文为空或过长。 / Replacement is empty or too long.')
    body = original.split(r'\begin_body', 1)[1].split(r'\end_body', 1)[0]
    insets = list(body_insets(body))
    existing_refs = {}
    for start, end, raw in reversed(insets):
        kind = raw.split('\n', 1)[0][len('\\begin_inset '):]
        if kind in ('CommandInset citation', 'CommandInset ref'):
            params = dict(re.findall(r'(?m)^(key|reference|before|after|nolink) "(.*)"$', raw))
            command = re.search(r'(?m)^LatexCommand (.+)$', raw)
            if command:
                params['command'] = command[1]
            existing_refs[reference_text(kind, params)] = raw
        body = body[:start] + body[end:]
    if r'\change_' in body:
        raise ValueError('请先接受或拒绝修订，再应用改写。 / Accept or reject tracked changes before applying.')
    if re.search(r'\\begin_layout (?:Code|LyX-Code|Verbatim)', body):
        raise ValueError('请在主正文中选取完整文本和公式，不能替换嵌套对象内部。 / Select main body prose, not an inset interior.')
    leading, originals, trailing = paragraph_boundaries(native_paragraphs(original))
    if not originals:
        raise ValueError('No LyX paragraphs in destination')
    objects = []
    protected = []
    if 'LYXAIMATHPLACEHOLDER' in replacement:
        raise ValueError('Reserved placeholder in replacement')

    def stash(raw):
        objects.append(raw)
        return f'LYXAIMATHPLACEHOLDER{len(objects)-1}END'

    def protect_reference(match):
        return stash(existing_refs.get(match[0]) or reference_inset(match))

    for part in math_parts(replacement):
        if isinstance(part, Math):
            if re.search(r'\\(?:input|include|includegraphics|write|openout|read|catcode|csname|usepackage|documentclass|special|href|url)(?![A-Za-z])|\\(?:begin|end)_[A-Za-z]+|\\(?:begin|end)\{document\}', part.tex, re.I):
                raise ValueError('公式包含不支持的文件、链接或执行命令。 / Unsupported command in formula.')
            if not part.tex:
                raise ValueError('Empty formula')
            protected.append(stash('\\begin_inset Formula ' + formula_source(part) + '\n\\end_inset'))
        else:
            if not part.startswith(('`', '~~~')) and re.search(r'\\(?:begin|end)\{(?:' + ENVIRONMENTS + r')\}|\\[\[\]]', part):
                raise ValueError('公式定界符或环境不完整，请补全后再应用。 / Incomplete math environment or delimiter.')
            protected.append(REFERENCE.sub(protect_reference, part) if not part.startswith(('`', '~~~')) else part)
    tokens = MarkdownIt('commonmark', {'html': False}).parse(''.join(protected))
    paragraphs = []
    for token in tokens:
        if token.type in ('fence', 'code_block', 'html_block'):
            raise ValueError('请移除代码围栏，仅保留待替换正文。 / Remove code fences from replacement.')
        if token.type == 'inline':
            text = ''
            for child in token.children or []:
                if child.type in ('text', 'code_inline'):
                    text += child.content
                elif child.type in ('softbreak', 'hardbreak'):
                    text += '\n'
                elif child.type == 'image':
                    raise ValueError('Images cannot be inserted as prose')
            paragraphs.append(text)
    if not paragraphs:
        raise ValueError('No replacement prose')

    def plain(text):
        # Every source backslash is escaped as a LyX text character, preventing
        # model-supplied \end_layout/\begin_inset from becoming native syntax.
        return text.replace('\\', '\n\\backslash\n')

    result, depth = [], 0
    matched = len(paragraphs) == len(originals)
    uniform = len({(p.layout, p.depth) for p in originals}) == 1
    pairs = [('', p, True, True) for p in leading]
    pairs.extend((text, originals[i] if matched else originals[0] if uniform else NativeParagraph('Standard', ''),
                  matched or i == 0, matched) for i, text in enumerate(paragraphs))
    pairs.extend(('', p, True, True) for p in trailing)
    for paragraph, base, keep_metadata, keep_depth in pairs:
        target_depth = base.depth if keep_depth else 0
        while depth != target_depth:
            result.append('\\begin_deeper\n' if depth < target_depth else '\\end_deeper\n')
            depth += 1 if depth < target_depth else -1
        styles = []
        for line in base.body.splitlines():
            if not line.strip():
                continue
            if re.fullmatch(r'\\(?:lang|series|shape|family|size|color|emph) [\w-]+|\\(?:paragraph_spacing|noindent|indent|leftindent|align)\b[^\n]*', line):
                styles.append(line)
            elif not line.startswith('\\') or line.startswith('\\begin_inset'):
                break
        metadata = ''.join(raw + '\n' for _, _, raw in body_insets(base.body)
                           if raw.startswith(('\\begin_inset Argument ', '\\begin_inset CommandInset label\n'))) if keep_metadata else ''
        chunks = []
        for item in re.split(r'(LYXAIMATHPLACEHOLDER\d+END)', paragraph):
            if re.fullmatch(r'LYXAIMATHPLACEHOLDER\d+END', item):
                chunks.append('\n' + objects[int(item[len('LYXAIMATHPLACEHOLDER'):-3])] + '\n\n')
            else:
                chunks.append(plain(item))
        result.append('\\begin_layout ' + base.layout + '\n' + '\n'.join(styles) + '\n' + metadata + ''.join(chunks) + '\n\\end_layout\n')
    result.extend('\\end_deeper\n' for _ in range(depth))
    return original.split(r'\begin_body', 1)[0] + '\\begin_body\n\n' + '\n'.join(result) + '\n\\end_body\n\\end_document\n'
