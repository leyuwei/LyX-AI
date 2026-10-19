import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from lyxai.selection import compose_context, extract_body


def fragment(text):
    return "\\lyxformat 643\n\\begin_document\n\\begin_body\n" + text + "\n\\end_body\n\\end_document"


def paragraph(text):
    return "\\begin_layout Standard\n" + text + "\n\\end_layout"


class SelectionTests(unittest.TestCase):
    def test_excludes_notes_footnotes_nested_objects(self):
        body = paragraph("正文前。\n\\begin_inset Note Note\nstatus open\n\\begin_layout Plain Layout\n备注 SECRET-NOTE\n\\begin_inset Foot\n\\begin_layout Plain Layout\n嵌套脚注\n\\end_layout\n\\end_inset\n\\end_layout\n\\end_inset\n正文中。\n\\begin_inset Foot\nstatus collapsed\n\\begin_layout Plain Layout\n脚注 SECRET-FOOT\n\\end_layout\n\\end_inset\n正文后。")
        result = extract_body(fragment(body))
        self.assertEqual(result.text, "正文前。正文中。正文后。")
        self.assertEqual(result.excluded, 2)

    def test_keeps_unicode_paragraphs_math_citations_and_inline_style(self):
        body = paragraph('中文 α。\n\\begin_inset Flex Emph\nstatus collapsed\n\\begin_layout Plain Layout\n强调正文\n\\end_layout\n\\end_inset\n\\begin_inset Formula $x_{i}=\\alpha$\n\\end_inset\n\\begin_inset CommandInset citation\nLatexCommand cite\nkey "paper2026"\n\\end_inset')
        result = extract_body(fragment(body + "\n" + paragraph("Second paragraph.")))
        self.assertEqual(result.text, '中文 α。强调正文$x_{i}=\\alpha$[paper2026]\n\nSecond paragraph.')

    def test_excludes_margins_figures_tables_unknown_blocks(self):
        for kind in ("Marginal", "Float figure", "Tabular", "Branch review", "UnknownObject"):
            with self.subTest(kind=kind):
                result = extract_body(fragment(paragraph(f"Before\n\\begin_inset {kind}\n\\begin_layout Plain Layout\nHIDDEN\n\\end_layout\n\\end_inset\nAfter")))
                self.assertEqual(result.text, "BeforeAfter")
                self.assertEqual(result.excluded, 1)

    def test_changed_deleted_text_is_not_sent(self):
        result = extract_body(fragment(paragraph("A\n\\change_deleted 0 123\nDELETED\n\\change_unchanged\nB")))
        self.assertEqual(result.text, "AB")

    def test_no_plaintext_fallback_or_malformed_insets(self):
        for source in ("plain text with footnote", fragment(paragraph("\\begin_inset Note Note\nsecret")), fragment(paragraph("\\end_inset")), fragment(paragraph("\\begin_inset Foot\n\\begin_layout Plain Layout\nsecret\n\\end_layout\n\\end_inset"))):
            with self.assertRaises(ValueError):
                extract_body(source)

    def test_target_and_context_are_separate(self):
        text = compose_context("TARGET", "BEFORE", "AFTER")
        self.assertLess(text.index("BEFORE"), text.index("TARGET"))
        self.assertLess(text.index("TARGET"), text.index("AFTER"))
        self.assertIn("revise only the target passage", text)
        self.assertEqual(compose_context("TARGET"), "TARGET")


class ContextWindowTests(unittest.TestCase):
    def test_stream_fragments_are_batched_and_flushed_on_finish(self):
        from PySide6.QtWidgets import QApplication
        from lyxai.core import Store
        from lyxai.ui import MainWindow
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow("TARGET", Store(Path(tmp)))
            for _ in range(1000):
                w.receive("字", "")
            self.assertEqual(w.answer.toPlainText(), "")
            self.assertTrue(w.display_timer.isActive())
            w.pending = [{"role": "user", "content": "TARGET"}]
            w.finished(dict(text="字" * 1000, finish="stop"))
            self.assertEqual(w.answer.toPlainText(), "字" * 1000)
            self.assertFalse(w.display_timer.isActive())
            w.close()

    def test_append_context_preserves_target_and_request_uses_it(self):
        from PySide6.QtWidgets import QApplication
        from lyxai.core import Store
        from lyxai.ui import MainWindow, choose
        app = QApplication.instance() or QApplication([])
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow("TARGET", Store(Path(tmp)))
            w.accept_message(dict(kind="before", text="BEFORE", excluded=1))
            w.accept_message(dict(kind="after", text="AFTER"))
            w.accept_message(dict(kind="before", text="MORE BEFORE"))
            self.assertEqual(w.selection.toPlainText(), "TARGET")
            self.assertEqual(w.before.toPlainText(), "BEFORE\n\nMORE BEFORE")
            request = w.initial_messages()[-1]["content"]
            self.assertIn("BEFORE", request)
            self.assertIn("AFTER", request)
            choose(w.language, "en")
            self.assertEqual(w.before.toPlainText(), "BEFORE\n\nMORE BEFORE")
            w.accept_message(dict(kind="selection", text="NEW TARGET"))
            self.assertEqual(w.before.toPlainText(), "")
            self.assertEqual(w.after.toPlainText(), "")
            w.close()

    def test_single_instance_delivery_ack(self):
        from PySide6.QtCore import QEventLoop, QProcess, QProcessEnvironment, QTimer
        from PySide6.QtWidgets import QApplication
        from lyxai.instance import InstanceServer
        app = QApplication.instance() or QApplication([])
        old = os.environ.get("LYXAI_DATA_DIR")
        with tempfile.TemporaryDirectory() as tmp:
            os.environ["LYXAI_DATA_DIR"] = tmp
            server = InstanceServer()
            self.assertTrue(server.listen())
            received = []
            server.received.connect(received.append)
            process = QProcess()
            env = QProcessEnvironment.systemEnvironment()
            env.insert("LYXAI_DATA_DIR", tmp)
            env.insert("QT_QPA_PLATFORM", "offscreen")
            process.setProcessEnvironment(env)
            code = "from PySide6.QtCore import QCoreApplication;from lyxai.instance import deliver;a=QCoreApplication([]);assert deliver({'kind':'before','text':'中文 context'});print('ACK')"
            process.start(sys.executable, ["-c", code])
            loop = QEventLoop()
            process.finished.connect(loop.quit)
            watchdog = QTimer()
            watchdog.setSingleShot(True)
            watchdog.timeout.connect(loop.quit)
            watchdog.start(4000)
            loop.exec()
            watchdog.stop()
            if process.state() != QProcess.ProcessState.NotRunning:
                process.kill()
                process.waitForFinished(500)
            error = bytes(process.readAllStandardError()).decode("utf-8", "replace")
            self.assertEqual(process.exitCode(), 0, error)
            self.assertEqual(received, [{"kind": "before", "text": "中文 context"}])
            server.server.close()
        if old is None:
            os.environ.pop("LYXAI_DATA_DIR", None)
        else:
            os.environ["LYXAI_DATA_DIR"] = old


if __name__ == "__main__":
    unittest.main()
