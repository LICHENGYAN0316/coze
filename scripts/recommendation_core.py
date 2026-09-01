#!/usr/bin/env python3
"""日化历史样本的可复算检索与排序核心。

豆包只负责把自然语言转为 parsed 字段；商品过滤、样本价比较、
证据门槛、排序和事实字段全部由确定性代码处理。
"""

from __future__ import annotations

from typing import Any, Iterable


RULE_VERSION = "daily_rule_v1"
WEIGHTS = {
    "need_match": 0.40,
    "budget_match": 0.20,
    "historical_sales_normalized": 0.15,
    "historical_comments_normalized": 0.10,
    "evidence_quality": 0.15,
}

TRACE_SOURCES = {
    "rule_version": "assets",
    "catalog_version": "assets",
    "retrieval_executed": "build_response",
    "eligible_count": "retrieve_catalog",
    "returned_count": "build_response",
    "excluded_by_category": "retrieve_catalog",
    "excluded_by_budget": "retrieve_catalog",
    "excluded_by_evidence": "retrieve_catalog",
    "same_category_total_count": "retrieve_catalog",
    "clarified_field": "clarify_one_field",
}


def unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value and value not in result:
            result.append(value)
    return result


def evidence_profile(product: dict[str, Any]) -> dict[str, Any]:
    value = product.get("verified_attributes")
    return value if isinstance(value, dict) else {}


def product_evidence_text(product: dict[str, Any]) -> list[str]:
    verified = evidence_profile(product)
    values: list[str] = []
    for key in ("use_cases", "merchant_title_claims", "highlights"):
        values.extend(str(item) for item in product.get(key, []))
    for key in ("official_claims", "key_ingredients"):
        values.extend(str(item) for item in verified.get(key, []))
    return values


def matched_needs(product: dict[str, Any], demand_tokens: list[str]) -> list[str]:
    evidence = product_evidence_text(product)
    return [token for token in demand_tokens if any(token in item for item in evidence)]


def passes_evidence_policy(product: dict[str, Any], parsed: dict[str, Any]) -> bool:
    verified = evidence_profile(product)
    sensitive = parsed.get("skin_type") == "敏感肌"
    avoid = unique(str(value) for value in parsed.get("avoid_ingredients", []))
    if not sensitive and not avoid and not parsed.get("requires_verified_evidence"):
        return True
    if verified.get("status") != "official_current_reference":
        return False
    if sensitive and verified.get("sensitive_skin_claim") is not True:
        return False
    formulated_without = set(str(value) for value in verified.get("formulated_without", []))
    return all(value in formulated_without for value in avoid)


def hard_filter(products: list[dict[str, Any]], parsed: dict[str, Any]) -> dict[str, list[dict[str, Any]]]:
    category = parsed["category"]
    budget = float(parsed["budget"])
    same_category = [product for product in products if product["category"] == category]
    within_budget = [product for product in same_category if product["sample_price"] <= budget]
    return {
        "eligible": [product for product in within_budget if passes_evidence_policy(product, parsed)],
        "excluded_by_category": [product for product in products if product["category"] != category],
        "excluded_by_budget": [product for product in same_category if product["sample_price"] > budget],
        "excluded_by_evidence": [product for product in within_budget if not passes_evidence_policy(product, parsed)],
        "same_category": same_category,
        "within_budget": within_budget,
    }


def score_products(
    eligible: list[dict[str, Any]], budget: float, demand_tokens: list[str]
) -> list[dict[str, Any]]:
    if not eligible:
        return []
    max_sales = max(float(product.get("historical_sales_count") or 0) for product in eligible) or 1.0
    max_comments = max(float(product.get("historical_comment_count") or 0) for product in eligible) or 1.0
    scored: list[dict[str, Any]] = []
    for product in eligible:
        matches = matched_needs(product, demand_tokens)
        verified = evidence_profile(product)
        breakdown = {
            "need_match": len(matches) / len(demand_tokens) * 100 if demand_tokens else 0.0,
            "budget_match": float(product["sample_price"]) / budget * 100,
            "historical_sales_normalized": float(product.get("historical_sales_count") or 0) / max_sales * 100,
            "historical_comments_normalized": float(product.get("historical_comment_count") or 0) / max_comments * 100,
            "evidence_quality": 100.0 if verified.get("status") == "official_current_reference" else 25.0,
        }
        score = sum(WEIGHTS[key] * breakdown[key] for key in WEIGHTS)
        scored.append({"product": product, "matched_needs": matches, "breakdown": breakdown, "score": score})
    scored.sort(
        key=lambda item: (
            -item["score"],
            -float(item["product"].get("historical_sales_count") or 0),
            float(item["product"]["sample_price"]),
            item["product"]["id"],
        )
    )
    return scored


def empty_trace(catalog_version: str, clarified_field: str | None) -> dict[str, Any]:
    return {
        "rule_version": RULE_VERSION,
        "catalog_version": catalog_version,
        "retrieval_executed": False,
        "eligible_count": 0,
        "returned_count": 0,
        "excluded_by_category": [],
        "excluded_by_budget": [],
        "excluded_by_evidence": [],
        "same_category_total_count": 0,
        "clarified_field": clarified_field,
        "source_nodes": TRACE_SOURCES,
    }


