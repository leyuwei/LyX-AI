"""Run once explicitly: actual browser and optionally a hidden native Windows desktop."""
import os
from pathlib import Path
import subprocess
import sys
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


if '--native' in sys.argv:
    import ctypes
    from ctypes import wintypes
    u = ctypes.WinDLL('user32', use_last_error=True)
    u.CreateDesktopW.argtypes = [wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p]
    u.CreateDesktopW.restype = wintypes.HANDLE
    u.CloseDesktop.argtypes = [wintypes.HANDLE]
    name = 'LyXAI_UI_' + uuid.uuid4().hex
    desktop = u.CreateDesktopW(name, None, None, 0, 0x1ff, None)
    if not desktop:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        startup = subprocess.STARTUPINFO()
        startup.lpDesktop = name
        env = dict(os.environ, QT_QPA_PLATFORM='windows', PYTHONIOENCODING='utf-8')
        result = subprocess.run([sys.executable, str(Path(__file__).resolve()), '--worker'], env=env, startupinfo=startup, creationflags=0x08000000, capture_output=True, timeout=40)
        print(result.stdout.decode('utf-8', 'replace'))
        assert result.returncode == 0, result.stderr.decode('utf-8', 'replace')
    finally:
        u.CloseDesktop(desktop)
else:
    if '--worker' not in sys.argv:
        os.environ['QT_QPA_PLATFORM'] = 'offscreen'
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts)
    QApplication.setAttribute(Qt.ApplicationAttribute.AA_DontCreateNativeWidgetSiblings)
    app = QApplication([])
    from lyxai.ui_check import check_window
    report = ROOT / '.test-runtime' / ('ui-native.json' if '--worker' in sys.argv else 'ui-offscreen.json')
    check_window(app, report)
    print(report.read_text(encoding='utf-8'))
