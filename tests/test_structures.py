"""Fast structural regressions. No LyX, subprocess, clipboard or desktop."""
from pathlib import Path
import unittest
from unittest.mock import patch, Mock

from lyxai.core import builtin_templates, STRUCTURE_RULES
from lyxai.bridge import apply_replacement, automatic_context, WindowsLyXServer
from lyxai.latex_import import layout_configuration, normalize_environments
from lyxai.replacement import latex_input, structured_selection, source_destination, replacement_fragment
from lyxai.selection import extract_body
from lyxai.structure import (protected_objects, restore_objects, merge_metadata,
                             require_preserved, marker, wrap, OBJECT)
from test_writeback import native
import test_writeback

FIXTURES = Path(__file__).with_name('fixtures')


class StructureTests(unittest.TestCase):
    def setUp(self):
        self.objects = (FIXTURES.parents[1] / 'examples/objects-demo.lyx').read_text(encoding='utf-8')

    def test_selected_content_includes_tables_boxes_captions_labels_and_source(self):
        text = extract_body(self.objects).text
        for value in ('Original figure', 'Original table', 'Alpha', '$x_1$', 'Inside box',
                      r'\label{fig:sample}', r'\label{tab:sample}', r'\centering', r'\includegraphics{sample.png}'):
            self.assertIn(value, text)
        for value in ('<cell', 'topline=', 'placement htbp', 'has_inner_box', 'status open', 'width 30text%'):
            self.assertNotIn(value, text)

    def test_request_contains_editable_structures_and_preserves_resource_provenance(self):
        text = structured_selection(self.objects)
        for value in (r'\begin{figure}[htbp]', r'\begin{table}[htbp]', r'\caption{',
                      r'\begin{tabular}{lr}', r'\begin{minipage}{0.6\textwidth}',
                      r'\label{fig:sample}', r'\noindent', r'\begin{spacing}{1.5}'):
            self.assertIn(value, text)
        self.assertEqual(len(OBJECT.findall(text)), 2)  # Graphics and native hspace.
        self.assertEqual(len(protected_objects(self.objects)), 2)
        require_preserved(self.objects, text)

    def test_unknown_and_merged_tables_remain_native_and_expose_readable_content(self):
        raw = '\\begin_inset UnknownObject\nstatus open\n\\begin_layout Plain Layout\nReadable content\n\\end_layout\n\\end_inset'
        original = native(raw)
        text = structured_selection(original)
        self.assertIn('Readable content', text)
        self.assertIn(marker(raw), text)
        self.assertIn(marker(raw), protected_objects(original))
        table = self.objects.replace('alignment="left" valignment="top" topline', 'multicolumn="1" alignment="left" valignment="top" topline', 1)
        self.assertIn('LyX Tabular:', structured_selection(table))
        self.assertEqual(len(protected_objects(table)), 3)

    def test_annotations_do_not_leak_through_nested_container_or_comments(self):
        note = '\\begin_inset Note Note\nstatus collapsed\n\\begin_layout Plain Layout\nTOP SECRET\n\\begin_inset CommandInset label\nLatexCommand label\nname "secret:label"\n\\end_inset\n\\end_layout\n\\end_inset'
        original = self.objects.replace('Original figure ', 'Original figure \n' + note + '\n')
        for text in (structured_selection(original), extract_body(original).text):
            self.assertNotIn('TOP SECRET', text)
            self.assertNotIn('secret:label', text)
        self.assertEqual(extract_body(original).excluded, 1)
        require_preserved(original, structured_selection(original))

    def test_object_token_survives_only_display_state_changes(self):
        one = '\\begin_inset Graphics\nstatus open\nfilename sample.png\n\\end_inset'
        self.assertEqual(marker(one), marker(one.replace('status open', 'status collapsed')))
        self.assertNotEqual(marker(one), marker(one.replace('sample.png', 'changed.png')))

    def test_resource_paths_use_clipboard_origin_before_native_paste(self):
        root = FIXTURES.resolve()
        raw = '\\begin_inset Graphics\n\tfilename sample.png\nwidth 30text%\n\\end_inset'
        original = native(raw).replace('\\end_header', '\\origin ' + str(root).replace('\\', '/') + '/\n\\end_header')
        objects = protected_objects(original)
        self.assertIn(marker(raw), objects)
        self.assertIn(str(root / 'sample.png').replace('\\', '/'), objects[marker(raw)])

    def test_automatic_context_matches_images_despite_clipboard_path_rebasing(self):
        raw = '\\begin_inset Graphics\nfilename sample.png\n\\end_inset'
        target = native('Caption.\n' + raw.replace('sample.png', '../rebased/sample.png'))
        snapshot = native('Before.\nCaption.\n' + raw + '\nAfter.')
        context = automatic_context(target, snapshot)
        self.assertEqual((context['before'], context['after']), ('Before.', 'After.'))

    def test_missing_selected_label_or_picture_is_reported(self):
        text = structured_selection(self.objects)
        with self.assertRaisesRegex(ValueError, 'label: fig:sample'):
            require_preserved(self.objects, text.replace(r'\label{fig:sample}', ''))
        token = next(key for key, raw in protected_objects(self.objects).items() if 'Graphics' in raw)
        with self.assertRaisesRegex(ValueError, 'Graphics'):
            require_preserved(self.objects, text.replace(token, ''))

    def test_repeated_images_cannot_be_silently_collapsed(self):
        raw = '\\begin_inset Graphics\nfilename sample.png\n\\end_inset'
        original = native(raw + '\n' + raw)
        text = structured_selection(original)
        with self.assertRaisesRegex(ValueError, 'Graphics'):
            require_preserved(original, text.replace(marker(raw), '', 1))

    def test_labels_in_comments_do_not_bypass_preservation_check(self):
        text = structured_selection(self.objects)
        text = text.replace(r'\label{fig:sample}', '') + '\n% \\label{fig:sample}\n'
        with self.assertRaisesRegex(ValueError, 'label: fig:sample'):
            require_preserved(self.objects, text)

    def test_labels_inside_opaque_objects_do_not_require_separate_duplicate_labels(self):
        label = '\\begin_inset CommandInset label\nLatexCommand label\nname "inner:label"\n\\end_inset'
        raw = '\\begin_inset UnknownContainer\n\\begin_layout Plain Layout\n' + label + '\nText\n\\end_layout\n\\end_inset'
        require_preserved(native(raw), marker(raw))

    def test_framed_box_keeps_its_original_native_type(self):
        original = self.objects.replace('Box Frameless', 'Box Framed')
        result = merge_metadata(original, self.objects.replace('Inside box', 'Changed box'))
        self.assertIn(r'\begin_inset Box Framed', result)
        self.assertIn('Changed box', result)

    def test_caption_short_title_is_separate_from_editable_caption(self):
        argument = '\\begin_inset Argument 1\nstatus open\n\\begin_layout Plain Layout\nShort title\n\\end_layout\n\\end_inset'
        original = self.objects.replace('Original figure ', argument + '\nOriginal figure ')
        self.assertIn(r'\caption[{Short title}]{Original figure', structured_selection(original))

    def test_restore_only_recognized_complete_ert_nodes(self):
        raw = '\\begin_inset Graphics\nfilename sample.png\n\\end_inset'
        token = marker(raw)
        ert = '\\begin_inset ERT\nstatus collapsed\n\\begin_layout Plain Layout\n\\backslash\n' + token[1:] + '\n\\end_layout\n\\end_inset'
        converted = native('A\n' + ert + '\nB')
        result = restore_objects(converted, {token: raw})
        self.assertIn(raw, result)
        self.assertNotIn('lyxaiobject', result)
        self.assertEqual(restore_objects(native('Literal ' + token), {token: raw}), native('Literal ' + token))

    def test_table_borders_widths_float_box_and_spacing_survive_edits(self):
        rewritten = self.objects.replace('Alpha', 'Gamma').replace('Original figure', 'Revised figure').replace('Inside box', 'Revised box')
        rewritten = rewritten.replace('topline="true"', 'topline="false"').replace('width "60text%"', 'width "80text%"').replace('placement htbp', 'placement p').replace('\\paragraph_spacing other 1.5', '\\paragraph_spacing double')
        result = merge_metadata(self.objects, rewritten)
        for value in ('Gamma', 'Revised figure', 'Revised box', 'width "60text%"', 'topline="true"', 'placement htbp', r'\paragraph_spacing other 1.5'):
            self.assertIn(value, result)
        self.assertNotIn('topline="false"', result)
        self.assertNotIn('width "80text%"', result)

    def test_caption_and_box_plain_layout_are_prose_not_source(self):
        self.assertIsNone(source_destination(native('Caption text', 'Plain Layout')))
        result = replacement_fragment(native('Caption text', 'Plain Layout'), r'Revised $x$')
        self.assertIn(r'\begin_inset Formula $x$', result)

    def test_every_builtin_contains_structure_rules(self):
        for template in builtin_templates():
            self.assertIn(STRUCTURE_RULES, template['prompt'])
            self.assertEqual(template['prompt'].count('{selection}'), 1)