def _fallback(filters: dict[str, list[dict[str, Any]]], parsed: dict[str, Any]) -> dict[str, Any]:
    budget = float(parsed["budget"])
    if filters["within_budget"] and filters["excluded_by_evidence"]:
        return {
            "type": "insufficient_verified_evidence",
            "reason": "当前样本中有符合品类与预算的商品，但没有商品同时满足敏感肌及成分避雷的官方证据门槛。",
            "available_sample_price_floor": None,
            "required_budget_increase": None,
            "actions": ["取消未有官方依据的安全断言。", "扩充经产品身份匹配的官方成分资料后再检索。"],
        }
    if filters["same_category"]:
        floor = min(float(product["sample_price"]) for product in filters["same_category"])
        return {
            "type": "budget_below_sample_floor",
            "reason": "当前离线日化历史样本中，没有同时满足品类和样本价上限的候选。",
            "available_sample_price_floor": floor,
            "required_budget_increase": max(floor - budget, 0),
            "actions": [f"将样本价上限调整到至少 {floor:g} 元后重新比较。", "扩展离线样本库后再检索。"],
        }
    return {
        "type": "category_not_covered",
        "reason": "当前离线日化历史样本尚未覆盖该品类。",
        "available_sample_price_floor": None,
        "required_budget_increase": None,
        "actions": ["扩充对应品类的历史商品样本。"],
    }


def build_output(
    catalog: dict[str, Any], parsed: dict[str, Any], missing_fields: list[str]
) -> dict[str, Any]:
    catalog_version = str(catalog["dataset"]["version"])
    if missing_fields:
        clarified = "budget" if "budget" in missing_fields else missing_fields[0]
        questions = {
            "budget": "你的样本价预算上限是多少？例如 100 元、200 元或 300 元。",
            "category": "你想找补水喷雾、保湿乳霜，还是清洁定妆产品？",
            "use_case": "你最在意哪种功效，例如补水、保湿、控油或清洁？",
        }
        return {
            "status": "need_clarification",
            "parsed": parsed,
            "missing_fields": missing_fields,
            "question": questions.get(clarified, "请补充一项关键需求。"),
            "recommendations": [],
            "fallback": None,
            "trace": empty_trace(catalog_version, clarified),
        }

    products = catalog["products"]
    filters = hard_filter(products, parsed)
    trace = {
        "rule_version": RULE_VERSION,
        "catalog_version": catalog_version,
        "retrieval_executed": True,
        "eligible_count": len(filters["eligible"]),
        "returned_count": 0,
        "excluded_by_category": [product["id"] for product in filters["excluded_by_category"]],
        "excluded_by_budget": [product["id"] for product in filters["excluded_by_budget"]],
        "excluded_by_evidence": [product["id"] for product in filters["excluded_by_evidence"]],
        "same_category_total_count": len(filters["same_category"]),
        "clarified_field": None,
        "source_nodes": TRACE_SOURCES,
    }
    if not filters["eligible"]:
        return {
            "status": "no_result",
            "parsed": parsed,
            "missing_fields": [],
            "question": None,
            "recommendations": [],
            "fallback": _fallback(filters, parsed),
            "trace": trace,
        }

    tokens = unique(list(parsed.get("use_case", [])) + list(parsed.get("priority", [])))
    scored = score_products(filters["eligible"], float(parsed["budget"]), tokens)[:3]
    recommendations: list[dict[str, Any]] = []
    for rank, item in enumerate(scored, start=1):
        product = item["product"]
        verified = evidence_profile(product)
        sample_price = float(product["sample_price"])
        budget = float(parsed["budget"])
        matches = item["matched_needs"]
        if parsed.get("requires_verified_evidence"):
            why_fit = "通过当前官方证据门槛"
            if parsed.get("skin_type") == "敏感肌":
                why_fit += "，官方页面明确包含敏感肌适用表述"
            if parsed.get("avoid_ingredients"):
                why_fit += "，且明确不添加" + "、".join(parsed["avoid_ingredients"])
            why_fit += "。"
        else:
            why_fit = "基础功效检索命中" + ("、".join(matches) if matches else "品类与预算") + "；功效词按原字段的证据等级展示。"
        recommendations.append(
            {
                "rank": rank,
                "id": product["id"],
                "shop": product["shop"],
                "name": product["name"],
                "sample_price": product["sample_price"],
                "sample_price_label": "样本价",
                "score": round(item["score"], 2),
                "score_breakdown": {key: round(value, 2) for key, value in item["breakdown"].items()},
                "matched_needs": matches,
                "why_fit": why_fit,
                "budget_gap": budget - sample_price,
                "sample_price_relation": f"样本价为 {sample_price:g} 元，与预算上限相差 {budget - sample_price:g} 元。",
                "tradeoff": product["limitations"][0],
                "evidence_level": verified.get("status", "not_verified"),
                "evidence_sources": verified.get("sources", []),
            }
        )
    trace["returned_count"] = len(recommendations)
    return {
        "status": "recommend",
        "parsed": parsed,
        "missing_fields": [],
        "question": None,
        "recommendations": recommendations,
        "fallback": None,
        "trace": trace,
    }
