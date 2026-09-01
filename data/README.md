# 日化历史商品样本

`products.json` 是 Coze MVP 使用的 15 条商品级小样本，不是原始表的镜像。

## 清洗口径

1. 以商品 ID 为主键，在完全重复行去重后取每个 ID 的最后一条观测；
2. 价格转为正数并命名为 `sample_price`；
3. 历史销量和评论转为非负数，原表缺失时保留 `null`；
4. 展示名称去掉促销日期、预售、专享和包邮等与产品身份无关的文案；
5. 商家标题中的功效词另存为 `merchant_title_claims`，不写成官方成分或安全性结论；
6. 不保留用户、订单、地址、支付、设备或聊天字段；
7. 原始表不提交到 GitHub。

`scripts/verify_source_subset.py` 可在本地按商品 ID 核对商店、样本价、历史销量与历史评论，但不会复制或输出原始表。

```bash
python3 scripts/verify_source_subset.py --source-csv "/path/to/history.csv"
```

## 证据层

| 状态 | 可以做什么 | 不可以做什么 |
| --- | --- | --- |
| `not_verified` | 基础品类、样本价和标题功效检索 | 敏感肌适用、配方安全或明确不含某成分的断言 |
| `official_current_reference` | 在产品身份匹配范围内，使用当前官方成分、不添加项和肤质声称 | 倒推历史配方必然相同，或保证个体不会过敏 |

官方引用为当前参考页面，并在每条记录内保存 `checked_at`、`identity_match`、`scope_note` 和 `sources`。最终使用时仍应核对手中产品包装成分表。

## 字段说明

| 字段 | 语义 |
| --- | --- |
| `id` | 历史源表的商品 ID，用于去重与可追溯核对 |
| `category` | MVP 的三个应用品类之一 |
| `shop` | 源表商店字段，不自动等同于生产商或商标权利人 |
| `name` | 去除促销噪声后的商品展示名 |
| `sample_price` | 离线快照金额，只用于 MVP 预算过滤 |
| `historical_sales_count` | 源表的历史销量字段，可为 `null` |
| `historical_comment_count` | 源表的历史评论字段，可为 `null` |
| `merchant_title_claims` | 从标题中保留的商家功效表述 |
| `verified_attributes` | 结构化官方参考属性与证据边界 |
