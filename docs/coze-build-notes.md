# Coze 日化版同步说明

## 可证实的当前状态

- 平台项目 ID：`7679015075092578350`；
- 公开仓库内的日化等价配置、商品样本、固定用例和回归测试已完成；
- 本次没有登录 Coze 改动画布，没有配置 `ARK_API_KEY` Secret，也没有执行日化版原生调用；
- 项目保持未部署。

[`workflow/coze-workflow-equivalent.json`](../workflow/coze-workflow-equivalent.json) 是跨版本可读的节点蓝图，不是 Coze 原生导出，不应假设可以直接导入。

## 同步原则

1. 保留原节点 ID、连线、三种输出状态与七个顶层输出字段；
2. 替换品类、字段契约、硬过滤、排序公式、理由边界和兜底文案；
3. 商品库使用 `data/products.json`，不上传原始表、订单或顾客信息；
4. 将豆包凭证保存为 Coze Secret，节点中只引用 Secret 名称；
5. 重新执行 A–D 四个用例，保存已脱敏的新截图之后，才能更改 `coze-platform-runs.json` 的原生运行状态。

## 豆包 Secret

| 环境变量 | 用途 |
| --- | --- |
| `ARK_API_KEY` | 火山方舟 API 凭证，必须使用 Secret |
| `ARK_MODEL` | 需求抽取节点的豆包模型端点 |
| `ARK_BASE_URL` | 火山方舟 API 根路径 |

禁止把凭证写进 JSON、提示词、调试输出、截图或 Git 历史。本仓库仅提供空白 [`.env.example`](../.env.example)。

## 节点同步清单

| 节点 | 必须替换的内容 |
| --- | --- |
| `IntentExtract` | 日化需求 JSON Schema、豆包 Secret 和不猜测事实的 system prompt |
| `NormalizeFields` | 日化品类、功效、肤质和成分别名 |
| `RetrieveCatalog` | `sample_price`、敏感肌和 `formulated_without` 证据门槛 |
| `RuleRankV1` | `daily_rule_v1` 五分项公式 |
| `ReasonGenerate` | 样本价、历史热度和官方证据级别表达 |
| `FactGuard` | 禁止把商家标题功效词升级为配方或安全结论 |
| `NoResultFallback` | 区分样本价门槛与证据不足 |
| `BuildResponse` / `End` | 保留七字段统一契约，trace 增加 `excluded_by_evidence` |

## 原生验收顺序

1. 在 Coze 内取得编辑权限并备份当前画布；
2. 按等价配置逐节点替换文本和代码，不改 UI 与节点连线结构；
3. 在 Secret 管理器中配置 `ARK_API_KEY`，不把密钥发到聊天或文档；
4. 执行 A–D，核对需求抽取、单问题追问、三种状态、样本价命名与证据门槛；
5. 仅当原生运行确实完成后，更新平台状态文件和新的脱敏证据。
