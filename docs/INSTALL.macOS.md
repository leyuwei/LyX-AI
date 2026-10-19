# macOS 安装与发布 / Installation and release

适用环境：macOS 12+、LyX 2.5。默认发布包为 Universal 2，包含 Apple Silicon 和 Intel 架构。打包版自带 Python、Qt、KaTeX 和字体，使用者无需安装 Python。实际联调环境为 Apple Silicon、macOS 27.0.1、LyX 2.5.0；Intel 和旧版 macOS 尚未实机验证。

## 安装

1. 完整解压 `LyXAI-0.3.1-macOS-universal2.zip`，保存文档并退出 LyX 和助手。
2. 双击 `Install-macOS.command`，也可以在终端执行 `bash Install-macOS.command`。
3. 正常启动 LyX，在主正文选取文字，右键选择“问询 AI / Ask AI…”；在助手内配置自己的接口和密钥。
4. 检查待替换正文后应用；在 LyX 使用 **⌘Z** 撤销。

本地构建使用 ad-hoc 签名，未使用 Developer ID 签名，也未经过 Apple 公证。从网络下载后，Gatekeeper 可能阻止应用或安装脚本。仅在确认来源可信时，按系统提示进入“系统设置 → 隐私与安全性”选择“仍要打开”。正式对外发布前，可使用自己的 Developer ID 完成签名和公证；本仓库不包含证书或公证凭据。

安装位置为 `~/Applications/LyXAI.app`。LyX 菜单写入 `~/Library/Application Support/LyX-2.5/ui/stdcontext.inc`，保留原菜单备份；不修改 `/Applications/LyX.app`。配置位于 `~/Library/Application Support/LyXAI/config.json`，密钥、自定义请求头、服务地址及代理信息保存在当前用户钥匙串中，服务名为 `org.lyxai.credentials`。请不要跨账户直接复制配置文件代替重新填写凭据。

菜单固定为中英双语，助手界面可以独立切换语言。自定义 LyX UI 的安装检查与 Windows 版一致，检测到非默认 UI 时会保留配置并拒绝自动覆盖。

非默认安装位置可在终端指定：

```bash
LYX_APP="$HOME/Applications/LyX.app" \
LYX_USER_DIR="$HOME/Library/Application Support/LyX-2.5" \
bash Install-macOS.command
```

覆盖安装会保留模型、模板和语言设置。运行 `Uninstall-macOS.command` 移除菜单和应用，配置及钥匙串凭据默认保留。彻底清理时，另行删除上述配置目录，并在“钥匙串访问”中删除 `org.lyxai.credentials` 对应条目。

## 写回行为

`\eqref{eq:demo}`、`\ref{fig:demo}`、`\ref{tab:demo}`、`\ref{sec:demo}`、`\pageref{sec:demo}` 和 `\cite{paper2026}` 等命令会转换成可编辑的原生引用对象，引用目标及文献须存在于文档中。文献引用支持常用 cite/citep/citet/parencite/textcite 命令及纯文本前后附注。原有引用的格式参数在原样往返时保留。代码片段内的命令保留为文字。

跨正文选区中的 Note、Footnote、Marginal、图表等非正文对象不发送给 AI；应用时覆盖整个当前选区，因此其中的这些对象会被删除。**⌘Z 一次撤销可同时恢复正文及这些对象。**应用读取最新选区；无选区时在光标处插入。等待期间可调整位置或编辑同一文档；切换到其他文档、未处理的修订、跨不同正文布局仍会拒绝写入。请从主正文选择完整公式；不要进入脚注或公式内部单独选取。

## 从源码构建

使用 python.org 的 Universal 2 Python 3.13，在 macOS 上执行：

```bash
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-macos-build.txt
./build-macos.sh
```

构建脚本生成应用图标、打包完整运行时、写入版本信息、执行 ad-hoc 签名并检查签名，输出：

- `dist/LyXAI.app`
- `dist/LyXAI-0.3.1-macOS-universal2.zip`
- `dist/LyXAI-0.3.1-macOS-universal2.zip.sha256`

ZIP 包含应用、安装/卸载脚本、文档、示例、项目许可证和 `BUILD-DEPENDENCIES.txt`。发布时上传 ZIP 和 SHA-256 文件。ZIP 与应用均位于被 Git 忽略的 `dist/` 中。

可用 `ARCH=arm64 ./build-macos.sh` 或 `ARCH=x86_64 ./build-macos.sh` 生成单架构包。Universal 2 构建要求 Python 及原生依赖均包含两种架构；PyInstaller 会检查这一条件。脚本默认使用 `.venv/bin/python`，也可通过 `PYTHON` 指定解释器。

## 验证

```bash
QT_QPA_PLATFORM=offscreen .venv/bin/python -m unittest discover -s tests -p 'test_*.py'
.venv/bin/python tests/smoke_macos.py
.venv/bin/python tests/smoke_package.py dist/LyXAI.app/Contents/MacOS/LyXAI
LYXAI_SMOKE_EXE="$PWD/dist/LyXAI.app/Contents/MacOS/LyXAI" .venv/bin/python tests/smoke_macos.py
QT_QPA_PLATFORM=offscreen dist/LyXAI.app/Contents/MacOS/LyXAI --self-test-preview "$PWD/build/macos/preview.json"
codesign --verify --deep --strict dist/LyXAI.app
```

真实 LyX 检查使用临时文档、独立用户目录和剪贴板备份，会短暂打开测试窗口；请避免在测试过程中操作剪贴板或测试文档。覆盖原生公式、引用解析、非正文过滤与覆盖、撤销、最新选区替换和光标插入。XHTML 导出检查确认公式、图、表、章节和文献引用解析成编号。不会调用真实 AI 接口。

## English quick start

Requires macOS 12+ and LyX 2.5. Extract the complete Universal 2 ZIP, quit LyX and LyX AI, then run `Install-macOS.command`. The app installs to `~/Applications/LyXAI.app`; open LyX normally and use the bilingual context menu. Undo with **⌘Z**. Credentials are stored in macOS Keychain. `Uninstall-macOS.command` removes the app and menu while retaining settings and credentials.

This build is ad-hoc signed and is not Apple notarized. For a trusted download blocked by Gatekeeper, follow macOS Privacy & Security prompts. Developer ID signing and notarization require the publisher's own Apple credentials. The native integration was tested on Apple Silicon; Intel and older macOS versions still require hardware validation.
