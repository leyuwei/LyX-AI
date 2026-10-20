"""Explicit native integration check on a private Windows window station.

No visible desktop, mouse events, screenshots, or user files. If a private
window station is prohibited, preserve/restore clipboard formats instead.
Requires this machine's configured LyX 2.5; not part of fast test discovery.
"""
import ctypes
from ctypes import wintypes
import os
from pathlib import Path
import shutil
import re
import subprocess
import sys
import tempfile
import time
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def clipboard_html():
    """Read Qt's native HTML export to confirm math has an actual table tree."""
    u = ctypes.WinDLL('user32', use_last_error=True)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    k.GlobalSize.argtypes = [wintypes.HANDLE]
    k.GlobalSize.restype = ctypes.c_size_t
    k.GlobalLock.argtypes = [wintypes.HANDLE]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HANDLE]
    assert u.OpenClipboard(None)
    try:
        handle = u.GetClipboardData(u.RegisterClipboardFormatW('HTML Format'))
        assert handle, 'LyX did not publish HTML'
        size = k.GlobalSize(handle)
        assert 0 < size < 16_000_000
        pointer = k.GlobalLock(handle)
        assert pointer
        try:
            return ctypes.string_at(pointer, size).rstrip(b'\0').decode('utf-8-sig')
        finally:
            k.GlobalUnlock(handle)
    finally:
        u.CloseClipboard()


def export_latex(server, path):
    server.command('buffer-export', 'pdflatex ' + str(path).replace('\\', '/'))
    deadline = time.monotonic() + 5
    while time.monotonic() < deadline:
        if path.exists():
            text = path.read_text(encoding='utf-8-sig')
            if r'\end{document}' in text:
                return text
        time.sleep(.02)
    raise AssertionError('LaTeX export did not complete: ' + str(path))


