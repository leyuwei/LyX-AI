#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
if [[ "$(uname -s)" != Darwin ]]; then
    echo 'Build this package on macOS.' >&2
    exit 1
fi
task_python="${PYTHON:-.venv/bin/python}"
task_version="$("$task_python" -c 'from lyxai import __version__; print(__version__)')"
task_arch="${ARCH:-universal2}"
task_package="LyXAI-${task_version}-macOS-${task_arch}"
mkdir -p build/macos dist
task_iconset='build/macos/logo.iconset'
mkdir -p "$task_iconset"
for size in 16 32 128 256 512; do
    sips -z "$size" "$size" lyxai/assets/logo.png --out "$task_iconset/icon_${size}x${size}.png" >/dev/null
    double=$((size * 2))
    sips -z "$double" "$double" lyxai/assets/logo.png --out "$task_iconset/icon_${size}x${size}@2x.png" >/dev/null
done
iconutil -c icns "$task_iconset" -o build/macos/logo.icns
"$task_python" -m PyInstaller --noconfirm --clean --windowed --onedir --name LyXAI \
    --target-arch "$task_arch" --osx-bundle-identifier org.lyxai.app \
    --icon "$PWD/build/macos/logo.icns" --add-data "$PWD/lyxai/assets:lyxai/assets" \
    --exclude-module tkinter --exclude-module PySide6.QtQml --exclude-module PySide6.QtQuick \
    --specpath build/macos "$PWD/main.py"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $task_version" dist/LyXAI.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $task_version" dist/LyXAI.app/Contents/Info.plist
/usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 12.0' dist/LyXAI.app/Contents/Info.plist
# Plist metadata changes invalidate the bundle signature produced by PyInstaller.
codesign --force --deep --sign - dist/LyXAI.app
codesign --verify --deep --strict dist/LyXAI.app
task_stage="$(mktemp -d "$PWD/build/macos/package.XXXXXX")"
trap 'rm -rf "$task_stage"' EXIT
mkdir "$task_stage/$task_package"
ditto dist/LyXAI.app "$task_stage/$task_package/LyXAI.app"
cp Install-macOS.command Uninstall-macOS.command README.md README.en.md LICENSE "$task_stage/$task_package/"
ditto docs "$task_stage/$task_package/docs"
ditto examples "$task_stage/$task_package/examples"
"$task_python" -m pip freeze > "$task_stage/$task_package/BUILD-DEPENDENCIES.txt"
"$task_python" - "$task_stage/$task_package/THIRD-PARTY-LICENSES" <<'PY'
from importlib.metadata import distributions
from pathlib import Path
import shutil
import sys
root = Path(sys.argv[1])
for dist in distributions():
    target_dir = root / dist.metadata['Name']
    target_dir.mkdir(parents=True, exist_ok=True)
    (target_dir / 'METADATA.txt').write_text(dist.read_text('METADATA') or '', encoding='utf-8')
    for entry in dist.files or []:
        if '.dist-info/' in str(entry) and ('/licenses/' in str(entry) or entry.name.lower().startswith(('license', 'copying', 'notice'))):
            source = Path(dist.locate_file(entry))
            if source.is_file():
                target = target_dir.joinpath(*entry.parts[1:])
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, target)
PY
ditto -c -k --sequesterRsrc --keepParent "$task_stage/$task_package" "dist/$task_package.zip"
(cd dist && shasum -a 256 "$task_package.zip" > "$task_package.zip.sha256")
echo "Package: $PWD/dist/$task_package.zip"
