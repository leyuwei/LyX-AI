"""Provider protocols and local configuration. No GUI or vendor SDK required."""
from __future__ import annotations

import base64
import codecs
import copy
import ctypes
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
from urllib.parse import urlsplit, urlunsplit
import uuid


PRESETS = {
    "OpenAI": ("https://api.openai.com/v1", "responses", "gpt-5.4"),
    "Claude": ("https://api.anthropic.com/v1", "anthropic", "claude-sonnet-4-6"),
    "DeepSeek": ("https://api.deepseek.com/v1", "chat", "deepseek-chat"),
    "Kimi": ("https://api.moonshot.cn/v1", "chat", "kimi-k2.6"),
    "Grok": ("https://api.x.ai/v1", "responses", "grok-4.7"),
    "GLM / BigModel": ("https://open.bigmodel.cn/api/paas/v4", "chat", "glm-5.3"),
    "BigModel Coding": ("https://open.bigmodel.cn/api/coding/paas/v4", "chat", "glm-5.3"),
    "Z.ai": ("https://api.z.ai/api/paas/v4", "chat", "glm-5.3"),
    "Custom / Relay": ("", "chat", ""),
}
PROTOCOLS = {"chat": "OpenAI Chat Completions", "responses": "OpenAI Responses", "anthropic": "Claude Messages"}
DEFAULT_PROMPT = (
    "请检查以下文字的表达与逻辑，保留事实、数字、公式和引用。"
    "先列出具体问题，再给出建议改写和修改理由。使用 {reply_language} 回答。\n\n{selection}"
)
EN_PROMPT = (
    "Review the clarity and logic of the text below. Preserve facts, numbers, equations and citations. "
    "List specific issues, suggest a revision, and explain the changes. Reply in {reply_language}.\n\n{selection}"
)


def builtin_templates():
    tasks = [
        ('academic', '学术润色 / Academic editing', DEFAULT_PROMPT),
        ('english', 'English editing', EN_PROMPT),
        ('proofread', '错别字与语法 / Proofreading', '仅修正目标正文的错别字、标点和语法，尽量少改，不重写作者风格。保留事实、数字、公式和引用，简述每处必要修改。'),
        ('concise', '精简文字 / Concision', '压缩目标正文的重复表达和冗余，保留论点、限定条件、事实、数字、公式与引用。不要为了简短删除实质内容，说明精简理由。'),
        ('flow', '逻辑与衔接 / Logic & flow', '结合前后文检查目标正文的论证次序、指代、过渡与因果关系。指出逻辑缺口，在现有证据范围内改善衔接，不编造实验、结论或引用。'),
        ('notation', '公式与符号检查 / Equations & notation', '检查目标公式的符号定义、维度、下标、边界条件及与正文的一致性。区分确定错误和需作者确认的问题；缺少依据时不要擅自改变数学结论。保留标签与引用键。'),
        ('latex', 'LaTeX 公式整理 / LaTeX cleanup', '整理目标公式的 LaTeX、括号配对、对齐点与多行排版，保持数学含义不变。多行使用 align 或 aligned，保留 label、nonumber 和编号意图，不把公式放进代码围栏。'),
        ('translate_en', '中译英 / Chinese to English', '将目标正文译为准确自然的学术英语，译文必须为英语；保留事实、数字、术语、公式、标签和引用，不添加论断。解释可使用指定回答语言。'),
        ('translate_zh', '英译中 / English to Chinese', '将目标正文译为通顺严谨的学术中文，译文必须为中文；保持事实、数字、术语、公式、标签和引用，保留必要英文缩写。解释可使用指定回答语言。'),
        ('critique', '审稿式诊断 / Critical review', '从读者和审稿人角度检查目标正文的清晰度、论证强度、假设与证据匹配。按重要程度给出具体、可操作的建议；不虚构参考文献、数据或结果。仅在依据充分时给出修改稿。'),
    ]
    return [dict(id='builtin.'+key, name=name, prompt=prompt if key in ('academic', 'english') else prompt+'\n使用 {reply_language} 解释，仅修改目标正文。\n\n{selection}') for key, name, prompt in tasks]