def worker(desktop):
    from lyxai.bridge import LyXServer, load_context, apply_replacement, native_body
    from lyxai.integration import capture_lyx_payload
    lyx = Path(r'C:\Program Files\LyX 2.5')
    with tempfile.TemporaryDirectory(prefix='lyxai-native-') as tmp:
        folder = Path(tmp)
        user = folder / 'user'
        user.mkdir()
        support = Path(os.environ['APPDATA']) / 'LyX2.5'
        for file in support.iterdir():
            if file.is_file() and file.suffix in ('.lst', '.defaults'):
                shutil.copy2(file, user / file.name)
        stem = r'\\.\pipe\lyxai-test-' + uuid.uuid4().hex
        (user / 'preferences').write_text('Format 38\n\\serverpipe "'+stem+'"\n\\use_single_instance false\n\\gui_language english\n', encoding='utf-8')
        doc = folder / 'demo.lyx'
        shutil.copy2(ROOT / 'examples/context-demo.lyx', doc)
        original_disk = doc.read_bytes()
        env = dict(os.environ, QT_QPA_PLATFORM='windows', PATH=str(lyx/'bin')+';'+str(lyx/'Python')+';'+os.environ['WINDIR']+'\\System32;'+os.environ['WINDIR'])
        start = subprocess.STARTUPINFO()
        start.lpDesktop = desktop
        start.dwFlags = subprocess.STARTF_USESHOWWINDOW
        start.wShowWindow = 0
        proc = subprocess.Popen([str(lyx/'bin/LyX.exe'), '-userdir', str(user), '-n', str(doc)], env=env, startupinfo=start, creationflags=0x08000000, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        try:
            with LyXServer(stem, timeout=8) as server:
                assert server.command('server-get-filename').replace('/', '\\').casefold() == str(doc).casefold()
                baseline = server.snapshot()
                for action in ('buffer-begin', 'paragraph-down', 'paragraph-select', 'copy'):
                    server.command(action)
                payload = capture_lyx_payload()
                print('Selected:', payload['text'])
                print('Selection language:', re.findall(r'\\(?:language|lang) [^\n]+', payload['native']))
                assert payload['text'].startswith('Target passage:'), payload['text']
                payload.update(load_context(payload, stem))
                assert 'Context BEFORE' in payload['before'] and 'Context AFTER' in payload['after']
                assert 'DO NOT SEND' not in payload['before']+payload['after']
                assert payload['context_excluded'] == 2
                print('Live context and Note/Foot exclusion: OK')
                # Exercise the exact detached LFUN emitted for the menu, including
                # real native clipboard capture and single-instance delivery.
                from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
                from lyxai.instance import InstanceServer
                from lyxai.integration import menu_text
                app = QCoreApplication.instance() or QCoreApplication([])
                os.environ['LYXAI_DATA_DIR'] = str(folder / 'AI')
                receiver = InstanceServer(app)
                assert receiver.listen()
                messages = []
                loop = QEventLoop()
                receiver.received.connect(lambda message: (messages.append(message), loop.quit()))
                launcher = [os.environ['LYXAI_SMOKE_EXE']] if os.environ.get('LYXAI_SMOKE_EXE') else [sys.executable, str(ROOT/'main.py')]
                command = launcher + ['--data-dir', str(folder/'AI'), '--lyx-user-dir', str(user)]
                generated = menu_text('Menu "context-edit"\nEnd\n', command, 'auto')
                encoded = re.search(r'Item "[^"]*" "((?:\\.|[^"\\])*)"', generated)[1]
                lfun = re.sub(r'\\(.)', r'\1', encoded)
                server.command('command-sequence', lfun.split(' ', 1)[1])
                timer = QTimer()
                timer.setSingleShot(True)
                timer.timeout.connect(loop.quit)
                timer.start(5000)
                loop.exec()
                timer.stop()
                assert len(messages) == 1 and messages[0]['text'] == payload['text'], messages
                assert messages[0]['native'] and messages[0]['lyx_user_dir'] == str(user)
                receiver.server.close()
                print('Actual menu LFUN, detached launch, clipboard capture and IPC: OK')
                chain = (ROOT/'examples/multiline-formula.tex').read_text(encoding='utf-8').strip()
                revised = r'Our revised method uses $x_i^2$ and a displayed formula: \[y=\frac{a}{b}\].' + '\n\n' + chain + '\n\n' + r'\begin{aligned}a&=b\\c&=d\end{aligned}'
                apply_replacement(payload, revised, stem)
                changed = server.snapshot()
                assert re.search(r'\\begin_inset Formula \$x[^$]*\$', changed), changed[-1800:]
                assert re.search(r'\\begin_inset Formula\s+\\\[\ny=\\frac\{a\}\{b\}\n\\\]', changed)
                assert 'Our revised method uses' in changed
                assert 'Target passage:' not in changed
                assert r'\lang chinese-simplified' not in native_body(changed)
                assert 'DO NOT SEND THIS NOTE' in changed and 'DO NOT SEND THIS FOOTNOTE' in changed
                assert changed.count(r'\begin_inset Formula') == 4
                assert r'\begin{align}' in changed and r'\label{eq:chain}' in changed
                assert changed.count(r'\nonumber') == 3
                assert r'\begin{aligned}' in changed
                assert r'\backslash' not in native_body(changed), 'Math was inserted as source prose'
                server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
                rendered = clipboard_html()
                assert len(re.findall(r'<(?:[\w]+:)?mtable\b', rendered)) >= 2, 'No aligned MathML tables'
                assert len(re.findall(r'<(?:[\w]+:)?mtr\b', rendered)) >= 6, 'Multiline rows were lost'
                print('Actual native paste: inline, Displayed, supplied align + label/nonumber, aligned; MathML rows: OK')
                server.command('undo')
                restored = server.snapshot()
                assert native_body(restored) == native_body(baseline), 'Undo did not restore original body'
                print('One undo restores complete original body: OK')
                server.command('buffer-begin')
                server.command('paragraph-select')
                result = apply_replacement(payload, 'Latest selection $z=2$.', stem)
                assert result['mode'] == 'replace'
                changed = server.snapshot()
                assert 'Context BEFORE:' not in changed and 'Latest selection' in changed, native_body(changed)
                assert 'Target passage:' in changed and 'Context AFTER:' in changed
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline)
                print('Changed selection is replaced; original query target untouched; one undo: OK')
                server.command('buffer-begin')
                result = apply_replacement(payload, r'Inserted at caret $q^2$. \[v=3\]', stem)
                assert result['mode'] == 'insert'
                changed = server.snapshot()
                assert 'Inserted at caret' in changed
                assert changed.index('Inserted at caret') < changed.index('Context BEFORE:')
                assert 'Target passage:' in changed and 'DO NOT SEND THIS NOTE' in changed and 'DO NOT SEND THIS FOOTNOTE' in changed
                assert changed.count(r'\begin_inset Formula') == 2
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline)
                print('Caret insertion preserves surrounding prose/objects with native equations; one undo: OK')
                server.command('buffer-begin')
                server.command('self-insert', 'User edit. ')
                edited = server.snapshot()
                result = apply_replacement(payload, 'Revision after user edit. ', stem)
                assert result['mode'] == 'insert'
                assert 'User edit.' in server.snapshot()
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(edited)
                print('Intervening document edit accepted and survives undo of application: OK')
                other_doc = folder / 'other.lyx'
                shutil.copy2(doc, other_doc)
                server.command('file-open', str(other_doc).replace('\\', '/'))
                try:
                    apply_replacement(payload, revised, stem)
                except ValueError as exc:
                    assert 'document changed' in str(exc)
                    pass
                else:
                    raise AssertionError('Other document was overwritten')
                assert 'Revision after' not in server.snapshot()
                assert doc.read_bytes() == original_disk
                print('Other-document refusal and source file unchanged: OK')
                regions = folder / 'regions.lyx'
                shutil.copy2(ROOT / 'examples/regions-demo.lyx', regions)
                region_disk = regions.read_bytes()
                server.command('file-open', str(regions).replace('\\', '/'))
                baseline_regions = server.snapshot()
                server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-select; copy')
                region_payload = capture_lyx_payload()
                region_payload.update(load_context(region_payload, stem))
                apply_replacement(region_payload, r'Revised theorem $x=2$. \[y=3\]', stem)
                changed = server.snapshot()
                assert '\\begin_layout Theorem\nRevised theorem' in changed
                server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
                assert 'theorem_label' in clipboard_html()
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-select')
                apply_replacement(region_payload, r'\begin{theorem}[Bound]\label{thm:bound}\textbf{New theorem} $x=2$.\end{theorem}', stem)
                changed = server.snapshot()
                assert r'\begin_inset Argument 1' in changed and r'\begin_inset CommandInset label' in changed
                assert r'\series bold' in changed and r'\begin_layout Theorem' in changed
                assert r'\backslash' not in native_body(changed).split(r'\begin_layout Lemma')[0]
                server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
                rendered = clipboard_html()
                assert 'theorem_label' in rendered and 'New theorem' in rendered and 'thm_bound' in rendered
                latex = folder / 'regions-export.tex'
                server.command('buffer-export', 'pdflatex ' + str(latex).replace('\\', '/'))
                exported = latex.read_text(encoding='utf-8-sig')
                assert r'\begin{thm}[Bound]' in exported and r'\label{thm:bound}' in exported, exported
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-down; paragraph-select')
                apply_replacement(region_payload, r'\begin{lemma}\textit{New lemma} $z=5$.\end{lemma}', stem)
                changed = server.snapshot()
                assert '\\begin_layout Lemma\n' in changed and r'\shape italic' in changed, native_body(changed)
                server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
                rendered = clipboard_html()
                assert 'lemma_label' in rendered and 'New lemma' in rendered
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                print('Theorem/Lemma layouts, LaTeX environments, title/label/fonts and math render natively; one undo: OK')
                server.command('command-sequence', 'buffer-begin; paragraph-select')
                apply_replacement(region_payload, r'\section{Imported heading}\textbf{Bold body} and \emph{emphasis} $b=1$.', stem)
                changed = server.snapshot()
                assert r'\begin_layout Section' in changed and r'\series bold' in changed and r'\emph on' in changed
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                print('LaTeX headings, emphasis and formulas import as native structures: OK')
                server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-down; paragraph-down; paragraph-select; copy')
                source_payload = capture_lyx_payload()
                assert r'\textbf{Old source}' in source_payload['text'], source_payload['text']
                source_payload.update(load_context(source_payload, stem))
                apply_replacement(source_payload, r'\textbf{New source $s=4$}', stem)
                latex = folder / 'regions-source-export.tex'
                server.command('buffer-export', 'pdflatex ' + str(latex).replace('\\', '/'))
                exported = latex.read_text(encoding='utf-8-sig')
                assert r'\textbf{New source $s=4$}' in exported, exported
                assert 'Body before regions.' in exported and 'Body after regions.' in exported
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-down; paragraph-down; char-forward')
                assert server.command('server-get-layout') == 'Plain Layout'
                server.command('paragraph-select')
                apply_replacement(source_payload, r'\emph{Interior source $u=7$}', stem)
                latex = folder / 'regions-interior-export.tex'
                server.command('buffer-export', 'pdflatex ' + str(latex).replace('\\', '/'))
                assert r'\emph{Interior source $u=7$}' in latex.read_text(encoding='utf-8-sig'), latex.read_text(encoding='utf-8-sig')
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                server.command('command-sequence', 'buffer-begin; paragraph-down; paragraph-down; paragraph-down; char-forward')
                assert apply_replacement(source_payload, r'\textit{Prefix} ', stem)['mode'] == 'insert'
                latex = folder / 'regions-source-caret.tex'
                server.command('buffer-export', 'pdflatex ' + str(latex).replace('\\', '/'))
                exported = latex.read_text(encoding='utf-8-sig')
                assert r'\textit{Prefix}' in exported and r'\textbf{Old source}' in exported
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(baseline_regions)
                assert regions.read_bytes() == region_disk
                print('Whole ERT, source interior replacement and caret insertion export real LaTeX; one undo: OK')
                from lyxai.replacement import native_paragraphs, structured_selection
                mixed = folder / 'mixed.lyx'
                shutil.copy2(ROOT / 'examples/mixed-layouts-demo.lyx', mixed)
                mixed_disk = mixed.read_bytes()
                server.command('file-open', str(mixed).replace('\\', '/'))
                mixed_baseline = server.snapshot()
                select_mixed = 'buffer-begin; paragraph-down; ' + 'paragraph-down-select; ' * 4 + 'line-end-select; copy'
                server.command('command-sequence', select_mixed)
                mixed_payload = capture_lyx_payload()
                mixed_payload.update(load_context(mixed_payload, stem))
                expected = ['Theorem', 'Proof', 'Standard', 'Theorem', 'Proof']
                assert [p.layout for p in native_paragraphs(mixed_payload['native'])] == expected, mixed_payload['native']
                request_target = structured_selection(mixed_payload['native'])
                assert request_target.count(r'\begin{theorem}') == 2 and request_target.count(r'\begin{proof}') == 2
                assert r'\fbox{embedded source}' in request_target
                apply_replacement(mixed_payload, 'First revised theorem $x=2$.\n\nFirst revised proof.\n\nRevised body.\n\nSecond revised theorem.\n\nSecond revised proof.', stem)
                changed = server.snapshot()
                assert [p.layout for p in native_paragraphs(changed)] == ['Standard'] + expected + ['Standard'], native_body(changed)
                assert 'Before mixed selection.' in changed and 'After mixed selection.' in changed
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(mixed_baseline)
                print('Mixed Theorem/Proof/Standard native paragraphs preserve each layout and math; one undo: OK')
                server.command('command-sequence', select_mixed.replace('line-end-select; ', ''))
                partial = apply_replacement(mixed_payload, 'Partial theorem.\n\nPartial proof.\n\nPartial body.\n\nPartial second theorem.', stem)
                assert not partial['layout_fallback']
                changed = server.snapshot()
                assert [p.layout for p in native_paragraphs(changed)] == ['Standard'] + expected + ['Standard'], native_body(changed)
                assert 'Second proof.' in native_paragraphs(changed)[-2].body
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(mixed_baseline)
                print('Empty clipboard boundary preserves the unselected proof paragraph and its layout; one undo: OK')
                server.command('command-sequence', select_mixed.replace('line-end-select; ', ''))
                apply_replacement(mixed_payload, r'\begin{theorem}Partial theorem.\end{theorem}\begin{proof}Partial proof.\end{proof}' + '\n\nPartial body.\n\n' + r'\begin{theorem}Partial second theorem.\end{theorem}', stem)
                changed = server.snapshot()
                assert [p.layout for p in native_paragraphs(changed)] == ['Standard'] + expected + ['Standard'], native_body(changed)
                assert 'Second proof.' in native_paragraphs(changed)[-2].body
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(mixed_baseline)
                print('LaTeX import at an empty clipboard boundary preserves the unselected proof; one undo: OK')
                server.command('command-sequence', select_mixed)
                mixed_revision = (r'\begin{theorem}[First bound]\label{thm:mixed}First revised theorem $x=2$.\end{theorem}' + '\n\n'
                                  + r'\begin{proof}First revised proof.\end{proof}' + '\n\nBody ' + '\n```latex\n'
                                  + r'\fbox{Rendered source}' + '\n```\nand ' + r'\textbf{bold}.' + '\n\n'
                                  + r'\begin{theorem}Second revised theorem $y=3$.\end{theorem}' + '\n\n'
                                  + r'\begin{proof}Second revised proof.\end{proof}')
                apply_replacement(mixed_payload, mixed_revision, stem)
                changed = server.snapshot()
                assert [p.layout for p in native_paragraphs(changed) if p.layout != 'Standard'] == ['Theorem', 'Proof', 'Theorem', 'Proof'], native_body(changed)
                mixed_latex = folder / 'mixed-export.tex'
                exported = export_latex(server, mixed_latex)
                assert exported.count(r'\begin{thm}') == 2 and exported.count(r'\begin{proof}') == 2, exported
                assert r'\label{thm:mixed}' in exported and (r'\fbox{' in exported or r'\fcolorbox{' in exported) and 'Rendered source' in exported, exported
                assert r'\textbackslash' not in exported, exported
                server.command('command-sequence', 'buffer-begin; buffer-end-select; copy')
                assert clipboard_html().count('theorem_label') >= 2
                server.command('undo')
                assert native_body(server.snapshot()) == native_body(mixed_baseline)
                assert mixed.read_bytes() == mixed_disk
                print('Multiple theorem/proof environments with inline ERT and mixed LaTeX fences export real commands and labels; one undo: OK')
                engine = shutil.which('pdflatex')
                if engine:
                    for name in ('regions-export.tex', 'regions-source-export.tex', 'mixed-export.tex'):
                        result = subprocess.run([engine, '-interaction=nonstopmode', '-halt-on-error', '-no-shell-escape', name], cwd=folder, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, timeout=20, creationflags=0x08000000)
                        assert result.returncode == 0, result.stdout.decode('utf-8', 'replace')[-3000:]
                        assert (folder / name.replace('.tex', '.pdf')).exists()
                    print('Native theorem title/label, ERT formulas and mixed environments compile to PDF with shell escape disabled: OK')
        finally:
            proc.terminate()
            proc.wait(timeout=5)


