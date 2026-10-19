"""Offline Markdown/KaTeX preview with a stable, reusable browser widget."""
from __future__ import annotations

import html
from pathlib import Path
import uuid

from markdown_it import MarkdownIt
from PySide6.QtCore import QTimer, QUrl
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from .replacement import Math, math_parts, preview_tex

ASSETS = Path(__file__).resolve().parent / 'assets'


def preview_html(text):
    nonce = uuid.uuid4().hex
    markers = {}
    protected = []
    for part in math_parts(text[:250_000]):
        if isinstance(part, Math):
            marker = 'LYXAIPREVIEW' + uuid.uuid4().hex
            markers[marker] = '<span class="math" data-display="' + str(part.display).lower() + '">' + html.escape(preview_tex(part.tex)) + '</span>'
            protected.append(marker)
        else:
            protected.append(part)
    parser = MarkdownIt('commonmark', {'html': False, 'linkify': False}).enable('table')
    parser.renderer.rules['image'] = lambda tokens, idx, options, env: html.escape(tokens[idx].content)
    body = parser.render(''.join(protected))
    for marker, formula in markers.items():
        body = body.replace(marker, formula)
    if len(text) > 250_000:
        body += '<p>Preview limited to 250,000 characters. Full text is in Source.</p>'
    return '''<!doctype html><html><head><meta charset="utf-8">
<meta http-equiv="Content-Security-Policy" content="default-src 'none'; script-src 'nonce-''' + nonce + '''' file:; style-src 'unsafe-inline' file:; font-src file:; img-src 'none'; connect-src 'none'; frame-src 'none'; base-uri 'none'">
<link rel="stylesheet" href="katex/katex.min.css"><style>
body{font:15px/1.8 'Segoe UI','Microsoft YaHei',sans-serif;color:#233449;background:#fff;margin:24px;overflow-wrap:anywhere}
h1,h2,h3{line-height:1.4;color:#155d74}a{color:#2465bb}pre,code{background:#f1f5f9;border-radius:5px;font-family:Consolas,monospace}pre{padding:14px;overflow:auto}blockquote{border-left:3px solid #53b9b5;margin-left:0;padding-left:18px;color:#536778}table{border-collapse:collapse}td,th{border:1px solid #d6e1e9;padding:7px 12px}.katex-display{overflow-x:auto;overflow-y:hidden;padding:7px}.math{white-space:pre-wrap}
</style></head><body>''' + body + '''<script src="katex/katex.min.js"></script><script nonce="''' + nonce + '''">
document.querySelectorAll('.math').forEach(e=>{let source=e.textContent;try{katex.render(source,e,{displayMode:e.dataset.display==='true',throwOnError:false,trust:false,maxExpand:500,maxSize:20,strict:'ignore'});}catch(err){e.textContent=source;e.style.color='#b33';}});window.lyxaiReady=true;
</script></body></html>'''


