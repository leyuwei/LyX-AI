"""Preflight LaTeX conversion outside LyX; paste only validated native data."""
from pathlib import Path
import os
import re
import subprocess
import sys
import tempfile

from .integration import default_lyx_dir, default_user_dir


def support_dir():
    return default_lyx_dir() / 'Resources'


def layout_configuration(document, user_dir=None):
    """Resolve installed class/module declarations without changing the document.

    Dependencies are alternatives, exclusions work in both directions, and
    class-provided functionality has precedence over optional modules.
    """
    document = document.replace('\r\n', '\n')
    user_dir = Path(user_dir or default_user_dir())
    roots = [user_dir / 'layouts', support_dir() / 'layouts']
    class_match = re.search(r'(?m)^\\textclass ([\w.-]+)$', document)
    textclass = class_match[1] if class_match else 'article'
    layouts, provided, excluded, defaults = {}, set(), set(), []
    visiting = set()
    sources = {}

    def locate(name):
        if Path(name).name != name:
            return None
        return next((root / name for root in roots if (root / name).is_file()), None)

    def read(name):
        path = locate(name)
        if path and path not in visiting:
            visiting.add(path)
            try:
                parse(source(path))
            finally:
                visiting.remove(path)

    def source(path):
        if path not in sources:
            sources[path] = path.read_text(encoding='utf-8-sig')
        return sources[path]

    def parse(text):
        active = None
        argument = False
        literal = None
        for line in text.splitlines():
            stripped = line.strip()
            if literal:
                if stripped in ('EndPreamble', 'End' + literal):
                    literal = None
                continue
            if stripped.startswith('#'):
                continue
            if re.fullmatch(r'(?:AddTo)?(?:HTML|Lang|Babel|DocBook)?Preamble', stripped):
                literal = stripped
                continue
            match = re.match(r'Input\s+"?([^"\s]+)', stripped)
            if match:
                read(match[1])
            match = re.match(r'ProvidesModule\s+(\S+)', stripped)
            if match:
                provided.add(match[1])
            match = re.match(r'ExcludesModule\s+(\S+)', stripped)
            if match:
                excluded.add(match[1])
            match = re.match(r'DefaultModule\s+(\S+)', stripped)
            if match and match[1] not in defaults:
                defaults.append(match[1])
            match = re.match(r'NoStyle\s+(.+)', stripped)
            if match:
                layouts.pop(match[1].strip('"'), None)
                active = None
            match = re.match(r'(?:Style|ModifyStyle)\s+(.+)', stripped)
            if match:
                active = match[1].strip('"')
                argument = False
            elif re.match(r'(?:InsetLayout|Float|Counter|ClassOptions)\b', stripped):
                active = None
            elif active:
                if re.match(r'Argument\s+', stripped):
                    argument = True
                elif stripped == 'EndArgument':
                    argument = False
                if argument:
                    continue
                copy = re.match(r'CopyStyle\s+(.+)', stripped)
                latex = re.match(r'LatexName\s+(.+)', stripped, re.I)
                if copy and copy[1].strip('"') in layouts:
                    layouts[active] = layouts[copy[1].strip('"')]
                if latex:
                    layouts[active] = latex[1].strip('"')
                if stripped == 'End':
                    active = None

    read(textclass + '.layout')
    local = re.search(r'\\begin_local_layout\n([\s\S]*?)\\end_local_layout', document)
    if local:
        parse(local[1])  # Local class-level declarations affect module selection.
    modules = re.search(r'\\begin_modules\n([\s\S]*?)\\end_modules', document)
    requested = list(dict.fromkeys(modules[1].split())) if modules else []
    removed = re.search(r'\\begin_removed_modules\n([\s\S]*?)\\end_removed_modules', document)
    removed = set(removed[1].split()) if removed else set()
    metadata = {}

    def module_info(module, required=False):
        path = locate(module + '.module')
        if not path and required:
            raise ValueError('找不到 LyX 模块，原文未修改。 / LyX module not found; document unchanged: ' + module)
        if module in metadata:
            return metadata[module]
        text = source(path) if path else ''
        def field(name):
            match = re.search(r'(?m)^[ \t]*#+[ \t]*' + name + r':[ \t]*([^\r\n]*)', text)
            return set(filter(None, re.split(r'[\s|]+', match[1]))) if match else set()
        metadata[module] = field('Requires'), field('Excludes')
        return metadata[module]

    def conflicts(first, second):
        return second in module_info(first)[1] or first in module_info(second)[1]

    blocked = set(excluded) | (removed - set(requested))
    candidates = []
    for module in requested:
        if module in provided:
            continue
        module_info(module, required=True)
        if module in excluded or any(conflicts(module, p) for p in provided):
            blocked.add(module)
        else:
            candidates.append(module)
    accepted_defaults = []
    for module in defaults:
        if module in candidates or module in provided or module in removed:
            continue
        module_info(module, required=True)
        if module in excluded or any(conflicts(module, p) for p in provided | set(candidates) | set(accepted_defaults)):
            blocked.add(module)
        else:
            accepted_defaults.append(module)
    candidates = accepted_defaults + candidates
    # Remove dependants of class-incompatible modules to a fixed point. A
    # missing, never-selected dependency is an error, not a reason to lose data.
    changed = True
    while changed:
        changed = False
        for module in list(candidates):
            requires = module_info(module)[0]
            if requires and not requires & (provided | set(candidates)) and requires & blocked:
                candidates.remove(module)
                blocked.add(module)
                changed = True
    for i, module in enumerate(candidates):
        for other in candidates[i+1:]:
            if conflicts(module, other):
                raise ValueError('LyX 模块互斥，原文未修改。 / Conflicting LyX modules; document unchanged: ' + module + ' / ' + other)
        requires = module_info(module)[0]
        if requires and not requires & (provided | set(candidates)):
            raise ValueError('LyX 模块缺少依赖，原文未修改。 / Missing LyX module dependency; document unchanged: ' + module + ' -> ' + ' | '.join(sorted(requires)))
    enabled = []
    while candidates:
        ready = next((m for m in candidates if not module_info(m)[0] or module_info(m)[0] & (provided | set(enabled))), None)
        if ready is None:
            raise ValueError('LyX 模块存在循环依赖，原文未修改。 / Cyclic LyX module dependencies; document unchanged: ' + ', '.join(candidates))
        candidates.remove(ready)
        enabled.append(ready)
        read(ready + '.module')
    if local:
        parse(local[1])  # Local style overrides must remain last.
    return textclass, enabled, layouts


