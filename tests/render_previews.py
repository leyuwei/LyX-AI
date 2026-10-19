"""Render documentation screenshots offscreen, without touching desktop windows."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication, QSplitter
from lyxai.core import PRESETS, Store, new_profile
from lyxai.ui import MainWindow, SettingsDialog, HistoryDialog, STYLE
from lyxai.history import timestamp

QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
app = QApplication([])
app.setQuitOnLastWindowClosed(False)
app.setStyle("Fusion")
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for name in ("segoeui.ttf", "msyh.ttc"):
    font = fonts / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Microsoft YaHei", 10))
app.setStyleSheet(STYLE)
folder = Path(__file__).resolve().parents[1] / "docs/images"
folder.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    window = MainWindow("本文提出一种分布式计算方法，在保持准确率的同时降低通信开销。", Store(Path(tmp)))
    window.resize(1160, 930)
    window.before.setPlainText("现有方法需要频繁交换中间结果，通信开销较高。")
    window.after.setPlainText("实验部分将比较不同网络条件下的性能。")
    window.show()
    app.processEvents()
    window.grab().save(str(folder / "main.png"))
    config = window.config
    config["profiles"] = [new_profile(k) for k in PRESETS]
    config["active"] = config["profiles"][0]["id"]
    dialog = SettingsDialog(config, window)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(folder / "models.png"))
    dialog.close()
    window.close()
print("Documentation previews rendered offscreen.")


if '--readme' in sys.argv:
    # Explicit documentation generation only; never part of the fast tests.
    import json
    os.environ.setdefault('QTWEBENGINE_CHROMIUM_FLAGS', '--disable-gpu')
    for lang in ('zh', 'en'):
        with tempfile.TemporaryDirectory(prefix='lyxai-readme-') as tmp:
            store = Store(Path(tmp))
            config = store.load()
            config['language'] = lang
            config['template_index'] = 1 if lang == 'en' else 0
            config['reply_language'] = 'English' if lang == 'en' else '中文'
            config['profiles'][0].update(name='Writing model', model='your-model-id', url='https://api.example.com')
            store.save(config)
            target = '系统状态由上一时刻确定，观测由当前状态决定。' if lang == 'zh' else 'The next system state depends on the current state, and observations depend on the state.'
            window = MainWindow(target, store)
            window.resize(1160, 930)
            window.before.setPlainText('考虑一个离散时间系统，记状态为 x，观测为 y。' if lang == 'zh' else 'Consider a discrete-time system with state x and observation y.')
            window.after.setPlainText('随后讨论状态递推关系及观测函数的性质。' if lang == 'zh' else 'We next discuss the state transition and observation functions.')
            equation = r'\begin{align}x_{t+1}&=f(x_t),\nonumber\\y_t&=g(x_t).\label{eq:state}\end{align}'
            answer = ('### 修改建议\n\n将状态递推与观测关系分别定义，表达更清晰。\n\n**建议修改稿**\n\n设系统状态为 $x_t$，观测为 $y_t$，则\n\n' if lang == 'zh' else '### Suggested revision\n\nDefine the state transition and observation separately.\n\n**Revised passage**\n\nLet $x_t$ denote the state and $y_t$ the observation. Then\n\n') + equation
            window.answer_text = answer
            window.answer.setPlainText(answer)
            window.replacement.setPlainText(('设系统状态为 $x_t$，观测为 $y_t$，则\n\n' if lang == 'zh' else 'Let $x_t$ denote the state and $y_t$ the observation. Then\n\n') + equation)
            window.status.setText('界面演示 · 未调用 AI 接口' if lang == 'zh' else 'Interface demonstration · No AI request sent')
            window.output_tabs.setCurrentWidget(window.rich_preview)
            window.rich_preview.set_text(answer)
            window.show()
            window.panes.setSizes([410, 360])
            window.rich_preview.timer.stop()
            window.rich_preview.render()
            loop = QEventLoop()
            watchdog = QTimer()
            watchdog.setSingleShot(True)
            watchdog.timeout.connect(loop.quit)
            ready = {}
            def inspect():
                def received(value):
                    ready.update(json.loads(value) if value else {})
                    if ready.get('fonts') and ready.get('math') == 3 and ready.get('tables') == 1:
                        loop.quit()
                    elif watchdog.isActive():
                        QTimer.singleShot(100, inspect)
                window.rich_preview.page.runJavaScript("JSON.stringify({fonts:document.fonts.status==='loaded',math:document.querySelectorAll('.katex').length,tables:document.querySelectorAll('math mtable').length})", received)
            window.rich_preview.view.loadFinished.connect(lambda ok: QTimer.singleShot(150, inspect) if ok else loop.quit())
            watchdog.start(10000)
            loop.exec()
            watchdog.stop()
            assert ready.get('fonts') and ready.get('math') == 3 and ready.get('tables') == 1, ready
            app.processEvents()
            window.grab().save(str(folder / f'main-{lang}.png'))
            config = window.config.copy()
            config['profiles'] = [new_profile(k) for k in PRESETS]
            for profile in config['profiles']:
                profile.update(url='https://api.example.com', model='your-model-id')
            config['active'] = config['profiles'][0]['id']
            dialog = SettingsDialog(config, window)
            dialog.show()
            app.processEvents()
            dialog.grab().save(str(folder / f'models-{lang}.png'))
            dialog.close()
            demonstration = window.archive.new(target=target, before=window.before.toPlainText(), after=window.after.toPlainText(), profile={'name': 'Writing model', 'model': 'your-model-id'})
            demonstration['turns'] = [dict(time=timestamp(), status='complete', question='请检查原文表达，保留公式和事实。' if lang == 'zh' else 'Review the passage, preserving equations and facts.', answer=answer, reasoning='', profile=demonstration['profile'])]
            window.archive.save(demonstration)
            history = HistoryDialog(window.archive, lang, window)
            history.show()
            app.processEvents()
            history.grab().save(str(folder / f'history-{lang}.png'))
            history.close()
            window.close()
            import shiboken6
            shiboken6.delete(history)
            shiboken6.delete(dialog)
            shiboken6.delete(window)
            app.processEvents()
    print('Bilingual README screenshots rendered with offline math; no API calls.')
