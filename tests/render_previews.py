"""Render documentation screenshots offscreen, without touching desktop windows."""
import os
os.environ["QT_QPA_PLATFORM"] = "offscreen"
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PySide6.QtGui import QFont, QFontDatabase
from PySide6.QtWidgets import QApplication
from lyxai.core import PRESETS, Store, new_profile
from lyxai.ui import MainWindow, SettingsDialog, STYLE

app = QApplication([])
app.setStyle("Fusion")
fonts = Path(os.environ.get("WINDIR", "C:/Windows")) / "Fonts"
for name in ("segoeui.ttf", "msyh.ttc"):
    font = fonts / name
    if font.exists():
        QFontDatabase.addApplicationFont(str(font))
app.setFont(QFont("Microsoft YaHei", 10))
app.setStyleSheet(STYLE)
folder = Path(__file__).resolve().parents[1] / "docs/images"
folder.mkdir(parents=True, exist_ok=True)
with tempfile.TemporaryDirectory() as tmp:
    window = MainWindow("本文提出一种分布式计算方法，在保持准确率的同时降低通信开销。", Store(Path(tmp)))
    window.before.setPlainText("现有方法需要频繁交换中间结果，通信开销较高。")
    window.after.setPlainText("实验部分将比较不同网络条件下的性能。")
    window.show()
    app.processEvents()
    window.grab().save(str(folder / "main.png"))
    config = window.config
    config["profiles"] = [new_profile(k) for k in PRESETS]
    config["active"] = config["profiles"][0]["id"]
    dialog = SettingsDialog(config, window)
    dialog.show()
    app.processEvents()
    dialog.grab().save(str(folder / "models.png"))
    dialog.close()
    window.close()
print("Documentation previews rendered offscreen.")
