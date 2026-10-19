"""User-level gettext overlay: LyX chooses these labels in its own UI language."""
from __future__ import annotations

import ctypes
from pathlib import Path
import struct
import os

from .core import atomic_write

LABELS = ('AI Writing Assistant…', 'Add context before', 'Add context after')
TRANSLATIONS = {
    'zh_CN': ('AI 写作助手…', '补充 AI 前文', '补充 AI 后文'),
    'zh_TW': ('AI 寫作助手…', '補充 AI 前文', '補充 AI 後文'),
    'de': ('AI-Schreibassistent…', 'Vorherigen Kontext ergänzen', 'Nachfolgenden Kontext ergänzen'),
    'fr': ('Assistant de rédaction IA…', 'Ajouter le contexte précédent', 'Ajouter le contexte suivant'),
    'es': ('Asistente de escritura IA…', 'Añadir contexto anterior', 'Añadir contexto posterior'),
    'it': ('Assistente di scrittura IA…', 'Aggiungi contesto precedente', 'Aggiungi contesto successivo'),
    'ja': ('AI 文章アシスタント…', '前の文脈を追加', '後の文脈を追加'),
    'ko': ('AI 글쓰기 도우미…', '앞 문맥 추가', '뒤 문맥 추가'),
    'pt': ('Assistente de escrita IA…', 'Adicionar contexto anterior', 'Adicionar contexto posterior'),
    'ru': ('Помощник письма ИИ…', 'Добавить предыдущий контекст', 'Добавить следующий контекст'),
}


def extend_catalog(raw, labels):
    """Preserve original plural msgids and translations byte for byte."""
    endian = '<' if raw[:4] == b'\xde\x12\x04\x95' else '>'
    magic, revision, count, originals, translations = struct.unpack_from(endian+'5I', raw)
    if magic != 0x950412de or revision >> 16 > 1:
        raise ValueError('Unsupported gettext catalog')
    catalog = {}
    for i in range(count):
        size, offset = struct.unpack_from(endian+'2I', raw, originals+8*i)
        key = raw[offset:offset+size]
        size, offset = struct.unpack_from(endian+'2I', raw, translations+8*i)
        catalog[key] = raw[offset:offset+size]
    for key, value in zip(LABELS, labels):
        catalog[key.encode()] = value.encode()
    keys = sorted(catalog)
    count = len(keys)
    start = 28+16*count
    key_data = b''.join(k+b'\0' for k in keys)
    values = [catalog[k] for k in keys]
    offsets = []
    cursor = start
    for key in keys:
        offsets.append((len(key), cursor))
        cursor += len(key)+1
    cursor = start+len(key_data)
    for value in values:
        offsets.append((len(value), cursor))
        cursor += len(value)+1
    return struct.pack('<7I', 0x950412de, 0, count, 28, 28+8*count, 0, 0) + b''.join(struct.pack('<2I', *item) for item in offsets) + key_data + b''.join(v+b'\0' for v in values)


def registry_locale(value=None, *, write=False):
    import winreg
    with winreg.CreateKey(winreg.HKEY_CURRENT_USER, 'Environment') as key:
        try:
            old = winreg.QueryValueEx(key, 'LYX_LOCALEDIR')[0]
        except FileNotFoundError:
            old = None
        if write:
            if value is None:
                try:
                    winreg.DeleteValue(key, 'LYX_LOCALEDIR')
                except FileNotFoundError:
                    pass
            else:
                winreg.SetValueEx(key, 'LYX_LOCALEDIR', 0, winreg.REG_SZ, value)
            result = ctypes.c_size_t()
            notify = ctypes.windll.user32.SendMessageTimeoutW
            notify.argtypes = [ctypes.c_void_p, ctypes.c_uint, ctypes.c_size_t, ctypes.c_wchar_p, ctypes.c_uint, ctypes.c_uint, ctypes.c_void_p]
            notify(0xffff, 0x1a, 0, 'Environment', 2, 1000, ctypes.byref(result))
        return old


def install_overlay(lyx_dir, user_dir, manifest):
    old = registry_locale()
    overlay = Path(user_dir) / 'lyxai-locale'
    manifest.setdefault('previous_locale', old)
    # Respect an existing translation customization as the source on first install.
    source = Path(manifest.get('previous_locale') or Path(lyx_dir) / 'Resources/locale')
    files = list(source.glob('*/LC_MESSAGES/LyX2.5.mo'))
    if not files:
        raise ValueError('LyX language catalogs unavailable / 未找到 LyX 语言文件')
    for file in files:
        lang = file.parent.parent.name
        labels = TRANSLATIONS.get(lang, TRANSLATIONS.get(lang.split('_')[0], LABELS))
        atomic_write(overlay / lang / 'LC_MESSAGES/LyX2.5.mo', extend_catalog(file.read_bytes(), labels))
    manifest['locale_overlay'] = str(overlay)
    return str(overlay)


def activate_overlay(manifest):
    registry_locale(manifest['locale_overlay'], write=True)


def remove_overlay(manifest):
    if manifest.get('locale_overlay') and registry_locale() == manifest['locale_overlay']:
        registry_locale(manifest.get('previous_locale'), write=True)
