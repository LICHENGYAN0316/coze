#!/usr/bin/env python3
"""验证日化历史数据 Coze MVP 公开交付包。"""

from __future__ import annotations

import argparse
import json
import math
import re
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from recommendation_core import RULE_VERSION, TRACE_SOURCES, WEIGHTS, build_output, hard_filter


ROOT = Path(__file__).resolve().parents[1]
JSON_PATHS = {
    "workflow": Path("workflow/coze-workflow-equivalent.json"),
    "catalog": Path("data/products.json"),
    "attributes": Path("data/verified-product-attributes.json"),
    "examples": Path("examples/input-output.json"),
    "platform_runs": Path("examples/coze-platform-runs.json"),
}
EXPECTED_CATEGORIES = {"补水喷雾", "保湿乳霜", "清洁定妆"}
EXPECTED_STATUSES = {"A": "recommend", "B": "need_clarification", "C": "no_result", "D": "recommend"}
OUTPUT_FIELDS = {"status", "parsed", "missing_fields", "question", "recommendations", "fallback", "trace"}
TRACE_FIELDS = {
    "rule_version", "catalog_version", "retrieval_executed", "eligible_count", "returned_count",
    "excluded_by_category", "excluded_by_budget", "excluded_by_evidence",
    "same_category_total_count", "clarified_field", "source_nodes",
}
OFFICIAL_PRODUCT_IDS = {"A520711852230", "A20332739108", "A18297865077", "A15486609514"}


@dataclass
class ValidationResult:
    errors: list[str] = field(default_factory=list)
    checks: int = 0

    def check(self, condition: bool, message: str) -> None:
        self.checks += 1
        if not condition:
            self.errors.append(message)

    @property
    def ok(self) -> bool:
        return not self.errors


