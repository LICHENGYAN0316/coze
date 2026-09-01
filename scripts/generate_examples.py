#!/usr/bin/env python3
"""从固定 parsed 用例生成可复算的离线示例。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from recommendation_core import RULE_VERSION, build_output


ROOT = Path(__file__).resolve().parents[1]
CASES = [
    {
        "case_id": "A",
        "title": "功效推荐：补水喷雾",
        "input": {"query": "预算200元，想要补水喷雾，通勤随身用，补水优先"},
        "parsed": {"category": "补水喷雾", "budget": 200, "use_case": ["补水", "通勤"], "priority": ["补水"], "skin_type": None, "avoid_ingredients": [], "requires_verified_evidence": False},
        "missing_fields": [],
    },
    {
        "case_id": "B",
        "title": "信息不足：敏感肌与成分避雷",
        "input": {"query": "想找适合敏感肌的保湿乳霜，避开香精"},
        "parsed": {"category": "保湿乳霜", "budget": None, "use_case": ["保湿"], "priority": [], "skin_type": "敏感肌", "avoid_ingredients": ["香精"], "requires_verified_evidence": True},
        "missing_fields": ["budget"],
    },
    {
        "case_id": "C",
        "title": "无结果：样本价上限过低",
        "input": {"query": "预算20元，想买控油定妆产品"},
        "parsed": {"category": "清洁定妆", "budget": 20, "use_case": ["控油", "定妆"], "priority": ["控油"], "skin_type": None, "avoid_ingredients": [], "requires_verified_evidence": False},
        "missing_fields": [],
    },
    {
        "case_id": "D",
        "title": "严格证据：敏感肌、避开香精与保湿",
        "input": {"query": "300元内想买保湿乳霜，敏感肌，希望保湿修护，避开香精"},
        "parsed": {"category": "保湿乳霜", "budget": 300, "use_case": ["保湿", "修护"], "priority": ["保湿"], "skin_type": "敏感肌", "avoid_ingredients": ["香精"], "requires_verified_evidence": True},
        "missing_fields": [],
    },
]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=ROOT / "examples/input-output.json")
    args = parser.parse_args()
    with (ROOT / "data/products.json").open(encoding="utf-8") as handle:
        catalog = json.load(handle)
    cases = []
    for fixture in CASES:
        cases.append({key: fixture[key] for key in ("case_id", "title", "input")} | {"output": build_output(catalog, fixture["parsed"], fixture["missing_fields"])})
    artifact = {
        "artifact_type": "local_equivalent_examples",
        "schema_version": "2.0.0",
        "catalog_version": catalog["dataset"]["version"],
        "rule_version": RULE_VERSION,
        "coze_native_execution": False,
        "disclaimer_zh": "以下结果由日化历史商品样本和确定性规则离线复算，不是 Coze 平台运行日志；样本价只是离线数据字段。",
        "cases": cases,
    }
    args.output.write_text(json.dumps(artifact, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
