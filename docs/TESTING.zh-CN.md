# 测试方式与验证状态

2026-10-19，版本 0.3.1。默认快速回归不操作桌面；真实 LyX 和浏览器检查独立显式执行，不放进日常测试循环。

## 快速回归

```powershell
python -m unittest discover -s tests -q
```

本机 **59 项通过，套件约 1.2 秒**。使用 Qt offscreen、本机 HTTP mock 与临时配置，不调用真实 API、不移动鼠标、不截图、不切换窗口、不启动真实 LyX。

新增检查：全局应用按钮在每个输出标签下均可见；语言保存、关闭重开及切回；旧配置模板追加、不覆盖用户编辑且不重复添加；align/aligned 等环境与内嵌定界符、标签/编号保留、不完整环境拒绝。

覆盖三种 API 协议、生成与思考参数、超时、取消、错误和流式解析、DPAPI、单实例通信、安装回滚、结构化正文过滤、上下文歧义、Markdown/公式分段、原生公式序列化、结构对象拒绝覆盖、原生语法注入拒绝、完整修改稿提取、失败/截断不提取、语言切换保留待替换正文，以及预览安全边界。

预览标签隐藏时不会创建浏览器。开始新请求会清空旧替换稿，防止误用上一轮结果。

## 真实 LyX 的独立检查

```powershell
python tests/smoke_lyx.py
```

本机约 **7.8 秒**，只用临时文档和独立 LyX 用户目录，通过官方 LyX Server 执行命令。没有鼠标、截图或屏幕坐标依赖。优先用独立 Windows window station；本机权限不允许时使用不可见 desktop，测试前复制剪贴板全部 Qt 格式，并在 finally 中恢复。此检查不应作为高频后台任务运行。

已实际验证：

- 当前内存文档导出，无需保存用户文档。
- Windows 原生 `application/x-lyx` 剪贴板读取与进程来源检查。
- 与菜单相同的完整 LFUN：copy、detached Python 引导、启动助手、捕获选区、单实例 IPC 接收及确认。
- 目标前后正文自动读取，Note、Foot 内容排除。
- 原生粘贴替换目标，行内公式和**单行 Displayed 公式**均成为真正 Formula inset。
- 使用用户提供的完整 align 多行公式和 aligned 进行实际粘贴，验证 label、三处 nonumber 保留；LyX 的 HTML 剪贴板导出包含 MathML 表格及至少六行，确认实际对齐结构，而非文字源码。
- 原文语言设置保留，周围 Note、Foot 完整保留。
- **一次 undo 恢复整个原始正文**。
- 选区变化拒绝覆盖；磁盘原文件不被保存改写。

此测试运行中不会打开用户的工作文档。它验证菜单使用的命令链；真实桌面中菜单显示和点击位置仍属于人工短验收。

## 离线预览与打包检查

```powershell
$env:QT_QPA_PLATFORM = 'offscreen'
python main.py --self-test-preview .test-runtime/preview.json
python tests/smoke_package.py
```

预览检查等待字体加载完成，检查行内/Displayed/align/aligned 四个公式、两处 MathML 对齐表格、Markdown 加粗、无公式解析错误、脚本不执行、远程图片不加载；生成一次离屏图用于核对。`--self-test-preview` 也可对打包 EXE 执行，要求进程正常退出，不能仅以报告文件存在视为成功。

打包检查包含 Qt 运行时、中文选区 IPC、隔离菜单安装与卸载。构建隔离 PATH，避免其他应用的 ICU DLL 混入。浏览器页面先于其 profile 销毁，已修复关闭时崩溃。KaTeX 及字体均随包分发。

可设置 `LYXAI_SMOKE_EXE` 为打包 EXE 的绝对路径，再运行 `smoke_lyx.py`，把真实菜单 LFUN 的启动目标换为打包版，验证打包后的取词与 IPC。

文档图片用 `python tests/render_previews.py` 离屏生成，不读取桌面。目录中的 main/models 图片是界面快照，不是实际 API 回答验收。

27 份 LyX 原有语言目录已逐一合并校验，保留原翻译条目与复数形式；新增菜单按配置语言翻译，未提供翻译的语言回退英文。真实桌面切换语言仍建议按升级教程短验收。

## 尚需用户账户或人工验收

- 各官方服务商和每个中转站的真实账户、网络、模型权限；尚未提供 API 密钥。
- 用户桌面上右键菜单的显示、点击与当前 LyX 界面语言。
- 所有自定义布局、宏和复杂 inset 组合；复杂目标采用拒绝自动覆盖策略。

请按[覆盖升级教程](UPGRADE.zh-CN.md#无-api-的短验收)在文档副本上验收一次。测试时间为本机测量，不代表 AI 响应耗时或 GUI 冷启动延迟。
