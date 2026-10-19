"""macOS pasteboard, Keychain and bounded LyX FIFO transport."""
from __future__ import annotations

import errno
import fcntl
import os
import select
import stat
import time
import uuid

from .selection import extract_body
from .errors import LyXCommandError

LYX_TYPE = 'com.trolltech.anymime.application--x-lyx'


def capture_payload():
    import objc
    from AppKit import NSPasteboard
    with objc.autorelease_pool():
        board = NSPasteboard.generalPasteboard()
        revision = board.changeCount()
        data = board.dataForType_(LYX_TYPE)
        if data is None or not 0 < len(data) <= 16_000_000:
            raise ValueError('Re-select body text in LyX / 请重新框选 LyX 正文')
        native = bytes(data).rstrip(b'\0').decode('utf-8-sig')
        if board.changeCount() != revision:
            raise ValueError('Clipboard changed; retry / 剪贴板已变化，请重试')
    selection = extract_body(native)
    if len(selection.text) > 2_000_000:
        raise ValueError('Selection too large / 选区过长，请分段问询')
    # macOS exposes no clipboard owner PID; writeback checks the buffer filename
    # and uses the live selection/caret through the selected LyX server.
    return dict(text=selection.text, excluded=selection.excluded, native=native, owner_pid=0)


def set_clipboard(native, text):
    import objc
    from AppKit import NSPasteboard, NSPasteboardItem, NSPasteboardTypeString
    from Foundation import NSData
    with objc.autorelease_pool():
        item = NSPasteboardItem.alloc().init()
        raw = native.encode('utf-8')
        if not item.setData_forType_(NSData.dataWithBytes_length_(raw, len(raw)), LYX_TYPE):
            raise RuntimeError('Cannot prepare LyX clipboard')
        item.setString_forType_(text, NSPasteboardTypeString)
        board = NSPasteboard.generalPasteboard()
        board.clearContents()
        if not board.writeObjects_([item]):
            raise RuntimeError('Cannot write LyX clipboard')


def keychain(account, raw=None, *, delete=False):
    import Security as sec
    query = {sec.kSecClass: sec.kSecClassGenericPassword,
             sec.kSecAttrService: 'org.lyxai.credentials', sec.kSecAttrAccount: account}
    if delete:
        status = sec.SecItemDelete(query)
        if status == sec.errSecItemNotFound:
            return
    elif raw is not None:
        status, _ = sec.SecItemAdd(dict(query, **{sec.kSecValueData: raw}), None)
    else:
        status, value = sec.SecItemCopyMatching(dict(query, **{sec.kSecReturnData: True}), None)
        if status == 0:
            return bytes(value)
    if status != 0:
        raise RuntimeError(f'macOS Keychain error {status} / 无法访问 macOS 钥匙串')


class MacLyXServer:
    def __init__(self, stem=None, timeout=3):
        from .bridge import pipe_name
        self.stem = stem or pipe_name()
        self.timeout = timeout
        self.client = 'lyxai' + uuid.uuid4().hex[:12]
        self.handles = []
        self.buffer = b''
        self.lock = None

    def __enter__(self):
        return self

    def __exit__(self, *args):
        for handle in self.handles:
            os.close(handle)
        self.handles.clear()
        if self.lock is not None:
            os.close(self.lock)
            self.lock = None

    def _connect(self, deadline):
        # A shared output FIFO must have only one LyX AI reader at a time.
        self.lock = os.open(self.stem + '.lyxai.lock', os.O_CREAT | os.O_RDWR, 0o600)
        while True:
            try:
                fcntl.flock(self.lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
                break
            except BlockingIOError:
                if time.monotonic() >= deadline:
                    raise TimeoutError('LyX Server is busy / LyX Server 忙，请重试')
                time.sleep(.02)
        while time.monotonic() < deadline:
            try:
                for suffix in ('.out', '.in'):
                    if not stat.S_ISFIFO(os.stat(self.stem + suffix).st_mode):
                        raise ValueError('LyX Server path is not a FIFO')
                output = os.open(self.stem + '.out', os.O_RDONLY | os.O_NONBLOCK)
                self.handles.append(output)
                source = os.open(self.stem + '.in', os.O_WRONLY | os.O_NONBLOCK)
                self.handles.append(source)
                return
            except OSError as exc:
                for handle in self.handles:
                    os.close(handle)
                self.handles.clear()
                if exc.errno not in (errno.ENOENT, errno.ENXIO):
                    raise
                time.sleep(.02)
        raise TimeoutError('Cannot connect to LyX Server; restart LyX / 无法连接 LyX Server，请重启 LyX')

    def command(self, command, argument=''):
        try:
            return self._command(command, argument)
        finally:
            self.__exit__()

    def _command(self, command, argument):
        if any(c in command + argument for c in '\r\n\0'):
            raise ValueError('Invalid LyX command')
        deadline = time.monotonic() + self.timeout
        if not self.handles:
            try:
                self._connect(deadline)
            except Exception:
                self.__exit__()
                raise
        output, source = self.handles
        raw = f'LYXCMD:{self.client}:{command}:{argument}\n'.encode('utf-8')
        if len(raw) > 65536:
            raise ValueError('LyX command exceeds limit')
        if not select.select([], [source], [], max(0, deadline-time.monotonic()))[1]:
            raise TimeoutError('LyX command write timed out')
        if os.write(source, raw) != len(raw):
            raise RuntimeError('LyX connection closed')
        while time.monotonic() < deadline:
            if not select.select([output], [], [], max(0, deadline-time.monotonic()))[0]:
                break
            data = os.read(output, 65536)
            if not data:
                time.sleep(.01)
                continue
            self.buffer += data
            if len(self.buffer) > 1_000_000:
                raise RuntimeError('LyX reply exceeds limit')
            while b'\n' in self.buffer:
                line, self.buffer = self.buffer.split(b'\n', 1)
                reply = line.decode('utf-8', errors='replace')
                for prefix in ('INFO:', 'ERROR:'):
                    token = f'{prefix}{self.client}:{command}:'
                    if reply.startswith(token):
                        if prefix == 'ERROR:':
                            raise LyXCommandError(reply[len(token):])
                        return reply[len(token):]
        raise TimeoutError('LyX response timed out; close modal dialogs / LyX 响应超时，请关闭模态对话框')
