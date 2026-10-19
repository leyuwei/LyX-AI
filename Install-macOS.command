#!/bin/bash
set -euo pipefail
cd "$(dirname "$0")"
task_source="$PWD/LyXAI.app"
[[ -d "$task_source" ]] || task_source="$PWD/dist/LyXAI.app"
task_destination="$HOME/Applications/LyXAI.app"
task_lyx="${LYX_APP:-/Applications/LyX.app}"
task_user="${LYX_USER_DIR:-$HOME/Library/Application Support/LyX-2.5}"
if [[ ! -x "$task_source/Contents/MacOS/LyXAI" || ! -d "$task_lyx" ]]; then
    echo 'LyXAI.app or LyX.app is missing. See docs/INSTALL.macOS.md.' >&2
    exit 1
fi
if pgrep -x lyx >/dev/null || pgrep -x LyXAI >/dev/null; then
    echo 'Save your documents and quit LyX and LyX AI before installing.' >&2
    exit 1
fi
mkdir -p "$HOME/Applications"
task_stage="$(mktemp -d "$HOME/Applications/.lyxai-install.XXXXXX")"
trap 'rm -rf "$task_stage"' EXIT
ditto "$task_source" "$task_stage/LyXAI.app"
if [[ -e "$task_destination" ]]; then
    mv "$task_destination" "$task_stage/previous.app"
fi
mv "$task_stage/LyXAI.app" "$task_destination"
if ! "$task_destination/Contents/MacOS/LyXAI" --install --lyx-dir "$task_lyx" --lyx-user-dir "$task_user" --menu-language both; then
    rm -rf "$task_destination"
    if [[ -d "$task_stage/previous.app" ]]; then
        mv "$task_stage/previous.app" "$task_destination"
    fi
    echo 'Menu installation failed; the previous app was restored.' >&2
    exit 1
fi
echo "Installed: $task_destination"
echo 'Restart LyX and select body text → right-click → Ask AI.'
echo '启动 LyX，框选正文 → 右键 → 问询 AI。'
