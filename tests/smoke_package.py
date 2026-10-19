"""Explicit packaged-runtime check: offscreen IPC + isolated menu install/remove."""
import os
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from pathlib import Path
import subprocess
import sys
import tempfile
import time

from PySide6.QtCore import QCoreApplication, QEventLoop, QProcess, QProcessEnvironment, QTimer

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from lyxai.instance import InstanceServer


def check(executable):
    app = QCoreApplication.instance() or QCoreApplication([])
    executable = Path(executable).resolve()
    with tempfile.TemporaryDirectory(prefix="lyxai-package-") as tmp:
        root = Path(tmp)
        os.environ["LYXAI_DATA_DIR"] = str(root / "AI")
        server = InstanceServer()
        assert server.listen()
        received = []
        server.received.connect(received.append)
        text = root / "正文.txt"
        text.write_text("Packaged runtime 中文正文。", encoding="utf-8")
        child = QProcess()
        env = QProcessEnvironment.systemEnvironment()
        env.insert("LYXAI_DATA_DIR", str(root / "AI"))
        env.insert("QT_QPA_PLATFORM", "offscreen")
        error_path = root / "startup-error.txt"
        env.insert("LYXAI_TEST_ERROR_FILE", str(error_path))
        child.setProcessEnvironment(env)
        loop = QEventLoop()
        child.finished.connect(loop.quit)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(10000)
        start = time.perf_counter()
        child.start(str(executable), ["--selection-file", str(text), "--data-dir", str(root / "AI")])
        loop.exec()
        timer.stop()
        if child.state() != QProcess.ProcessState.NotRunning:
            child.kill()
            child.waitForFinished(1000)
            raise AssertionError("Packaged process did not exit")
        assert child.exitCode() == 0, error_path.read_text(encoding="utf-8") if error_path.exists() else bytes(child.readAllStandardError())
        assert len(received) == 1 and received[0]["text"] == text.read_text(encoding="utf-8")
        print(f"Packaged runtime IPC: OK ({time.perf_counter() - start:.3f}s; not GUI cold-start latency)")
        server.server.close()
        user = root / "LyX2.5"
        subprocess.run([str(executable), "--install", "--lyx-user-dir", str(user), '--menu-language', 'en'], check=True, timeout=10)
        menu = (user / "ui/stdcontext.inc").read_text(encoding="utf-8")
        assert menu.count("--context-before".encode().hex()) == 1
        assert menu.count("--context-after".encode().hex()) == 1
        subprocess.run([str(executable), "--uninstall", "--lyx-user-dir", str(user)], check=True, timeout=10)
        assert not (user / "ui/stdcontext.inc").exists()
        print("Packaged isolated menu install / uninstall: OK")


if __name__ == "__main__":
    check(sys.argv[1] if len(sys.argv) > 1 else "dist/LyXAI/LyXAI.exe")