def load_bundle(base_dir: Path = ROOT) -> tuple[dict[str, Any], list[str]]:
    loaded: dict[str, Any] = {}
    errors: list[str] = []
    for name, relative in JSON_PATHS.items():
        try:
            loaded[name] = json.loads((base_dir / relative).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{relative}: JSON 读取失败：{exc}")
    return loaded, errors


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(float(value))


def _validate_workflow(workflow: dict[str, Any], result: ValidationResult) -> None:
    result.check(workflow.get("native_export") is False, "workflow: 等价配置不得伪装成 Coze 原生导出")
    project = workflow.get("project", {})
    result.check(project.get("publication_status") == "未部署", "workflow: 发布状态必须保持未部署")
    result.check("日化" in str(project.get("name")), "workflow: 项目名称未切换为日化")
    doubao = workflow.get("doubao", {})
    result.check(doubao.get("secret_ref") == "ARK_API_KEY", "workflow: 豆包密钥必须使用 ARK_API_KEY Secret 引用")
    result.check(doubao.get("integration_state") == "configuration_ready_secret_not_provisioned", "workflow: 不得在未配密钥时声称已完成在线调用")
    result.check(workflow.get("assets", {}).get("price_field") == "sample_price", "workflow: 价格字段必须是 sample_price")
    required = set(workflow.get("output_schema", {}).get("required", []))
    result.check(required == OUTPUT_FIELDS, "workflow: 七个统一顶层字段契约已改变")
    nodes = {node.get("id"): node for node in workflow.get("graph", {}).get("nodes", []) if isinstance(node, dict)}
    expected_nodes = {
        "start", "intent_extract", "normalize_fields", "required_fields", "clarify_one_field",
        "retrieve_catalog", "has_candidates", "rule_rank_v1", "reason_generate", "fact_guard",
        "no_result_fallback", "build_response", "end",
    }
    result.check(set(nodes) == expected_nodes, "workflow: 原交互节点结构已变更")
    intent = nodes.get("intent_extract", {}).get("config", {})
    result.check(intent.get("credential") == {"type": "secret_ref", "name": "ARK_API_KEY"}, "workflow: IntentExtract 未使用 Coze Secret")
    formula = nodes.get("rule_rank_v1", {}).get("config", {}).get("formula")
    expected_formula = "0.40*need_match + 0.20*budget_match + 0.15*historical_sales_normalized + 0.10*historical_comments_normalized + 0.15*evidence_quality"
    result.check(formula == expected_formula, "workflow: daily_rule_v1 公开公式不一致")
    result.check(math.isclose(sum(WEIGHTS.values()), 1.0), "workflow: 排序权重之和不为 1")
    build = nodes.get("build_response", {})
    result.check(OUTPUT_FIELDS <= set(build.get("outputs", [])), "workflow: BuildResponse 统一输出不完整")
    branches = build.get("config", {}).get("branch_mappings", {})
    result.check(set(branches) == {"need_clarification", "recommend", "no_result"}, "workflow: 三种交互分支已改变")
    for mapping in branches.values():
        result.check(OUTPUT_FIELDS <= set(mapping), "workflow: 分支未输出统一字段")
    result.check(build.get("config", {}).get("trace_mapping", {}).get("source_nodes") == TRACE_SOURCES, "workflow: trace 来源映射不一致")


def _validate_catalog(catalog: dict[str, Any], result: ValidationResult) -> list[dict[str, Any]]:
    metadata = catalog.get("dataset", {})
    products = catalog.get("products", [])
    result.check(metadata.get("historical") is True, "catalog: 必须明确 historical=true")
    result.check(metadata.get("price_field") == "sample_price" and metadata.get("price_label") == "样本价", "catalog: 样本价语义未锁定")
    result.check(metadata.get("product_count") == 15 and isinstance(products, list) and len(products) == 15, "catalog: 必须包含 15 条日化商品样本")
    if not isinstance(products, list):
        return []
    ids = [product.get("id") for product in products if isinstance(product, dict)]
    result.check(len(ids) == len(set(ids)), "catalog: 商品 ID 不唯一")
    counts = Counter(product.get("category") for product in products if isinstance(product, dict))
    result.check(set(counts) == EXPECTED_CATEGORIES, "catalog: 日化品类集合不正确")
    for category in EXPECTED_CATEGORIES:
        result.check(counts[category] == 5, f"catalog: {category} 应有 5 条")
    required = {
        "id", "category", "shop", "name", "sample_price", "historical_sales_count",
        "historical_comment_count", "use_cases", "merchant_title_claims", "highlights",
        "limitations", "verified_attributes",
    }
    official_ids: set[str] = set()
    for product in products:
        product_id = str(product.get("id", "<unknown>"))
        result.check(required <= set(product), f"catalog/{product_id}: 字段不完整")
        result.check("price" not in product, f"catalog/{product_id}: 不得使用无时间语义的 price 字段")
        result.check(_is_number(product.get("sample_price")) and product["sample_price"] > 0, f"catalog/{product_id}: sample_price 必须为正数")
        for field_name in ("historical_sales_count", "historical_comment_count"):
            value = product.get(field_name)
            result.check(value is None or (_is_number(value) and value >= 0), f"catalog/{product_id}: {field_name} 必须为非负数或 null")
        verified = product.get("verified_attributes", {})
        status = verified.get("status")
        result.check(status in {"official_current_reference", "not_verified"}, f"catalog/{product_id}: 证据状态无效")
        if status == "official_current_reference":
            official_ids.add(product_id)
            result.check(verified.get("identity_match") in {"exact_product_and_size", "product_line_match"}, f"catalog/{product_id}: 缺少产品身份匹配类型")
            result.check(bool(verified.get("sources")) and all(str(url).startswith("https://") for url in verified["sources"]), f"catalog/{product_id}: 缺少官方 HTTPS 来源")
            result.check(re.fullmatch(r"\d{4}-\d{2}-\d{2}", str(verified.get("checked_at"))) is not None, f"catalog/{product_id}: checked_at 无效")
            result.check("历史" in str(verified.get("scope_note")) or "当前" in str(verified.get("scope_note")), f"catalog/{product_id}: 缺少配方版本边界")
        else:
            result.check(verified.get("sources") == [] and verified.get("sensitive_skin_claim") is None, f"catalog/{product_id}: 未核实商品不得带安全性来源或断言")
    result.check(official_ids == OFFICIAL_PRODUCT_IDS, "catalog: 官方核实商品集合与结构化属性表不一致")
    return products


def _validate_attribute_table(attributes: dict[str, Any], catalog: dict[str, Any], result: ValidationResult) -> None:
    rows = attributes.get("products", [])
    result.check(attributes.get("record_count") == 4 and isinstance(rows, list) and len(rows) == 4, "attributes: 必须包含 4 条官方核实属性")
    if not isinstance(rows, list):
        return
    by_id = {row.get("id"): row for row in rows if isinstance(row, dict)}
    result.check(set(by_id) == OFFICIAL_PRODUCT_IDS, "attributes: 商品 ID 集合不正确")
    products_by_id = {product.get("id"): product for product in catalog.get("products", []) if isinstance(product, dict)}
    for product_id in OFFICIAL_PRODUCT_IDS:
        row = by_id.get(product_id, {})
        product = products_by_id.get(product_id, {})
        verified = product.get("verified_attributes", {})
        result.check(row.get("name") == product.get("name"), f"attributes/{product_id}: name 与商品库不一致")
        for key in (
            "identity_match", "ingredient_list_complete", "ingredients", "key_ingredients",
            "formulated_without", "sensitive_skin_claim", "official_claims", "scope_note", "sources",
        ):
            result.check(row.get(key) == verified.get(key), f"attributes/{product_id}: {key} 与商品库嵌入属性不一致")
        result.check(verified.get("checked_at") == attributes.get("checked_at"), f"attributes/{product_id}: 核查日期不一致")


def _validate_examples(examples: dict[str, Any], catalog: dict[str, Any], result: ValidationResult) -> None:
    result.check(examples.get("coze_native_execution") is False, "examples: 离线示例不得标成 Coze 原生执行")
    result.check(examples.get("catalog_version") == catalog.get("dataset", {}).get("version"), "examples: catalog_version 不一致")
    result.check(examples.get("rule_version") == RULE_VERSION, "examples: rule_version 不一致")
    cases = examples.get("cases", [])
    by_id = {case.get("case_id"): case for case in cases if isinstance(case, dict)}
    result.check(set(by_id) == set(EXPECTED_STATUSES), "examples: 必须且只能包含 A-D")
    for case_id, expected_status in EXPECTED_STATUSES.items():
        case = by_id.get(case_id)
        if case is None:
            continue
        output = case.get("output", {})
        result.check(set(output) == OUTPUT_FIELDS, f"case {case_id}: 七个顶层字段不完整")
        result.check(output.get("status") == expected_status, f"case {case_id}: status 错误")
        trace = output.get("trace", {})
        result.check(TRACE_FIELDS <= set(trace), f"case {case_id}: trace 字段不完整")
        result.check(trace.get("source_nodes") == TRACE_SOURCES, f"case {case_id}: trace.source_nodes 错误")
        expected = build_output(catalog, output.get("parsed", {}), list(output.get("missing_fields", [])))
        result.check(output == expected, f"case {case_id}: 输出与 daily_rule_v1 重算结果不一致")
        for recommendation in output.get("recommendations", []):
            result.check("price" not in recommendation and recommendation.get("sample_price_label") == "样本价", f"case {case_id}: 推荐未使用样本价语义")
        if output.get("parsed", {}).get("requires_verified_evidence") and output.get("status") == "recommend":
            filters = hard_filter(catalog["products"], output["parsed"])
            eligible_ids = {product["id"] for product in filters["eligible"]}
            rec_ids = {recommendation["id"] for recommendation in output["recommendations"]}
            result.check(rec_ids <= eligible_ids, f"case {case_id}: 敏感肌/避雷推荐绕过官方证据门槛")
            result.check(all(recommendation.get("evidence_level") == "official_current_reference" for recommendation in output["recommendations"]), f"case {case_id}: 严格证据推荐混入未核实商品")


def _validate_platform_runs(platform_runs: dict[str, Any], result: ValidationResult) -> None:
    result.check(platform_runs.get("project_id") == "7679015075092578350", "platform_runs: project_id 不正确")
    result.check(platform_runs.get("publication_status") == "未部署", "platform_runs: 必须保持未部署")
    migration = platform_runs.get("daily_migration", {})
    result.check(migration.get("native_canvas_updated") is False, "platform_runs: 未操作 Coze 画布时不得声称已同步")
    result.check(migration.get("native_run") == "not_performed", "platform_runs: 未执行时不得声称日化版原生运行通过")
    result.check(migration.get("secret_provisioned") is False, "platform_runs: 未配置密钥时不得声称已接通豆包")
    result.check(platform_runs.get("evidence") == [], "platform_runs: 日化版未实测时不应挂载旧截图")


def _validate_secret_boundary(base_dir: Path, result: ValidationResult) -> None:
    env_path = base_dir / ".env.example"
    try:
        env_text = env_path.read_text(encoding="utf-8")
    except OSError as exc:
        result.check(False, f"secret: .env.example 读取失败：{exc}")
        return
    result.check(re.search(r"(?m)^ARK_API_KEY=$", env_text) is not None, "secret: .env.example 必须保留空的 ARK_API_KEY 占位")
    result.check("doubao-seed" in env_text, "secret: .env.example 缺少可替换的豆包模型占位")
    for path in base_dir.rglob("*"):
        if not path.is_file() or ".git" in path.parts or path.suffix.lower() in {".png", ".jpg", ".jpeg", ".gif"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        result.check(re.search(r"(?i)(?:api[_-]?key|authorization)\s*[:=]\s*['\"]?[A-Za-z0-9_-]{24,}", text) is None, f"secret: {path.relative_to(base_dir)} 疑似包含真实密钥")


def validate_loaded(
    workflow: dict[str, Any],
    catalog: dict[str, Any],
    examples: dict[str, Any],
    platform_runs: dict[str, Any] | None = None,
    base_dir: Path = ROOT,
    attributes: dict[str, Any] | None = None,
) -> ValidationResult:
    result = ValidationResult()
    _validate_workflow(workflow, result)
    _validate_catalog(catalog, result)
    if attributes is None:
        try:
            attributes = json.loads((base_dir / JSON_PATHS["attributes"]).read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            result.check(False, f"attributes: 读取失败：{exc}")
    if attributes is not None:
        _validate_attribute_table(attributes, catalog, result)
    _validate_examples(examples, catalog, result)
    if platform_runs is not None:
        _validate_platform_runs(platform_runs, result)
    _validate_secret_boundary(base_dir, result)
    return result


def validate_bundle(base_dir: Path = ROOT) -> ValidationResult:
    loaded, errors = load_bundle(base_dir)
    if errors:
        return ValidationResult(errors=errors, checks=len(JSON_PATHS))
    return validate_loaded(
        loaded["workflow"], loaded["catalog"], loaded["examples"], loaded["platform_runs"],
        base_dir, attributes=loaded["attributes"],
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证智选 Agent 日化历史数据 Coze MVP 交付包")
    parser.add_argument("--base-dir", type=Path, default=ROOT)
    args = parser.parse_args(argv)
    result = validate_bundle(args.base_dir.resolve())
    if result.ok:
        print(f"PASS: {result.checks} 项断言全部通过。")
        print("已验证：15 条日化历史商品样本、样本价语义、A-D 交互、敏感肌/成分证据门槛、daily_rule_v1、豆包 Secret 边界。")
        print("说明：Coze 日化画布与豆包在线调用仍标记为尚未执行。")
        return 0
    print(f"FAIL: {len(result.errors)} 项失败（共执行 {result.checks} 项断言）。")
    for error in result.errors:
        print(f"- {error}")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
