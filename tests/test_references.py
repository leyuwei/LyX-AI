import unittest

from lyxai.replacement import replacement_fragment
from lyxai.selection import extract_body


def native(body):
    return '\\lyxformat 643\n\\begin_document\n\\begin_header\n\\textclass article\n\\end_header\n\\begin_body\n\\begin_layout Standard\n' + body + '\n\\end_layout\n\\end_body\n\\end_document\n'


class ReferenceTests(unittest.TestCase):
    def test_references_and_citations_become_editable_native_objects(self):
        text = r'See \eqref{eq:demo}, \ref{fig:demo}, \ref{tab:demo}, \ref{sec:demo}, \pageref*{sec:demo} and \cite[see][p. 7]{paper2026,paper2025}.'
        result = replacement_fragment(native('Original'), text)
        self.assertEqual(result.count('\\begin_inset CommandInset ref\n'), 5)
        self.assertEqual(result.count('\\begin_inset CommandInset citation\n'), 1)
        self.assertIn('LatexCommand eqref\nreference "eq:demo"', result)
        self.assertIn('LatexCommand pageref\nreference "sec:demo"\nnolink "true"', result)
        self.assertIn('before "see"\nafter "p. 7"', result)
        self.assertNotIn(r'\backslash', result)
        self.assertEqual(extract_body(result).text, text)

    def test_existing_reference_options_survive_round_trip(self):
        original = native('See\n\\begin_inset CommandInset ref\nLatexCommand formatted\nreference "fig:demo"\nplural "true"\ncaps "true"\nnolink "false"\n\\end_inset\n.')
        result = replacement_fragment(original, extract_body(original).text)
        self.assertIn('plural "true"\ncaps "true"', result)
        self.assertIn('LatexCommand formatted', result)

    def test_nested_notes_and_footnotes_do_not_block_full_replacement(self):
        hidden = '\\begin_inset Note Note\nstatus collapsed\n\\begin_layout Plain Layout\nSECRET NOTE\n\\begin_inset Foot\n\\begin_layout Plain Layout\nSECRET NESTED FOOT\n\\end_layout\n\\end_inset\n\\end_layout\n\\end_inset\n'
        hidden += '\\begin_inset Foot\nstatus collapsed\n\\begin_layout Plain Layout\nSECRET FOOT\n\\end_layout\n\\end_inset\n'
        source = native('Before\n' + hidden + 'After')
        self.assertEqual(extract_body(source).text, 'BeforeAfter')
        result = replacement_fragment(source, r'Revised \eqref{eq:demo}.')
        self.assertNotIn('SECRET', result)
        self.assertNotIn('Plain Layout', result)
        self.assertNotIn('Note Note', result)
        self.assertEqual(extract_body(result).text, r'Revised \eqref{eq:demo}.')

    def test_reference_values_cannot_inject_native_or_latex_commands(self):
        for value in (r'\ref{bad"key}', r'\ref{\input secret}', r'\cite[\input secret]{paper}'):
            with self.subTest(value=value), self.assertRaises(ValueError):
                replacement_fragment(native('Original'), value)
        result = replacement_fragment(native('Original'), r'`\eqref{literal}` and \eqref{eq:demo}')
        self.assertEqual(result.count('CommandInset ref'), 1)
        self.assertIn(r'\backslash', result)


if __name__ == '__main__':
    unittest.main()
