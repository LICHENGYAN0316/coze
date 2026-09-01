# Coze 原生运行证据

本目录保存真实、已脱敏的 Coze Coding 项目截图。项目 ID 为 `7679015075092578350`，四组原生运行版本为 `v0.2.0`，当前项目版本为 `v0.2.1`，状态保持 **未部署**。

`v0.2.1` 只把 15 个商品 `name` 从现实或近似现实系列名替换为原创中文名称，未改 ID、价格、库存、评分、销量、场景、优缺点、代码、路由或分数。名称黑名单扫描通过；平台随后因资源点耗尽无法再次调用 LLM，因此本目录不把 `v0.2.0` 截图标成 `v0.2.1` 原生运行。

## 证据索引

| 文件 | 证明内容 |
| --- | --- |
| [`coze-workflow-and-test.png`](coze-workflow-and-test.png) | `v0.2.0` 工作流画布、版本记录与测试上下文同屏 |
| [`coze-case-a-recommend.png`](coze-case-a-recommend.png) | `v0.2.0`：完整笔记本需求进入 `recommend`，返回 Top 3 |
| [`coze-case-b-clarification.png`](coze-case-b-clarification.png) | `v0.2.0`：“想买降噪耳机”缺预算，进入 `need_clarification`，只追问一个关键问题 |
| [`coze-case-c-no-result.png`](coze-case-c-no-result.png) | `v0.2.0`：100 元高性能笔记本进入 `no_result`，推荐数组为空并给出预算/优先项/相邻品类建议 |
| [`coze-case-d-recommend.png`](coze-case-d-recommend.png) | `v0.2.0`：5000 元内拍照手机进入 `recommend`，返回 Top 3 |
| [`coze-native-v0.2.0.png`](coze-native-v0.2.0.png) | v0.2.0 阶段的四用例汇总与画布；保留为迭代过程证据 |

## 验收边界

- `v0.2.0` 四次试运行均由 Coze 项目直接执行，未手工编辑节点输出；
- 输入全部来自仓库中的四组固定合成用例；
- 截图只保留项目画布、合成输入、结构化输出和版本信息；
- 未公开账号、邮箱、头像、令牌、Cookie、工作区列表、运行日志或本机路径；
- 本目录证明 Coze 原生流程已运行，不把本地复算结果冒充平台输出。

## 为什么没有原生单文件导出

当前 Coze Coding 项目视图未提供可直接导入的单文件工作流导出入口。因此仓库同时提供：

1. [`../workflow/coze-workflow-equivalent.json`](../workflow/coze-workflow-equivalent.json)：结构化等价配置；
2. [`../workflow/workflow-spec.md`](../workflow/workflow-spec.md)：节点、变量、分支与规则契约；
3. 本目录的原生画布和四组运行截图；
4. [`../scripts/validate_bundle.py`](../scripts/validate_bundle.py)：可复现的 271 项本地一致性检查。

这四层材料共同满足免登录审阅，同时明确不声称等价 JSON 是平台原生导出。

隐私标准见 [`../docs/privacy.md`](../docs/privacy.md)。
