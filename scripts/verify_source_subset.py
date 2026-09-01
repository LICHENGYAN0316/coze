#!/usr/bin/env python3
"""在本地核对 Coze 15 条小样本与用户指定的历史 CSV。

脚本不会复制原表、输出原始标题或写回任何源文件。
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]


def nullable_int(value: str) -> int | None:
    text = value.strip()
    return None if text == "" else int(float(text))


def latest_rows(source_csv: Path, wanted_ids: set[str]) -> dict[str, dict[str, str]]:
    latest: dict[str, dict[str, str]] = {}
    with source_csv.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        required = {"update_time", "id", "price", "sale_count", "comment_count", "店名"}
        missing = required - set(reader.fieldnames or [])
        if missing:
            raise ValueError("源表缺少字段：" + "、".join(sorted(missing)))
        for row in reader:
            product_id = row["id"]
            if product_id not in wanted_ids:
                continue
            previous = latest.get(product_id)
            if previous is None or row["update_time"] > previous["update_time"]:
                latest[product_id] = row
    return latest


def verify(source_csv: Path, catalog_path: Path) -> list[str]:
    catalog: dict[str, Any] = json.loads(catalog_path.read_text(encoding="utf-8"))
    products = catalog.get("products", [])
    wanted_ids = {str(product["id"]) for product in products}
    source = latest_rows(source_csv, wanted_ids)
    errors: list[str] = []
    for product in products:
        product_id = str(product["id"])
        row = source.get(product_id)
        if row is None:
            errors.append(f"{product_id}: 源表中未找到")
            continue
        expected = {
            "shop": row["店名"].strip(),
            "sample_price": float(row["price"]),
            "historical_sales_count": nullable_int(row["sale_count"]),
            "historical_comment_count": nullable_int(row["comment_count"]),
        }
        for field_name, expected_value in expected.items():
            actual = product.get(field_name)
            if isinstance(expected_value, float) and isinstance(actual, (int, float)):
                equal = abs(float(actual) - expected_value) < 1e-9
            else:
                equal = actual == expected_value
            if not equal:
                errors.append(f"{product_id}: {field_name} 与最后一条源观测不一致")
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description="核对 Coze 日化历史小样本")
    parser.add_argument("--source-csv", type=Path, required=True)
    parser.add_argument("--catalog", type=Path, default=ROOT / "data/products.json")
    args = parser.parse_args()
    errors = verify(args.source_csv, args.catalog)
    if errors:
        print(f"FAIL: {len(errors)} 项不一致。")
        for error in errors:
            print(f"- {error}")
        return 1
    print("通过：15 条商品的商店、样本价、历史销量与历史评论已与本地源表最后一条观测核对。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
