import os
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import shiboken6

from PySide6.QtCore import Qt, QEventLoop, QTimer
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication

from lyxai.core import Store, new_profile
from lyxai.history import HistoryStore, transcript
from lyxai.ui import MainWindow, HistoryDialog, SettingsDialog, STYLE, choose

APP = QApplication.instance() or QApplication([])


class PersistenceTests(unittest.TestCase):
    def setUp(self):
        patcher = patch('lyxai.ui.RichPreview.prepare')
        patcher.start()
        self.addCleanup(patcher.stop)
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)

    def window(self, text='Target'):
        w = MainWindow(text, Store(self.folder))
        self.addCleanup(lambda: shiboken6.delete(w))
        return w

    def answer(self, w, text='[REVISED]Revised $x$[/REVISED]', followup=False):
        with patch('lyxai.ui.NetworkJob'):
            w.run_request((w.history if followup else []) + [{'role': 'user', 'content': 'Question with 中文 100%_literal'}], followup=followup)
            w.finished(dict(text=text, reasoning='Returned summary', finish='stop', usage={'total_tokens': 12}))

    def test_all_preferences_and_each_edited_template_survive_reopen(self):
        w = self.window()
        p = new_profile('DeepSeek')
        w.config['profiles'].append(p)
        w.fill_profiles()
        choose(w.profile, p['id'])
        w.reply_lang.setEditText('My custom reply language')
        w.context_radius.setCurrentIndex(w.context_radius.findData(1200))
        w.auto_context.setChecked(False)
        w.prompt.setPlainText('Edited template A {selection}')
        w.templates.setCurrentIndex(3)
        w.prompt.setPlainText('Edited template B {selection}')
        w.input_tabs.setCurrentIndex(2)
        w.output_tabs.setCurrentIndex(2)
        w.resize(720, 480)
        w.save_preferences()  # Same callback as the debounce timer; no Save button.
        saved = Store(self.folder).load()
        self.assertEqual(saved['context_radius'], 1200)
        self.assertEqual(saved['reply_language'], 'My custom reply language')
        self.assertEqual(saved['active'], p['id'])
        self.assertFalse(saved['auto_context'])
        w.close()
        reopened = self.window()
        self.assertEqual(reopened.templates.currentIndex(), 3)
        self.assertEqual(reopened.prompt.toPlainText(), 'Edited template B {selection}')
        self.assertEqual(reopened.config['templates'][0]['prompt'], 'Edited template A {selection}')
        self.assertEqual(reopened.reply_lang.currentText(), 'My custom reply language')
        self.assertEqual(reopened.context_radius.currentData(), 1200)
        self.assertEqual(reopened.profile.currentData(), p['id'])
        self.assertEqual(reopened.input_tabs.currentIndex(), 2)
        self.assertEqual(reopened.output_tabs.currentIndex(), 2)
        self.assertEqual(reopened.size().toTuple(), (720, 480))

    def test_close_flushes_pending_preferences_and_language_switch_preserves_them(self):
        w = self.window()
        w.reply_lang.setEditText('Français')
        choose(w.context_radius, 1200)
        choose(w.language, 'en')
        self.assertEqual(w.reply_lang.currentText(), 'Français')
        self.assertEqual(w.context_radius.currentData(), 1200)
        w.templates.setCurrentIndex(5)
        w.prompt.setPlainText('Last unsaved edit {selection}')
        w.close()
        reopened = self.window()
        self.assertEqual(reopened.lang, 'en')
        self.assertEqual(reopened.templates.currentIndex(), 5)
        self.assertEqual(reopened.prompt.toPlainText(), 'Last unsaved edit {selection}')

    def test_preference_changes_reach_disk_automatically_without_closing(self):
        w = self.window()
        loop = QEventLoop()
        deadline = QTimer()
        deadline.setSingleShot(True)
        deadline.timeout.connect(loop.quit)
        w.preferences_timer.timeout.connect(loop.quit)
        w.reply_lang.setEditText('Deutsch')
        choose(w.context_radius, 1200)
        deadline.start(2000)
        loop.exec()
        deadline.stop()
        saved = Store(self.folder).load()
        self.assertEqual(saved['reply_language'], 'Deutsch')
        self.assertEqual(saved['context_radius'], 1200)

    def test_model_dialog_state_is_kept_when_parameter_edits_are_cancelled(self):
        w = self.window()
        dlg = SettingsDialog(w.config, w)
        original = dlg.model.currentText()
        dlg.model.setEditText('Uncommitted model')
        dlg.tabs.setCurrentIndex(3)
        dlg.resize(720, 480)
        with patch('lyxai.ui.SettingsDialog', return_value=dlg), patch.object(dlg, 'exec', side_effect=lambda: (dlg.reject(), dlg.result())[1]):
            w.settings()
        w.close()
        reopened = self.window()
        restored = SettingsDialog(reopened.config, reopened)
        self.assertEqual(restored.tabs.currentIndex(), 3)
        self.assertEqual(restored.model.currentText(), original)
        self.assertEqual(restored.size().toTuple(), (720, 480))
        restored.close()

    def test_completed_followups_restore_after_restart_without_credentials_or_target_binding(self):
        w = self.window()
        w.config['profiles'][0].update(api_key='SECRET-API-KEY', headers={'Authorization': 'SECRET-HEADER'}, proxy='http://user:SECRET-PASSWORD@localhost:1234')
        self.answer(w)
        first_id = w.session['id']
        self.answer(w, 'Latest answer', followup=True)
        self.assertEqual(w.session['id'], first_id)
        self.assertEqual(len(w.archive.list()), 1)
        self.assertEqual(len(w.archive.get(first_id)['turns']), 2)
        self.assertIn('Latest answer', w.conversation.toPlainText())
        w.close()
        reopened = self.window('')
        self.assertEqual(reopened.answer_text, 'Latest answer')
        self.assertEqual(len(reopened.history), 4)
        self.assertTrue(reopened.follow_btn.isEnabled())
        self.assertIsNone(reopened.lyx_payload)
        raw = reopened.archive.path.read_bytes()
        for secret in (b'SECRET-API-KEY', b'SECRET-HEADER', b'SECRET-PASSWORD'):
            self.assertNotIn(secret, raw)

    def test_new_request_archives_previous_and_partial_error_is_recoverable(self):
        w = self.window()
        self.answer(w, 'First answer')
        first = w.session['id']
        with patch('lyxai.ui.NetworkJob'):
            w.run_request([{'role': 'user', 'content': 'Another question'}])
            w.receive('Partial output', 'Partial reasoning')
            w.failed('Cancelled / 已取消')
        self.assertEqual(len(w.archive.list()), 2)
        self.assertEqual(w.archive.get(first)['turns'][0]['answer'], 'First answer')
        turn = w.archive.get(w.session['id'])['turns'][0]
        self.assertEqual(turn['status'], 'cancelled')
        self.assertEqual(turn['answer'], 'Partial output')
        self.assertIn('Another question', w.conversation.toPlainText())
        self.assertIn('Partial reasoning', w.conversation.toPlainText())
        self.assertEqual(w.history, [])
        self.assertFalse(w.follow_btn.isEnabled())

    def test_reopening_history_does_not_override_latest_model_preference(self):
        w = self.window()
        self.answer(w)
        model = new_profile('DeepSeek')
        w.config['profiles'].append(model)
        w.profile.blockSignals(True)
        w.fill_profiles()
        w.profile.blockSignals(False)
        choose(w.profile, model['id'])
        w.close()
        reopened = self.window('')
        self.assertEqual(reopened.profile.currentData(), model['id'])
        self.assertEqual(reopened.answer_text, '[REVISED]Revised $x$[/REVISED]')

    def test_pending_request_survives_interruption_and_search_treats_wildcards_literally(self):
        w = self.window()
        with patch('lyxai.ui.NetworkJob'):
            w.run_request([{'role': 'user', 'content': '100%_literal'}])
            saved = w.archive.get(w.session['id'])
            self.assertEqual(saved['turns'][0]['status'], 'interrupted')
            self.assertIn('interrupted', transcript(saved))
            self.assertEqual(len(w.archive.list('%_literal')), 1)
            self.assertEqual(len(w.archive.list('not present')), 0)
            w.job = None

    def test_history_dialog_search_load_and_delete(self):
        w = self.window()
        self.answer(w)
        dlg = HistoryDialog(w.archive, 'zh', w)
        self.assertEqual(dlg.list.count(), 1)
        self.assertIn('Question with 中文', dlg.detail.toPlainText())
        dlg.search.setText('absent')
        dlg.refresh()
        self.assertEqual(dlg.list.count(), 0)
        self.assertFalse(dlg.load_btn.isEnabled())
        dlg.search.clear()
        dlg.refresh()
        dlg.delete_selected()
        self.assertFalse(w.archive.list())
        w.session = None
        dlg.close()

    def test_single_line_status_keeps_full_multiline_message_in_tooltip(self):
        w = self.window()
        full = 'First line\nSecond line\r\n' + 'Long message ' * 100
        height = w.status.height()
        w.status.resize(180, height)
        w.status.setText(full)
        self.assertNotIn('\n', w.status.text())
        self.assertEqual(w.status.height(), height)
        self.assertEqual(w.status.toolTip(), full)
        self.assertEqual(w.status.full_text, full)

    def test_small_windows_keep_global_controls_reachable_in_both_languages(self):
        for name in ('segoeui.ttf', 'msyh.ttc'):
            font = Path(os.environ.get('WINDIR', '')) / 'Fonts' / name
            if font.exists():
                QFontDatabase.addApplicationFont(str(font))
        previous_font = APP.font()
        APP.setFont(QFont('Segoe UI', 10))
        previous_style = APP.styleSheet()
        APP.setStyleSheet(STYLE)
        try:
            w = self.window()
            for lang in ('zh', 'en'):
                choose(w.language, lang)
                for size in ((640, 480), (800, 600), (1024, 600)):
                    w.resize(*size)
                    w.show()
                    APP.processEvents()
                    self.assertEqual(w.size().toTuple(), size)
                    for button in (w.apply_btn, w.send_btn, w.history_btn):
                        self.assertTrue(w.centralWidget().rect().contains(button.geometry()))
                    self.assertGreater(w.source_scroll.verticalScrollBar().maximum(), 0)
            dlg = SettingsDialog(w.config, w)
            dlg.resize(640, 480)
            dlg.show()
            APP.processEvents()
            self.assertEqual(dlg.size().toTuple(), (640, 480))
            self.assertEqual(dlg.split.orientation(), Qt.Orientation.Vertical)
            dlg.close()
        finally:
            APP.setFont(previous_font)
            APP.setStyleSheet(previous_style)