class RichPreview(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.text = ''
        self.view = None
        self.last_rendered = None
        self.layout = QVBoxLayout(self)
        self.layout.setContentsMargins(0, 0, 0, 0)
        self.placeholder = QLabel('Markdown · LaTeX · Offline preview')
        self.layout.addWidget(self.placeholder)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(350)
        self.timer.timeout.connect(self.render)

    def set_text(self, text):
        if text == self.text:
            return
        self.text = text
        if self.isVisible():
            self.timer.start()

    def showEvent(self, event):
        super().showEvent(event)
        self.timer.start()

    def prepare(self):
        if self.view is None:
            from PySide6.QtWebEngineCore import QWebEnginePage, QWebEngineProfile, QWebEngineSettings, QWebEngineUrlRequestInterceptor
            from PySide6.QtWebEngineWidgets import QWebEngineView

            class Offline(QWebEngineUrlRequestInterceptor):
                def interceptRequest(inner, request):
                    url = request.requestUrl()
                    allowed = url.scheme() == 'data' and request.resourceType() == request.ResourceType.ResourceTypeMainFrame
                    if url.isLocalFile():
                        try:
                            allowed = Path(url.toLocalFile()).resolve().is_relative_to(ASSETS.resolve())
                        except ValueError:
                            allowed = False
                    request.block(not allowed)

            class Page(QWebEnginePage):
                def acceptNavigationRequest(inner, url, kind, main):
                    return kind != QWebEnginePage.NavigationType.NavigationTypeLinkClicked and url.scheme() in ('data', 'file', 'about')

            # QObject children are destroyed in creation order: delete the view
            # and its page before the profile, including on application exit.
            self.view = QWebEngineView(self)
            self.profile = QWebEngineProfile(self)
            self.interceptor = Offline(self.profile)
            self.profile.setUrlRequestInterceptor(self.interceptor)
            self.page = Page(self.profile, self.view)
            self.view.setPage(self.page)
            for flag in ('LocalContentCanAccessRemoteUrls', 'JavascriptCanOpenWindows', 'LocalStorageEnabled', 'PluginsEnabled'):
                self.page.settings().setAttribute(getattr(QWebEngineSettings.WebAttribute, flag), False)
            self.layout.removeWidget(self.placeholder)
            self.placeholder.deleteLater()
            self.layout.addWidget(self.view)
    def render(self):
        if not self.isVisible() or self.last_rendered == self.text:
            return
        self.prepare()
        self.last_rendered = self.text
        self.view.setHtml(preview_html(self.text), QUrl.fromLocalFile(str(ASSETS) + '/'))


def check_preview(app, report_path):
    """Explicit offscreen smoke check, also available in the frozen app."""
    import json
    import os
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
    from PySide6.QtCore import QEventLoop
    widget = RichPreview()
    widget.resize(850, 600)
    widget.text = r'# Preview check' + '\n\n**Bold** and $x_i^2$.\n\n' + r'\[y=\frac{a}{b}\]' + '\n\n<script>window.INJECTED=true</script>\n\n![blocked](https://example.invalid/image.png)'
    widget.text += '\n\n' + r'\begin{align}a&=b\nonumber\\c&=d\label{eq:check}\end{align}' + '\n\n' + r'\begin{aligned}u&=v\\x&=y\end{aligned}'
    widget.show()
    widget.render()
    loop = QEventLoop()
    report = {}
    timer = QTimer()
    timer.setSingleShot(True)
    timer.timeout.connect(loop.quit)
    def loaded(ok):
        if not ok:
            report.update(load=False)
            loop.quit()
            return
        QTimer.singleShot(250, inspect)
    def inspect():
        def received(value):
            report.update(json.loads(value) if value else {})
            if not report.get('fontsReady'):
                QTimer.singleShot(100, inspect)
                return
            loop.quit()
        widget.page.runJavaScript("JSON.stringify({ready:window.lyxaiReady===true,math:document.querySelectorAll('.katex').length,display:document.querySelectorAll('.katex-display').length,tables:document.querySelectorAll('math mtable').length,bold:document.querySelectorAll('strong').length,injected:window.INJECTED===true,images:document.images.length,errors:document.querySelectorAll('.katex-error').length,fontsReady:document.fonts.status==='loaded',fontsLoaded:Array.from(document.fonts).filter(f=>f.status==='loaded').length})", received)
    widget.view.loadFinished.connect(loaded)
    timer.start(15000)
    loop.exec()
    timer.stop()
    passed = all(report.get(k) == v for k,v in dict(ready=True, math=4, display=3, bold=1, injected=False, images=0, errors=0, fontsReady=True).items()) and report.get('fontsLoaded', 0) > 0 and report.get('tables', 0) >= 2
    report.update(passed=passed)
    Path(report_path).write_text(json.dumps(report), encoding='utf-8')
    if passed:
        widget.grab().save(str(Path(report_path).with_suffix('.png')))
    widget.close()
    import shiboken6
    shiboken6.delete(widget)
    app.processEvents()
    return 0 if passed else 1
