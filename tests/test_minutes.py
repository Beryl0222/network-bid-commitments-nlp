"""纪要回查：当时判断、失效原因与草稿更新。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.boundaries import parse_boundaries
from acceptance.minutes import review_minutes

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return [
        json.loads(line)
        for line in (ROOT / "materials" / f"{name}.jsonl").read_text(
            encoding="utf-8").splitlines()
    ]


class MinutesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boundaries = parse_boundaries(load("conditions"))
        cls.reviews = {r.minute["id"]: r for r in review_minutes(
            load("minutes"), load("terms"), load("replies"), boundaries)}

    def test_m1_invalidated_by_addon(self):
        review = self.reviews["m1"]
        self.assertEqual(review.validity, "已失效")
        # 变更原因指明补遗把 40 台改为 60 台
        self.assertTrue(any("40 台改为 60 台" in e for e in review.events))
        # 当时依据可回查：需求书原文与位置
        self.assertTrue(any(doc_id == "r1" for doc_id, _, _ in review.basis))
        self.assertIn("满载", review.minute["notes"])

    def test_m2_remains_valid(self):
        review = self.reviews["m2"]
        self.assertEqual(review.validity, "继续有效")
        self.assertEqual(review.current["T1·满载"], "可验收")
        self.assertEqual(review.current["T3·施工期间·全仓"], "需采购方确认")

    def test_m3_draft_needs_update(self):
        review = self.reviews["m3"]
        self.assertEqual(review.validity, "草稿需更新")
        # 西区由无承诺变为可验收（a4 澄清纳入默认方案）
        self.assertEqual(review.as_of["T2·接替·西区"], "无承诺")
        self.assertEqual(review.current["T2·接替·西区"], "可验收")
        self.assertTrue(any(e.startswith("a4") for e in review.events))

    def test_as_of_uses_only_then_available_material(self):
        # m1 发出时供应商材料尚未到达，当时全部无承诺
        review = self.reviews["m1"]
        self.assertTrue(all(status == "无承诺" for status in review.as_of.values()))
        # m2 发出时 b3 尚未到达，东区口径仍是均值
        review = self.reviews["m2"]
        self.assertEqual(review.as_of["T2·接替·东区"], "需补证")


if __name__ == "__main__":
    unittest.main()
