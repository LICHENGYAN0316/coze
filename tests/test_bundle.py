#!/usr/bin/env python3
"""Regression tests for the public Coze MVP bundle."""

from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import validate_bundle as validator  # noqa: E402


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
        result = validator.validate_loaded(
            self.workflow, self.catalog, self.examples, self.platform_runs, ROOT
        )
        self.assertTrue(result.ok, "\n".join(result.errors))
        self.assertGreater(result.checks, 100)

    def test_budget_violation_is_rejected(self) -> None:
        examples = copy.deepcopy(self.examples)
        case_a = next(case for case in examples["cases"] if case["case_id"] == "A")
        case_a["output"]["recommendations"][0]["id"] = "NB-005"
        result = validator.validate_loaded(self.workflow, self.catalog, examples)
        self.assertTrue(any("硬过滤" in error for error in result.errors))

    def test_budget_gap_mismatch_is_rejected(self) -> None:
        examples = copy.deepcopy(self.examples)
        case_d = next(case for case in examples["cases"] if case["case_id"] == "D")
        case_d["output"]["recommendations"][0]["budget_gap"] += 1
        result = validator.validate_loaded(self.workflow, self.catalog, examples)
        self.assertTrue(any("budget_gap" in error for error in result.errors))

    def test_trace_source_mismatch_is_rejected(self) -> None:
        examples = copy.deepcopy(self.examples)
        case_b = next(case for case in examples["cases"] if case["case_id"] == "B")
        case_b["output"]["trace"]["source_nodes"]["retrieval_executed"] = "retrieve_catalog"
        result = validator.validate_loaded(self.workflow, self.catalog, examples)
        self.assertTrue(any("source_nodes" in error for error in result.errors))

    def test_unperformed_v021_native_rerun_cannot_be_marked_passed(self) -> None:
        platform_runs = copy.deepcopy(self.platform_runs)
        platform_runs["v0_2_1_change"]["native_rerun"] = "passed"
        result = validator.validate_loaded(
            self.workflow, self.catalog, self.examples, platform_runs, ROOT
        )
        self.assertTrue(any("不得把 v0.2.1" in error for error in result.errors))


if __name__ == "__main__":
    unittest.main()
