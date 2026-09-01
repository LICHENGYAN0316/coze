# Coze 原生证据状态

当前日化版尚没有 Coze 原生运行截图。

原因是本次工作只更新 GitHub 子项目，没有在 Coze 平台中改动画布、配置 `ARK_API_KEY` Secret 或执行日化版在线调用。为了不把旧域截图冒充成日化版证据，仓库已移除旧截图。

新证据只能在以下条件全部满足后添加：

1. Coze 画布已按 [`workflow/coze-workflow-equivalent.json`](../workflow/coze-workflow-equivalent.json) 同步；
2. 豆包凭证通过 Coze Secret 配置，截图不显示密钥；
3. A–D 四个日化用例在平台内实际运行；
4. 截图已脱敏且可看清输入、结构化输出、版本和状态；
5. [`examples/coze-platform-runs.json`](../examples/coze-platform-runs.json) 仅记录真实完成的原生运行。

在此之前，[`examples/input-output.json`](../examples/input-output.json) 始终标记为离线复算，不作为 Coze 原生执行证据。
