# 安装与卸载教程

当前版本 0.3.1。已有旧版请先看[覆盖升级教程](UPGRADE.zh-CN.md)，无需先卸载，模型配置和界面语言保留。

## 1. 准备

- Windows 10/11，已安装 LyX 2.5；默认目录是 `C:\Program Files\LyX 2.5`。
- 已解压完整的 `LyXAI-Windows.zip`。不要在压缩包内直接运行。
- 一个可用的 API 账户和密钥，或你自己的中转站配置。

打包版自带 Python/Qt 运行环境，不需要安装 Python。菜单启动桥梁使用 LyX 2.5 自带的 Python，请保留 LyX 安装目录中的 `Python` 文件夹及其默认搜索路径。

本版本已通过离屏回归、真实 LyX Server/结构化剪贴板/公式粘贴与撤销检查。真实桌面右键点击和真实 API 账户仍需短验收，请先用测试文档。

## 2. 安装打包版

1. 保存并退出 LyX，关闭已打开的 LyX AI。
2. 解压安装包，双击 `Install.cmd`。通常不需要管理员权限。
3. 成功后，助手程序位于 `%LOCALAPPDATA%\LyXAI\LyXAI.exe`。
4. 从开始菜单 **LyX AI - Start LyX** 打开 LyX，在主正文框选文字后右键，应出现中文的“AI 写作助手…”或英文的“AI Writing Assistant…”，以及补充前后文菜单，跟随 LyX 的界面语言。
5. 打开助手，点击“模型配置…”，按[使用说明](USER-GUIDE.zh-CN.md)设置接口。

如果 PowerShell 的执行策略阻止脚本，不需要修改系统策略。可以手动复制解压目录里的整个 `LyXAI` 文件夹到 `%LOCALAPPDATA%\LyXAI`，然后在 PowerShell 中执行这个本地程序：

```powershell
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --install
```

程序是目录式分发，`_internal` 等依赖文件夹必须与 EXE 一起保留。不要只复制一个 EXE。

### 非默认安装路径

在解压目录打开 PowerShell：

```powershell
.\Install.ps1 -LyXDir 'D:\Apps\LyX 2.5' -LyXUserDir "$env:APPDATA\LyX2.5"
```

也可以直接给程序传入路径：

```powershell
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --install --lyx-dir 'D:\Apps\LyX 2.5' --lyx-user-dir "$env:APPDATA\LyX2.5"
```

LyX 用户目录请在 LyX“帮助 → 关于 LyX”中核对。如果同时使用多个 LyX 版本，应传入对应版本的用户目录。

## 3. 从源码运行或安装

如果你没有打包版，在源码目录执行：

```powershell
py -3.12 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe main.py --configure
```

确认助手能打开后，保存并退出 LyX，然后安装菜单：

```powershell
.\.venv\Scripts\python.exe main.py --install
```

本机已有完整依赖时也可直接使用 `python main.py --configure` 和 `python main.py --install`。源码安装的菜单会指向当前 Python 和源码位置；安装后不要移动源码目录或删除虚拟环境，移动后需要重新执行安装命令。

源码安装后若旧启动器尚未刷新语言环境，可以在当前 PowerShell 设置 `$env:LYX_LOCALEDIR = "$env:APPDATA\LyX2.5\lyxai-locale"` 后启动 LyX，或注销 Windows 再登录。

从源码打包需要额外安装 PyInstaller，然后运行 `build.ps1`；输出为 `dist\LyXAI-Windows.zip`。脚本只负责构建和复制文件，不会修改 LyX 配置。

## 4. 菜单语言

