"""Bounded LyX Server operations. Run these on a worker, never the GUI thread."""
from __future__ import annotations

import ctypes
import hashlib
from ctypes import wintypes
import os
from pathlib import Path
import re
import sys
import tempfile
import time
import uuid

from .selection import extract_body


class OVERLAPPED(ctypes.Structure):
    _fields_ = [('Internal', ctypes.c_size_t), ('InternalHigh', ctypes.c_size_t),
                ('Offset', wintypes.DWORD), ('OffsetHigh', wintypes.DWORD), ('hEvent', wintypes.HANDLE)]


def pipe_name(user_dir=None):
    from .integration import default_user_dir
    user = Path(user_dir or default_user_dir())
    preferences = user / 'preferences'
    content = preferences.read_text(encoding='utf-8') if preferences.exists() else ''
    match = re.search(r'(?m)^\\serverpipe\s+"(.*)"', content)
    stem = match[1] if match else (str(user / '.lyxpipe') if sys.platform == 'darwin' else r'\\.\pipe\$$UserDir\lyxpipe')
    stem = stem.replace('$$UserDir', str(user).replace('\\', '/'))
    if not stem:
        raise ValueError('LyX Server 已禁用，请在 LyX 首选项中启用。 / LyX Server is disabled.')
    return str(Path(stem).expanduser()) if sys.platform == 'darwin' else stem.replace('/', '\\')


