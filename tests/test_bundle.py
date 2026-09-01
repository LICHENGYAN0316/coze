#!/usr/bin/env python3
"""日化历史数据 Coze MVP 回归测试。"""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_bundle as validator  # noqa: E402
from recommendation_core import hard_filter  # noqa: E402


class BundleValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        loaded, errors = validator.load_bundle(ROOT)
        if errors:
            raise AssertionError("；".join(errors))
        cls.workflow = loaded["workflow"]
        cls.catalog = loaded["catalog"]
        cls.examples = loaded["examples"]
        cls.platform_runs = loaded["platform_runs"]

    def test_current_bundle_passes_all_checks(self) -> None:
        result = validator.validate_loaded(self.workflow, self.catalog, self.examples, self.platform_runs, ROOT)
        self.assertTrue(result.ok, "\n".join(result.errors))
        self.assertGreater(result.checks, 100)

    def test_sample_price_mismatch_is_rejected(self) -> None:
        examples = copy.deepcopy(self.examples)
        case_a = next(case for case in examples["cases"] if case["case_id"] == "A")
        case_a["output"]["recommendations"][0]["sample_price"] += 1
        result = validator.validate_loaded(self.workflow, self.catalog, examples, self.platform_runs, ROOT)
        self.assertTrue(any("重算结果" in error for error in result.errors))

    def test_sensitive_skin_cannot_use_unverified_title_claim(self) -> None:
        parsed = {
            "category": "保湿乳霜", "budget": 300, "use_case": ["保湿"], "priority": [],
            "skin_type": "敏感肌", "avoid_ingredients": ["香精"], "requires_verified_evidence": True,
        }
        filters = hard_filter(self.catalog["products"], parsed)
        eligible_ids = {product["id"] for product in filters["eligible"]}
        self.assertEqual(eligible_ids, {"A20332739108", "A18297865077"})
        self.assertIn("A521465605447", {product["id"] for product in filters["excluded_by_evidence"]})

    def test_avoid_claim_needs_explicit_official_without_field(self) -> None:
        parsed = {
            "category": "保湿乳霜", "budget": 300, "use_case": ["保湿"], "priority": [],
            "skin_type": "敏感肌", "avoid_ingredients": ["矿物油"], "requires_verified_evidence": True,
        }
        filters = hard_filter(self.catalog["products"], parsed)
        self.assertEqual(filters["eligible"], [])

    def test_doubao_key_cannot_be_marked_as_provisioned(self) -> None:
        runs = copy.deepcopy(self.platform_runs)
        runs["daily_migration"]["secret_provisioned"] = True
        result = validator.validate_loaded(self.workflow, self.catalog, self.examples, runs, ROOT)
        self.assertTrue(any("密钥" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
