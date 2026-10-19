"""One companion window per settings directory; local messages have a 16 MiB limit."""
from __future__ import annotations

import hashlib
import json
import sys

from PySide6.QtCore import QObject, QTimer, Signal, QLockFile
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from shiboken6 import isValid

from .core import data_dir

MAX_MESSAGE = 16 * 1024 * 1024


def server_name():
    return "LyXAI-" + hashlib.sha256(str(data_dir().resolve()).casefold().encode()).hexdigest()[:24]


def validate_message(obj):
    if not isinstance(obj, dict) or obj.get("kind") not in ("selection", "before", "after", "activate", "configure"):
        raise ValueError("Invalid companion message")
    if obj["kind"] in ("selection", "before", "after"):
        if not isinstance(obj.get("text"), str) or not obj["text"].strip() or len(obj["text"]) > 2_000_000:
            raise ValueError("Invalid selection text")
        if 'native' in obj and (not isinstance(obj['native'], str) or len(obj['native']) > 16_000_000 or not isinstance(obj.get('owner_pid'), int)):
            raise ValueError('Invalid native LyX selection')
    return obj


def deliver(message):
    """Return False only if no companion exists, never after a partial send."""
    validate_message(message)
    raw = json.dumps(message, ensure_ascii=False).encode()
    if len(raw) > MAX_MESSAGE:
        raise ValueError("Selection message is too large")
    sock = QLocalSocket()
    sock.connectToServer(server_name())
    if not sock.waitForConnected(100):
        return False
    sock.write(len(raw).to_bytes(4, "big") + raw)
    if sock.bytesToWrite() and not sock.waitForBytesWritten(1000):
        raise RuntimeError("Unable to pass selection to the existing window / 无法传递选区，请重试")
    if not sock.waitForReadyRead(1500) or bytes(sock.readAll()) != b"OK":
        raise RuntimeError("Companion did not acknowledge selection / 助手未确认接收，请检查助手窗口")
    sock.disconnectFromServer()
    return True


class InstanceServer(QObject):
    received = Signal(object)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.server = QLocalServer(self)
        self.server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        self.buffers = {}
        self.lock = None
        self.server.newConnection.connect(self.accept_connections)

    def listen(self):
        if sys.platform == 'darwin':
            # Unix sockets survive a crash. Only the lock owner may reclaim one.
            data_dir().mkdir(parents=True, exist_ok=True)
            self.lock = QLockFile(str(data_dir() / 'instance.lock'))
            self.lock.setStaleLockTime(0)
            if not self.lock.tryLock(0):
                return False
            QLocalServer.removeServer(server_name())
        return self.server.listen(server_name())

    def accept_connections(self):
        while self.server.hasPendingConnections():
            sock = self.server.nextPendingConnection()
            self.buffers[sock] = bytearray()
            sock.readyRead.connect(lambda s=sock: self.read(s))
            sock.disconnected.connect(lambda s=sock: self.cleanup(s))
            timer = QTimer(sock)
            timer.setSingleShot(True)
            timer.timeout.connect(lambda s=sock: s.abort() if isValid(s) else None)
            timer.start(3000)
            if sock.bytesAvailable():
                self.read(sock)

    def cleanup(self, sock):
        self.buffers.pop(sock, None)
        if isValid(sock):
            sock.deleteLater()

    def read(self, sock):
        if sock not in self.buffers:
            return
        data = self.buffers[sock]
        data.extend(bytes(sock.readAll()))
        if len(data) < 4:
            return
        size = int.from_bytes(data[:4], "big")
        if not 0 < size <= MAX_MESSAGE or len(data) > size + 4:
            sock.abort()
            return
        if len(data) != size + 4:
            return
        try:
            message = validate_message(json.loads(data[4:]))
            self.received.emit(message)
            sock.write(b"OK")
            sock.flush()
        except (ValueError, TypeError):
            sock.abort()
        self.buffers.pop(sock, None)
