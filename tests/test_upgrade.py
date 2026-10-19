import gettext
import io
import struct
import unittest
from pathlib import Path

from lyxai.bridge import automatic_context, pipe_name
from lyxai.localization import extend_catalog, LABELS, TRANSLATIONS
from lyxai.preview import preview_html
from lyxai.replacement import Math, math_parts, replacement_fragment, revised_text, formula_source
from lyxai.selection import extract_body


def native(body):
    return '\\lyxformat 643\n\\begin_document\n\\begin_header\n\\textclass article\n\\language english\n\\end_header\n\\begin_body\n\\begin_layout Standard\n'+body+'\n\\end_layout\n\\end_body\n\\end_document\n'


class UpgradeTests(unittest.TestCase):
    def test_live_body_context_excludes_nested_notes_and_footnotes(self):
        document = (Path(__file__).resolve().parents[1] / 'examples/context-demo.lyx').read_text(encoding='utf-8')
        target = native('Target passage: Our method reduces communication overhead while preserving accuracy.')
        context = automatic_context(target, document, 100)
        self.assertIn('Context AFTER', context['after'])
        self.assertNotIn('DO NOT SEND', context['before']+context['after'])
        self.assertEqual(context['context_excluded'], 2)
        self.assertLessEqual(len(context['before']), 100)

    def test_repeated_target_refuses_ambiguous_context(self):
        with self.assertRaisesRegex(ValueError, 'ambiguous'):
            automatic_context(native('same'), native('same and same'))

    def test_math_styles_and_code_spans(self):
        parts = math_parts(r'$x_i$ \(y\) $$z$$ \[a=b\] \begin{equation}c=d\end{equation} `$notmath$`')
        math = [part for part in parts if isinstance(part, Math)]
        self.assertEqual([m.display for m in math], [False, False, True, True, True])
        self.assertEqual(math[-1].tex, r'\begin{equation}c=d\end{equation}')

    def test_multiline_environments_are_math_and_keep_numbering_and_labels(self):
        example = (Path(__file__).resolve().parents[1]/'examples/multiline-formula.tex').read_text(encoding='utf-8').strip()
        parts = [part for part in math_parts(example) if isinstance(part, Math)]
        self.assertEqual(len(parts), 1)
        self.assertTrue(parts[0].display)
        self.assertEqual(formula_source(parts[0]), example)
        fragment = replacement_fragment(native('Original'), example)
        self.assertIn('\\begin_inset Formula '+example, fragment)
        self.assertNotIn('\\backslash', fragment)
        self.assertIn(r'\label{eq:chain}', fragment)
        self.assertEqual(fragment.count(r'\nonumber'), 3)
        page = preview_html(example)
        self.assertIn('data-display="true"', page)
        self.assertNotIn(r'\label{eq:chain}', page)

    def test_top_level_and_nested_math_environments(self):
        for env in ('align', 'align*', 'alignat', 'alignat*', 'gather', 'gather*', 'multline', 'multline*', 'eqnarray', 'aligned', 'alignedat', 'gathered', 'split'):
            source = r'\begin{'+env+r'}a&=b\\c&=d\end{'+env+'}'
            with self.subTest(env=env):
                for wrapped in (source, '\\[\n'+source+'\n\\]'):
                    fragment = replacement_fragment(native('A'), wrapped)
                    self.assertEqual(fragment.count('\\begin_inset Formula '), 1)
                    self.assertIn(source, fragment)
                    self.assertNotIn('\\backslash', fragment)
        with self.assertRaises(ValueError):
            replacement_fragment(native('A'), r'\begin{align}a&=b')

    def test_native_writeback_math_and_preserved_language(self):
        result = replacement_fragment(native('\\lang english\nOriginal'), r'**Revised** $x_i^2$ and \[y=\frac{a}{b}\].')
        self.assertIn('\\lang english\n', result)
        self.assertIn('\\begin_inset Formula $x_i^2$', result)
        self.assertIn('\\begin_inset Formula \\[\ny=\\frac{a}{b}\n\\]', result)
        self.assertEqual(extract_body(result).excluded, 0)
        self.assertNotIn('**', result)

    def test_lyx_serialized_display_formula_survives_readback(self):
        body = extract_body(native('A\n\\begin_inset Formula \n\\[\ny=1\n\\]\n\n\\end_inset\nB'))
        self.assertEqual(body.excluded, 0)
        self.assertIn(r'\[', body.text)
        self.assertIn('y=1', body.text)

    def test_structural_targets_and_unsafe_math_are_not_overwritten(self):
        for body in ('A\n\\begin_inset Foot\nstatus collapsed\n\\begin_layout Plain Layout\nnote\n\\end_layout\n\\end_inset', 'A\n\\change_inserted 0 0\nB'):
            with self.assertRaises(ValueError):
                replacement_fragment(native(body), 'Revised')
        for text in (r'$\input{secret}$', r'$\write18{command}$', '\\[a\n\\end_inset\n\\begin_inset ERT\n\\]', '```\nNot prose\n```'):
            with self.assertRaises(ValueError):
                replacement_fragment(native('A'), text)

    def test_model_cannot_inject_native_insets_as_prose(self):
        result = replacement_fragment(native('A'), r'\end_layout\begin_inset Foot')
        self.assertEqual(result.count('\\begin_layout '), 1)
        self.assertNotIn('\\begin_inset Foot', result)
        self.assertIn('\\backslash', result)

    def test_only_one_revision_block_is_staged(self):
        self.assertEqual(revised_text('Explanation\n[REVISED]Text $x$[/REVISED]\nMore'), 'Text $x$')
        self.assertEqual(revised_text('[REVISED]A[/REVISED][REVISED]B[/REVISED]'), '')

    def test_preview_escapes_html_and_blocks_remote_images(self):
        page = preview_html('<script>evil()</script>\n\n![remote](https://example.com/a.png)\n\n' + r'\[x=1\]')
        self.assertIn('&lt;script&gt;', page)
        self.assertNotIn('<img', page)
        self.assertNotIn('src="https:', page)
        self.assertIn('trust:false', page)
        self.assertIn('data-display="true"', page)

    def test_locale_overlay_preserves_original_messages(self):
        header = b'Content-Type: text/plain; charset=UTF-8\nPlural-Forms: nplurals=2; plural=(n != 1);\n'
        raw = struct.pack('<7I', 0x950412de, 0, 1, 28, 36, 0, 0) + struct.pack('<4I', 0, 44, len(header), 45) + b'\0' + header + b'\0'
        translated = gettext.GNUTranslations(io.BytesIO(extend_catalog(raw, TRANSLATIONS['zh_CN'])))
        self.assertEqual(translated.gettext(LABELS[0]), 'AI 写作助手…')
        self.assertEqual(translated.gettext('Unchanged'), 'Unchanged')
        updated = gettext.GNUTranslations(io.BytesIO(extend_catalog(extend_catalog(raw, TRANSLATIONS['zh_CN']), TRANSLATIONS['fr'])))
        self.assertEqual(updated.gettext(LABELS[0]), TRANSLATIONS['fr'][0])


if __name__ == '__main__':
    unittest.main()
