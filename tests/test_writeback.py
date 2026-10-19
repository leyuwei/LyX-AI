"""Live destination semantics without starting LyX or touching the clipboard."""
import unittest
from unittest.mock import MagicMock, patch

from lyxai.bridge import apply_replacement, load_context
from lyxai.errors import LyXCommandError


def native(text, layout='Standard'):
    return ('\\lyxformat 643\n\\begin_document\n\\begin_header\n\\language english\n'
            '\\end_header\n\\begin_body\n\\begin_layout ' + layout + '\n' + text +
            '\n\\end_layout\n\\end_body\n\\end_document\n')


class LiveDestinationTests(unittest.TestCase):
    def setUp(self):
        self.payload = dict(filename='original.lyx', owner_pid=123, native=native('Old target'), text='Old target', document_hash='obsolete')
        self.server = MagicMock()
        self.server.__enter__.return_value = self.server
        self.server.command.side_effect = self.command
        self.server.snapshot.return_value = native('Edited document with Old target')
        self.copy_error = None
        self.filename = 'original.lyx'
        self.layout = 'Standard'
        self.selection = dict(owner_pid=123, native=native('New destination', 'Section'))

    def command(self, name, argument=''):
        if name == 'server-get-filename':
            return self.filename
        if name == 'server-get-layout':
            return self.layout
        if name == 'copy' and self.copy_error:
            raise self.copy_error
        return ''

    def apply(self):
        with patch('lyxai.bridge.LyXServer', return_value=self.server), patch('lyxai.integration.capture_lyx_payload', return_value=self.selection) as capture, patch('lyxai.bridge.set_native_clipboard') as clipboard:
            result = apply_replacement(self.payload, r'Revised $x^2$', stem='test')
            return result, capture, clipboard

    def test_latest_selection_supplies_layout_despite_document_edits(self):
        result, capture, clipboard = self.apply()
        self.assertEqual(result['mode'], 'replace')
        self.assertIn('\\begin_layout Section\n', clipboard.call_args.args[0])
        self.assertIn('\\begin_inset Formula $x^2$', clipboard.call_args.args[0])
        self.server.snapshot.assert_not_called()  # No obsolete full-document hash guard.
        self.assertEqual(self.server.command.call_args.args, ('paste',))

    def test_caret_ignores_stale_clipboard_and_uses_live_layout(self):
        self.copy_error = LyXCommandError('Command disabled')
        self.layout = 'Subsection'
        result, capture, clipboard = self.apply()
        self.assertEqual(result['mode'], 'insert')
        capture.assert_not_called()
        self.assertIn('\\begin_layout Subsection\n', clipboard.call_args.args[0])
        self.assertNotIn('Old target', clipboard.call_args.args[0])

    def test_transport_failure_never_becomes_insertion(self):
        self.copy_error = TimeoutError('LyX did not reply')
        with patch('lyxai.bridge.LyXServer', return_value=self.server), patch('lyxai.bridge.set_native_clipboard') as clipboard:
            with self.assertRaises(TimeoutError):
                apply_replacement(self.payload, 'Revised', stem='test')
            clipboard.assert_not_called()
        self.assertFalse(any(call.args[0] == 'paste' for call in self.server.command.call_args_list))

    def test_document_switch_during_preparation_stops_paste(self):
        def switch():
            self.filename = 'other.lyx'
            return self.selection
        with patch('lyxai.bridge.LyXServer', return_value=self.server), patch('lyxai.integration.capture_lyx_payload', side_effect=switch), patch('lyxai.bridge.set_native_clipboard'):
            with self.assertRaisesRegex(ValueError, 'document changed'):
                apply_replacement(self.payload, 'Revised', stem='test')
        self.assertFalse(any(call.args[0] == 'paste' for call in self.server.command.call_args_list))

    def test_other_document_or_process_is_not_overwritten(self):
        self.filename = 'other.lyx'
        with self.assertRaisesRegex(ValueError, 'document changed'):
            self.apply()
        self.filename = 'original.lyx'
        self.selection['owner_pid'] = 456
        with self.assertRaisesRegex(ValueError, 'process changed'):
            self.apply()
        self.assertFalse(any(call.args[0] == 'paste' for call in self.server.command.call_args_list))

    def test_context_does_not_need_original_selection_to_stay_active(self):
        self.copy_error = LyXCommandError('Command disabled')
        with patch('lyxai.bridge.LyXServer', return_value=self.server):
            result = load_context(self.payload, stem='test')
        self.assertEqual(result['filename'], 'original.lyx')
        self.assertEqual(result['before'], 'Edited document with')
        self.assertFalse(any(call.args[0] == 'copy' for call in self.server.command.call_args_list))
