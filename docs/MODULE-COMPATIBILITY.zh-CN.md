# 文档类与模块兼容性

转换参数根据 LyX 已安装的布局/模块声明计算，不按 IEEEtran 或某两个模块名称编写特例。用户目录中的布局优先于系统布局，并递归读取 `Input` 引入的定义。

| 声明或情况 | 处理方式 |
|---|---|
| `ProvidesModule` | 使用文档类已提供的功能，不重复传入等价模块；同时检查它与其他模块的双向互斥。 |
| `ExcludesModule` | 排除文档类不允许的模块，并逐层处理依赖这些模块的扩展。 |
| `#Excludes` | 任一方向声明互斥即视为不兼容；两项显式模块互斥时列出名称，不擅自二选一。 |
| `#Requires` | 按 LyX 规则将 `A | B` 解释为至少一个依赖；按依赖关系重排，而不是依赖原列表顺序。 |
| `DefaultModule` | 加载兼容的默认模块，保留声明顺序；用户显式选择优先于冲突的默认项。 |
| `begin_removed_modules` | 尊重用户移除默认模块的选择，不重新添加。 |
| 缺失模块、依赖缺失或循环 | 在转换/写回前给出具体原因，原文不变；不安装新模块，也不猜测替代模块。 |
| 布局环境名称 | 从实际 `Style` / `CopyStyle` / `LatexName` 读取，处理 `NoStyle` 和本地覆盖；定理可用性没有文档类名称白名单。参数中的 `LatexName` 不会覆盖父布局。 |

这些规则只整理临时转换所用的模块，不修改原文档设置。转换后的环境还要检查是否产生相应的原生布局，避免已知布局变成源码后仍当作成功写回。

声明语义参照安装目录中的 LyX Customization 手册及[官方自定义手册](https://ftp.lyx.de/Documentation/en/Customization.pdf)。这套兼容性处理不是完整的 LyX/TeX 解析器：任意自定义类、复杂宏和第三方模块组合仍不能声称全部经过验证；未知宏仍可能以 ERT 保留，由原文档配置负责排版。

## 可重复验证

```powershell
python -m unittest discover -s tests -q
python tests/smoke_modules.py
python tests/smoke_lyx.py --structures-only
```

快速测试不启动转换器、LyX 或桌面：使用临时定义验证所有依赖顺序、替代依赖、双向互斥、默认/移除项、传递依赖、循环、缺失模块、本地覆盖及任意名称的自定义类。

真实转换矩阵包含 **18 个成功用例**：article、book、IEEEtran、beamer、powerdot、siamltex、svmono、svmult、ijmpc、ijmpd、amsart、amsbook；AMS 的不同组合及倒序依赖，`enumitem`、`paralist` 等非定理模块，以及临时注册的自定义 Observation 模块。同时验证 **4 个互斥组合**在转换前被拒绝：`enumitem/paralist` 和 `knitr/lilypond` 的正反两种顺序。

上述矩阵检查实际 tex2lyx 输出的原生布局，不代表对每种文档类进行了完整 PDF 编译。独立的真实 LyX 检查验证长篇 lemma/proof、图表及数学对象的写回、LaTeX/HTML 导出、PDF 编译和一次撤销。所有检查都使用临时数据，不调用 AI API，不修改已安装的布局和模块。
