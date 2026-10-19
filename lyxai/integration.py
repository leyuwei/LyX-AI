"""User-level LyX menu installation. Never changes Program Files or a document."""
from __future__ import annotations

import ctypes
from ctypes import wintypes
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import time
from .core import atomic_write
from .selection import extract_body

BEGIN = "# BEGIN LYXAI MANAGED MENU"
END = "# END LYXAI MANAGED MENU"


def command_line():
    if getattr(sys, "frozen", False):
        return [str(Path(sys.executable).resolve())]
    pythonw = Path(sys.executable).with_name("pythonw.exe")
    return [str(pythonw if pythonw.exists() else Path(sys.executable)), str(Path(__file__).resolve().parents[1] / "main.py")]


def menu_text(source, command, language="both"):
    # vc-command reads its entire command as ONE quote-delimited argument and
    # waits for exit. A tiny bundled-Python bootstrap launches the GUI detached.
    # A hex integer avoids both LyX's and Systemcall's quote stripping, and
    # preserves spaces/Unicode. LyX 2.5 bundles Python 3.12 (big-endian default).
    labels = {
        "auto": ("AI Writing Assistant…", "Add context before", "Add context after"),
        "zh": ("AI 写作助手…", "补充 AI 前文", "补充 AI 后文"),
        "en": ("AI Writing Assistant…", "Add context before", "Add context after"),
        "both": ("问询 AI / Ask AI…|A", "加入前文 / Context before|B", "加入后文 / Context after|F"),
    }[language]
    items = []
    for label, extra in zip(labels, ([], ["--context-before"], ["--context-after"])):
        code = "import subprocess;subprocess.Popen(" + repr(command + ["--from-lyx"] + extra) + ",stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,close_fds=True,creationflags=0x08000000)"
        payload = code.encode("utf-8")
        bootstrap = "pythonw -c exec((0x" + payload.hex() + ").to_bytes(" + str(len(payload)) + "))"
        lfun = 'command-sequence copy; vc-command U . "' + bootstrap + '"'
        escaped = lfun.replace("\\", "\\\\").replace('"', '\\"')
        items.append(f'\t\tItem "{label}" "{escaped}"')
    block = BEGIN + "\n" + "\n".join(items) + "\n" + END
    source = re.sub(r"(?m)^# BEGIN LYXAI MANAGED MENU\r?\n.*?^# END LYXAI MANAGED MENU\r?\n?", "", source, flags=re.S)
    marker = re.search(r'(?m)^[ \t]*Menu "context-edit"[ \t]*\r?$', source)
    if not marker:
        raise ValueError("No context-edit menu found / 未找到正文右键菜单")
    return source[:marker.end()] + "\n" + block + source[marker.end():]


def install(lyx_dir=Path(r"C:\Program Files\LyX 2.5"), user_dir=None, *, command=None, language="both"):
    lyx_dir = Path(lyx_dir)
    user_dir = Path(user_dir or Path(os.environ["APPDATA"]) / "LyX2.5")
    if not (lyx_dir / "Resources/ui/stdcontext.inc").exists():
        raise ValueError("LyX installation directory not found / LyX 安装目录无效")
    preferences = user_dir / "preferences"
    if preferences.exists():
        configured = re.search(r'(?m)^\\ui_file\s+"([^"]+)"', preferences.read_text(encoding="utf-8"))
        if configured and Path(configured[1]).name != "default.ui":
            raise ValueError("Custom LyX UI detected. Add the menu to that UI manually; existing configuration was preserved. / 检测到自定义 UI，请按说明手动接入，现有配置已保留。")
    target = user_dir / "ui/stdcontext.inc"
    manifest_path = user_dir / "lyxai-install.json"
    original = target.read_bytes() if target.exists() else None
    manifest = json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.exists() else None
    source = (original if original is not None else (lyx_dir / "Resources/ui/stdcontext.inc").read_bytes()).decode("utf-8-sig")
    updated = menu_text(source, (command or command_line()) + ['--lyx-user-dir', str(user_dir)], language).encode("utf-8")
    if manifest is None:
        backup = user_dir / "ui/stdcontext.inc.before-lyxai"
        if backup.exists():
            raise ValueError("An earlier menu backup exists; inspect it before installation / 已有旧备份，请先检查")
        if original is not None:
            atomic_write(backup, original)
        manifest = {"version": 1, "had_original": original is not None, "backup": str(backup)}
    manifest.update(installed_hash=hashlib.sha256(updated).hexdigest(), language=language, target=str(target))
    if language == 'auto':
        from .localization import install_overlay
        install_overlay(lyx_dir, user_dir, manifest)
    # Journal first so an interrupted installation is still reversible.
    atomic_write(manifest_path, json.dumps(manifest, ensure_ascii=False, indent=2).encode())
    atomic_write(target, updated)
    if language == 'auto':
        from .localization import activate_overlay
        activate_overlay(manifest)
    return str(target)