class PreflightTests(unittest.TestCase):
    def test_snapshot_waits_for_deferred_and_partial_windows_exports(self):
        for partial in (None, 'incomplete export'):
            with self.subTest(partial=partial):
                server = object.__new__(WindowsLyXServer)
                server.timeout = 1
                target = []
                def export(_, argument):
                    target.append(Path(argument[4:]))
                    if partial:
                        target[0].write_text(partial, encoding='utf-8')
                server.command = Mock(side_effect=export)
                with patch('lyxai.bridge.time.sleep', side_effect=lambda _: target[0].write_text(native('Ready'), encoding='utf-8')):
                    self.assertEqual(server.snapshot(), native('Ready'))
                server.command.assert_called_once()

    def test_snapshot_timeout_does_not_resend_the_export(self):
        server = object.__new__(WindowsLyXServer)
        server.timeout = 0
        server.command = Mock()
        with self.assertRaisesRegex(RuntimeError, 'complete current LyX buffer'):
            server.snapshot()
        server.command.assert_called_once()

    def test_ieee_class_provides_standard_theorems_and_excludes_ams_modules(self):
        # Minimal installed-layout model keeps this regression platform-independent.
        files = {
            'IEEEtran.layout': 'Input theorems.inc\nProvidesModule theorems-std\nStyle Proof\n LatexName IEEEproof\nEnd',
            'theorems.inc': 'Style Lemma\n LatexName lem\nEnd',
            'theorems-ams-bytype.module': '#Excludes: theorems-std | theorems-ams\n',
            'theorems-ams-extended-bytype.module': '#Requires: theorems-ams-bytype\n',
        }
        doc = native('Old').replace('\\end_header', '\\textclass IEEEtran\n\\begin_modules\ntheorems-ams-bytype\ntheorems-ams-extended-bytype\n\\end_modules\n\\end_header')
        with patch.object(Path, 'is_file', lambda p: p.name in files), patch.object(Path, 'read_text', lambda p, **_: files[p.name]):
            cls, modules, layouts = layout_configuration(doc)
            self.assertEqual((cls, modules, layouts['Proof']), ('IEEEtran', [], 'IEEEproof'))
            text = normalize_environments(r'\begin{lemma}A\end{lemma}\begin{proof}B\end{proof}', doc)
            self.assertIn(r'\begin{lem}', text)
            self.assertIn(r'\begin{IEEEproof}', text)

    def test_conversion_failure_stops_before_clipboard_and_paste(self):
        helper = test_writeback.LiveDestinationTests()
        helper.setUp()
        with patch('lyxai.bridge.LyXServer', return_value=helper.server), patch('lyxai.integration.capture_lyx_payload', return_value=helper.selection), patch('lyxai.bridge.set_native_clipboard') as clipboard, patch('lyxai.latex_import.convert_latex', side_effect=ValueError('conversion failed')):
            with self.assertRaisesRegex(ValueError, 'conversion failed'):
                apply_replacement(helper.payload, r'\textbf{Revised}', stem='test')
            clipboard.assert_not_called()
        self.assertFalse(any(c.args[0] in ('paste', 'command-sequence') for c in helper.server.command.call_args_list))

    def test_unknown_object_token_stops_before_conversion(self):
        helper = test_writeback.LiveDestinationTests()
        helper.setUp()
        with patch('lyxai.bridge.LyXServer', return_value=helper.server), patch('lyxai.integration.capture_lyx_payload', return_value=helper.selection), patch('lyxai.latex_import.convert_latex') as converter:
            with self.assertRaisesRegex(ValueError, 'unknown object token'):
                apply_replacement(helper.payload, r'Text \lyxaiobject{000000000000000000000000}', stem='test')
            converter.assert_not_called()

    def test_literal_source_is_not_blocked_by_unsafe_words_in_comments(self):
        self.assertEqual(latex_input('\\textbf{Text}% \\includegraphics{context-only}\n', native('Old')), '\\textbf{Text}% \\includegraphics{context-only}\n')

    def test_incomplete_commands_and_math_do_not_reach_converter(self):
        for text in (r'\textbf{Unclosed', r'\textbf{Extra}}', r'\textbf{Text} \[x=1', r'\textbf{Text} $x'):
            with self.subTest(text=text), self.assertRaises(ValueError):
                latex_input(text, native('Old'))