class WindowsLyXServer:
    def __init__(self, stem=None, timeout=3):
        self.stem = stem or pipe_name()
        self.timeout = timeout
        self.client = 'lyxai' + uuid.uuid4().hex[:12]
        self.k = ctypes.WinDLL('kernel32', use_last_error=True)
        self.k.CreateFileW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD, wintypes.DWORD, wintypes.HANDLE]
        self.k.CreateFileW.restype = wintypes.HANDLE
        self.k.ReadFile.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.k.WriteFile.argtypes = self.k.ReadFile.argtypes
        self.k.PeekNamedPipe.argtypes = [wintypes.HANDLE, ctypes.c_void_p, wintypes.DWORD, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), ctypes.c_void_p]
        self.k.CloseHandle.argtypes = [wintypes.HANDLE]
        self.k.CreateEventW.argtypes = [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
        self.k.CreateEventW.restype = wintypes.HANDLE
        self.k.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
        self.k.GetOverlappedResult.argtypes = [wintypes.HANDLE, ctypes.c_void_p, ctypes.POINTER(wintypes.DWORD), wintypes.BOOL]
        self.k.CancelIoEx.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        self.handles = []
        self.buffer = b''

    def __enter__(self):
        return self

    def __exit__(self, *args):
        for handle in self.handles:
            self.k.CloseHandle(handle)
        self.handles.clear()

    def command(self, command, argument=''):
        # Windows LyX disconnects each pipe after an exchange, unlike a Unix
        # persistent FIFO. Open fresh handles; never resend a mutation on retry.
        try:
            return self._command(command, argument)
        finally:
            self.__exit__(None, None, None)

    def _open(self, suffix, access, deadline):
        while time.monotonic() < deadline:
            handle = self.k.CreateFileW(self.stem + suffix, access, 0, None, 3, 0x40000000 if suffix == '.out' else 0, None)
            if handle != ctypes.c_void_p(-1).value:
                self.handles.append(handle)
                return handle
            time.sleep(.02)
        raise TimeoutError('无法连接 LyX Server，请重启 LyX 并关闭模态对话框。 / Cannot connect to LyX Server.')

    def _command(self, command, argument):
        if any(c in command + argument for c in '\r\n\0'):
            raise ValueError('Invalid LyX command')
        raw = f'LYXCMD:{self.client}:{command}:{argument}\n'.encode('utf-8')
        deadline = time.monotonic() + self.timeout
        input_pipe = self._open('.in', 0x40000000, deadline)
        sent = False
        while time.monotonic() < deadline:
            output_pipe = self._open('.out', 0x80000000, deadline)
            event = self.k.CreateEventW(None, True, False, None)
            overlap = OVERLAPPED(hEvent=event)
            data = ctypes.create_string_buffer(65536)
            count = wintypes.DWORD()
            pending = not self.k.ReadFile(output_pipe, data, len(data), ctypes.byref(count), ctypes.byref(overlap))
            error = ctypes.get_last_error() if pending else 0
            try:
                if not sent:
                    written = wintypes.DWORD()
                    if not self.k.WriteFile(input_pipe, raw, len(raw), ctypes.byref(written), None) or written.value != len(raw):
                        raise RuntimeError('LyX connection closed')
                    sent = True
                    self.k.CloseHandle(input_pipe)
                    self.handles.remove(input_pipe)
                if pending and error == 997:
                    wait = self.k.WaitForSingleObject(event, max(1, int((deadline-time.monotonic())*1000)))
                    if wait != 0:
                        raise TimeoutError('LyX response timed out; close modal dialogs / LyX 响应超时，请关闭模态对话框')
                    pending = False
                    if not self.k.GetOverlappedResult(output_pipe, ctypes.byref(overlap), ctypes.byref(count), False):
                        continue
                elif pending:
                    continue
                self.buffer += data.raw[:count.value]
                if len(self.buffer) > 1_000_000:
                    raise RuntimeError('LyX reply exceeds limit')
                while b'\n' in self.buffer:
                    line, self.buffer = self.buffer.split(b'\n', 1)
                    reply = line.decode('utf-8', errors='replace')
                    for prefix in ('INFO:', 'ERROR:'):
                        token = f'{prefix}{self.client}:{command}:'
                        if reply.startswith(token):
                            if prefix == 'ERROR:':
                                raise RuntimeError(reply[len(token):])
                            return reply[len(token):]
            finally:
                if pending and error == 997:
                    self.k.CancelIoEx(output_pipe, None)
                    self.k.GetOverlappedResult(output_pipe, ctypes.byref(overlap), ctypes.byref(count), True)
                self.k.CloseHandle(event)
                self.k.CloseHandle(output_pipe)
                self.handles.remove(output_pipe)
        raise TimeoutError('LyX response timed out / LyX 响应超时')

    def snapshot(self):
        with tempfile.TemporaryDirectory(prefix='lyxai-') as folder:
            path = Path(folder) / 'snapshot.lyx'
            self.command('buffer-export', 'lyx ' + str(path).replace('\\', '/'))
            if sys.platform == 'darwin':
                # macOS LyX acknowledges an export before its worker finishes.
                deadline = time.monotonic() + self.timeout
                while not path.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
            if not path.exists() or path.stat().st_size > 16_000_000:
                raise RuntimeError('Unable to export current LyX buffer')
            return path.read_text(encoding='utf-8-sig')


if sys.platform == 'darwin':
    from .macos import MacLyXServer

    class LyXServer(MacLyXServer):
        snapshot = WindowsLyXServer.snapshot
else:
    LyXServer = WindowsLyXServer


def automatic_context(native, snapshot, radius=1800):
    target = extract_body(native).text
    body = extract_body(snapshot)
    # A repeated target is ambiguous: never silently pick the first occurrence.
    if body.text.count(target) != 1:
        raise ValueError('正文中无法唯一定位选区，请扩大原文选区或手动补充上下文。 / Target is ambiguous in body text.')
    start = body.text.index(target)
    return dict(before=body.text[max(0, start-radius):start].strip(), after=body.text[start+len(target):start+len(target)+radius].strip(), context_excluded=body.excluded)


def native_body(native):
    match = re.search(r'\\begin_body\s*\n(.*?)\\end_body', native.replace('\r\n', '\n'), re.S)
    if not match:
        raise ValueError('Invalid LyX fragment')
    return match[1].strip()


def load_context(payload, stem=None, radius=1800, include_context=True):
    from .integration import capture_lyx_payload
    with LyXServer(stem or pipe_name(payload.get('lyx_user_dir'))) as server:
        filename = server.command('server-get-filename')
        server.command('copy')
        current = capture_lyx_payload()
        if current['owner_pid'] != payload['owner_pid'] or native_body(current['native']) != native_body(payload['native']):
            raise ValueError('LyX 选区已切换，请重新问询。 / LyX selection changed.')
        snapshot = server.snapshot()
        # Export must not have switched buffers while acquiring context.
        if server.command('server-get-filename') != filename:
            raise ValueError('LyX 文档已切换，请重新问询。 / LyX document changed.')
    context = automatic_context(payload['native'], snapshot, radius)
    if not include_context:
        context.update(before='', after='')
    return dict(filename=filename, document_hash=hashlib.sha256(native_body(snapshot).encode()).hexdigest(), **context)


def verify_target(payload, server):
    from .integration import capture_lyx_payload
    if server.command('server-get-filename') != payload.get('filename'):
        raise ValueError('当前 LyX 文档已变化，请回原文重新框选并问询。 / LyX document changed.')
    server.command('copy')
    current = capture_lyx_payload()
    if current.get('owner_pid') != payload.get('owner_pid') or native_body(current['native']) != native_body(payload['native']):
        raise ValueError('LyX 当前选区已变化，请重新框选原文并问询，未执行覆盖。 / LyX selection changed; nothing replaced.')


def apply_replacement(payload, replacement, stem=None):
    from .replacement import replacement_fragment
    fragment = replacement_fragment(payload['native'], replacement)
    with LyXServer(stem or pipe_name(payload.get('lyx_user_dir'))) as server:
        current_hash = hashlib.sha256(native_body(server.snapshot()).encode()).hexdigest()
        if current_hash != payload.get('document_hash'):
            raise ValueError('问询后 LyX 正文已更改，请重新问询以使用最新原文。 / Document changed after capture; capture it again.')
        verify_target(payload, server)
        set_native_clipboard(fragment, replacement)
        if server.command('server-get-filename') != payload['filename']:
            raise ValueError('LyX document changed; nothing replaced')
        server.command('paste')
    return {'applied': True}


def set_native_clipboard(native, text):
    if sys.platform == 'darwin':
        from .macos import set_clipboard
        return set_clipboard(native, text)
    u = ctypes.WinDLL('user32', use_last_error=True)
    k = ctypes.WinDLL('kernel32', use_last_error=True)
    k.GlobalAlloc.argtypes = [wintypes.UINT, ctypes.c_size_t]
    k.GlobalAlloc.restype = wintypes.HGLOBAL
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalFree.argtypes = [wintypes.HGLOBAL]
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u.SetClipboardData.argtypes = [wintypes.UINT, wintypes.HANDLE]
    u.SetClipboardData.restype = wintypes.HANDLE
    u.CreateWindowExW.argtypes = [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.HWND, wintypes.HMENU, wintypes.HINSTANCE, ctypes.c_void_p]
    u.CreateWindowExW.restype = wintypes.HWND
    u.DestroyWindow.argtypes = [wintypes.HWND]
    u.OpenClipboard.argtypes = [wintypes.HWND]
    owner = u.CreateWindowExW(0, 'STATIC', 'LyX AI clipboard', 0, 0, 0, 0, 0, wintypes.HWND(-3), None, None, None)
    if not owner:
        raise ctypes.WinError(ctypes.get_last_error())
    blocks = []
    try:
        for fmt, raw in ((u.RegisterClipboardFormatW('application/x-lyx'), native.encode()+b'\0'), (13, text.encode('utf-16le')+b'\0\0')):
            handle = k.GlobalAlloc(0x42, len(raw))
            if not handle:
                raise MemoryError('Clipboard allocation failed')
            blocks.append([fmt, handle])
            ptr = k.GlobalLock(handle)
            if not ptr:
                raise ctypes.WinError(ctypes.get_last_error())
            ctypes.memmove(ptr, raw, len(raw))
            k.GlobalUnlock(handle)
        for _ in range(20):
            if u.OpenClipboard(owner):
                break
            time.sleep(.015)
        else:
            raise RuntimeError('Clipboard busy')
        try:
            if not u.EmptyClipboard():
                raise ctypes.WinError(ctypes.get_last_error())
            for block in blocks:
                if not u.SetClipboardData(*block):
                    raise ctypes.WinError(ctypes.get_last_error())
                block[1] = None  # ownership transferred to Windows
        finally:
            u.CloseClipboard()
    finally:
        for _, handle in blocks:
            if handle:
                k.GlobalFree(handle)
        u.DestroyWindow(owner)
