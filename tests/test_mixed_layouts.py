"""Mixed native layouts, LaTeX/ERT provenance and request structure; no desktop."""
import unittest
from unittest.mock import patch

from lyxai.bridge import apply_replacement
from lyxai.replacement import (latex_input, native_paragraphs, replacement_fragment,
                              source_destination, structured_selection)
from test_writeback import native
import test_writeback as writeback_tests


def mixed(*parts):
    return native('').split(r'\begin_body')[0].replace('\\end_header', '\\begin_modules\ntheorems-ams\n\\end_modules\n\\end_header') + '\\begin_body\n' + ''.join('\\begin_layout ' + layout + '\n' + text.replace('\\begin_inset', '\n\\begin_inset') + '\n\\end_layout\n' for layout, text in parts) + '\\end_body\n\\end_document\n'


ERT = '\\begin_inset ERT\nstatus open\n\\begin_layout Plain Layout\n\\backslash\nfbox{source}\n\\end_layout\n\\end_inset'


class MixedLayoutTests(unittest.TestCase):
    def test_preserves_each_layout_style_label_and_nested_structure(self):
        label = '\\begin_inset CommandInset label\nLatexCommand label\nname "thm:one"\n\\end_inset'
        original = mixed(('Theorem', label + '\nOld theorem.'), ('Proof', '\\lang english\nProof.'), ('Standard', 'Body ' + ERT), ('Theorem', 'Second theorem.'))
        result = replacement_fragment(original, 'New theorem $a$.\n\nNew proof.\n\nNew body.\n\nSecond new theorem.')
        paragraphs = native_paragraphs(result)
        self.assertEqual([p.layout for p in paragraphs], ['Theorem', 'Proof', 'Standard', 'Theorem'])
        self.assertIn(label, paragraphs[0].body)
        self.assertIn('\\lang english', paragraphs[1].body)
        self.assertIn('\\begin_inset Formula $a$', result)
        nested = original.replace('\\begin_layout Proof', '\\begin_deeper\n\\begin_layout Proof').replace('\\begin_layout Standard', '\\end_deeper\n\\begin_layout Standard')
        rewritten = replacement_fragment(nested, 'A.\n\nB.\n\nC.\n\nD.')
        self.assertEqual([p.depth for p in native_paragraphs(rewritten)], [0, 1, 0, 0])

    def test_unstructured_changed_paragraph_count_uses_body_without_guessing_theorems(self):
        original = mixed(('Theorem', 'A.'), ('Proof', 'B.'))
        self.assertEqual([p.layout for p in native_paragraphs(replacement_fragment(original, 'One body paragraph.'))], ['Standard'])

    def test_empty_clipboard_edges_keep_the_unselected_paragraph_layout(self):
        original = mixed(('Standard', ''), ('Theorem', 'A.'), ('Proof', 'B.'), ('Theorem', ''))
        result = replacement_fragment(original, 'New A.\n\nNew B.')
        paragraphs = native_paragraphs(result)
        self.assertEqual([p.layout for p in paragraphs], ['Standard', 'Theorem', 'Proof', 'Theorem'])
        self.assertNotIn('New', paragraphs[0].body + paragraphs[-1].body)
        text = structured_selection(original)
        self.assertEqual(text.count(r'\begin{theorem}'), 1)

    def test_structured_request_keeps_theorems_proofs_ert_math_refs_and_filters_notes(self):
        note = '\\begin_inset Note Note\n\\begin_layout Plain Layout\nDO NOT SEND\n\\end_layout\n\\end_inset'
        reference = '\\begin_inset CommandInset ref\nLatexCommand ref\nreference "thm:one"\n\\end_inset'
        original = mixed(('Theorem', 'Rate is 10% ' + note), ('Proof', 'From ' + reference), ('Standard', 'Body & ' + ERT), ('Theorem', '\\begin_inset Formula $x_i$\n\\end_inset'))
        text = structured_selection(original)
        self.assertEqual(text.count(r'\begin{theorem}'), 2)
        self.assertIn(r'\begin{proof}', text)
        self.assertIn(r'\fbox{source}', text)
        self.assertIn(r'\ref{thm:one}', text)
        self.assertIn(r'10\%', text)
        self.assertIn(r'Body \&', text)
        self.assertIn('$x_i$', text)
        self.assertNotIn('DO NOT SEND', text)
        self.assertNotIn('LYXAISOURCEPLACEHOLDER', text)
        imported = latex_input(text, original)
        self.assertIn(r'\begin{thm}', imported)

    def test_embedded_latex_fences_and_commands_route_to_importer_safely(self):
        text = 'Body.\n\n```latex\n\\begin{theorem}A.\\end{theorem}\n```\n\n```tex\n\\begin{proof}B.\\end{proof}\n```\n\n\\fbox{Ending}'
        imported = latex_input(text, mixed(('Theorem', 'A.')))
        self.assertIn(r'\begin{thm}', imported)
        self.assertIn(r'\begin{proof}', imported)
        self.assertIn(r'\fbox{Ending}', imported)
        self.assertNotIn('```', imported)
        self.assertIsNone(latex_input(r'Body $x$ and \ref{key}.', native('A')))
        self.assertIsNone(latex_input(r'`\fbox{literal code}`', native('A')))
        with self.assertRaises(ValueError):
            latex_input('Body\n```latex\n\\input{secret}\n```', native('A'))
        with self.assertRaises(ValueError):
            latex_input('\\end_layout\n\\begin_inset ERT', native('A'))

    def test_mixed_empty_paragraph_and_ert_are_not_an_entire_source_object(self):
        self.assertIsNone(source_destination(mixed(('Theorem', ''), ('Standard', ERT))))
        self.assertEqual(source_destination(mixed(('Standard', ERT))), 'object')


