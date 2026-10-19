"""Non-blocking Qt HTTP client with cancellation and three independent deadlines."""
from __future__ import annotations

import json
from urllib.parse import urlsplit, unquote

from PySide6.QtCore import QObject, QTimer, QUrl, Signal
from PySide6.QtNetwork import QNetworkAccessManager, QNetworkProxy, QNetworkReply, QNetworkRequest

from .core import SSEDecoder, StreamResult, build_request, endpoint, parse_response, redact, request_headers


class NetworkJob(QObject):
    delta = Signal(str, str)
    completed = Signal(object)
    failed = Signal(str)
    MAX_BYTES = 32 * 1024 * 1024

    def __init__(self, profile, parent=None):
        super().__init__(parent)
        self.profile = profile
        self.manager = QNetworkAccessManager(self)
        self.reply = None
        self.result = StreamResult(profile["protocol"])
        self.decoder = SSEDecoder()
        self.raw = bytearray()
        self.received = 0
        self.mode = None
        self.error = ""
        self.ended = False
        self.fetch_models = False
        self.first = QTimer(self)
        self.idle = QTimer(self)
        self.total = QTimer(self)
        for timer, message in ((self.first, "First response timeout / 等待响应超时"),
                               (self.idle, "Read idle timeout / 读取空闲超时"),
                               (self.total, "Total request timeout / 请求总时限已到")):
            timer.setSingleShot(True)
            timer.timeout.connect(lambda m=message: self.stop(m))

    def start(self, messages=None, *, models=False):
        try:
            self.fetch_models = models
            p = self.profile
            if models:
                url, headers, body = endpoint(p, models=True), request_headers(p), None
            else:
                url, headers, body = build_request(p, messages)
            proxy_url = p.get("proxy", "").strip()
            if proxy_url:
                parsed = urlsplit(proxy_url)
                if parsed.scheme not in ("http", "socks5") or not parsed.hostname or parsed.path not in ("", "/"):
                    raise ValueError("Proxy: use http://host:port or socks5://host:port / 代理地址格式无效")
                kind = QNetworkProxy.ProxyType.Socks5Proxy if parsed.scheme == "socks5" else QNetworkProxy.ProxyType.HttpProxy
                self.manager.setProxy(QNetworkProxy(kind, parsed.hostname, parsed.port or (1080 if parsed.scheme == "socks5" else 8080),
                                                   unquote(parsed.username or ""), unquote(parsed.password or "")))
            req = QNetworkRequest(QUrl(url))
            req.setAttribute(QNetworkRequest.Attribute.RedirectPolicyAttribute, QNetworkRequest.RedirectPolicy.ManualRedirectPolicy)
            for name, value in headers.items():
                req.setRawHeader(name.encode("ascii"), value.encode("utf-8"))
            self.reply = self.manager.get(req) if models else self.manager.post(req, json.dumps(body, ensure_ascii=False, allow_nan=False).encode())
            self.reply.metaDataChanged.connect(self.headers_received)
            self.reply.readyRead.connect(self.read)
            self.reply.finished.connect(self.finish)
            self.first.start(round(p.get("first_timeout", 120) * 1000))
            self.total.start(round(p.get("total_timeout", 600) * 1000))
        except Exception as exc:
            self.error = redact(str(exc), self.profile)
            QTimer.singleShot(0, self.finish)

    def headers_received(self):
        self.first.stop()
        self.idle.start(round(self.profile.get("idle_timeout", 120) * 1000))

    def read(self):
        try:
            self.read_available()
        except Exception as exc:
            self.stop("Response error / 响应读取失败: " + str(exc))

    def read_available(self):
        if self.ended or not self.reply:
            return
        chunk = bytes(self.reply.readAll())
        if not chunk:
            return
        self.first.stop()
        self.idle.start(round(self.profile.get("idle_timeout", 120) * 1000))
        self.received += len(chunk)
        if self.received > self.MAX_BYTES:
            self.stop("Response exceeds 32 MiB / 响应超过 32 MiB")
            return
        status = self.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
        content_type = str(self.reply.header(QNetworkRequest.KnownHeaders.ContentTypeHeader) or "").lower()
        if self.mode is None:
            self.mode = "sse" if "text/event-stream" in content_type and 200 <= status < 300 else "json"
        if self.mode == "sse":
            try:
                for event in self.decoder.feed(chunk):
                    self.delta.emit(*self.result.event(event))
            except Exception as exc:
                self.stop("Stream error / 流式解析失败: " + str(exc))
        else:
            self.raw.extend(chunk)

    def stop(self, message="Cancelled / 已取消"):
        if self.ended:
            return
        self.error = redact(message, self.profile)
        if self.reply and self.reply.isRunning():
            self.reply.abort()
        else:
            self.finish()

    def finish(self):
        if self.ended:
            return
        if self.reply and not self.error:
            self.read()
        # read() may have aborted and re-entered finish().
        if self.ended:
            return
        self.ended = True
        for timer in (self.first, self.idle, self.total):
            timer.stop()
        try:
            if self.error:
                raise ValueError(self.error)
            if not self.reply:
                raise ValueError("Request did not start / 请求未启动")
            status = self.reply.attribute(QNetworkRequest.Attribute.HttpStatusCodeAttribute) or 0
            if 300 <= status < 400:
                raise ValueError(f"HTTP {status}: redirect refused; enter the final endpoint / 请填写重定向后的最终 API 地址")
            if not 200 <= status < 300:
                detail = self.raw.decode("utf-8", "replace")[:2000]
                try:
                    error = json.loads(detail).get("error", detail)
                    detail = error.get("message", str(error)) if isinstance(error, dict) else str(error)
                except (ValueError, AttributeError):
                    pass
                raise ValueError(f"HTTP {status}: {detail or self.reply.errorString()}")
            if self.reply.error() != QNetworkReply.NetworkError.NoError:
                raise ValueError(self.reply.errorString())
            if self.fetch_models:
                obj = json.loads(self.raw)
                models = [x["id"] for x in obj.get("data", []) if isinstance(x, dict) and isinstance(x.get("id"), str)]
                if not models:
                    raise ValueError("No model IDs returned; enter a model manually / 未返回模型列表，可手动填写模型名")
                self.completed.emit({"models": models})
            elif self.mode == "sse":
                for event in self.decoder.feed(b"", final=True):
                    self.delta.emit(*self.result.event(event))
                if not self.result.done:
                    raise ValueError("Stream ended before completion; partial answer retained / 流式连接提前结束，已保留部分回答")
                if not self.result.text:
                    raise ValueError("No answer text; increase output limit or check model parameters / 没有回答正文，请检查输出上限和参数")
                self.completed.emit(dict(text=self.result.text, reasoning=self.result.reasoning, finish=self.result.finish, usage=self.result.usage))
            else:
                text, reason, finish, usage = parse_response(self.profile["protocol"], json.loads(self.raw))
                self.delta.emit(text, reason)
                self.completed.emit(dict(text=text, reasoning=reason, finish=finish, usage=usage))
        except Exception as exc:
            self.failed.emit(redact(str(exc), self.profile))
        finally:
            if self.reply:
                self.reply.deleteLater()
            self.deleteLater()