def add_builtin_templates(config):
    """Restore immutable presets, keeping legacy edits as custom templates."""
    templates = config.setdefault('templates', [])
    selected = config.get('template_index', 0)
    presets = builtin_templates()
    by_id = {t['id']: t for t in presets}
    by_name = {t['name']: t for t in presets}
    seen = set()
    for index, item in enumerate(list(templates)):
        preset = by_id.get(item.get('id')) or (by_name.get(item.get('name')) if not item.get('id') else None)
        if not preset:
            item.setdefault('id', 'custom.' + uuid.uuid4().hex)
            continue
        if 'prompt' in item and item['prompt'] != preset['prompt']:
            custom = dict(item, id='custom.' + uuid.uuid4().hex, name='用户自定义 / Custom · ' + item.get('name', preset['name']))
            templates.append(custom)
            if index == selected:
                config['template_index'] = len(templates) - 1
        templates[index] = dict(preset)
        seen.add(preset['id'])
    templates.extend(dict(t) for t in presets if t['id'] not in seen)
    return config


def data_dir() -> Path:
    if sys.platform == 'darwin':
        return Path(os.environ.get('LYXAI_DATA_DIR') or Path.home() / 'Library/Application Support/LyXAI')
    return Path(os.environ.get("LYXAI_DATA_DIR") or Path(os.environ.get("APPDATA", Path.home())) / "LyXAI")


def new_profile(provider="OpenAI") -> dict:
    url, protocol, model = PRESETS[provider]
    return dict(id=uuid.uuid4().hex, name=provider, provider=provider, url=url, protocol=protocol,
                model=model, api_key="", auth="auto", headers={}, params={}, stream=True,
                token_field="auto", max_tokens=8192, thinking="default", effort="",
                thinking_budget=None, verbosity="", system="", first_timeout=120,
                idle_timeout=120, total_timeout=600, proxy="")


def default_config() -> dict:
    p = new_profile()
    return dict(version=2, language="zh", profiles=[p], active=p["id"], reply_language="中文",
                templates=builtin_templates(), template_index=0, auto_context=True,
                context_radius=1800, ui_state={})


def json_object(text: str, label="JSON") -> dict:
    def invalid(value):
        raise ValueError(f"{label}: invalid number {value}")
    obj = json.loads(text or "{}", parse_constant=invalid)
    if not isinstance(obj, dict):
        raise ValueError(f"{label}: expected a JSON object / 需要 JSON 对象")
    return obj


def _dpapi(raw: bytes, decrypt=False) -> bytes:
    if os.name != "nt":
        raise RuntimeError("Windows DPAPI is required to save credentials")
    from ctypes import wintypes

    class Blob(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("data", ctypes.POINTER(ctypes.c_ubyte))]

    buf = ctypes.create_string_buffer(raw)
    source = Blob(len(raw), ctypes.cast(buf, ctypes.POINTER(ctypes.c_ubyte)))
    target = Blob()
    crypt = ctypes.WinDLL("crypt32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if decrypt:
        fn = crypt.CryptUnprotectData
        fn.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(target))
    else:
        fn = crypt.CryptProtectData
        fn.argtypes = [ctypes.POINTER(Blob), wintypes.LPCWSTR, ctypes.c_void_p, ctypes.c_void_p,
                       ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        ok = fn(ctypes.byref(source), "LyX AI credentials", None, None, None, 1, ctypes.byref(target))
    if not ok:
        raise ctypes.WinError(ctypes.get_last_error())
    try:
        return ctypes.string_at(target.data, target.size)
    finally:
        kernel.LocalFree(target.data)


def atomic_write(path: Path, content: bytes):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + ".", dir=path.parent)
    try:
        with os.fdopen(fd, "wb") as out:
            out.write(content)
            out.flush()
            os.fsync(out.fileno())
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


