"""Explicit real tex2lyx module matrix. No GUI, clipboard, network or AI API."""
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from lyxai.integration import default_user_dir
from lyxai.latex_import import layout_configuration, convert_latex
from lyxai.replacement import latex_input, native_paragraphs


def document(cls, modules):
    return ('\\lyxformat 643\n\\begin_document\n\\begin_header\n\\textclass ' + cls
            + '\n\\begin_modules\n' + '\n'.join(modules)
            + '\n\\end_modules\n\\language english\n\\end_header\n\\begin_body\n'
            '\\begin_layout Standard\nOriginal.\n\\end_layout\n\\end_body\n\\end_document\n')


def check():
    started = time.perf_counter()
    proof = r'\begin{lemma}Bound $x=1$.\end{lemma}\begin{proof}Reason.\end{proof}'
    enumeration = r'\begin{enumerate}\item One\item Two\end{enumerate}'
    cases = [
        ('article', ['theorems-ams'], proof, ['Lemma', 'Proof']),
        ('article', ['theorems-ams-extended-bytype', 'theorems-ams-bytype'], proof, ['Lemma', 'Proof']),
        ('book', ['theorems-chap-bytype', 'theorems-bytype'], proof, ['Lemma', 'Proof']),
        ('article', ['theorems-sec', 'theorems-std'], proof, ['Lemma', 'Proof']),
        ('article', ['theorems-sec', 'theorems-ams'], proof, ['Lemma', 'Proof']),
        ('IEEEtran', ['theorems-ams-bytype', 'theorems-ams-extended-bytype'], proof, ['Lemma', 'Proof']),
        ('beamer', ['enumitem'], enumeration, ['Enumerate', 'Enumerate']),
        ('powerdot', ['enumitem'], enumeration, ['Enumerate', 'Enumerate']),
        ('siamltex', ['theorems-ams', 'theorems-ams-extended'], proof, ['Lemma', 'Proof']),
        ('svmono', ['theorems-ams-bytype', 'theorems-ams-extended-bytype'], proof, ['Lemma', 'Proof']),
        ('svmult', ['theorems-ams'], proof, ['Lemma', 'Proof']),
        ('ijmpc', ['theorems-ams-bytype'], proof, ['Lemma', 'Proof']),
        ('ijmpd', ['theorems-ams'], proof, ['Lemma', 'Proof']),
        ('amsart', [], proof, ['Lemma', 'Proof']),
        ('amsbook', [], proof, ['Lemma', 'Proof']),
        ('article', ['enumitem'], enumeration, ['Enumerate', 'Enumerate']),
        ('article', ['paralist'], r'\begin{compactenum}\item One\item Two\end{compactenum}', ['CompactEnum', 'CompactEnum']),
    ]
    report = []
    for cls, requested, text, expected in cases:
        native = document(cls, requested)
        _, enabled, _ = layout_configuration(native)
        result = convert_latex(latex_input(text, native), native)
        actual = [p.layout for p in native_paragraphs(result)]
        assert actual == expected, (cls, requested, actual)
        assert 'LYXAIMATHPLACEHOLDER' not in result
        report.append(dict(textclass=cls, requested=requested, enabled=enabled, layouts=actual))

    # A locally installed user module exercises both custom layout aliases and
    # the actual converter. No installation files or user settings are changed.
    with tempfile.TemporaryDirectory(prefix='lyxai-module-') as tmp:
        user = Path(tmp)
        (user / 'layouts').mkdir()
        for name in ('lyxmodules.lst', 'textclass.lst'):
            shutil.copy2(default_user_dir() / name, user / name)
        with (user / 'lyxmodules.lst').open('a', encoding='utf-8') as out:
            out.write('\n"User Observation" "custom-observation" "User native environment" "" "" "" "Maths" "false"\n')
        (user / 'layouts/custom-observation.module').write_text(
            'Format 111\nStyle Observation\n LatexType Environment\n LatexName obs\n'
            ' Margin Static\n LabelType Static\n LabelString "Observation"\nEnd\n', encoding='utf-8')
        native = document('article', ['custom-observation'])
        result = convert_latex(r'\begin{observation}Custom $x=1$.\end{observation}', native, user)
        assert [p.layout for p in native_paragraphs(result)] == ['Observation']
        report.append(dict(textclass='article', requested=['custom-observation'], enabled=['custom-observation'], layouts=['Observation']))

    rejected = []
    for modules in (['enumitem', 'paralist'], ['paralist', 'enumitem'], ['knitr', 'lilypond'], ['lilypond', 'knitr']):
        try:
            layout_configuration(document('article', modules))
        except ValueError as exc:
            assert 'Conflicting LyX modules' in str(exc), str(exc)
            rejected.append(modules)
        else:
            raise AssertionError('Mutually incompatible modules accepted: ' + repr(modules))
    result = dict(passed=True, conversions=report, conflicts_rejected=rejected, seconds=round(time.perf_counter()-started, 3))
    path = ROOT / '.test-runtime/modules-0.5.0.json'
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding='utf-8')
    print(f'Real module matrix: {len(report)} native conversions passed, {len(rejected)} invalid combinations rejected ({result["seconds"]}s).')
    return result


if __name__ == '__main__':
    check()
