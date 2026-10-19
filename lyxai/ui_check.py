"""Explicit UI regression, using only temporary data and application widgets."""
import json
import os
from pathlib import Path
import tempfile

from PySide6.QtCore import QEvent, QEventLoop, QObject, QTimer
from PySide6.QtGui import QFont, QFontDatabase

from .core import Store
from .ui import MainWindow, SettingsDialog, STYLE, choose


def check_window(app, report_path):
    if app.platformName() == 'offscreen':
        os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
    app.setQuitOnLastWindowClosed(False)
    app.setStyle('Fusion')
    app.setStyleSheet(STYLE)
    for name in ('segoeui.ttf', 'msyh.ttc'):
        font = Path(os.environ.get('WINDIR', '')) / 'Fonts' / name
        if font.exists():
            QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI', 10))
    report_path = Path(report_path)
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report = {}

    class Watcher(QObject):
        events = []
        def eventFilter(self, obj, event):
            if event.type() in (QEvent.Type.Hide, QEvent.Type.Close, QEvent.Type.WinIdChange):
                self.events.append(event.type().name)
            return False

    with tempfile.TemporaryDirectory(prefix='lyxai-ui-') as tmp:
        w = MainWindow('Keep this target', Store(Path(tmp)))
        w.answer_text = '# Preview\n\n' + r'$x_i^2$' + '\n\n' + '\n\n'.join('Paragraph ' + str(i) for i in range(70))
        w.rich_preview.set_text(w.answer_text)
        w.show()
        app.processEvents()
        identity, rectangle = int(w.winId()), w.geometry()
        browser, page = w.rich_preview.view, w.rich_preview.page
        watcher = Watcher(w)
        w.installEventFilter(watcher)
        loads = []
        browser.loadStarted.connect(lambda: loads.append(True))
        w.output_tabs.setCurrentWidget(w.rich_preview)
        w.rich_preview.timer.stop()
        w.rich_preview.render()
        loop = QEventLoop()
        timeout = QTimer()
        timeout.setSingleShot(True)
        timeout.timeout.connect(loop.quit)
        readiness = {}
        def inspect():
            def received(value):
                readiness.update(json.loads(value) if value else {})
                if readiness.get('ready') and readiness.get('math') == 1 and readiness.get('fonts'):
                    page.runJavaScript('window.scrollTo(0,document.body.scrollHeight)', lambda _: loop.quit())
                elif timeout.isActive():
                    QTimer.singleShot(75, inspect)
            page.runJavaScript("JSON.stringify({ready:window.lyxaiReady===true,math:document.querySelectorAll('.katex').length,fonts:document.fonts.status==='loaded'})", received)
        browser.loadFinished.connect(lambda ok: QTimer.singleShot(100, inspect) if ok else loop.quit())
        timeout.start(12000)
        loop.exec()
        timeout.stop()
        assert readiness.get('ready') and readiness.get('math') == 1 and readiness.get('fonts'), readiness
        initial_loads = len(loads)
        first_preview = dict(handle=int(w.winId()), surface=w.windowHandle().surfaceType().name, events=list(watcher.events))
        w.output_tabs.setCurrentIndex(0)
        w.output_tabs.setCurrentWidget(w.rich_preview)
        choose(w.language, 'en')
        QTimer.singleShot(500, loop.quit)
        loop.exec()
        scroll = []
        page.runJavaScript('window.scrollY', lambda value: (scroll.append(value), loop.quit()))
        QTimer.singleShot(2000, loop.quit)
        loop.exec()
        assert int(w.winId()) == identity and w.geometry() == rectangle, dict(before=identity, after=int(w.winId()), geometry_before=rectangle.getRect(), geometry_after=w.geometry().getRect(), events=watcher.events, first_preview=first_preview)
        assert w.rich_preview.view is browser and w.rich_preview.page is page
        assert not watcher.events, watcher.events
        assert len(loads) == initial_loads, 'Unchanged preview was reloaded'
        assert scroll and scroll[0] > 0, scroll
        assert w.selection.toPlainText() == 'Keep this target'
        report.update(stable_window=True, reused_browser=True, no_extra_loads=True, scroll_preserved=True)
        w.removeEventFilter(watcher)
        sizes = []
        for lang in ('zh', 'en'):
            choose(w.language, lang)
            for width, height in ((640, 480), (800, 600), (1024, 600)):
                w.resize(width, height)
                app.processEvents()
                assert w.size().width() == width and w.size().height() == height, dict(language=lang, requested=[width, height], actual=w.size().toTuple(), minimum=w.minimumSizeHint().toTuple())
                for button in (w.apply_btn, w.send_btn, w.history_btn):
                    assert w.centralWidget().rect().contains(button.geometry())
                sizes.append([lang, width, height])
            w.resize(800, 600)
            app.processEvents()
            w.grab().save(str(report_path.with_name(report_path.stem + '-small-' + lang + '.png')))
        original_height = w.status.height()
        w.status.setText('First line\nSecond line\n' + 'Long status ' * 200)
        app.processEvents()
        assert w.status.height() == original_height and '\n' not in w.status.text()
        dialog = SettingsDialog(w.config, w)
        dialog.resize(640, 480)
        dialog.show()
        app.processEvents()
        assert dialog.size().toTuple() == (640, 480)
        dialog.close()
        report.update(small_windows=sizes, one_line_status=True, settings_fit=True, passed=True)
        w.close()
        import shiboken6
        shiboken6.delete(dialog)
        shiboken6.delete(w)
        app.processEvents()
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    return 0
