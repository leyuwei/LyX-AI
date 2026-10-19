"""Real macOS LyX integration, using a temporary userdir and document copy."""
from pathlib import Path
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


def check():
    from AppKit import NSPasteboard, NSPasteboardItem
    from lyxai.bridge import LyXServer, load_context, apply_replacement, native_body
    from lyxai.integration import capture_lyx_payload, menu_text
    board = NSPasteboard.generalPasteboard()
    backup = []
    for item in board.pasteboardItems() or []:
        copy = NSPasteboardItem.alloc().init()
        for kind in item.types():
            data = item.dataForType_(kind)
            if data is not None:
                copy.setData_forType_(data, kind)
        backup.append(copy)
    try:
        with tempfile.TemporaryDirectory(prefix='lyxai-native-') as tmp:
            folder = Path(tmp)
            user = folder / 'user'
            user.mkdir()
            support = Path.home() / 'Library/Application Support/LyX-2.5'
            for file in support.iterdir():
                if file.is_file() and file.suffix in ('.lst', '.defaults'):
                    shutil.copy2(file, user / file.name)
            stem = str(folder / 'lyxpipe')
            (user / 'preferences').write_text('Format 38\n\\serverpipe "'+stem+'"\n\\gui_language english\n', encoding='utf-8')
            doc = folder / 'demo.lyx'
            shutil.copy2(ROOT / 'examples/context-demo.lyx', doc)
            original = doc.read_bytes()
            log = open(folder / 'lyx.log', 'w+')
            proc = subprocess.Popen(['/Applications/LyX.app/Contents/MacOS/lyx', '-userdir', str(user), '-n', str(doc)], env=dict(os.environ, QT_QPA_PLATFORM='cocoa'), stdout=log, stderr=log)
            try:
                with LyXServer(stem, timeout=15) as server:
                    assert server.command('server-get-filename') == str(doc)
                    baseline = server.snapshot()
                    server.command('buffer-begin')
                    server.command('word-find-forward', 'Target passage:')
                    for action in ('paragraph-select', 'copy'):
                        server.command(action)
                    payload = capture_lyx_payload()
                    assert payload['text'].startswith('Target passage:'), payload['text']
                    payload.update(load_context(payload, stem))
                    assert 'Context BEFORE' in payload['before'] and 'Context AFTER' in payload['after']
                    assert 'DO NOT SEND' not in payload['before'] + payload['after']
                    assert payload['context_excluded'] == 2
                    print('Native clipboard + live context + Note/Foot exclusion: OK')
                    from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer
                    from lyxai.instance import InstanceServer
                    app = QCoreApplication.instance() or QCoreApplication([])
                    os.environ['LYXAI_DATA_DIR'] = str(folder / 'AI')
                    receiver = InstanceServer(app)
                    assert receiver.listen()
                    messages = []
                    loop = QEventLoop()
                    receiver.received.connect(lambda message: (messages.append(message), loop.quit()))
                    launcher = [os.environ['LYXAI_SMOKE_EXE']] if os.environ.get('LYXAI_SMOKE_EXE') else [sys.executable, str(ROOT/'main.py')]
                    command = launcher + ['--data-dir', str(folder/'AI'), '--lyx-user-dir', str(user)]
                    generated = menu_text('Menu "context-edit"\nEnd\n', command, 'both')
                    encoded = re.search(r'Item "[^"]*" "((?:\\.|[^"\\])*)"', generated)[1]
                    lfun = re.sub(r'\\(.)', r'\1', encoded)
                    server.command('command-sequence', lfun.split(' ', 1)[1])
                    timer = QTimer()
                    timer.setSingleShot(True)
                    timer.timeout.connect(loop.quit)
                    timer.start(15000)
                    loop.exec()
                    timer.stop()
                    receiver.server.close()
                    if receiver.lock:
                        receiver.lock.unlock()
                    assert len(messages) == 1 and messages[0]['text'] == payload['text'], messages
                    assert messages[0]['native'] and messages[0]['lyx_user_dir'] == str(user)
                    print('Actual menu LFUN + detached launch + native capture + IPC: OK')
                    revised = r'Our revised method uses $x_i^2$ and \[y=\frac{a}{b}\].' + '\n\n' + (ROOT/'examples/multiline-formula.tex').read_text().strip()
                    apply_replacement(payload, revised, stem)
                    changed = server.snapshot()
                    assert 'Our revised method uses' in changed and 'Target passage:' not in changed
                    assert changed.count(r'\begin_inset Formula') == 3
                    assert r'\begin{align}' in changed and r'\label{eq:chain}' in changed
                    assert 'DO NOT SEND THIS NOTE' in changed and 'DO NOT SEND THIS FOOTNOTE' in changed
                    print('Native writeback: inline, displayed and multiline editable equations: OK')
                    server.command('undo')
                    assert native_body(server.snapshot()) == native_body(baseline)
                    server.command('buffer-begin')
                    server.command('paragraph-select')
                    assert apply_replacement(payload, 'Latest selection $z=2$.', stem)['mode'] == 'replace'
                    changed = server.snapshot()
                    assert 'Latest selection' in changed and 'Context BEFORE:' not in changed
                    assert 'Target passage:' in changed
                    server.command('undo')
                    assert native_body(server.snapshot()) == native_body(baseline)
                    server.command('buffer-begin')
                    assert apply_replacement(payload, r'Caret insertion $q^2$. \[v=3\]', stem)['mode'] == 'insert'
                    changed = server.snapshot()
                    assert changed.index('Caret insertion') < changed.index('Context BEFORE:')
                    assert 'Target passage:' in changed and changed.count(r'\begin_inset Formula') == 2
                    server.command('undo')
                    assert native_body(server.snapshot()) == native_body(baseline)
                    assert doc.read_bytes() == original
                    print('Latest selection + caret insertion + single undo + source file unchanged: OK')
                    references = folder / 'references.lyx'
                    shutil.copy2(ROOT / 'tests/references-demo.lyx', references)
                    server.command('file-open', str(references))
                    baseline_refs = server.snapshot()
                    server.command('buffer-begin')
                    server.command('word-find-forward', 'Target references:')
                    server.command('paragraph-select')
                    server.command('copy')
                    ref_payload = capture_lyx_payload()
                    assert ref_payload['text'].startswith('Target references:')
                    assert ref_payload['excluded'] == 2 and 'SECRET' not in ref_payload['text']
                    ref_payload.update(load_context(ref_payload, stem))
                    ref_text = r'Revised references: equation \eqref{eq:demo}, figure \ref{fig:demo}, table \ref{tab:demo}, section \ref{sec:demo}, bibliography \cite{paper2026}.'
                    apply_replacement(ref_payload, ref_text, stem)
                    changed_refs = server.snapshot()
                    assert 'Target references:' not in changed_refs and 'SECRET' not in changed_refs
                    assert changed_refs.count('\\begin_inset CommandInset ref\n') == 4
                    assert changed_refs.count('\\begin_inset CommandInset citation\n') == 1
                    assert 'LatexCommand eqref' in changed_refs and r'\backslash' not in changed_refs
                    exported = folder / 'references.xhtml'
                    server.command('buffer-export', 'xhtml ' + str(exported))
                    deadline = time.monotonic() + 15
                    while not exported.exists() and time.monotonic() < deadline:
                        time.sleep(.02)
                    rendered = ET.parse(exported)
                    links = [(a.attrib.get('href', ''), ''.join(a.itertext())) for a in rendered.iter() if a.tag.rsplit('}', 1)[-1] == 'a']
                    for key in ('eq:demo', 'fig:demo', 'tab:demo', 'sec:demo', 'paper2026'):
                        assert any(key.replace(':', '_') in href.replace(':', '_') and text.strip() and '?' not in text and '\\' not in text for href, text in links), (key, links)
                    server.command('undo')
                    assert native_body(server.snapshot()) == native_body(baseline_refs)
                    assert references.read_bytes() == (ROOT/'tests/references-demo.lyx').read_bytes()
                    print('Equation/figure/table/section/citation references resolve in exported XHTML: OK')
                    print('Note/Footnote selection fully replaced; single undo restores both: OK')
            except Exception:
                log.flush()
                log.seek(0)
                print(log.read()[-4000:], file=sys.stderr)
                raise
            finally:
                proc.terminate()
                try:
                    proc.wait(timeout=3)
                except subprocess.TimeoutExpired:
                    proc.kill()
                    proc.wait(timeout=3)
                log.close()
    finally:
        board.clearContents()
        if backup:
            board.writeObjects_(backup)


if __name__ == '__main__':
    check()