def uninstall(user_dir=None):
    user_dir = Path(user_dir or Path(os.environ["APPDATA"]) / "LyX2.5")
    manifest_path = user_dir / "lyxai-install.json"
    if not manifest_path.exists():
        return "No LyX AI menu installed / 没有已安装的菜单"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    from .localization import remove_overlay
    remove_overlay(manifest)
    target = user_dir / "ui/stdcontext.inc"
    if target.exists():
        current = target.read_bytes()
        if hashlib.sha256(current).hexdigest() == manifest["installed_hash"]:
            if manifest["had_original"]:
                atomic_write(target, (user_dir / "ui/stdcontext.inc.before-lyxai").read_bytes())
            else:
                target.unlink()
        else:
            # Keep edits made since installation; remove only our bounded block.
            text = current.decode("utf-8-sig")
            text = re.sub(r"(?ms)^# BEGIN LYXAI MANAGED MENU\r?\n.*?^# END LYXAI MANAGED MENU\r?\n?", "", text)
            atomic_write(target, text.encode())
    manifest_path.unlink()
    backup = user_dir / "ui/stdcontext.inc.before-lyxai"
    if backup.exists():
        backup.unlink()
    return "Menu removed. Restart LyX. Settings retained. / 菜单已移除，重启 LyX 生效，模型配置已保留。"


def capture_lyx_payload():
    """Capture native structured selection before Qt; refuse unsafe plain-text fallback."""
    if os.name != "nt":
        raise RuntimeError("Windows is required")
    u = ctypes.WinDLL("user32", use_last_error=True)
    k = ctypes.WinDLL("kernel32", use_last_error=True)
    u.GetClipboardOwner.restype = wintypes.HWND
    u.GetClipboardData.argtypes = [wintypes.UINT]
    u.GetClipboardData.restype = wintypes.HANDLE
    u.GetWindowThreadProcessId.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    k.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    k.OpenProcess.restype = wintypes.HANDLE
    k.QueryFullProcessImageNameW.argtypes = [wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR, ctypes.POINTER(wintypes.DWORD)]
    k.CloseHandle.argtypes = [wintypes.HANDLE]
    k.GlobalLock.argtypes = [wintypes.HGLOBAL]
    k.GlobalLock.restype = ctypes.c_void_p
    k.GlobalUnlock.argtypes = [wintypes.HGLOBAL]
    k.GlobalSize.argtypes = [wintypes.HGLOBAL]
    k.GlobalSize.restype = ctypes.c_size_t
    u.RegisterClipboardFormatW.argtypes = [wintypes.LPCWSTR]
    u.RegisterClipboardFormatW.restype = wintypes.UINT
    for _ in range(20):
        if u.OpenClipboard(None):
            break
        time.sleep(0.015)
    else:
        raise RuntimeError("Clipboard busy; retry / 剪贴板忙，请重试")
    try:
        pid = wintypes.DWORD()
        owner = u.GetClipboardOwner()
        if not owner:
            raise ValueError("No clipboard owner; select text in LyX again / 请重新选中 LyX 文字")
        u.GetWindowThreadProcessId(owner, ctypes.byref(pid))
        process = k.OpenProcess(0x1000, False, pid.value)
        if not process:
            raise ValueError("Cannot verify LyX clipboard / 无法确认选区来自 LyX")
        try:
            buffer = ctypes.create_unicode_buffer(32768)
            size = wintypes.DWORD(len(buffer))
            if not k.QueryFullProcessImageNameW(process, 0, buffer, ctypes.byref(size)) or Path(buffer.value).name.lower() != "lyx.exe":
                raise ValueError("Clipboard is not from LyX; select text again / 剪贴板不是 LyX 选区，请重试")
        finally:
            k.CloseHandle(process)
        native_format = u.RegisterClipboardFormatW("application/x-lyx")
        handle = u.GetClipboardData(native_format)
        if not handle:
            raise ValueError("Structured LyX selection unavailable. Re-select body text and use the LyX AI menu; plain text cannot reliably exclude notes. / 无法读取结构化选区，请重新框选正文后使用 LyX AI 菜单；纯文本无法可靠过滤备注脚注。")
        size = k.GlobalSize(handle)
        if not 0 < size <= 16_000_000:
            raise ValueError("Selection too large or invalid / 选区过大或无效")
        pointer = k.GlobalLock(handle)
        if not pointer:
            raise ctypes.WinError(ctypes.get_last_error())
        try:
            native = ctypes.string_at(pointer, size).rstrip(b"\x00").decode("utf-8-sig")
        finally:
            k.GlobalUnlock(handle)
        selection = extract_body(native)
        if len(selection.text) > 2_000_000:
            raise ValueError("Selection too large / 选区过长，请分段问询")
        return {"text": selection.text, "excluded": selection.excluded, "native": native, "owner_pid": pid.value}
    finally:
        u.CloseClipboard()


def capture_lyx_selection():
    return capture_lyx_payload()["text"]


