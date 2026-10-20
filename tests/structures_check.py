"""Explicit native structure checks, sharing smoke_lyx's isolated LyX session."""
from pathlib import Path
import re
import shutil
import subprocess

from lyxai.bridge import apply_replacement, load_context, native_body
from lyxai.integration import capture_lyx_payload
from lyxai.latex_import import convert_latex
from lyxai.replacement import latex_input, native_paragraphs, structured_selection, body_insets
from lyxai.structure import protected_objects, kind

ROOT = Path(__file__).resolve().parents[1]


def check(server, folder, stem):
    from smoke_lyx import export_latex, clipboard_html
    report_files = []
    proof = (ROOT / 'tests/fixtures/lemma-proof.tex').read_text(encoding='utf-8')
    original = (ROOT / 'examples/mixed-layouts-demo.lyx').read_text(encoding='utf-8')
    # Actual converter matrix, including the exact module combination that
    # failed in the supplied screenshot. No mock and no TeX execution here.
    for cls, modules in (('article', ['theorems-ams']), ('article', ['theorems-ams-bytype', 'theorems-ams-extended-bytype']),
                         ('IEEEtran', ['theorems-ams-bytype', 'theorems-ams-extended-bytype']), ('IEEEtran', [])):
        header = original.split(r'\begin_body', 1)[0].replace(r'\textclass article', r'\textclass ' + cls)
        header = re.sub(r'\\begin_modules\n[\s\S]*?\\end_modules', lambda _: '\\begin_modules\n'+'\n'.join(modules)+'\n\\end_modules' if modules else '', header)
        doc = header + '\\begin_body\n\\begin_layout Lemma\nOriginal lemma.\n\\end_layout\n\\begin_layout Proof\nOriginal proof.\n\\end_layout\n\\end_body\n\\end_document\n'
        converted = convert_latex(latex_input(proof, doc), doc)
        assert r'\begin_layout Lemma' in converted and r'\begin_layout Proof' in converted
        assert converted.count(r'\begin_inset Formula') >= 50
        assert 'lyxaiobject' not in converted
        if cls == 'IEEEtran' and modules:
            ieee_source = doc
    print('Actual tex2lyx: full supplied lemma/proof, article + two AMS configurations, IEEEtran with/without conflicting modules: OK', flush=True)
    ieee = folder / 'ieee-regression.lyx'
    ieee.write_text(ieee_source, encoding='utf-8')
    server.command('file-open', str(ieee).replace('\\', '/'))
    baseline = server.snapshot()
    server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
    payload = capture_lyx_payload()
    payload.update(load_context(payload, stem))
    apply_replacement(payload, proof, stem)
    changed = server.snapshot()
    assert r'\begin_layout Lemma' in changed and r'\begin_layout Proof' in changed
    assert changed.count(r'\begin_inset Formula') >= 50
    exported = export_latex(server, folder / 'ieee-proof-export.tex')
    assert r'\begin{lem}' in exported and any(env in exported for env in (r'\begin{IEEEproof}', r'\begin{proof}'))
    assert r'\textbackslash' not in exported
    assert 'eq:trancedental_eq' in exported and 'lem:client-derivative-criterion' in exported
    server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
    rendered = clipboard_html()
    assert 'lemma_label' in rendered and '<mtable' in rendered
    server.command('undo')
    assert native_body(server.snapshot()) == native_body(baseline)
    report_files.append('ieee-proof-export.tex')
    print('Real IEEEtran: supplied long lemma/proof -> native Lemma/Proof/math, HTML math tables, LaTeX export, one undo: OK', flush=True)

    objects = folder / 'objects.lyx'
    shutil.copy2(ROOT / 'examples/objects-demo.lyx', objects)
    shutil.copy2(ROOT / 'lyxai/assets/logo.png', folder / 'sample.png')
    disk = objects.read_bytes()
    server.command('file-open', str(objects).replace('\\', '/'))
    baseline = server.snapshot()
    server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-select; copy')
    figure_payload = capture_lyx_payload()
    figure_context = load_context(figure_payload, stem)
    assert 'Before objects.' in figure_context['before'] and 'Original table.' in figure_context['after'], figure_context
    print('Live figure selection gets surrounding context despite rebased image paths: OK', flush=True)
    server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
    payload = capture_lyx_payload()
    payload.update(load_context(payload, stem))
    text = structured_selection(payload['native'])
    assert all(value in text for value in (r'\label{fig:sample}', r'\label{tab:sample}', 'Alpha', 'Inside box', r'\centering'))
    resources = protected_objects(payload['native'])
    revised = text.replace('Original figure', 'Revised figure').replace('Original table', 'Revised table').replace('Alpha', 'Gamma').replace('Inside box', 'Revised box')
    apply_replacement(payload, revised, stem)
    changed = server.snapshot()
    for value in ('Revised figure', 'Revised table', 'Gamma', 'Revised box', r'\begin_inset Float figure', r'\begin_inset Float table', r'\begin_inset Caption Standard', r'\begin_inset Tabular', r'\begin_inset Box Frameless', '\\paragraph_spacing other 1.5', '\\noindent'):
        assert value in changed, value
    def canonical(raw):
        filename = re.search(r'(?m)^\s*filename (.+)$', raw)
        if filename:
            path = Path(filename[1].strip('"'))
            absolute = str((path if path.is_absolute() else folder / path).resolve()).replace('\\', '/').casefold()
            raw = raw[:filename.start(1)] + absolute + raw[filename.end(1):]
        return '\n'.join(line.strip() for line in raw.splitlines() if line.strip() and not line.startswith('status '))
    new_resources = list(protected_objects(changed).values())
    for token, raw in resources.items():
        assert any(canonical(raw) == canonical(new) for new in new_resources), 'Native resource was altered: ' + token + '\n' + repr(raw) + '\n' + repr(new_resources)
    original_cells = re.findall(r'<(?:cell|column|row|features)[^>]*>', baseline)
    assert re.findall(r'<(?:cell|column|row|features)[^>]*>', changed) == original_cells
    exported = export_latex(server, folder / 'objects-export.tex')
    for value in (r'\begin{figure}', r'\begin{table}', r'\caption{', r'\label{fig:sample}', r'\label{tab:sample}', r'\begin{tabular}', r'\includegraphics', r'\begin{minipage}', r'\hspace{1em}', r'\begin{spacing}{1.5}', 'Gamma'):
        assert value in exported, value + '\n' + exported
    assert r'\textbackslash' not in exported
    server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
    rendered = clipboard_html()
    assert 'Revised figure' in rendered and 'Gamma' in rendered and 'Revised box' in rendered and '<table' in rendered
    server.command('undo')
    assert native_body(server.snapshot()) == native_body(baseline)
    assert objects.read_bytes() == disk
    report_files.append('objects-export.tex')
    print('Real Float/Caption/labels/Tabular/cells/graphics/minipage/hspace/paragraph spacing: editable content, native settings, HTML and LaTeX, one undo: OK', flush=True)

    # A Caption is Plain Layout, just like ERT. Copying its text must not make
    # the destination a raw-source editor. Reach it through native navigation.
    # The whole-object test above covers all native containers; direct interior
    # cases use a minimal box document with an unambiguous cursor route.
    box = folder / 'box-interior.lyx'
    box_raw = next(raw for p in native_paragraphs(baseline) for _, _, raw in body_insets(p.body) if kind(raw).startswith('Box '))
    box_raw = box_raw[:box_raw.index(r'\begin_layout ')] + '\\begin_layout Plain Layout\nBox interior.\n\\end_layout\n\\end_inset'
    box_source = original.split(r'\begin_body', 1)[0] + '\\begin_body\n\\begin_layout Standard\n' + box_raw + '\n\\end_layout\n\\end_body\n\\end_document\n'
    box.write_text(box_source, encoding='utf-8')
    server.command('file-open', str(box).replace('\\', '/'))
    box_baseline = server.snapshot()
    server.command('command-sequence', 'buffer-begin; char-forward; paragraph-select; copy')
    interior = capture_lyx_payload()
    assert 'Box interior.' in interior['text']
    interior.update(filename=server.command('server-get-filename'))
    apply_replacement(interior, r'Edited interior $q=9$.', stem)
    changed = server.snapshot()
    assert r'\begin_inset Formula $q=9$' in changed and 'Edited interior' in changed
    assert r'\begin_inset ERT' not in changed
    server.command('undo')
    assert native_body(server.snapshot()) == native_body(box_baseline)
    print('Plain Layout box interior receives native formulas and remains editable prose; one undo: OK', flush=True)
    caption = folder / 'caption-interior.lyx'
    caption.write_text(convert_latex(r'\begin{figure}\caption{Original caption.}\end{figure}', original), encoding='utf-8')
    server.command('file-open', str(caption).replace('\\', '/'))
    caption_baseline = server.snapshot()
    server.command('command-sequence', 'buffer-begin; char-forward; char-forward; paragraph-select; copy')
    interior = capture_lyx_payload()
    assert interior['text'] == 'Original caption.', interior['text']
    assert server.command('server-get-layout') == 'Plain Layout'
    interior.update(filename=server.command('server-get-filename'))
    apply_replacement(interior, r'Revised caption $c=1$.', stem)
    changed = server.snapshot()
    assert r'\begin_inset Formula $c=1$' in changed and r'\begin_inset Caption Standard' in changed
    exported = export_latex(server, folder / 'caption-export.tex')
    assert r'\caption{Revised caption $c=1$.}' in exported
    server.command('undo')
    assert native_body(server.snapshot()) == native_body(caption_baseline)
    report_files.append('caption-export.tex')
    print('Plain Layout caption interior receives a native equation inside the caption, exports caption LaTeX, one undo: OK', flush=True)
    return report_files
