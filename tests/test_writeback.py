"""Live destination semantics without starting LyX or touching the clipboard."""
import unittest
from unittest.mock import MagicMock, patch

from lyxai.bridge import apply_replacement, load_context, notify_lyx_clipboard
from lyxai.errors import LyXCommandError
from lyxai.replacement import latex_input, source_destination, source_fragment
from lyxai.selection import extract_body


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
        self.assertEqual(clipboard.call_args.kwargs, {'notify_pid': 123})
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

    def test_clipboard_refresh_failure_never_pastes(self):
        with patch('lyxai.bridge.LyXServer', return_value=self.server), patch('lyxai.integration.capture_lyx_payload', return_value=self.selection), patch('lyxai.bridge.set_native_clipboard', side_effect=RuntimeError('Clipboard refresh timed out')):
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                apply_replacement(self.payload, 'Revision', stem='test')
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

    def test_latex_text_uses_native_importer_and_current_document(self):
        with patch('lyxai.bridge.LyXServer', return_value=self.server), patch('lyxai.integration.capture_lyx_payload', return_value=self.selection), patch('lyxai.bridge.set_native_clipboard') as clipboard:
            apply_replacement(self.payload, r'\textbf{Bold} $x=1$', stem='test')
        self.assertEqual(self.server.command.call_args.args, ('paste', 'latex'))
        self.assertEqual(clipboard.call_args.args[1], r'\textbf{Bold} $x=1$')
        self.assertIsNone(clipboard.call_args.args[0])  # Do not leave stale native text on the clipboard.

    def test_ert_interior_with_standard_clipboard_layout_uses_live_layout(self):
        self.layout = 'Plain Layout'
        self.selection['native'] = native('\\backslash\ntextbf{Old code}')
        with patch('lyxai.bridge.LyXServer', return_value=self.server), patch('lyxai.integration.capture_lyx_payload', return_value=self.selection), patch('lyxai.bridge.set_native_clipboard') as clipboard:
            apply_replacement(self.payload, r'\emph{New $x$}', stem='test')
        self.assertEqual(self.server.command.call_args.args, ('paste',))
        self.assertIn('\\begin_layout Plain Layout\n', clipboard.call_args.args[0])
        self.assertIn('\\backslash\nemph{New $x$}', clipboard.call_args.args[0])
        self.assertNotIn('\\begin_inset Formula', clipboard.call_args.args[0])


class ClipboardNotificationTests(unittest.TestCase):
    def test_only_target_process_clipboard_listener_is_refreshed_and_failures_abort(self):
        api = MagicMock()
        api.EnumWindows.side_effect = lambda callback, _: callback(101, 0)
        def owner(hwnd, pointer):
            pointer._obj.value = 456 if hwnd == 201 else 123
        def name(hwnd, buffer, size):
            buffer.value = 'MainWindow' if hwnd == 101 else 'Qt6QWindowClipboardView'
        api.GetWindowThreadProcessId.side_effect = owner
        api.GetClassNameW.side_effect = name
        with patch('lyxai.bridge.ctypes.WinDLL', return_value=api, create=True), patch('lyxai.bridge.ctypes.WINFUNCTYPE', return_value=lambda fn: fn, create=True):
            api.FindWindowExW.side_effect = [201, 202, None]
            api.SendMessageTimeoutW.return_value = 1
            notify_lyx_clipboard(123)
            self.assertEqual(api.SendMessageTimeoutW.call_count, 1)
            self.assertEqual(api.SendMessageTimeoutW.call_args.args[:6], (202, 0x031D, 0, 0, 2, 1500))
            api.FindWindowExW.side_effect = [None]
            with self.assertRaisesRegex(RuntimeError, 'listener unavailable'):
                notify_lyx_clipboard(123)
            api.FindWindowExW.side_effect = [202, None]
            api.SendMessageTimeoutW.return_value = 0
            with self.assertRaisesRegex(RuntimeError, 'timed out'):
                notify_lyx_clipboard(123)


class RegionSerializationTests(unittest.TestCase):
    def test_theorem_aliases_respect_loaded_module_and_preserve_math(self):
        document = native('Existing').replace('\\end_header', '\\begin_modules\ntheorems-ams\n\\end_modules\n\\end_header')
        result = latex_input(r'\begin{lemma}[Title]\label{lem:x}A $x$ and \begin{aligned}a&=b\\c&=d\end{aligned}.\end{lemma}', document)
        self.assertIn(r'\begin{lem}[Title]', result)
        self.assertIn(r'\label{lem:x}', result)
        self.assertIn('\\[\n\\begin{aligned}', result)
        self.assertIn(r'\end{lem}', result)
        with self.assertRaisesRegex(ValueError, 'AMS Theorems'):
            latex_input(r'\begin{theorem}A\end{theorem}', native('No module'))

    def test_plain_theorem_passage_keeps_its_native_layout(self):
        from lyxai.replacement import replacement_fragment
        result = replacement_fragment(native('Old lemma', 'Lemma'), r'New lemma $x$.')
        self.assertIn('\\begin_layout Lemma\n', result)
        self.assertIn('\\begin_inset Formula $x$', result)

    def test_ert_is_available_only_for_selected_import_not_body_context(self):
        ert = '\\begin_inset ERT\nstatus open\n\\begin_layout Plain Layout\n\\backslash\ntextbf{Old source}\n\\end_layout\n\\end_inset'
        selection = native(ert)
        with self.assertRaisesRegex(ValueError, 'No body text'):
            extract_body(selection)
        self.assertEqual(extract_body(selection, include_ert=True).text, r'\textbf{Old source}')
        self.assertEqual(source_destination(selection), 'object')
        result = source_fragment(selection, '\\textbf{New}\n$x=1$', 'object')
        self.assertIn('\\begin_inset ERT\n', result)
        self.assertEqual(extract_body(result, include_ert=True).text, '\\textbf{New}\n$x=1$')
        self.assertNotIn('\\begin_inset Formula', result)

    def test_source_interior_preserves_backslashes_and_cannot_inject_native_insets(self):
        original = native(r'\textbf{Old}', 'Plain Layout')
        self.assertEqual(source_destination(original), 'interior')
        result = source_fragment(original, r'\emph{New $x$}', 'interior')
        self.assertIn('\\begin_layout Plain Layout\n', result)
        self.assertNotIn('\\begin_inset Formula', result)
        with self.assertRaises(ValueError):
            source_fragment(original, '\\end_layout\n\\begin_inset ERT', 'interior')

    def test_latex_fences_are_explicit_and_unsafe_commands_are_refused(self):
        self.assertEqual(latex_input('```latex\n\\textbf{Bold}\n```', native('A')), r'\textbf{Bold}')
        self.assertIsNone(latex_input('```python\n\\textbf{Bold}\n```', native('A')))
        self.assertIsNone(latex_input(r'`\textbf{Code}`', native('A')))
        for code in (r'\input{secret}', r'\write18{execute}', r'\csname input\endcsname{secret}'):
            with self.assertRaises(ValueError):
                latex_input('```tex\n'+code+'\n```', native('A'))
        with self.assertRaisesRegex(ValueError, 'Incomplete'):
            latex_input(r'\begin{lemma}Unclosed', native('A'))
