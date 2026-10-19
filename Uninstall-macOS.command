#!/bin/bash
set -euo pipefail
task_app="$HOME/Applications/LyXAI.app"
task_user="${LYX_USER_DIR:-$HOME/Library/Application Support/LyX-2.5}"
if pgrep -x lyx >/dev/null || pgrep -x LyXAI >/dev/null; then
    echo 'Save your documents and quit LyX and LyX AI before uninstalling.' >&2
    exit 1
fi
if [[ -x "$task_app/Contents/MacOS/LyXAI" ]]; then
    "$task_app/Contents/MacOS/LyXAI" --uninstall --lyx-user-dir "$task_user"
    rm -rf "$task_app"
fi
echo 'Removed LyX AI. Settings and Keychain credentials retained. / 已卸载，配置与钥匙串凭据已保留。'
