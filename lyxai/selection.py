"""Extract prose from a structured LyX clipboard fragment, never from rendered notes."""
from __future__ import annotations

from dataclasses import dataclass
import re


@dataclass
class BodySelection:
    text: str
    excluded: int = 0


def reference_text(kind, params):
    """Keep reference commands and keys intact during the AI round trip."""
    citation = kind == 'CommandInset citation'
    key = params.get('key' if citation else 'reference', '')
    if not key:
        return ''
    command = params.get('command', 'cite' if citation else 'ref')
    options = ''
    if citation:
        before, after = params.get('before', ''), params.get('after', '')
        if before:
            options = '[' + before + '][' + after + ']'
        elif after:
            options = '[' + after + ']'
    elif params.get('nolink') == 'true':
        command += '*'
    return '\\' + command + options + '{' + key + '}'


def extract_body(source: str, include_ert=False) -> BodySelection:
    """Read LyX paragraphs and a small, explicit set of inline insets.

    Unknown block insets are omitted, rather than guessed to be body prose.
    Notes/footnotes/margin notes/figures/tables/branches are never traversed.
    """
    if len(source) > 16_000_000:
        raise ValueError("LyX selection is too large / 选区过大，请缩小范围")
    lines = source.replace("\r\n", "\n").splitlines()
    try:
        begin = next(i for i, line in enumerate(lines) if line.strip() == r"\begin_body")
        end = next(i for i in range(begin + 1, len(lines)) if lines[i].strip() == r"\end_body")
    except StopIteration:
        raise ValueError("Invalid structured LyX clipboard / 缺少完整的 LyX 结构化选区") from None
    stack = []
    output = []
    excluded = 0
    layout_depth = 0
    deleted = False
    for line in lines[begin + 1:end]:
        stripped = line.strip()
        suppressed = any(frame[0] for frame in stack)
        if stripped.startswith(r"\begin_inset "):
            kind = stripped[len(r"\begin_inset "):]
            keep = (include_ert and kind == 'ERT') or kind == 'Formula' or kind.startswith(("Formula ", "Quotes ", "space ", "Newline ", "CommandInset citation", "CommandInset ref", "Flex "))
            if not keep and not suppressed:
                excluded += 1
            stack.append((suppressed or not keep, kind, {}))
            if len(stack) > 128:
                raise ValueError("LyX inset nesting exceeds supported depth / 选区嵌套过深")
            if not any(frame[0] for frame in stack) and not deleted:
                if kind == 'Formula' or kind.startswith("Formula "):
                    output.append(kind[len("Formula "):])
                elif kind.startswith("Quotes "):
                    output.append('"')
                elif kind.startswith("space "):
                    output.append(" ")
                elif kind.startswith("Newline "):
                    output.append("\n")
            continue
        if stripped == r"\end_inset":
            if not stack:
                raise ValueError("Unbalanced LyX inset / LyX 选区结构不完整")
            hidden, kind, params = stack.pop()
            if not hidden and not deleted and kind in ('CommandInset citation', 'CommandInset ref'):
                output.append(reference_text(kind, params))
            continue
        if suppressed:
            continue
        if stripped.startswith(r"\begin_layout "):
            layout_depth += 1
            continue
        if stripped == r"\end_layout":
            if not layout_depth:
                raise ValueError("Unbalanced LyX paragraph / 段落结构不完整")
            layout_depth -= 1
            if not stack:
                output.append("\n\n")
                deleted = False
            elif include_ert and stack[-1][1] == 'ERT':
                output.append('\n')
            continue
        if stripped.startswith(r"\change_deleted"):
            deleted = True
            continue
        if stripped.startswith((r"\change_unchanged", r"\change_inserted")):
            deleted = False
            continue
        if deleted:
            continue
        if stack:
            if stack[-1][1] == 'Formula' or stack[-1][1].startswith("Formula "):
                output.append("\n" + line)
                continue
            if stripped.startswith('LatexCommand '):
                stack[-1][2]['command'] = stripped.split(' ', 1)[1]
                continue
            match = re.fullmatch(r'(key|reference|before|after|nolink) "(.*)"', stripped)
            if match:
                stack[-1][2][match[1]] = match[2]
                continue
            if stripped.startswith(("status ", "LatexCommand ", "literal ", "name ", "plural ", "caps ", "nolink ")) or re.match(r'^[a-z_]+ "', stripped):
                continue
        if stripped == r"\backslash":
            output.append("\\")
        elif stripped.startswith(r"\SpecialChar "):
            char = stripped[len(r"\SpecialChar "):]
            output.append({"LyX": "LyX", "LaTeX": "LaTeX", "TeX": "TeX", "ldots": "…", "menuseparator": " → ", "nobreakdash": "-"}.get(char, ""))
        elif stripped.startswith((r"\begin_deeper", r"\end_deeper", r"\paragraph_spacing")):
            continue
        elif stripped.startswith("\\"):
            # Font/language/layout metadata must not become part of the prompt.
            continue
        elif layout_depth or stack:
            output.append(line)
    if stack or layout_depth:
        raise ValueError("Incomplete LyX selection / LyX 选区结构不完整")
    text = "".join(output)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    if not text:
        raise ValueError("No body text in selection / 选区中没有正文，备注和脚注不会加入")
    return BodySelection(text, excluded)


def compose_context(target: str, before: str = "", after: str = "") -> str:
    """User text is data. Context is explicitly separate from the edit target."""
    if not before.strip() and not after.strip():
        return target
    sections = ["以下前后文仅供理解，请只修改【问询原文】。\nContext is reference only; revise only the target passage."]
    if before.strip():
        sections.append("【前文 / Before】\n" + before.strip())
    sections.append("【问询原文 / Target】\n" + target)
    if after.strip():
        sections.append("【后文 / After】\n" + after.strip())
    return "\n\n".join(sections)
