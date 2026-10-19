import json
import os
# Tests must never claim desktop focus or capture the user's screen.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import tempfile
import threading
import time
import unittest

from PySide6.QtCore import QEventLoop, QTimer
from PySide6.QtWidgets import QApplication, QDialog

from lyxai.core import Store, default_config, new_profile
from lyxai.network import NetworkJob
from lyxai.ui import MainWindow, SettingsDialog, choose

APP = QApplication.instance() or QApplication([])


class Handler(BaseHTTPRequestHandler):
    requests = []

    def log_message(self, *args):
        pass

    def do_GET(self):
        body = json.dumps({"data": [{"id": "test-model"}, {"id": "test-thinking"}]}).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        try:
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            Handler.requests.append((self.path, body, dict(self.headers)))
            if "/first-timeout/" in self.path:
                time.sleep(0.4)
            if "/redirect/" in self.path:
                self.send_response(307)
                self.send_header("Location", "http://127.0.0.1:1/should-not-follow")
                self.end_headers()
                return
            if "/auth-error/" in self.path:
                self.send_response(401)
                self.send_header("Content-Type", "application/json")
                self.end_headers()
                self.wfile.write(b'{"error":{"message":"invalid key SECRET-TEST"}}')
                return
            protocol = "chat" if self.path.endswith("/chat/completions") else "anthropic" if self.path.endswith("/messages") else "responses"
            if body["stream"]:
                self.send_response(200)
                self.send_header("Content-Type", "text/event-stream; charset=utf-8")
                self.end_headers()
                if "/idle-timeout/" in self.path:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    time.sleep(0.4)
                if "/total-timeout/" in self.path:
                    for _ in range(20):
                        self.wfile.write(b": ping\n\n")
                        self.wfile.flush()
                        time.sleep(0.03)
                if protocol == "chat":
                    events = [{"choices": [{"delta": {"reasoning_content": "接口返回的摘要"}}]}, {"choices": [{"delta": {"content": "建议改写：中文测试。"}}]}]
                    if "/truncated/" not in self.path:
                        events += [{"choices": [{"delta": {}, "finish_reason": "stop"}], "usage": {"total_tokens": 11}}]
                elif protocol == "anthropic":
                    events = [{"type": "content_block_delta", "delta": {"thinking": "接口返回的摘要"}}, {"type": "content_block_delta", "delta": {"text": "建议改写：中文测试。"}}, {"type": "message_delta", "delta": {"stop_reason": "end_turn"}, "usage": {"output_tokens": 11}}, {"type": "message_stop"}]
                else:
                    events = [{"type": "response.reasoning_summary_text.delta", "delta": "接口返回的摘要"}, {"type": "response.output_text.delta", "delta": "建议改写：中文测试。"}, {"type": "response.completed", "response": {"status": "completed", "usage": {"total_tokens": 11}}}]
                for event in events:
                    raw = ("data: " + json.dumps(event, ensure_ascii=False) + "\r\n\r\n").encode()
                    # Split inside Chinese UTF-8 sequences to exercise incremental decoding.
                    for i in range(0, len(raw), 7):
                        self.wfile.write(raw[i:i + 7])
                        self.wfile.flush()
                return
            fixtures = {
                "chat": {"choices": [{"message": {"content": "非流式回答"}, "finish_reason": "stop"}]},
                "anthropic": {"content": [{"type": "text", "text": "非流式回答"}], "stop_reason": "end_turn"},
                "responses": {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "非流式回答"}]}]},
            }
            raw = json.dumps(fixtures[protocol], ensure_ascii=False).encode()
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            pass


class NetworkTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        cls.server.daemon_threads = True
        cls.thread = threading.Thread(target=lambda: cls.server.serve_forever(poll_interval=0.02), daemon=True)
        cls.thread.start()
        cls.base = f"http://127.0.0.1:{cls.server.server_port}"

    @classmethod
    def tearDownClass(cls):
        cls.server.shutdown()
        cls.server.server_close()

    def run_request(self, protocol="chat", path="", stream=True, cancel=False, **options):
        p = new_profile("Claude" if protocol == "anthropic" else "OpenAI")
        p.update(protocol=protocol, url=self.base + path, stream=stream, api_key="SECRET-TEST", **options)
        job = NetworkJob(p)
        loop = QEventLoop()
        outcome = {}
        chunks = []
        job.delta.connect(lambda text, reason: chunks.append((text, reason)))
        job.completed.connect(lambda result: (outcome.update(result=result), loop.quit()))
        job.failed.connect(lambda error: (outcome.update(error=error), loop.quit()))
        watchdog = QTimer()
        watchdog.setSingleShot(True)
        watchdog.timeout.connect(loop.quit)
        watchdog.start(3000)
        job.start([{"role": "user", "content": "测试中文与 $x_i$"}])
        if cancel:
            QTimer.singleShot(30, job.stop)
        loop.exec()
        watchdog.stop()
        self.assertTrue(outcome, "Request hung")
        return outcome, chunks

    def test_three_streaming_protocols(self):
        for protocol in ("chat", "responses", "anthropic"):
            with self.subTest(protocol=protocol):
                result, chunks = self.run_request(protocol)
                self.assertNotIn("error", result)
                self.assertEqual(result["result"]["text"], "建议改写：中文测试。")
                self.assertEqual(result["result"]["reasoning"], "接口返回的摘要")
                self.assertTrue(chunks)

    def test_three_nonstream_protocols(self):
        for protocol in ("chat", "responses", "anthropic"):
            with self.subTest(protocol=protocol):
                result, _ = self.run_request(protocol, stream=False)
                self.assertEqual(result["result"]["text"], "非流式回答")

    def test_auth_error_is_redacted(self):
        result, _ = self.run_request(path="/auth-error")
        self.assertIn("401", result["error"])
        self.assertNotIn("SECRET-TEST", result["error"])

    def test_redirect_is_not_followed(self):
        result, _ = self.run_request(path="/redirect")
        self.assertIn("redirect", result["error"])

    def test_first_byte_timeout(self):
        result, _ = self.run_request(path="/first-timeout", first_timeout=0.1)
        self.assertIn("First response timeout", result["error"])

    def test_idle_timeout(self):
        result, _ = self.run_request(path="/idle-timeout", idle_timeout=0.1)
        self.assertIn("Read idle timeout", result["error"])

    def test_total_timeout(self):
        result, _ = self.run_request(path="/total-timeout", total_timeout=0.15)
        self.assertIn("Total request timeout", result["error"])

    def test_cancel(self):
        result, _ = self.run_request(path="/first-timeout", cancel=True)
        self.assertIn("Cancelled", result["error"])

    def test_truncated_stream_preserves_partial(self):
        result, chunks = self.run_request(path="/truncated")
        self.assertIn("before completion", result["error"])
        self.assertIn("建议改写", "".join(c[0] for c in chunks))

    def test_model_discovery(self):
        p = new_profile()
        p["url"] = self.base
        job = NetworkJob(p)
        loop = QEventLoop()
        result = {}
        job.completed.connect(lambda r: (result.update(r), loop.quit()))
        job.failed.connect(lambda e: (result.update(error=e), loop.quit()))
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(3000)
        job.start(models=True)
        loop.exec()
        timer.stop()
        self.assertEqual(result["models"], ["test-model", "test-thinking"])

    def test_main_window_send_and_followup(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            cfg = store.load()
            cfg["profiles"][0].update(url=self.base, protocol="chat")
            store.save(cfg)
            w = MainWindow("第一段中文。\n第二段 English text。", store)
            w.replacement.setPlainText('Outdated revision')
            w.send()
            self.assertEqual(w.replacement.toPlainText(), '')
            self.wait_window(w)
            self.assertEqual(w.answer_text, "建议改写：中文测试。")
            self.assertEqual(len(w.history), 2)
            w.followup.setText("Please explain why.")
            w.send_followup()
            self.wait_window(w)
            self.assertEqual(len(w.history), 4)
            self.assertEqual(Handler.requests[-1][1]["messages"][-1]["content"], "Please explain why.")
            w.close()

    def wait_window(self, w):
        if not w.job:
            return
        loop = QEventLoop()
        w.job.completed.connect(loop.quit)
        w.job.failed.connect(loop.quit)
        timer = QTimer()
        timer.setSingleShot(True)
        timer.timeout.connect(loop.quit)
        timer.start(3000)
        loop.exec()
        timer.stop()
        self.assertIsNone(w.job)


class DialogTests(unittest.TestCase):
    def test_global_apply_button_and_language_persist_after_reopening(self):
        with tempfile.TemporaryDirectory() as tmp:
            folder = Path(tmp)
            w = MainWindow('Original', Store(folder))
            # Hidden-tab checks do not start Chromium or show a desktop window.
            self.assertIs(w.apply_btn.parentWidget(), w.centralWidget())
            for index in range(w.output_tabs.count()):
                w.output_tabs.setCurrentIndex(index)
                self.assertTrue(w.apply_btn.isVisibleTo(w.centralWidget()))
            choose(w.language, 'en')
            w.close()
            reopened = MainWindow('New selection', Store(folder))
            self.assertEqual(reopened.lang, 'en')
            self.assertEqual(reopened.language.currentData(), 'en')
            self.assertIn('Apply', reopened.apply_btn.text())
            self.assertEqual(len(reopened.config['templates']), 10)
            choose(reopened.language, 'zh')
            reopened.close()
            self.assertEqual(Store(folder).load()['language'], 'zh')

    def test_only_complete_revision_is_staged_and_survives_language_switch(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow('Original', Store(Path(tmp)))
            w.pending = [{'role': 'user', 'content': 'Revise'}]
            w.finished({'text': 'Reason\n[REVISED]Revised $x$[/REVISED]', 'finish': 'stop'})
            self.assertEqual(w.replacement.toPlainText(), 'Revised $x$')
            choose(w.language, 'en')
            self.assertEqual(w.replacement.toPlainText(), 'Revised $x$')
            w.pending = [{'role': 'user', 'content': 'Revise'}]
            w.finished({'text': '[REVISED]Incomplete[/REVISED]', 'finish': 'length'})
            self.assertEqual(w.replacement.toPlainText(), '')
            self.assertIsNone(w.rich_preview.view)  # No browser starts for hidden tabs.
            w.close()

    def test_dialog_profile_isolation_and_save(self):
        cfg = default_config()
        dlg = SettingsDialog(cfg)
        dlg.fields["name"].setText("My relay")
        dlg.fields["url"].setText("https://relay.example/v1")
        dlg.fields["api_key"].setText("secret")
        dlg.fields["effort"].setEditText("high")
        dlg.fields["total_timeout"].setValue(1800)
        dlg.extra.setPlainText('{"reasoning":{"summary":"auto"}}')
        dlg.duplicate()
        self.assertEqual(len(dlg.profiles), 2)
        self.assertEqual(len(cfg["profiles"]), 1)
        dlg.fields["name"].setText("Second relay")
        dlg.accept_settings()
        self.assertEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertEqual(dlg.config["profiles"][1]["total_timeout"], 1800)
        self.assertEqual(dlg.config["profiles"][1]["effort"], "high")
        self.assertEqual(cfg["profiles"][0]["api_key"], "")

    def test_invalid_json_cannot_be_saved(self):
        dlg = SettingsDialog(default_config())
        dlg.extra.setPlainText("{broken")
        dlg.accept_settings()
        self.assertNotEqual(dlg.result(), QDialog.DialogCode.Accepted)
        self.assertTrue(dlg.status.toPlainText())

    def test_language_switch_preserves_text(self):
        with tempfile.TemporaryDirectory() as tmp:
            w = MainWindow("中文 $x_i$", Store(Path(tmp)))
            w.prompt.setPlainText("Custom {selection}")
            choose(w.language, "en")
            self.assertEqual(w.lang, "en")
            self.assertEqual(w.selection.toPlainText(), "中文 $x_i$")
            self.assertEqual(w.prompt.toPlainText(), "Custom {selection}")
            self.assertIn("Configure", w.settings_btn.text())
            w.close()


if __name__ == "__main__":
    unittest.main()
