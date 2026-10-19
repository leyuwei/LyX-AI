import copy
import json
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import re

from lyxai.core import (PRESETS, SSEDecoder, Store, StreamResult, build_request,
                        default_config, endpoint, new_profile, parse_response,
                        preview_request, redact, render_prompt, request_headers)
from lyxai.integration import install, menu_text, uninstall


class ProtocolTests(unittest.TestCase):
    def test_presets_and_endpoints(self):
        for provider in PRESETS:
            if provider == "Custom / Relay":
                continue
            p = new_profile(provider)
            self.assertTrue(endpoint(p).startswith("https://"))
            self.assertTrue(endpoint(p, True).endswith("/models"))
            self.assertEqual(build_request(p, [{"role": "user", "content": "你好"}])[2]["model"], p["model"])

    def test_relay_and_full_endpoint(self):
        p = new_profile("Claude")
        p.update(url="https://relay.example/prefix/v1/messages?api-version=1", auth="bearer", api_key="demo")
        self.assertEqual(endpoint(p), p["url"])
        self.assertEqual(request_headers(p)["Authorization"], "Bearer demo")
        self.assertEqual(endpoint(p, True), "https://relay.example/prefix/v1/models?api-version=1")
        p["protocol"] = "chat"
        with self.assertRaises(ValueError):
            endpoint(p)

    def test_invalid_urls(self):
        for url in ("file:///secret", "https://u:p@api.example", "not-a-url", "https://example.com/#secret"):
            p = new_profile()
            p["url"] = url
            with self.assertRaises(ValueError):
                endpoint(p)

    def test_native_messages_and_reasoning(self):
        messages = [{"role": "system", "content": "S"}, {"role": "user", "content": "你好"}]
        p = new_profile("Claude")
        p.update(thinking="enabled", thinking_budget=2048, effort="high", api_key="key")
        _, headers, b = build_request(p, messages)
        self.assertEqual(headers["x-api-key"], "key")
        self.assertEqual(b["system"], "S")
        self.assertEqual(b["messages"], messages[1:])
        self.assertEqual(b["thinking"], {"type": "enabled", "budget_tokens": 2048})
        self.assertEqual(b["output_config"], {"effort": "high"})
        p.update(thinking="adaptive", thinking_budget=None)
        self.assertEqual(build_request(p, messages)[2]["thinking"], {"type": "adaptive"})

    def test_claude_budget_validation_after_override(self):
        p = new_profile("Claude")
        p.update(thinking="enabled", thinking_budget=2048)
        for params in ({"max_tokens": 1024}, {"thinking": {"budget_tokens": 2}}):
            p["params"] = params
            with self.assertRaises(ValueError):
                build_request(p, [])

    def test_chat_and_responses_reasoning(self):
        p = new_profile()
        p.update(thinking="enabled", effort="high", verbosity="low")
        b = build_request(p, [{"role": "user", "content": "x"}])[2]
        self.assertEqual(b["reasoning"], {"effort": "high"})
        self.assertEqual(b["text"], {"verbosity": "low"})
        self.assertFalse(b["store"])
        p["protocol"] = "chat"
        b = build_request(p, [])[2]
        self.assertEqual(b["reasoning_effort"], "high")
        self.assertEqual(b["max_completion_tokens"], 8192)

    def test_deepseek_and_optional_fields(self):
        p = new_profile("DeepSeek")
        p.update(thinking="enabled", effort="high")
        b = build_request(p, [])[2]
        self.assertEqual(b["thinking"], {"type": "enabled"})
        self.assertEqual(b["reasoning_effort"], "high")
        self.assertNotIn("temperature", b)
        p.update(thinking="disabled", effort="")
        self.assertEqual(build_request(p, [])[2]["thinking"]["type"], "disabled")

    def test_advanced_merge_null_and_reserved(self):
        p = new_profile()
        p.update(effort="high", params={"reasoning": {"summary": "auto"}, "max_output_tokens": None, "temperature": 0.4})
        b = build_request(p, [])[2]
        self.assertEqual(b["reasoning"], {"effort": "high", "summary": "auto"})
        self.assertNotIn("max_output_tokens", b)
        self.assertEqual(b["temperature"], 0.4)
        p["params"] = {"messages": []}
        with self.assertRaises(ValueError):
            build_request(p, [])

    def test_headers_injection_and_case_override(self):
        p = new_profile()
        p.update(api_key="one", headers={"authorization": "Bearer two"})
        headers = request_headers(p)
        self.assertNotIn("Authorization", headers)
        self.assertEqual(headers["authorization"], "Bearer two")
        for h in ({"X-Header": "a\r\nb"}, {"Host": "evil"}, {"invalid space": "x"}):
            p["headers"] = h
            with self.assertRaises(ValueError):
                request_headers(p)

    def test_prompt_preserves_latex(self):
        text = r"$x_{i}$ {reply_language} \cite{abc}"
        self.assertEqual(render_prompt("{selection} / {reply_language}", text, "中文"), text + " / 中文")
        self.assertEqual(render_prompt("Review", text, "English"), "Review\n\n" + text)

    def test_preview_and_error_redaction(self):
        p = new_profile()
        p.update(api_key="SECRET123", headers={"X-Token": "PRIVATE456"}, url="https://example.com/v1?key=HIDDEN789")
        preview = preview_request(p, [{"role": "user", "content": "hello"}])
        for secret in ("SECRET123", "PRIVATE456", "HIDDEN789"):
            self.assertNotIn(secret, preview)
        self.assertNotIn("SECRET123", redact("echo SECRET123", p))

    def test_nonstream_protocols(self):
        fixtures = {
            "chat": {"choices": [{"message": {"content": "回答", "reasoning_content": "摘要"}, "finish_reason": "stop"}]},
            "anthropic": {"content": [{"type": "text", "text": "回答"}, {"type": "thinking", "thinking": "摘要"}], "stop_reason": "end_turn"},
            "responses": {"status": "completed", "output": [{"type": "message", "content": [{"type": "output_text", "text": "回答"}]}, {"type": "reasoning", "summary": [{"type": "summary_text", "text": "摘要"}]}]},
        }
        for protocol, fixture in fixtures.items():
            result = parse_response(protocol, fixture)
            self.assertEqual(result[:2], ("回答", "摘要"))
        with self.assertRaises(ValueError):
            parse_response("chat", {"choices": [{"message": {"content": None, "tool_calls": [{}]}}]})

    def test_sse_utf8_fragmentation(self):
        decoder = SSEDecoder()
        raw = ': keepalive\r\ndata: {"x": "中文"}\r\n\r\ndata: [DONE]\n\n'.encode()
        output = []
        for byte in raw:
            output += decoder.feed(bytes([byte]))
        self.assertEqual(output, ['{"x": "中文"}', '[DONE]'])

    def test_sse_multiline_final(self):
        decoder = SSEDecoder()
        self.assertEqual(decoder.feed(b'data: {\ndata: "x":1\ndata: }\n\n'), ['{\n"x":1\n}'])
        self.assertEqual(decoder.feed(b'data: [DONE]', final=True), ['[DONE]'])

    def test_stream_protocols(self):
        fixtures = {
            "chat": [{"choices": [{"delta": {"content": "回答", "reasoning_content": "摘要"}}]}, {"choices": [{"delta": {}, "finish_reason": "stop"}]}],
            "anthropic": [{"type": "content_block_delta", "delta": {"type": "text_delta", "text": "回答"}}, {"type": "content_block_delta", "delta": {"type": "thinking_delta", "thinking": "摘要"}}, {"type": "message_stop"}],
            "responses": [{"type": "response.output_text.delta", "delta": "回答"}, {"type": "response.reasoning_summary_text.delta", "delta": "摘要"}, {"type": "response.completed", "response": {"status": "completed"}}],
        }
        for protocol, events in fixtures.items():
            r = StreamResult(protocol)
            for event in events:
                r.event(json.dumps(event))
            self.assertEqual((r.text, r.reasoning, r.done), ("回答", "摘要", True))

    def test_stream_error(self):
        for protocol in ("chat", "responses", "anthropic"):
            with self.assertRaises(ValueError):
                StreamResult(protocol).event('{"type":"error","error":{"message":"bad key"}}')

    def test_store_dpapi_and_concurrent_write(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            cfg = store.load()
            cfg["profiles"][0].update(api_key="SECRET123", headers={"X-Key": "PRIVATE456"}, proxy="http://u:pass@localhost:1234")
            store.save(cfg)
            raw = store.path.read_text(encoding="utf-8")
            self.assertNotIn("SECRET123", raw)
            self.assertNotIn("PRIVATE456", raw)
            self.assertNotIn("u:pass", raw)
            other = Store(Path(tmp))
            loaded = other.load()
            self.assertEqual(loaded["profiles"][0]["api_key"], "SECRET123")
            store.save(cfg)
            with self.assertRaises(ValueError):
                other.save(loaded)


class InstallationTests(unittest.TestCase):
    def test_upgrade_appends_templates_without_replacing_user_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            store = Store(Path(tmp))
            cfg = store.load()
            # A legacy two-template config with an edited builtin and a custom one.
            cfg['templates'] = cfg['templates'][:2] + [dict(name='My prompt', prompt='Mine {selection}')]
            cfg['templates'][0].pop('id')
            cfg['templates'][1].pop('id')
            cfg['templates'][0]['prompt'] = 'My edits {selection}'
            cfg['template_index'] = 2
            cfg['language'] = 'en'
            store.save(cfg)
            upgraded = store.load()
            self.assertEqual(len(upgraded['templates']), 11)
            self.assertEqual(upgraded['templates'][0]['prompt'], 'My edits {selection}')
            self.assertEqual(upgraded['templates'][2]['name'], 'My prompt')
            self.assertEqual(upgraded['template_index'], 2)
            self.assertEqual(upgraded['language'], 'en')
            store.save(upgraded)
            self.assertEqual(len(Store(Path(tmp)).load()['templates']), 11)

    def test_all_three_bootstraps_decode_to_exact_arguments(self):
        source = 'Menu "context-edit"\nEnd\n'
        args = [r"C:\Program Files\Python312\pythonw.exe", r"C:\Users\中文 Name\main.py"]
        text = menu_text(source, args)
        payloads = re.findall(r'exec\(\(0x([0-9a-f]+)\)\.to_bytes\((\d+)\)\)', text)
        self.assertEqual(len(payloads), 3)
        for (encoded, size), flags in zip(payloads, ([], ["--context-before"], ["--context-after"])):
            with patch("subprocess.Popen") as launch:
                exec(int(encoded, 16).to_bytes(int(size)), {})
                self.assertEqual(launch.call_args.args[0], args + ["--from-lyx"] + flags)
                self.assertTrue(launch.call_args.kwargs["close_fds"])

    def test_menu_is_idempotent_and_quoted(self):
        source = 'Menuset\n\tMenu "context-edit"\n\t\tItem "Copy" "copy"\n\tEnd\nEnd\n'
        args = [r"C:\Program Files\Python312\pythonw.exe", r"C:\Users\中文 Name\main.py"]
        first = menu_text(source, args)
        self.assertEqual(menu_text(first, args), first)
        self.assertIn("command-sequence copy; vc-command", first)
        self.assertIn(".to_bytes", first)
        self.assertEqual(first.count("BEGIN LYXAI"), 1)

    def test_install_reinstall_restore_existing(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lyx, user = root / "lyx", root / "user"
            source = 'Menuset\nMenu "context-edit"\nEnd\nEnd\n'
            (lyx / "Resources/ui").mkdir(parents=True)
            (lyx / "Resources/ui/stdcontext.inc").write_text(source)
            target = user / "ui/stdcontext.inc"
            target.parent.mkdir(parents=True)
            target.write_text(source + "# personal\n")
            original = target.read_bytes()
            install(lyx, user, command=["app.exe"])
            install(lyx, user, command=["new.exe"])
            uninstall(user)
            self.assertEqual(target.read_bytes(), original)

    def test_uninstall_retains_later_edits(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            lyx, user = root / "lyx", root / "user"
            (lyx / "Resources/ui").mkdir(parents=True)
            (lyx / "Resources/ui/stdcontext.inc").write_text('Menu "context-edit"\nEnd\n')
            install(lyx, user, command=["app.exe"])
            target = user / "ui/stdcontext.inc"
            with target.open("a") as out:
                out.write("# new personal change\n")
            uninstall(user)
            self.assertIn("new personal change", target.read_text())
            self.assertNotIn("BEGIN LYXAI", target.read_text())


if __name__ == "__main__":
    unittest.main()
