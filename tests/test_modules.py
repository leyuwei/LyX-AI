"""Class-independent module graph regressions; temporary files, no converter."""
from itertools import permutations
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from lyxai.latex_import import layout_configuration, normalize_environments
from lyxai.replacement import latex_input


class ModuleTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.user = Path(folder.name)
        self.layouts = self.user / 'layouts'
        self.layouts.mkdir()
        patcher = patch('lyxai.latex_import.default_lyx_dir', return_value=self.user / 'unused-installation')
        patcher.start()
        self.addCleanup(patcher.stop)
        self.write('custom.layout', 'Format 111\nStyle Standard\n LatexName dummy\nEnd\n')

    def write(self, name, text):
        (self.layouts / name).write_text(text, encoding='utf-8')

    def document(self, modules=(), extra=''):
        return ('\\begin_header\n\\textclass custom\n\\begin_modules\n' + '\n'.join(modules)
                + '\n\\end_modules\n' + extra + '\n\\end_header\n\\begin_body\n'
                '\\begin_layout Standard\nOriginal.\n\\end_layout\n\\end_body\n\\end_document\n')

    def enabled(self, modules=(), extra=''):
        return layout_configuration(self.document(modules, extra), self.user)[1]

    def test_dependencies_work_in_every_declared_order(self):
        self.write('base.module', '')
        self.write('middle.module', '#Requires: base\n')
        self.write('leaf.module', '#Requires: middle\n')
        for order in permutations(('base', 'middle', 'leaf')):
            with self.subTest(order=order):
                self.assertEqual(self.enabled(order), ['base', 'middle', 'leaf'])

    def test_alternative_dependency_breaks_a_cycle_without_loading_both_alternatives(self):
        self.write('one.module', '#Requires: two | base\n')
        self.write('two.module', '#Requires: one\n')
        self.write('base.module', '')
        self.assertEqual(self.enabled(('one', 'two', 'base')), ['base', 'one', 'two'])
        self.assertEqual(self.enabled(('one', 'base')), ['base', 'one'])

    def test_mutual_exclusion_is_checked_in_both_directions(self):
        self.write('first.module', '#Excludes: second\n')
        self.write('second.module', '')
        for order in (('first', 'second'), ('second', 'first')):
            with self.subTest(order=order), self.assertRaisesRegex(ValueError, 'Conflicting LyX modules'):
                self.enabled(order)

    def test_empty_metadata_field_cannot_consume_the_next_line(self):
        self.write('first.module', '  ## Requires:\n#Excludes: second\n')
        self.write('second.module', '')
        self.assertEqual(self.enabled(('first',)), ['first'])
        with self.assertRaisesRegex(ValueError, 'Conflicting LyX modules'):
            self.enabled(('first', 'second'))

    def test_class_exclusion_prunes_all_transitive_dependants(self):
        self.write('custom.layout', 'ExcludesModule base\n')
        self.write('base.module', '')
        self.write('middle.module', '#Requires: base\n')
        self.write('leaf.module', '#Requires: middle\n')
        self.write('independent.module', '')
        for order in permutations(('leaf', 'middle', 'base')):
            self.assertEqual(self.enabled((*order, 'independent')), ['independent'])

    def test_class_provided_module_can_itself_declare_exclusions(self):
        self.write('custom.layout', 'ProvidesModule built-in\n')
        self.write('built-in.module', '#Excludes: incompatible\n')
        self.write('incompatible.module', '')
        self.write('extension.module', '#Requires: incompatible | built-in\n')
        self.assertEqual(self.enabled(('incompatible', 'built-in', 'extension')), ['extension'])

    def test_missing_dependency_cycle_and_unavailable_module_have_distinct_errors(self):
        self.write('first.module', '#Requires: second\n')
        with self.assertRaisesRegex(ValueError, 'Missing LyX module dependency'):
            self.enabled(('first',))
        self.write('second.module', '#Requires: first\n')
        with self.assertRaisesRegex(ValueError, 'Cyclic LyX module dependencies'):
            self.enabled(('first', 'second'))
        with self.assertRaisesRegex(ValueError, 'module not found'):
            self.enabled(('unavailable',))

    def test_class_defaults_keep_order_and_respect_user_removal(self):
        self.write('custom.layout', 'DefaultModule first\nDefaultModule second\n')
        self.write('first.module', '')
        self.write('second.module', '#Requires: first\n')
        self.assertEqual(self.enabled(), ['first', 'second'])
        removed = '\\begin_removed_modules\nfirst\nsecond\n\\end_removed_modules\n'
        self.assertEqual(self.enabled(extra=removed), [])
        # Removing the base default also disables dependent defaults, without
        # requiring the user to list every dependant in removed_modules.
        removed_base = '\\begin_removed_modules\nfirst\n\\end_removed_modules\n'
        self.assertEqual(self.enabled(extra=removed_base), [])

    def test_explicit_selection_has_precedence_over_incompatible_class_default(self):
        self.write('custom.layout', 'DefaultModule default-choice\n')
        self.write('default-choice.module', '#Excludes: explicit-choice\n')
        self.write('explicit-choice.module', '')
        self.assertEqual(self.enabled(('explicit-choice',)), ['explicit-choice'])

    def test_local_exclusions_take_effect_and_local_style_overrides_remain_last(self):
        self.write('custom.layout', 'Style Observation\n LatexName oldobserv\nEnd\n')
        self.write('formatting.module', 'Style Observation\n LatexName moduleobserv\nEnd\n')
        self.write('forbidden.module', '')
        local = ('\\begin_local_layout\nExcludesModule forbidden\nStyle Observation\n'
                 ' LatexName finalobserv\nEnd\n\\end_local_layout\n')
        _, modules, layouts = layout_configuration(self.document(('forbidden', 'formatting'), local), self.user)
        self.assertEqual(modules, ['formatting'])
        self.assertEqual(layouts['Observation'], 'finalobserv')

    def test_custom_class_theorems_do_not_require_a_class_name_whitelist(self):
        self.write('custom.layout', 'Style Lemma\n LatexName mylemma\nEnd\nStyle Proof\n LatexName myproof\nEnd\n')
        text = latex_input(r'\begin{lemma}Bound.\end{lemma}\begin{proof}Reason.\end{proof}', self.document(), self.user)
        self.assertIn(r'\begin{mylemma}', text)
        self.assertIn(r'\begin{myproof}', text)

    def test_custom_non_theorem_aliases_stars_and_deleted_styles(self):
        self.write('custom.layout', 'Style Observation\n LatexName obs\nEnd\nStyle Observation*\n LatexName obsstar\nEnd\nStyle Removed\n LatexName removed\nEnd\nNoStyle Removed\n')
        text = normalize_environments(r'\begin{observation}A.\end{observation}\begin{observation*}B.\end{observation*}', self.document(), self.user)
        self.assertIn(r'\begin{obs}', text)
        self.assertIn(r'\begin{obsstar}', text)
        self.assertNotIn('Removed', layout_configuration(self.document(), self.user)[2])

    def test_argument_latex_names_and_preamble_text_do_not_change_layout_mapping(self):
        self.write('custom.layout', 'Style Observation\n LatexName obs\n Argument 1\n  LatexName shorttitle\n EndArgument\nEnd\nAddToPreamble\nStyle Fake\n LatexName fake\nEnd\nEndPreamble\nStyle After\n LatexName after\nEnd\n')
        layouts = layout_configuration(self.document(), self.user)[2]
        self.assertEqual(layouts, {'Observation': 'obs', 'After': 'after'})
