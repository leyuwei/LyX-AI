"""Entry point. LyX clipboard capture happens before the Qt runtime is loaded."""
from __future__ import annotations

import argparse
import ctypes
import os
from pathlib import Path
import sys


def main():
    parser = argparse.ArgumentParser(description="LyX AI writing companion")
    parser.add_argument("--from-lyx", action="store_true")
    context = parser.add_mutually_exclusive_group()
    context.add_argument("--context-before", action="store_true")
    context.add_argument("--context-after", action="store_true")
    parser.add_argument("--configure", action="store_true")
    parser.add_argument("--install", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--lyx-dir", default=r"C:\Program Files\LyX 2.5")
    parser.add_argument("--lyx-user-dir")
    parser.add_argument("--menu-language", choices=["auto", "zh", "en", "both"], default="auto")
    parser.add_argument("--selection-file", help="Explicit plain text file for testing or standalone use")
    parser.add_argument("--data-dir", help="Isolated settings directory")
    parser.add_argument('--self-test-preview', metavar='REPORT', help=argparse.SUPPRESS)
    args = parser.parse_args()
    if args.data_dir:
        os.environ["LYXAI_DATA_DIR"] = str(Path(args.data_dir).resolve())
    from lyxai.integration import capture_lyx_payload, install, uninstall
    if args.install:
        result = install(args.lyx_dir, args.lyx_user_dir, language=args.menu_language)
        if sys.stdout:
            print(result)
        return 0
    if args.uninstall:
        result = uninstall(args.lyx_user_dir)
        if sys.stdout:
            print(result)
        return 0
    payload = capture_lyx_payload() if args.from_lyx else {"text": Path(args.selection_file).read_text(encoding="utf-8")} if args.selection_file else {}
    if payload and args.lyx_user_dir:
        payload['lyx_user_dir'] = args.lyx_user_dir
    kind = "before" if args.context_before else "after" if args.context_after else "selection"
    message = dict(kind=kind, **payload) if payload else {"kind": "configure" if args.configure else "activate"}
    from PySide6.QtWidgets import QApplication
    from PySide6.QtCore import QTimer, Qt
    from lyxai.instance import deliver, InstanceServer
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    app = QApplication(sys.argv[:1])
    if args.self_test_preview:
        if os.environ.get('QT_QPA_PLATFORM') != 'offscreen':
            raise ValueError('Preview self-check requires QT_QPA_PLATFORM=offscreen')
        from lyxai.preview import check_preview
        return check_preview(app, args.self_test_preview)
    if deliver(message):
        return 0
    server = InstanceServer(app)
    if not server.listen():
        if deliver(message):
            return 0
        raise RuntimeError("Another LyX AI instance is starting. Retry shortly. / 助手正在启动，请稍后重试。")
    # Reuse the existing window when present; only a first launch imports UI.
    from lyxai.ui import MainWindow, STYLE
    app.setApplicationName("LyX AI")
    app.setOrganizationName("LyXAI")
    app.setStyle("Fusion")
    app.setStyleSheet(STYLE)
    window = MainWindow(payload.get("text", "") if kind == "selection" else "")
    server.received.connect(window.accept_message)
    window.show()
    if payload:
        window.accept_message(message)
    if args.configure:
        QTimer.singleShot(0, window.settings)
    return app.exec()


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        # No transcript/credentials are logged. A failure must remain visible when
        # started as a windowless executable from the LyX menu.
        message = str(exc)
        if os.environ.get("QT_QPA_PLATFORM") == "offscreen":
            diagnostic = os.environ.get("LYXAI_TEST_ERROR_FILE")
            if diagnostic:
                Path(diagnostic).write_text(type(exc).__name__ + ": " + message, encoding="utf-8")
        elif os.name == "nt":
            ctypes.windll.user32.MessageBoxW(None, message, "LyX AI", 0x10)
        if sys.stderr:
            print(message, file=sys.stderr)
        sys.exit(1)