class Store:
    def __init__(self, folder: Path | None = None):
        self.folder = folder or data_dir()
        self.path = self.folder / "config.json"
        self.revision = None

    def load(self):
        if not self.path.exists():
            self.revision = None
            return default_config()
        raw = self.path.read_bytes()
        obj = json.loads(raw)
        if obj.get("version") not in (1, 2) or not isinstance(obj.get("profiles"), list):
            raise ValueError("Unsupported configuration / 配置格式不支持；原文件已保留")
        obj['version'] = 2
        for p in obj["profiles"]:
            account = p.pop('credentials_keychain', None)
            if account:
                from .macos import keychain
                p.update(json.loads(keychain(account)))
                continue
            secret = p.pop("credentials_dpapi", None)
            p.update(json.loads(_dpapi(base64.b64decode(secret), True)) if secret else {"api_key": "", "headers": {}})
        self.revision = hashlib.sha256(raw).hexdigest()
        return add_builtin_templates(obj)

    def save(self, obj):
        # Lock the read/compare/replace transaction across multiple companion windows.
        self.folder.mkdir(parents=True, exist_ok=True)
        with open(self.folder / "config.lock", "a+b") as lock:
            if lock.tell() == 0:
                lock.write(b"0")
                lock.flush()
            lock.seek(0)
            if os.name == "nt":
                import msvcrt
                msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(lock.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            new_accounts = []
            try:
                current = hashlib.sha256(self.path.read_bytes()).hexdigest() if self.path.exists() else None
                if current != self.revision:
                    raise ValueError("Configuration changed in another window. Reopen this window. / 配置已在其他窗口改变，请重新打开窗口。")
                saved = copy.deepcopy(obj)
                saved['version'] = 2
                preset_ids = {t['id'] for t in builtin_templates()}
                # Preset contents come from code; only custom prompts persist.
                saved['templates'] = [dict(id=t['id']) if t.get('id') in preset_ids else t for t in saved.get('templates', [])]
                old_raw = self.path.read_bytes() if self.path.exists() else b'{}'
                old = json.loads(old_raw)
                backup = self.folder / 'config.before-template-migration.json'
                backup_data = json.loads(backup.read_bytes()) if backup.exists() else old if old.get('version') == 1 else {}
                retained_accounts = {p.get('credentials_keychain') for p in backup_data.get('profiles', [])}
                for p in saved["profiles"]:
                    secret = {k: p.pop(k, "") for k in ("api_key", "url", "proxy")}
                    secret["headers"] = p.pop("headers", {})
                    if sys.platform == 'darwin':
                        from .macos import keychain
                        account = uuid.uuid4().hex
                        keychain(account, json.dumps(secret).encode())
                        new_accounts.append(account)
                        p['credentials_keychain'] = account
                    else:
                        p["credentials_dpapi"] = base64.b64encode(_dpapi(json.dumps(secret).encode())).decode()
                raw = json.dumps(saved, ensure_ascii=False, indent=2, allow_nan=False).encode("utf-8")
                if old.get('version') == 1 and not backup.exists():
                    atomic_write(backup, old_raw)
                atomic_write(self.path, raw)
                self.revision = hashlib.sha256(raw).hexdigest()
            except Exception:
                for account in new_accounts:
                    keychain(account, delete=True)
                raise
            finally:
                if os.name == "nt":
                    lock.seek(0)
                    msvcrt.locking(lock.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
            for p in old.get('profiles', []):
                if p.get('credentials_keychain') and p['credentials_keychain'] not in retained_accounts:
                    try:
                        keychain(p['credentials_keychain'], delete=True)
                    except RuntimeError:
                        pass  # A committed config must remain usable if cleanup is denied.


def endpoint(profile, models=False):
    url = profile.get("url", "").strip().rstrip("/")
    parts = urlsplit(url)
    if parts.scheme not in ("https", "http") or not parts.hostname or parts.username or parts.password or parts.fragment:
        raise ValueError("Enter an HTTP(S) Base URL or full endpoint without embedded credentials / API 地址无效")
    suffix = {"chat": "/chat/completions", "responses": "/responses", "anthropic": "/messages"}[profile["protocol"]]
    path = parts.path.rstrip("/")
    known = next((s for s in ("/chat/completions", "/responses", "/messages") if path.endswith(s)), None)
    if models:
        path = (path[:-len(known)] if known else path) + "/models"
    elif not path.endswith(suffix):
        if known:
            raise ValueError("Endpoint path does not match selected protocol / 完整端点与所选协议不匹配")
        path += suffix
    return urlunsplit((parts.scheme, parts.netloc, path, parts.query, ""))


def request_headers(p):
    auth = p.get("auth", "auto")
    if auth == "auto":
        auth = "x-api-key" if p["protocol"] == "anthropic" else "bearer"
    h = {"Content-Type": "application/json", "Accept": "text/event-stream, application/json"}
    key = p.get("api_key", "").strip()
    if key and auth != "none":
        h["x-api-key" if auth == "x-api-key" else "Authorization"] = key if auth == "x-api-key" else f"Bearer {key}"
    if p["protocol"] == "anthropic":
        h["anthropic-version"] = "2023-06-01"
    for name, val in p.get("headers", {}).items():
        if not re.fullmatch(r"[!#$%&'*+.^_`|~0-9A-Za-z-]+", name) or not isinstance(val, str) or any(x in val for x in ("\r", "\n", "\x00")):
            raise ValueError("Invalid custom header / 自定义请求头无效")
        if name.lower() in ("host", "content-length", "connection", "transfer-encoding"):
            raise ValueError(f"Reserved HTTP header: {name}")
        for existing in list(h):
            if existing.lower() == name.lower():
                del h[existing]
        h[name] = val
    return h


def merge_dict(base, extra):
    for k, v in extra.items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            merge_dict(base[k], v)
        elif v is None:
            base.pop(k, None)
        else:
            base[k] = copy.deepcopy(v)


def build_request(p, messages, *, test=False):
    protocol = p["protocol"]
    if protocol not in PROTOCOLS:
        raise ValueError("Unknown API protocol")
    if not p.get("model", "").strip():
        raise ValueError("Model is required / 请填写模型名称")
    for name in ("first_timeout", "idle_timeout", "total_timeout"):
        val = p.get(name, 120)
        if not isinstance(val, (int, float)) or not math.isfinite(val) or not 0.1 <= val <= 86400:
            raise ValueError(f"{name}: expected 0.1–86400 seconds")
    body = {"model": p["model"].strip(), "stream": bool(p.get("stream", True))}
    system = "\n\n".join(m["content"] for m in messages if m["role"] == "system")
    turns = [copy.deepcopy(m) for m in messages if m["role"] != "system"]
    if protocol == "anthropic":
        body["messages"] = turns
        if system:
            body["system"] = system
    elif protocol == "responses":
        body["input"] = turns
        body["store"] = False
        if system:
            body["instructions"] = system
    else:
        body["messages"] = copy.deepcopy(messages)
    params = copy.deepcopy(p.get("params", {}))
    max_tokens = p.get("max_tokens")
    if max_tokens is not None:
        if not isinstance(max_tokens, int) or isinstance(max_tokens, bool) or max_tokens <= 0:
            raise ValueError("max_tokens must be a positive integer")
        field = p.get("token_field", "auto")
        if field == "auto":
            field = "max_output_tokens" if protocol == "responses" else "max_completion_tokens" if protocol == "chat" and p.get("provider") == "OpenAI" else "max_tokens"
        body[field] = max_tokens
    thinking, effort = p.get("thinking", "default"), p.get("effort", "")
    if thinking != "default":
        if protocol == "responses":
            if thinking == "disabled":
                body["reasoning"] = {"effort": "none"}
            elif thinking == "adaptive":
                raise ValueError("Adaptive thinking is a Claude Messages option / adaptive 仅用于 Claude Messages")
            elif not effort:
                raise ValueError("Responses thinking: choose an effort / 请为 Responses 思考模式选择深度")
        elif protocol == "chat" and p.get("provider") in ("OpenAI", "Grok"):
            if thinking == "disabled":
                body["reasoning_effort"] = "none"
            elif thinking == "adaptive":
                raise ValueError("adaptive requires Claude Messages")
            elif not effort:
                raise ValueError("Choose reasoning effort / 请选择思考深度")
        else:
            body["thinking"] = {"type": thinking}
            if protocol == "anthropic" and thinking == "enabled":
                body["thinking"]["budget_tokens"] = p.get("thinking_budget") or 2048
    if effort:
        if thinking == "disabled":
            raise ValueError("Reasoning effort conflicts with disabled thinking / 关闭思考时请清空思考深度")
        if protocol == "responses":
            body.setdefault("reasoning", {})["effort"] = effort
        elif protocol == "anthropic":
            body["output_config"] = {"effort": effort}
        else:
            body["reasoning_effort"] = effort
    if p.get("thinking_budget") is not None:
        if protocol != "anthropic":
            raise ValueError("Thinking budget is native to Claude Messages; use extra JSON for other protocols / 其他协议请用高级 JSON 指定预算字段")
        if thinking != "enabled":
            raise ValueError("Manual budget requires enabled thinking / 手动预算只用于 enabled 思考模式")
    if p.get("verbosity"):
        if protocol == "responses":
            body.setdefault("text", {})["verbosity"] = p["verbosity"]
        elif protocol == "chat":
            body["verbosity"] = p["verbosity"]
        else:
            raise ValueError("Claude Messages has no generic verbosity field / Claude 请通过提示词或高级 JSON 控制详略")
    reserved = {"messages", "input", "instructions", "system", "model", "stream", "previous_response_id", "conversation", "background"}
    if reserved.intersection(params):
        raise ValueError("Extra JSON cannot replace conversation/model/stream fields / 高级 JSON 不能覆盖会话、模型或流式开关")
    merge_dict(body, params)
    if protocol == "anthropic":
        cap = body.get("max_tokens")
        if not isinstance(cap, int) or isinstance(cap, bool) or cap <= 0:
            raise ValueError("Claude Messages requires max_tokens / Claude Messages 必须设置最大输出")
        th = body.get("thinking", {})
        if th.get("type") == "enabled":
            budget = th.get("budget_tokens")
            if not isinstance(budget, int) or not 1024 <= budget < cap:
                raise ValueError("Claude: 1024 ≤ thinking budget < max_tokens / 思考预算必须小于最大输出")
    json.dumps(body, allow_nan=False)
    return endpoint(p), request_headers(p), body


def render_prompt(template, selection, reply_language):
    # Replace once: braces in LaTeX and placeholders inside selected text are literal.
    values = {"selection": selection, "reply_language": reply_language}
    prompt = re.sub(r"\{(selection|reply_language)\}", lambda m: values[m[1]], template)
    if "{selection}" not in template:
        prompt += "\n\n" + selection
    return prompt


def redact(value, p):
    text = str(value)
    secrets = [p.get("api_key", "")] + [v for k, v in p.get("headers", {}).items() if any(s in k.lower() for s in ("auth", "key", "token", "secret", "cookie"))]
    for secret in secrets:
        if secret:
            text = text.replace(secret, "[REDACTED]")
    return text


def preview_request(p, messages):
    url, headers, body = build_request(p, messages)
    # All custom header values are hidden, even if their names look innocuous.
    safe = {k: ("[REDACTED]" if k.lower() not in ("content-type", "accept", "anthropic-version") else v) for k, v in headers.items()}
    parts = urlsplit(url)
    safe_url = urlunsplit((parts.scheme, parts.netloc, parts.path, "[REDACTED]" if parts.query else "", ""))
    return json.dumps(dict(url=safe_url, headers=safe, body=body), ensure_ascii=False, indent=2)


def text_content(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(x.get("text", "") for x in content if isinstance(x, dict) and x.get("type") in ("text", "output_text", "summary_text"))
    return ""


def parse_response(protocol, obj):
    if obj.get("error"):
        error = obj["error"]
        raise ValueError(error.get("message", str(error)) if isinstance(error, dict) else str(error))
    reasoning, finish, usage = "", "", obj.get("usage", {})
    if protocol == "chat":
        choices = obj.get("choices", [])
        if not choices:
            raise ValueError("No choices in response / 响应缺少 choices")
        first = choices[0]
        msg = first.get("message", {})
        text = text_content(msg.get("content")) or text_content(msg.get("refusal"))
        reasoning = msg.get("reasoning_content") or msg.get("reasoning") or ""
        finish = first.get("finish_reason", "")
    elif protocol == "anthropic":
        text = text_content(obj.get("content"))
        reasoning = "".join(x.get("thinking", "") for x in obj.get("content", []) if x.get("type") == "thinking")
        finish = obj.get("stop_reason", "")
    else:
        if obj.get("status") in ("failed", "cancelled"):
            raise ValueError(f"Response status: {obj['status']}")
        text = obj.get("output_text") or "".join(text_content(x.get("content")) for x in obj.get("output", []) if x.get("type") == "message")
        reasoning = "".join(text_content(x.get("summary")) for x in obj.get("output", []) if x.get("type") == "reasoning")
        finish = obj.get("status", "")
        if finish == "incomplete":
            finish = "length" if obj.get("incomplete_details", {}).get("reason") == "max_output_tokens" else "incomplete"
    if not text:
        raise ValueError("Response contains no answer text (possibly token limit or tool-only output) / 没有回答正文，请检查输出上限或工具参数")
    return text, reasoning, finish, usage


class SSEDecoder:
    """Incremental UTF-8 and SSE framing, including fragmented CRLF and multi-line data."""
    def __init__(self):
        self.decoder = codecs.getincrementaldecoder("utf-8-sig")()
        self.buffer = ""
        self.lines = []

    def feed(self, raw, final=False):
        self.buffer += self.decoder.decode(raw, final)
        events = []
        while "\n" in self.buffer:
            line, self.buffer = self.buffer.split("\n", 1)
            line = line.rstrip("\r")
            if line:
                self.lines.append(line)
            else:
                data = [x[5:].lstrip(" ") for x in self.lines if x.startswith("data:")]
                if data:
                    events.append("\n".join(data))
                self.lines.clear()
        if final and (self.buffer or self.lines):
            if self.buffer:
                self.lines.append(self.buffer.rstrip("\r"))
                self.buffer = ""
            data = [x[5:].lstrip(" ") for x in self.lines if x.startswith("data:")]
            if data:
                events.append("\n".join(data))
            self.lines.clear()
        return events


class StreamResult:
    def __init__(self, protocol):
        self.protocol = protocol
        self.text = ""
        self.reasoning = ""
        self.usage = {}
        self.finish = ""
        self.done = False

    def event(self, data):
        if data.strip() == "[DONE]":
            self.done = True
            return "", ""
        obj = json.loads(data)
        if obj.get("error") or obj.get("type") in ("error", "response.failed"):
            e = obj.get("error") or obj.get("response", {}).get("error") or obj
            raise ValueError(e.get("message", str(e)) if isinstance(e, dict) else str(e))
        text, reasoning = "", ""
        if self.protocol == "chat":
            choices = obj.get("choices", [])
            if choices:
                first = choices[0]
                d = first.get("delta", {})
                text = text_content(d.get("content")) or text_content(d.get("refusal"))
                reasoning = d.get("reasoning_content") or d.get("reasoning") or ""
                if first.get("finish_reason"):
                    self.finish = first["finish_reason"]
                    self.done = True
            if obj.get("usage"):
                self.usage.update(obj["usage"])
        elif self.protocol == "anthropic":
            kind = obj.get("type")
            if kind == "content_block_start":
                block = obj.get("content_block", {})
                text = block.get("text", "")
                reasoning = block.get("thinking", "")
            elif kind == "content_block_delta":
                d = obj.get("delta", {})
                text = d.get("text", "")
                reasoning = d.get("thinking", "")
            elif kind == "message_delta":
                self.finish = obj.get("delta", {}).get("stop_reason", "")
            elif kind == "message_stop":
                self.done = True
            self.usage.update(obj.get("usage", {}))
            self.usage.update(obj.get("message", {}).get("usage", {}))
        else:
            kind = obj.get("type", "")
            if kind in ("response.output_text.delta", "response.refusal.delta"):
                text = obj.get("delta", "")
            elif kind in ("response.reasoning_summary_text.delta", "response.reasoning_text.delta"):
                reasoning = obj.get("delta", "")
            elif kind in ("response.completed", "response.incomplete"):
                response = obj.get("response", {})
                if not self.text:
                    text, r, self.finish, self.usage = parse_response("responses", response)
                    if not self.reasoning:
                        reasoning = r
                else:
                    self.finish = response.get("status", "completed")
                    if self.finish == "incomplete":
                        self.finish = "length" if response.get("incomplete_details", {}).get("reason") == "max_output_tokens" else "incomplete"
                    self.usage = response.get("usage", {})
                self.done = True
        if not isinstance(text, str) or not isinstance(reasoning, str):
            raise ValueError("Invalid text in stream / 流式正文格式无效")
        self.text += text
        self.reasoning += reasoning
        return text, reasoning