class MixedDestinationTests(unittest.TestCase):
    def setUp(self):
        helper = writeback_tests.LiveDestinationTests()
        helper.setUp()
        self.helper = helper

    def test_end_caret_in_ert_does_not_turn_the_whole_selection_into_source(self):
        h = self.helper
        h.layout = 'Plain Layout'
        h.selection['native'] = mixed(('Theorem', 'A.'), ('Proof', 'B.'), ('Standard', ERT))
        with patch('lyxai.bridge.LyXServer', return_value=h.server), patch('lyxai.integration.capture_lyx_payload', return_value=h.selection), patch('lyxai.bridge.set_native_clipboard') as clipboard:
            result = apply_replacement(h.payload, 'New A.\n\nNew B.\n\nNew C.', stem='test')
        self.assertFalse(result['layout_fallback'])
        self.assertEqual([p.layout for p in native_paragraphs(clipboard.call_args.args[0])], ['Theorem', 'Proof', 'Standard'])

    def test_mixed_target_supports_different_sized_structured_replacement_or_notice(self):
        h = self.helper
        h.selection['native'] = mixed(('Theorem', 'A.'), ('Proof', 'B.'))
        h.server.snapshot.return_value = h.selection['native']
        with patch('lyxai.bridge.LyXServer', return_value=h.server), patch('lyxai.integration.capture_lyx_payload', return_value=h.selection), patch('lyxai.bridge.set_native_clipboard'):
            result = apply_replacement(h.payload, 'Unstructured one paragraph.', stem='test')
            self.assertTrue(result['layout_fallback'])
            result = apply_replacement(h.payload, 'Intro.\n\\begin{theorem}A.\\end{theorem}\n\\begin{proof}B.\\end{proof}\nEnd.', stem='test')
            self.assertFalse(result['layout_fallback'])
            self.assertEqual(h.server.command.call_args.args, ('paste', 'latex'))

    def test_latex_import_keeps_the_trailing_unselected_paragraph_out_of_the_merge(self):
        h = self.helper
        h.layout = 'Proof'
        h.selection['native'] = mixed(('Theorem', 'A.'), ('Proof', ''))
        h.server.snapshot.return_value = h.selection['native']
        with patch('lyxai.bridge.LyXServer', return_value=h.server), patch('lyxai.integration.capture_lyx_payload', return_value=h.selection), patch('lyxai.bridge.set_native_clipboard'):
            apply_replacement(h.payload, r'\begin{theorem}New A.\end{theorem}', stem='test')
        self.assertEqual(h.server.command.call_args.args, ('command-sequence', 'char-backward-select; paste latex'))

    def test_ambiguous_reverse_latex_boundary_stops_before_clipboard_or_paste(self):
        h = self.helper
        h.layout = 'Theorem'
        h.selection['native'] = mixed(('Theorem', 'A.'), ('Proof', ''))
        h.server.snapshot.return_value = h.selection['native']
        with patch('lyxai.bridge.LyXServer', return_value=h.server), patch('lyxai.integration.capture_lyx_payload', return_value=h.selection), patch('lyxai.bridge.set_native_clipboard') as clipboard:
            with self.assertRaisesRegex(ValueError, 'mixed layouts are supported'):
                apply_replacement(h.payload, r'\begin{theorem}New A.\end{theorem}', stem='test')
            clipboard.assert_not_called()
        self.assertFalse(any(call.args[0] in ('paste', 'command-sequence') for call in h.server.command.call_args_list))
