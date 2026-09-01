#!/usr/bin/env python3
"""Validate the public Coze MVP bundle with Python's standard library only.

The validator independently reconstructs hard filtering and rule_v1 ranking from
the catalog. It also validates the separately labelled Coze platform manifest;
it never turns a local result or a name-only change into a native-run claim.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
JSON_PATHS = {
    "workflow": Path("workflow/coze-workflow-equivalent.json"),
    "catalog": Path("data/products.json"),
    "examples": Path("examples/input-output.json"),
    "platform_runs": Path("examples/coze-platform-runs.json"),
}
EXPECTED_CATEGORIES = {"笔记本电脑", "智能手机", "头戴耳机"}
EXPECTED_STATUSES = {
    "A": "recommend",
    "B": "need_clarification",
    "C": "no_result",
    "D": "recommend",
}
OUTPUT_FIELDS = {
    "status",
    "parsed",
    "missing_fields",
    "question",
    "recommendations",
    "fallback",
    "trace",
}
TRACE_FIELDS = {
    "rule_version",
    "catalog_version",
    "retrieval_executed",
    "eligible_count",
    "returned_count",
    "excluded_by_category",
    "excluded_by_budget",
    "excluded_by_stock",
    "same_category_total_count",
    "same_category_in_stock_count",
    "clarified_field",
    "source_nodes",
}
TRACE_SOURCES = {
    "rule_version": "assets",
    "catalog_version": "assets",
    "retrieval_executed": "build_response",
    "eligible_count": "retrieve_catalog",
    "returned_count": "build_response",
    "excluded_by_category": "retrieve_catalog",
    "excluded_by_budget": "retrieve_catalog",
    "excluded_by_stock": "retrieve_catalog",
    "same_category_total_count": "retrieve_catalog",
    "same_category_in_stock_count": "retrieve_catalog",
    "clarified_field": "clarify_one_field",
}
WEIGHTS = {
    "need_match": 0.35,
    "budget_match": 0.25,
    "rating_normalized": 0.20,
    "sales_normalized": 0.10,
    "stock_availability": 0.10,
}


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
    """Load all JSON artifacts and report parse errors without traceback."""
    loaded: dict[str, Any] = {}
    errors: list[str] = []
    for name, relative_path in JSON_PATHS.items():
        path = base_dir / relative_path
        try:
            with path.open("r", encoding="utf-8") as handle:
                loaded[name] = json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            errors.append(f"{relative_path}: JSON 读取失败：{exc}")
    return loaded, errors


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _close(actual: Any, expected: float, tolerance: float = 0.011) -> bool:
    return _is_number(actual) and math.isclose(
        float(actual), expected, rel_tol=0.0, abs_tol=tolerance
    )


def _unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def _product_text(product: dict[str, Any]) -> list[str]:
    values: list[str] = []
    for field_name in ("use_cases", "features", "highlights"):
        values.extend(str(value) for value in product.get(field_name, []))
    return values


def _matched_needs(product: dict[str, Any], demand_tokens: list[str]) -> list[str]:
    evidence = _product_text(product)
    return [token for token in demand_tokens if any(token in item for item in evidence)]


def _hard_filter(
    products: list[dict[str, Any]], category: str, budget: float
) -> dict[str, list[dict[str, Any]]]:
    same_category = [product for product in products if product["category"] == category]
    return {
        "eligible": [
            product
            for product in same_category
            if product["price"] <= budget and product["stock"] > 0
        ],
        "excluded_by_category": [
            product for product in products if product["category"] != category
        ],
        "excluded_by_budget": [
            product for product in same_category if product["price"] > budget
        ],
        # Reasons are mutually exclusive: out-of-stock is counted only in budget.
        "excluded_by_stock": [
            product
            for product in same_category
            if product["price"] <= budget and product["stock"] <= 0
        ],
        "same_category": same_category,
        "same_category_in_stock": [
            product for product in same_category if product["stock"] > 0
        ],
    }


def _score_products(
    eligible: list[dict[str, Any]], budget: float, demand_tokens: list[str]
) -> list[dict[str, Any]]:
    if not eligible:
        return []
    max_sales = max(product["sales"] for product in eligible)
    scored: list[dict[str, Any]] = []
    for product in eligible:
        matches = _matched_needs(product, demand_tokens)
        need_match = len(matches) / len(demand_tokens) * 100 if demand_tokens else 0.0
        breakdown = {
            "need_match": need_match,
            "budget_match": product["price"] / budget * 100,
            "rating_normalized": min(max(product["rating"] - 4.0, 0.0), 1.0) * 100,
            "sales_normalized": product["sales"] / max_sales * 100,
            "stock_availability": min(product["stock"] / 20, 1.0) * 100,
        }
        score = sum(WEIGHTS[key] * breakdown[key] for key in WEIGHTS)
        scored.append(
            {
                "product": product,
                "matched_needs": matches,
                "breakdown": breakdown,
                "score": score,
            }
        )
    scored.sort(
        key=lambda item: (
            -item["score"],
            -item["product"]["rating"],
            item["product"]["price"],
            item["product"]["id"],
        )
    )
    return scored


def _validate_workflow(workflow: dict[str, Any], result: ValidationResult) -> None:
    output_schema = workflow.get("output_schema", {})
    result.check(
        set(output_schema.get("required", [])) == OUTPUT_FIELDS,
        "workflow: output_schema 必须要求七个统一顶层字段",
    )
    nodes = {
        node.get("id"): node
        for node in workflow.get("graph", {}).get("nodes", [])
        if isinstance(node, dict)
    }
    for node_id in ("retrieve_catalog", "no_result_fallback", "build_response", "end"):
        result.check(node_id in nodes, f"workflow: 缺少节点 {node_id}")
    if "build_response" not in nodes or "end" not in nodes:
        return

    build = nodes["build_response"]
    end = nodes["end"]
    result.check(
        OUTPUT_FIELDS.issubset(set(build.get("outputs", []))),
        "workflow: BuildResponse 未完整产出七个顶层字段",
    )
    branch_mappings = build.get("config", {}).get("branch_mappings", {})
    result.check(
        set(branch_mappings) == {"need_clarification", "recommend", "no_result"},
        "workflow: BuildResponse 必须覆盖追问、推荐、无结果三分支",
    )
    for branch, expected_status in (
        ("need_clarification", "need_clarification"),
        ("recommend", "recommend"),
        ("no_result", "no_result"),
    ):
        mapping = branch_mappings.get(branch, {})
        result.check(
            mapping.get("status") == expected_status,
            f"workflow: {branch} 分支 status 映射错误",
        )
        result.check(
            OUTPUT_FIELDS <= set(mapping),
            f"workflow: {branch} 分支缺少统一响应字段映射",
        )

    result.check(
        set(end.get("outputs", [])) == OUTPUT_FIELDS,
        "workflow: End 必须显式输出七个字段",
    )
    field_mapping = end.get("config", {}).get("field_mapping", {})
    result.check(
        set(field_mapping) == OUTPUT_FIELDS,
        "workflow: End field_mapping 必须逐项映射七个字段",
    )
    result.check(
        all(field_mapping.get(key) == f"build_response.{key}" for key in OUTPUT_FIELDS),
        "workflow: End 字段必须全部来自 BuildResponse",
    )

    edges = {
        (edge.get("from"), edge.get("to"))
        for edge in workflow.get("graph", {}).get("edges", [])
        if isinstance(edge, dict)
    }
    for upstream in ("clarify_one_field", "fact_guard", "no_result_fallback"):
        result.check(
            (upstream, "build_response") in edges,
            f"workflow: {upstream} 未汇入 BuildResponse",
        )
    result.check(
        ("build_response", "end") in edges,
        "workflow: BuildResponse 未连接 End",
    )
    fallback_logic = " ".join(
        nodes.get("no_result_fallback", {}).get("config", {}).get("logic", [])
    )
    result.check(
        "no_stock" in fallback_logic and "same_category_in_stock_count == 0" in fallback_logic,
        "workflow: 无结果节点缺少同品类全部无库存的 no_stock 兜底",
    )
    source_nodes = build.get("config", {}).get("trace_mapping", {}).get("source_nodes", {})
    result.check(
        source_nodes == TRACE_SOURCES,
        "workflow: trace.source_nodes 与约定节点来源不一致",
    )
    formula = (
        nodes.get("rule_rank_v1", {}).get("config", {}).get("formula", "")
    )
    result.check(
        formula
        == "0.35*need_match + 0.25*budget_match + 0.20*rating_normalized + 0.10*sales_normalized + 0.10*stock_availability",
        "workflow: rule_v1 分数公式与公开规格不一致",
    )


def _validate_catalog(catalog: dict[str, Any], result: ValidationResult) -> list[dict[str, Any]]:
    products = catalog.get("products", [])
    metadata = catalog.get("dataset", {})
    result.check(isinstance(products, list), "catalog: products 必须是数组")
    if not isinstance(products, list):
        return []
    result.check(len(products) == 15, f"catalog: 应有 15 条商品，实际 {len(products)} 条")
    result.check(metadata.get("product_count") == 15, "catalog: product_count 必须为 15")
    result.check(metadata.get("synthetic") is True, "catalog: 必须明确 synthetic=true")
    ids = [product.get("id") for product in products if isinstance(product, dict)]
    result.check(len(ids) == len(set(ids)), "catalog: 商品 ID 必须唯一")
    counts = Counter(product.get("category") for product in products if isinstance(product, dict))
    result.check(set(counts) == EXPECTED_CATEGORIES, "catalog: 品类集合不正确")
    for category in sorted(EXPECTED_CATEGORIES):
        result.check(counts[category] == 5, f"catalog: {category} 应有 5 条商品")
    required = {
        "id",
        "category",
        "brand",
        "name",
        "price",
        "rating",
        "sales",
        "stock",
        "use_cases",
        "features",
        "highlights",
        "limitations",
    }
    for product in products:
        product_id = product.get("id", "<unknown>")
        result.check(required <= set(product), f"catalog: {product_id} 字段不完整")
        result.check(
            _is_number(product.get("price")) and product.get("price", 0) > 0,
            f"catalog: {product_id} price 必须为正数",
        )
        result.check(
            isinstance(product.get("stock"), int) and product.get("stock", -1) >= 0,
            f"catalog: {product_id} stock 必须为非负整数",
        )
    return products


def _ids(products: Iterable[dict[str, Any]]) -> list[str]:
    return [product["id"] for product in products]


def _validate_trace(
    case_id: str,
    trace: dict[str, Any],
    filters: dict[str, list[dict[str, Any]]] | None,
    returned_count: int,
    result: ValidationResult,
) -> None:
    result.check(TRACE_FIELDS <= set(trace), f"case {case_id}: trace 字段不完整")
    result.check(
        trace.get("source_nodes") == TRACE_SOURCES,
        f"case {case_id}: trace.source_nodes 不正确",
    )
    if filters is None:
        result.check(trace.get("retrieval_executed") is False, f"case {case_id}: 不应执行检索")
        result.check(trace.get("eligible_count") == 0, f"case {case_id}: 默认候选数应为 0")
        for key in ("excluded_by_category", "excluded_by_budget", "excluded_by_stock"):
            result.check(trace.get(key) == [], f"case {case_id}: {key} 默认值应为 []")
        result.check(
            trace.get("same_category_total_count") == 0
            and trace.get("same_category_in_stock_count") == 0,
            f"case {case_id}: 未检索时同品类计数应为 0",
        )
    else:
        result.check(trace.get("retrieval_executed") is True, f"case {case_id}: 应执行检索")
        expected = {
            "eligible_count": len(filters["eligible"]),
            "excluded_by_category": _ids(filters["excluded_by_category"]),
            "excluded_by_budget": _ids(filters["excluded_by_budget"]),
            "excluded_by_stock": _ids(filters["excluded_by_stock"]),
            "same_category_total_count": len(filters["same_category"]),
            "same_category_in_stock_count": len(filters["same_category_in_stock"]),
        }
        for key, value in expected.items():
            result.check(trace.get(key) == value, f"case {case_id}: trace.{key} 与硬过滤重算不一致")
    result.check(
        trace.get("returned_count") == returned_count,
        f"case {case_id}: returned_count 与推荐数组长度不一致",
    )


def _validate_examples(
    examples: dict[str, Any], products: list[dict[str, Any]], result: ValidationResult
) -> None:
    cases = examples.get("cases", [])
    result.check(isinstance(cases, list), "examples: cases 必须是数组")
    if not isinstance(cases, list):
        return
    by_id = {case.get("case_id"): case for case in cases if isinstance(case, dict)}
    result.check(set(by_id) == set(EXPECTED_STATUSES), "examples: 必须且只能包含 A、B、C、D 四个用例")
    products_by_id = {product["id"]: product for product in products}

    for case_id, expected_status in EXPECTED_STATUSES.items():
        case = by_id.get(case_id)
        if case is None:
            continue
        output = case.get("output", {})
        result.check(OUTPUT_FIELDS <= set(output), f"case {case_id}: 统一输出字段不完整")
        result.check(output.get("status") == expected_status, f"case {case_id}: status 应为 {expected_status}")
        recommendations = output.get("recommendations", [])
        result.check(isinstance(recommendations, list), f"case {case_id}: recommendations 必须是数组")
        if not isinstance(recommendations, list):
            recommendations = []
        trace = output.get("trace", {})

        if expected_status == "need_clarification":
            result.check(bool(output.get("missing_fields")), f"case {case_id}: 必须返回缺失字段")
            result.check(isinstance(output.get("question"), str) and bool(output["question"]), f"case {case_id}: 必须只返回一个追问文本")
            result.check(recommendations == [], f"case {case_id}: 追问分支不得推荐")
            result.check(output.get("fallback") is None, f"case {case_id}: 追问分支 fallback 应为 null")
            _validate_trace(case_id, trace, None, 0, result)
            result.check(trace.get("clarified_field") == "budget", "case B: 本轮应优先追问 budget")
            continue

        parsed = output.get("parsed", {})
        category = parsed.get("category")
        budget = parsed.get("budget")
        result.check(category in EXPECTED_CATEGORIES, f"case {case_id}: category 无效")
        result.check(_is_number(budget) and budget > 0, f"case {case_id}: budget 必须为正数")
        if category not in EXPECTED_CATEGORIES or not _is_number(budget) or budget <= 0:
            continue
        filters = _hard_filter(products, category, float(budget))
        _validate_trace(case_id, trace, filters, len(recommendations), result)
        result.check(trace.get("clarified_field") is None, f"case {case_id}: 非追问分支 clarified_field 应为 null")

        recommendation_ids = [item.get("id") for item in recommendations]
        eligible_ids = set(_ids(filters["eligible"]))
        result.check(
            len(recommendation_ids) == len(set(recommendation_ids)),
            f"case {case_id}: 推荐 ID 不得重复",
        )
        result.check(
            set(recommendation_ids) <= eligible_ids,
            f"case {case_id}: 推荐中存在未通过品类/预算/库存硬过滤的商品",
        )

        if expected_status == "no_result":
            result.check(not filters["eligible"], f"case {case_id}: no_result 但硬过滤仍有候选")
            result.check(recommendations == [], f"case {case_id}: no_result 推荐数组必须为空")
            fallback = output.get("fallback") or {}
            in_stock = filters["same_category_in_stock"]
            if in_stock:
                price_floor = min(product["price"] for product in in_stock)
                result.check(fallback.get("available_price_floor") == price_floor, f"case {case_id}: 最低可用价错误")
                result.check(
                    fallback.get("required_budget_increase") == price_floor - budget,
                    f"case {case_id}: 预算提升差额错误",
                )
                result.check(fallback.get("type") == "budget_below_floor", f"case {case_id}: fallback type 错误")
            continue

        result.check(bool(filters["eligible"]), f"case {case_id}: recommend 但没有硬过滤候选")
        result.check(output.get("fallback") is None, f"case {case_id}: recommend 分支 fallback 应为 null")
        result.check(output.get("question") is None, f"case {case_id}: recommend 分支 question 应为 null")
        demand_tokens = _unique(parsed.get("use_case", []) + parsed.get("priority", []))
        scored = _score_products(filters["eligible"], float(budget), demand_tokens)
        expected_top = scored[:3]
        result.check(
            recommendation_ids == [item["product"]["id"] for item in expected_top],
            f"case {case_id}: Top 3 顺序与 rule_v1 重算不一致",
        )

        for rank, (recommendation, expected) in enumerate(zip(recommendations, expected_top), start=1):
            product_id = recommendation.get("id")
            product = products_by_id.get(product_id, {})
            result.check(recommendation.get("rank") == rank, f"case {case_id}/{product_id}: rank 错误")
            result.check(
                recommendation.get("price") == product.get("price"),
                f"case {case_id}/{product_id}: price 与商品库不一致",
            )
            result.check(
                recommendation.get("budget_gap") == budget - product.get("price", 0),
                f"case {case_id}/{product_id}: budget_gap 必须等于 budget-price",
            )
            result.check(
                recommendation.get("matched_needs") == expected["matched_needs"],
                f"case {case_id}/{product_id}: matched_needs 重算不一致",
            )
            breakdown = recommendation.get("score_breakdown", {})
            for component, expected_value in expected["breakdown"].items():
                result.check(
                    _close(breakdown.get(component), round(expected_value, 2)),
                    f"case {case_id}/{product_id}: {component} 分项错误",
                )
            result.check(
                _close(recommendation.get("score"), round(expected["score"], 2)),
                f"case {case_id}/{product_id}: 总分不符合 rule_v1 公式",
            )
            tradeoff = str(recommendation.get("tradeoff", "")).rstrip("。")
            result.check(
                any(tradeoff == limitation.rstrip("。") for limitation in product.get("limitations", [])),
                f"case {case_id}/{product_id}: tradeoff 不来自 limitations",
            )
            why_fit = str(recommendation.get("why_fit", ""))
            result.check(
                "预算余量" not in why_fit and "预算差" not in why_fit,
                f"case {case_id}/{product_id}: why_fit 混入预算余量，应只放在 budget_relation",
            )


def _validate_platform_runs(
    platform_runs: dict[str, Any], result: ValidationResult, base_dir: Path = ROOT
) -> None:
    """Validate truthfulness boundaries and evidence links in the platform manifest."""
    result.check(
        platform_runs.get("project_id") == "7679015075092578350",
        "platform_runs: project_id 不正确",
    )
    result.check(
        platform_runs.get("publication_status") == "未部署",
        "platform_runs: 必须保持未部署",
    )
    result.check(
        platform_runs.get("native_run_version") == "v0.2.0",
        "platform_runs: 原生运行版本必须明确为 v0.2.0",
    )
    summary = platform_runs.get("native_run_summary", {})
    cases = summary.get("cases", [])
    by_id = {case.get("id"): case for case in cases if isinstance(case, dict)}
    result.check(summary.get("passed") == 4 and summary.get("total") == 4, "platform_runs: 原生运行应记录 4/4")
    result.check(set(by_id) == set(EXPECTED_STATUSES), "platform_runs: 必须且只能包含 A-D")
    for case_id, expected_status in EXPECTED_STATUSES.items():
        case = by_id.get(case_id, {})
        result.check(case.get("status") == expected_status, f"platform_runs/{case_id}: status 错误")
        evidence = case.get("evidence")
        result.check(isinstance(evidence, str) and bool(evidence), f"platform_runs/{case_id}: 缺少证据路径")
        if isinstance(evidence, str):
            evidence_path = (base_dir / "examples" / evidence).resolve()
            result.check(evidence_path.is_file(), f"platform_runs/{case_id}: 证据文件不存在")

    change = platform_runs.get("v0_2_1_change", {})
    result.check(platform_runs.get("current_project_version") == "v0.2.1", "platform_runs: 当前版本应为 v0.2.1")
    result.check(change.get("static_name_audit") == "passed", "platform_runs: v0.2.1 名称扫描未通过")
    result.check(
        change.get("native_rerun") == "not_completed_due_to_platform_resource_quota",
        "platform_runs: 不得把 v0.2.1 标为已完成原生复跑",
    )
    name_map = change.get("name_map", {})
    expected_ids = {f"NB{i:03d}" for i in range(1, 6)} | {f"PH{i:03d}" for i in range(1, 6)} | {f"EP{i:03d}" for i in range(1, 6)}
    result.check(set(name_map) == expected_ids, "platform_runs: v0.2.1 名称映射必须覆盖 15 个商品 ID")
    forbidden = (
        "Apple", "华为", "小米", "OPPO", "联想", "ThinkPad", "Redmi", "ROG",
        "Sony", "JBL", "Galaxy", "FindX", "SwiftBook", "ProTrek", "BookPro",
        "AirBook", "MatePro", "AirPods", "FreeBuds", "PhantomAir", "PinePhone",
    )
    for product_id, name in name_map.items():
        result.check(
            isinstance(name, str) and not any(token.lower() in name.lower() for token in forbidden),
            f"platform_runs/{product_id}: v0.2.1 名称仍含真实或近似系列词",
        )


def validate_loaded(
    workflow: dict[str, Any],
    catalog: dict[str, Any],
    examples: dict[str, Any],
    platform_runs: dict[str, Any] | None = None,
    base_dir: Path = ROOT,
) -> ValidationResult:
    """Validate already-loaded objects; useful for unit tests and negative fixtures."""
    result = ValidationResult()
    _validate_workflow(workflow, result)
    products = _validate_catalog(catalog, result)
    _validate_examples(examples, products, result)
    if platform_runs is not None:
        _validate_platform_runs(platform_runs, result, base_dir)
    return result


def validate_bundle(base_dir: Path = ROOT) -> ValidationResult:
    loaded, load_errors = load_bundle(base_dir)
    if load_errors:
        return ValidationResult(errors=load_errors, checks=3)
    return validate_loaded(
        loaded["workflow"],
        loaded["catalog"],
        loaded["examples"],
        loaded["platform_runs"],
        base_dir,
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="验证智选 Agent Coze MVP 公开交付包")
    parser.add_argument(
        "--base-dir",
        type=Path,
        default=ROOT,
        help="仓库根目录（默认自动使用脚本上一级目录）",
    )
    args = parser.parse_args(argv)
    result = validate_bundle(args.base_dir.resolve())
    if result.ok:
        print(f"PASS: {result.checks} 项断言全部通过。")
        print("已验证：4 份 JSON、15 条商品（每品类 5 条）、A-D 本地用例、硬过滤、rule_v1、关键 trace、平台证据路径与 v0.2.1 名称边界。")
        print("说明：本地复算、v0.2.0 原生运行记录与 v0.2.1 名称修正保持分层标注。")
        return 0
    print(f"FAIL: {len(result.errors)} 项失败（共执行 {result.checks} 项断言）。", file=sys.stderr)
    for error in result.errors:
        print(f"- {error}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
