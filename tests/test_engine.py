"""覆盖评估：逐供应商、逐验收项的结论、证据与前提。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.boundaries import area_facility_map, parse_boundaries
from acceptance.engine import derive_items, evaluate_all
from acceptance.model import (
    CONFLICT,
    COVERED,
    NEEDS_CONFIRMATION,
    NEEDS_EVIDENCE,
)
from acceptance.replies import parse_replies
from acceptance.terms import Baseline

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return [
        json.loads(line)
        for line in (ROOT / "materials" / f"{name}.jsonl").read_text(
            encoding="utf-8").splitlines()
    ]


class CoverageTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        baseline = Baseline.build(load("terms"))
        boundaries = parse_boundaries(load("conditions"))
        commitments = parse_replies(load("replies"),
                                    area_facility=area_facility_map(boundaries))
        cls.items = derive_items(baseline, boundaries)
        cls.coverage = evaluate_all(["折港", "川简"], cls.items, commitments,
                                    baseline.clauses, boundaries)

    def status(self, supplier, item_id):
        for coverage in self.coverage[supplier]:
            if coverage.item.item_id == item_id:
                return coverage
        self.fail(f"{supplier} 缺少验收项 {item_id}")

    def test_five_items_from_scenario_and_scope_split(self):
        self.assertEqual([i.item_id for i in self.items], [
            "T1·平时", "T1·满载", "T2·接替·东区", "T2·接替·西区", "T3·施工期间·全仓"])

    def test_zhegang(self):
        self.assertEqual(self.status("折港", "T1·平时").status, COVERED)
        self.assertEqual(self.status("折港", "T1·满载").status, NEEDS_EVIDENCE)
        self.assertEqual(self.status("折港", "T2·接替·东区").status, COVERED)
        self.assertEqual(self.status("折港", "T2·接替·西区").status, COVERED)
        self.assertEqual(self.status("折港", "T3·施工期间·全仓").status, CONFLICT)

    def test_chuanjian(self):
        self.assertEqual(self.status("川简", "T1·平时").status, COVERED)
        self.assertEqual(self.status("川简", "T1·满载").status, COVERED)
        self.assertEqual(self.status("川简", "T2·接替·东区").status, COVERED)
        self.assertEqual(self.status("川简", "T2·接替·西区").status, NEEDS_EVIDENCE)
        self.assertEqual(self.status("川简", "T3·施工期间·全仓").status,
                         NEEDS_CONFIRMATION)

    def test_one_scenario_does_not_cover_another(self):
        # 折港 40 台的高指标不盖 60 台满载的缺项
        full = self.status("折港", "T1·满载")
        self.assertEqual(full.status, NEEDS_EVIDENCE)
        self.assertTrue(any("40 台" in r and "60 台" in r for r in full.reasons))
        self.assertTrue(any("60台试验不能用40台" in q.text for q in full.questions))

    def test_suppliers_judged_independently(self):
        # 川简覆盖 60 台，不能补折港的缺项
        self.assertEqual(self.status("折港", "T1·满载").status, NEEDS_EVIDENCE)
        self.assertEqual(self.status("川简", "T1·满载").status, COVERED)

    def test_attachment_conditions_travel_with_evidence(self):
        east = self.status("折港", "T2·接替·东区")
        keys = {p.key for p in east.premises}
        self.assertIn("窗口/吞吐", keys)
        self.assertIn("触发/主链路不可用", keys)
        self.assertIn("测区/东区", keys)
        # 正文+附件组合：需求允许跨接入方式组合成为前提
        self.assertTrue(any(p.key.startswith("组合/") for p in east.premises))
        docs = {e.commitment.doc_id for e in east.evidence}
        self.assertEqual(docs, {"a1", "a2", "a4"})

    def test_optional_not_treated_as_default(self):
        t3 = self.status("川简", "T3·施工期间·全仓")
        self.assertEqual(t3.status, NEEDS_CONFIRMATION)
        self.assertTrue(any(q.audience == "采购方" for q in t3.questions))
        self.assertTrue(any("双电源" in p.text for p in t3.premises))
        self.assertTrue(any("没有双电源的确认记录" in p.text for p in t3.premises))

    def test_caliber_mismatch_raises_question(self):
        west = self.status("川简", "T2·接替·西区")
        self.assertEqual(west.status, NEEDS_EVIDENCE)
        self.assertTrue(any("均值" in r for r in west.reasons))
        self.assertTrue(any("窗口内最低值" in q.text for q in west.questions))

    def test_unstated_caliber_inherited_as_premise(self):
        west = self.status("折港", "T2·接替·西区")
        self.assertEqual(west.status, COVERED)
        self.assertTrue(any("未声明" in p.text for p in west.premises))

    def test_marketing_and_intent_kept_as_notes(self):
        east = self.status("折港", "T2·接替·东区")
        self.assertTrue(any("宣传" in n for n in east.notes))
        full = self.status("折港", "T1·满载")
        self.assertTrue(any("意向" in n for n in full.notes))

    def test_conflict_when_commitment_below_requirement(self):
        t3 = self.status("折港", "T3·施工期间·全仓")
        self.assertEqual(t3.status, CONFLICT)
        self.assertTrue(any("90 分钟" in r for r in t3.reasons))

    def test_evidence_carries_source_positions(self):
        east = self.status("折港", "T2·接替·东区")
        for evidence in east.evidence:
            source = evidence.commitment.source
            self.assertIsNotNone(source)
            self.assertGreater(source.end, source.start)
            self.assertTrue(source.excerpt)


if __name__ == "__main__":
    unittest.main()
