"""需求基线：条款解析、补遗更正链与 as_of 重建。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.terms import Baseline

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return [
        json.loads(line)
        for line in (ROOT / "materials" / f"{name}.jsonl").read_text(
            encoding="utf-8").splitlines()
    ]


class BaselineTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = Baseline.build(load("terms"))

    def test_clause_scenarios(self):
        self.assertEqual(sorted(self.baseline.clauses), ["T1", "T2", "T3"])
        self.assertEqual(sorted(self.baseline.clauses["T1"].scenarios), ["平时", "满载"])
        self.assertEqual(sorted(self.baseline.clauses["T2"].scenarios), ["接替"])
        self.assertEqual(sorted(self.baseline.clauses["T3"].scenarios), ["施工期间"])

    def test_metrics_normalized(self):
        latency = self.baseline.clauses["T1"].scenarios["平时"].metrics["时延"]
        self.assertEqual((latency.comparator, latency.value.value), ("le", 0.02))
        self.assertEqual(latency.caliber.percentile, 95)
        throughput = self.baseline.clauses["T2"].scenarios["接替"].metrics["吞吐"]
        self.assertEqual((throughput.comparator, throughput.value.value), ("ge", 50.0))
        independence = self.baseline.clauses["T3"].scenarios["施工期间"].metrics["独立时长"]
        self.assertEqual(independence.value.value, 7200)

    def test_addon_updates_load_and_keeps_history(self):
        conditions = self.baseline.clauses["T1"].scenarios["满载"].conditions
        load = [c for c in conditions if c.kind == "load"]
        self.assertEqual(len(load), 1)
        self.assertEqual(load[0].value.value, 60)  # r2 将 40 台改为 60 台
        summaries = [event.summary for event in self.baseline.clauses["T1"].history]
        self.assertTrue(any("40 台改为 60 台" in s for s in summaries))

    def test_combination_rule(self):
        rule = self.baseline.clauses["T2"].combination
        self.assertTrue(rule.allow_backup)
        self.assertTrue(rule.allow_different_access)
        self.assertTrue(rule.same_area_window)

    def test_timing_from_clarification(self):
        conditions = self.baseline.clauses["T3"].scenarios["施工期间"].conditions
        self.assertTrue(any(c.kind == "timing" and "业务恢复" in c.text
                            for c in conditions))

    def test_as_of_rebuilds_earlier_baseline(self):
        earlier = Baseline.build(load("terms"), as_of="2026-11-08")
        conditions = earlier.clauses["T1"].scenarios["满载"].conditions
        loads = [c for c in conditions if c.kind == "load"]
        self.assertEqual(loads[0].value.value, 40)  # r2 尚未发布
        self.assertFalse(earlier.clauses["T2"].combination.allow_different_access)

    def test_every_amendment_segment_handled(self):
        self.assertEqual(self.baseline.notes, [])


if __name__ == "__main__":
    unittest.main()