默认 `auto` 使用用户级翻译覆盖层，跟随 LyX 界面语言。新开始菜单入口立即使用该环境；旧快捷方式必要时需注销 Windows 后重新登录。改变 LyX 界面语言后重启生效，详见[升级教程](UPGRADE.zh-CN.md#语言生效方式)。也可指定固定语言：

```powershell
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --install --menu-language zh
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --install --menu-language en
```

助手窗口右上角可以直接切换中英文。菜单语言与窗口语言分别控制。

## 5. 安装修改了什么

| 位置 | 用途 |
|---|---|
| `%LOCALAPPDATA%\LyXAI` | 打包版程序及依赖 |
| `%APPDATA%\LyX2.5\ui\stdcontext.inc` | 用户级正文右键菜单 |
| `%APPDATA%\LyX2.5\ui\stdcontext.inc.before-lyxai` | 安装前已有用户菜单时的原始备份 |
| `%APPDATA%\LyX2.5\lyxai-install.json` | 安装记录，用于回滚 |
| `%APPDATA%\LyX2.5\lyxai-locale` | 保留原有翻译的菜单语言覆盖层 |
| 用户环境变量 `LYX_LOCALEDIR` | 指向翻译覆盖层；卸载时恢复旧值 |
| 开始菜单 `LyX AI - Start LyX` | 带正确语言环境的 LyX 启动入口 |
| `%APPDATA%\LyXAI\config.json` | 模型和模板配置，认证信息 DPAPI 加密 |

安装不会改写 `Program Files` 内的 LyX 文件，也不会改写 `.lyx` 文档。选区、上下文和会话不会自动保存到配置文件。自动上下文短暂导出本地临时快照，读取后删除；点击应用才通过 LyX 自己的粘贴修改内存文档，保存由用户决定。

检测到自定义 `ui_file` 时，自动安装会停止并保留现有设置。需要把生成的三项菜单接入实际使用的 UI 文件；此版本不自动合并任意第三方 UI。

## 6. 短验收：只做一次

1. 打开安装包中的 `examples/context-demo.lyx`，或者使用一份临时文档，写入正文 A、一个 Note、一个 Footnote、正文 B。
2. 框选正文中的目标句，右键“AI 写作助手”，检查助手原文。
3. 等待“正文已读取”，检查前后文自动填入，且不含 Note、Footnote 内容；可调整字符范围并重新拉取。
4. “补充前文 / 后文”仍可手动追加，复用同一窗口；但会改变当前 LyX 选区，写回前需重新框选目标并问询。
5. 点击“预览发送内容”，检查目标、前文、后文以及提示词。此步骤不访问 API。
6. 填入自己的模型配置后点击“测试连接”；只有这一步才验证真实账户、网络和模型能力，可能产生费用。

没有结构化选区时，程序会报错，不会退回无法过滤脚注的普通剪贴板文本。请从主正文选取，不要进入备注或脚注内部单独选取；原因见[正文过滤范围](USER-GUIDE.zh-CN.md#正文过滤范围)。

## 7. 更新与卸载

更新时退出 LyX 和 LyX AI，完整解压新版并运行安装脚本。已有模型配置保留。详见[覆盖升级与公式验收](UPGRADE.zh-CN.md)。

移除菜单：

```powershell
& "$env:LOCALAPPDATA\LyXAI\LyXAI.exe" --uninstall
```

或运行 `Uninstall.ps1`，还会移除开始菜单入口。原有菜单和语言环境可以恢复；安装后用户另改的菜单与环境变量会被保留。翻译缓存默认保留，卸载后不再使用。

重启 LyX 后，确认菜单已移除，再按需要手动删除 `%LOCALAPPDATA%\LyXAI`。模型配置默认保留；需要清除时另外删除 `%APPDATA%\LyXAI`。DPAPI 密文不能直接跨 Windows 账户迁移，迁移后需要重新填写密钥。

## 8. 常见问题

| 现象 | 检查方式 |
|---|---|
| 没有新增菜单 | 重启 LyX；核对用户目录；确认使用默认 UI |
| 菜单灰色 | 从主正文重新框选非空文字 |
| 点击没有打开助手 | 先单独启动 EXE；确认目录完整；核对 LyX 自带 Python 和搜索路径 |
| 菜单语言不符 | 用新开始菜单入口，或注销 Windows 后重新登录，再核对 LyX 界面语言 |
| 无法连接 LyX Server | 保持 LyX 打开，关闭模态对话框；确认 serverpipe 未禁用，用户目录正确 |
| 无法唯一定位目标 | 扩大原文选区；仍可手动补充上下文获取建议，安全覆盖需唯一定位 |
| 应用被拒绝 | 确认仍在问询时的文档；应用使用最新选区或光标，允许同文档编辑；处理未接受的修订，跨不同正文布局时分段应用 |
| 无结构化选区 | 重新在 LyX 主正文选择，使用 AI 菜单；不要先从其他软件复制 |
| 注释内容仍出现在手动粘贴中 | 普通文本已失去对象类型，请人工删掉，改用 LyX 菜单导入 |
| 配置提示被其他窗口修改 | 关闭旧助手窗口并重开；新版通过单窗口复用减少此问题 |
| Coding 端点拒绝请求 | 核对套餐专用密钥、端点和官方允许工具范围；普通 API 可选 GLM / BigModel |