def check():
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.CreateWindowStationW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    u.CreateWindowStationW.restype = wintypes.HANDLE
    u.GetProcessWindowStation.restype = wintypes.HANDLE
    u.SetProcessWindowStation.argtypes = [wintypes.HANDLE]
    u.CreateDesktopW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    u.CreateDesktopW.restype = wintypes.HANDLE
    u.CloseDesktop.argtypes = [wintypes.HANDLE]
    u.CloseWindowStation.argtypes = [wintypes.HANDLE]
    name = 'LyXAI_Test_' + uuid.uuid4().hex
    original = u.GetProcessWindowStation()
    station = u.CreateWindowStationW(name, 0, 0x37f, None)
    if not station:
        # Some Windows sessions forbid a second window station. Use a hidden
        # desktop and restore all Qt clipboard formats in a finally block.
        os.environ['QT_QPA_PLATFORM'] = 'windows'
        from PySide6.QtCore import QMimeData
        from PySide6.QtWidgets import QApplication
        app = QApplication([])
        clipboard = app.clipboard()
        source = clipboard.mimeData()
        backup = QMimeData()
        if source:
            for fmt in source.formats():
                backup.setData(fmt, source.data(fmt))
            if source.hasImage():
                backup.setImageData(source.imageData())
        desktop = u.CreateDesktopW(name, None, None, 0, 0x1ff, None)
        if not desktop:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            start = subprocess.STARTUPINFO()
            start.lpDesktop = name
            result = subprocess.run([sys.executable, '-u', str(Path(__file__).resolve()), '--worker', name], startupinfo=start, capture_output=True, timeout=90, creationflags=0x08000000)
            print(result.stdout.decode('utf-8', errors='replace'))
            if result.returncode:
                raise RuntimeError(result.stderr.decode('utf-8', errors='replace'))
        finally:
            clipboard.setMimeData(backup)
            app.processEvents()
            u.CloseDesktop(desktop)
        return
    desktop = None
    try:
        if not u.SetProcessWindowStation(station):
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            desktop = u.CreateDesktopW('default', None, None, 0, 0x1ff, None)
            if not desktop:
                raise ctypes.WinError(ctypes.get_last_error())
        finally:
            u.SetProcessWindowStation(original)
        start = subprocess.STARTUPINFO()
        start.lpDesktop = name + '\\default'
        subprocess.run([sys.executable, '-u', str(Path(__file__).resolve()), '--worker', start.lpDesktop], startupinfo=start, check=True, timeout=90, creationflags=0x08000000)
    finally:
        if desktop:
            u.CloseDesktop(desktop)
        u.CloseWindowStation(station)


if __name__ == '__main__':
    started = time.perf_counter()
    if '--worker' in sys.argv:
        worker(sys.argv[-1])
    else:
        check()
        print(f'Native LyX isolated check: {time.perf_counter()-started:.2f}s')
