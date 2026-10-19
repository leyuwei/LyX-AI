"""Shared math tokenization and safe native LyX replacement serialization."""
from __future__ import annotations

from dataclasses import dataclass
import re

from markdown_it import MarkdownIt


ENVIRONMENTS = r'equation\*?|displaymath|align\*?|aligned|alignat\*?|alignedat|flalign\*?|gather\*?|gathered|multline\*?|eqnarray\*?|split'
HULL = re.compile(r'\\begin\{(equation\*?|align\*?|alignat\*?|flalign\*?|gather\*?|multline\*?|eqnarray\*?)\}([\s\S]*)\\end\{\1\}')
MATH = re.compile(r'(?<!\\)(\$\$(.+?)\$\$|\\\[(.+?)\\\]|\\\((.+?)\\\)|\$(?!\$)([^\n$]+?)(?<!\\)\$|\\begin\{(' + ENVIRONMENTS + r')\}(.+?)\\end\{\6\})', re.S)


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
    kinds = re.findall(r'\\begin_inset ([^\n]+)', body)
    if any(kind != 'Formula' and not kind.startswith('Formula ') for kind in kinds) or r'\change_' in body:
        raise ValueError('目标含备注、脚注、引用或其他结构对象，不能无损重建；请缩小到正文及完整公式。 / Target contains structural objects; select prose and complete formulas only.')
    if re.search(r'\\begin_layout (?:Plain Layout|Code|LyX-Code|Verbatim)', body):
        raise ValueError('请在主正文中选取完整文本和公式，不能替换嵌套对象内部。 / Select main body prose, not an inset interior.')
    layouts = re.findall(r'\\begin_layout ([^\n]+)', body)
    if not layouts or len(set(layouts)) != 1 or r'\begin_deeper' in body:
        raise ValueError('目标跨越不同布局，请分段应用。 / Apply separately to each paragraph layout.')
    initial_style = []
    first = body.split('\\begin_layout ' + layouts[0], 1)[1].split('\n', 1)[1]
    for line in first.splitlines():
        if not line.strip():
            continue
        if re.fullmatch(r'\\(?:lang|series|shape|family|size|color|emph) [\w-]+', line):
            initial_style.append(line)
        elif not line.startswith('\\') or line.startswith('\\begin_inset'):
            break
    math = []
    protected = []
    for part in math_parts(replacement):
        if isinstance(part, Math):
            if re.search(r'\\(?:input|include|includegraphics|write|openout|read|catcode|csname|usepackage|documentclass|special|href|url)(?![A-Za-z])|\\(?:begin|end)_[A-Za-z]+|\\(?:begin|end)\{document\}', part.tex, re.I):
                raise ValueError('公式包含不支持的文件、链接或执行命令。 / Unsupported command in formula.')
            if not part.tex:
                raise ValueError('Empty formula')
            math.append(part)
            protected.append(f'LYXAIMATHPLACEHOLDER{len(math)-1}END')
        else:
            if 'LYXAIMATHPLACEHOLDER' in part:
                raise ValueError('Reserved placeholder in replacement')
            if not part.startswith(('`', '~~~')) and re.search(r'\\(?:begin|end)\{(?:' + ENVIRONMENTS + r')\}|\\[\[\]]', part):
                raise ValueError('公式定界符或环境不完整，请补全后再应用。 / Incomplete math environment or delimiter.')
            protected.append(part)
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

    result = []
    for paragraph in paragraphs:
        chunks = []
        for item in re.split(r'(LYXAIMATHPLACEHOLDER\d+END)', paragraph):
            if re.fullmatch(r'LYXAIMATHPLACEHOLDER\d+END', item):
                value = math[int(item[len('LYXAIMATHPLACEHOLDER'):-3])]
                formula = formula_source(value)
                chunks.append('\n\\begin_inset Formula ' + formula + '\n\\end_inset\n\n')
            else:
                chunks.append(plain(item))
        result.append('\\begin_layout ' + layouts[0] + '\n' + '\n'.join(initial_style) + '\n' + ''.join(chunks) + '\n\\end_layout\n')
    return original.split(r'\begin_body', 1)[0] + '\\begin_body\n\n' + '\n'.join(result) + '\n\\end_body\n\\end_document\n'
