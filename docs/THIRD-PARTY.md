# Third-party components

- PySide6 / Qt 6.11.1 (Windows), 6.8.3 (macOS): [Qt for Python](https://doc.qt.io/qtforpython-6/), [source packages](https://download.qt.io/official_releases/QtForPython/). Used as dynamically loaded libraries. Package metadata declares LGPL-3.0-only OR GPL-2.0-only OR GPL-3.0-only. Qt WebEngine includes Chromium components; [Qt WebEngine licensing information](https://doc.qt.io/qt-6/qtwebengine-licensing.html).
- KaTeX 0.16.22: MIT; original license is included under `lyxai/assets/katex/LICENSE` in source and `_internal/lyxai/assets/katex/LICENSE` in the Windows app.
- markdown-it-py 4.2.0 / markdown-it: MIT; license texts are included under the assets/licenses directory.
- Python and PyInstaller: their runtime files and dynamically linked libraries are used by the Windows and macOS builds; see [Python licensing](https://docs.python.org/3/license.html) and [PyInstaller licensing](https://pyinstaller.org/en/stable/license.html).

The application logo SVG was drawn specifically for this project.

The macOS build also uses PyObjC (Cocoa and Security frameworks), MIT licensed; see [PyObjC licensing](https://pyobjc.readthedocs.io/en/latest/license.html). Exact build dependency versions are included in `BUILD-DEPENDENCIES.txt` in the macOS ZIP.