def normalize_environments(text, document, user_dir=None):
    from .replacement import THEOREMS
    _, _, layouts = layout_configuration(document, user_dir)
    aliases = {}
    actual = set(layouts.values())
    for name, environment in layouts.items():
        for alias in (name.lower(), re.sub(r'[\s_]+', '', name).lower()):
            if re.fullmatch(r'[\w:-]+\*?', alias) and alias not in actual:
                aliases[alias] = environment
    for name, default in THEOREMS.items():
        environment = layouts.get(name.title())
        if environment:
            aliases[name] = aliases[default] = environment
    return re.sub(r'\\(begin|end)\{([\w:-]+\*?)\}',
                  lambda m: '\\' + m[1] + '{' + aliases.get(m[2], m[2]) + '}', text)


def convert_latex(text, document, user_dir=None, timeout=20):
    """No shell, no TeX execution, no mutation of the live buffer on failure."""
    from .replacement import native_paragraphs
    textclass, modules, layouts = layout_configuration(document, user_dir)
    binary = default_lyx_dir() / ('MacOS/tex2lyx' if sys.platform == 'darwin' else 'bin/tex2lyx.exe')
    if not binary.is_file():
        raise ValueError('找不到 LyX 的 tex2lyx 转换器。 / LyX tex2lyx converter was not found: ' + str(binary))
    with tempfile.TemporaryDirectory(prefix='lyxai-import-') as tmp:
        folder = Path(tmp)
        source, output = folder / 'revision.tex', folder / 'revision.lyx'
        # Declare the provenance macro's arity so tex2lyx keeps the entire
        # command as one ERT node. This file is parser metadata, never executed.
        syntax = folder / 'syntax'
        syntax.write_text('\\lyxaiobject{}\n', encoding='utf-8')
        # These comments are generated request hints. tex2lyx otherwise keeps
        # them as extra ERT objects alongside the restored resource.
        normalized = normalize_environments(re.sub(r'(?m)% LyX [^\n]*', '', text), document, user_dir)
        source.write_text(normalized, encoding='utf-8')
        command = [str(binary), '-fixedenc', 'utf8', '-c', textclass, '-s', str(syntax)]
        if user_dir:
            command += ['-userdir', str(user_dir)]
        if modules:
            command += ['-m', ','.join(modules)]
        command += ['-f', str(source), str(output)]
        env = dict(os.environ)
        if sys.platform == 'win32':
            env['PATH'] = ';'.join((str(binary.parent), str(Path(os.environ['WINDIR']) / 'System32'), os.environ['WINDIR']))
        try:
            result = subprocess.run(command, cwd=folder, env=env, capture_output=True,
                                    timeout=timeout, creationflags=0x08000000 if sys.platform == 'win32' else 0)
        except subprocess.TimeoutExpired as exc:
            raise ValueError('LaTeX 转换超时，原文未修改。 / LaTeX conversion timed out; document unchanged.') from exc
        if result.returncode or not output.is_file() or not output.stat().st_size:
            detail = result.stderr.decode('utf-8', 'replace').replace(str(folder), '<temporary>')
            raise ValueError('LaTeX 转换失败，原文未修改。 / LaTeX conversion failed; document unchanged.\n' + detail[-2000:])
        converted = output.read_text(encoding='utf-8-sig')
    native_paragraphs(converted)
    if r'\end_document' not in converted or not native_paragraphs(converted):
        raise ValueError('Invalid converter output; document unchanged / 转换结果无效，原文未修改')
    clean = re.sub(r'(?m)(?<!\\)%[^\n]*', '', normalized)
    for environment in set(re.findall(r'\\begin\{([\w*:-]+)\}', clean)):
        names = [name for name, env in layouts.items() if env == environment]
        if names and not any('\\begin_layout ' + name + '\n' in converted for name in names):
            if '\\begin_inset Float ' + environment.rstrip('*') not in converted:
                raise ValueError('布局未能转换为原生对象，原文未修改。 / Layout was not converted to a native object; document unchanged: ' + environment)
    for name in re.findall(r'\\label\{([^{}]+)\}', clean):
        if 'name "' + name + '"' not in converted and '\\label{' + name + '}' not in converted:
            raise ValueError('标签转换失败，原文未修改。 / Label conversion failed; document unchanged: ' + name)
    # The destination's class, modules, language and preamble remain authoritative.
    header = document.split(r'\begin_body', 1)[0]
    header = re.sub(r'\\begin_modules\n[\s\S]*?\\end_modules',
                    lambda _: '\\begin_modules\n' + '\n'.join(modules) + '\n\\end_modules' if modules else '', header)
    return header + r'\begin_body' + converted.split(r'\begin_body', 1)[1]
