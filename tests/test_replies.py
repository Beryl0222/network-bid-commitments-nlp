"""供应商材料解析：承诺分类、指代与引用、范围展开。"""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.boundaries import area_facility_map, parse_boundaries
from acceptance.model import INTENT, MARKETING, OPTIONAL, VERIFIABLE
from acceptance.replies import parse_replies

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    return [
        json.loads(line)
        for line in (ROOT / "materials" / f"{name}.jsonl").read_text(
            encoding="utf-8").splitlines()
    ]


class RepliesTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        boundaries = parse_boundaries(load("conditions"))
        cls.commitments = parse_replies(
            load("replies"), area_facility=area_facility_map(boundaries))

    def find(self, doc_id, indicator=None, scope=None, scenario=None):
        out = []
        for commitment in self.commitments:
            if commitment.doc_id != doc_id:
                continue
            if indicator and (not commitment.metric
                              or commitment.metric.indicator != indicator):
                continue
            if scope and commitment.scope != scope:
                continue
            if scenario and commitment.scenario != scenario:
                continue
            out.append(commitment)
        return out

    def test_marketing_and_intent_not_verifiable(self):
        peaks = [c for c in self.find("a2", indicator="吞吐", scope="东区")
                 if c.metric.caliber.kind == "peak"]
        self.assertEqual(peaks[0].status, MARKETING)
        (intent,) = self.find("a3", indicator="时延")
        self.assertEqual(intent.status, INTENT)
        self.assertEqual(intent.metric.value.value, 0.018)  # 指代 a1 解析成功
        self.assertEqual(intent.resolved, ["a1"])

    def test_verifiable_commitment_with_load_cap(self):
        (latency,) = self.find("a1", indicator="时延")
        self.assertEqual(latency.status, VERIFIABLE)
        self.assertAlmostEqual(latency.metric.value.value, 0.018)
        caps = [c for c in latency.conditions if c.kind == "load_cap"]
        self.assertEqual(caps[0].value.value, 40)

    def test_anaphora_same_level(self):
        (normal,) = self.find("b1", indicator="时延", scenario="平时")
        self.assertEqual(normal.metric.value.value, 0.02)
        (full,) = self.find("b1", indicator="时延", scenario="满载")
        loads = [c for c in full.conditions if c.kind == "load"]
        self.assertEqual(loads[0].value.value, 60)

    def test_anaphora_main_average(self):
        (west,) = self.find("b3", indicator="吞吐", scope="西区")
        self.assertEqual(west.metric.caliber.kind, "average")
        self.assertEqual(west.resolved, ["b1"])

    def test_scope_expansion(self):
        east = self.find("b1", indicator="吞吐", scope="东区")
        west = self.find("b1", indicator="吞吐", scope="西区")
        self.assertTrue(east and west)  # “两区”展开为两条

    def test_optional_not_default(self):
        (independence,) = self.find("b2", indicator="独立时长")
        self.assertEqual(independence.availability, OPTIONAL)
        enables = [c for c in independence.conditions if c.kind == "enable"]
        self.assertTrue(any("双电源" in c.text for c in enables))

    def test_pointer_resolves_to_attachment(self):
        pointers = [c for c in self.commitments if c.reference == "see_attachment"]
        self.assertEqual(len(pointers), 1)
        self.assertEqual(pointers[0].resolved, ["a2"])

    def test_area_only_sentence_located_by_boundary(self):
        # “保证55秒和55 Mbps”只写西区、不写设施名，按条件表定位到晾场库
        west = self.find("a4", indicator="恢复时间", scope="西区")
        self.assertEqual(west[0].facility, "晾场库")
        self.assertEqual(west[0].metric.value.value, 55)

    def test_as_of_filters_later_replies(self):
        boundaries = parse_boundaries(load("conditions"))
        early = parse_replies(load("replies"), as_of="2026-11-10",
                              area_facility=area_facility_map(boundaries))
        self.assertFalse(any(c.doc_id in ("a4", "b3") for c in early))


if __name__ == "__main__":
    unittest.main()
