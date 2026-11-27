"""项目容器：需求包接入、快照对比与新需求包再比对。"""
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.model import COVERED, NEEDS_EVIDENCE
from acceptance.project import Project

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / "tests" / "fixtures"


class ProjectTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="acceptance-test-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.project = Project.init(self.tmp / "demo")

    def test_ingest_evaluate_snapshot(self):
        counts = self.project.ingest("首轮", ROOT / "materials")
        self.assertEqual(counts, {"terms": 3, "replies": 7,
                                  "conditions": 3, "minutes": 3})
        evaluation = self.project.evaluate(label="首轮比对")
        self.assertEqual(len(evaluation.items), 5)
        self.assertEqual(sorted(evaluation.coverage), ["川简", "折港"])
        self.assertEqual(len(self.project.state["snapshots"]), 1)

    def test_duplicate_id_rejected(self):
        self.project.ingest("首轮", ROOT / "materials")
        with self.assertRaises(ValueError):
            self.project.ingest("重复", ROOT / "materials")

    def test_new_package_re_evaluation_in_same_project(self):
        self.project.ingest("首轮", ROOT / "materials")
        first = self.project.evaluate(label="首轮")
        status_before = {c.item.item_id: c.status
                         for c in first.coverage["川简"]}
        self.assertEqual(status_before["T2·接替·西区"], NEEDS_EVIDENCE)
        self.assertEqual(status_before["T1·满载"], COVERED)

        self.project.ingest("会后补充", FIXTURES / "pkg2")
        second = self.project.evaluate(label="补充后")
        status_after = {c.item.item_id: c.status
                        for c in second.coverage["川简"]}
        # 供应商澄清西区口径后，西区转为可验收（新证据接替）
        self.assertEqual(status_after["T2·接替·西区"], COVERED)
        # 补遗把满载改为 70 台后，原 60 台安排变成要补证
        self.assertEqual(status_after["T1·满载"], NEEDS_EVIDENCE)

        # 快照对比说明变化与原因
        diff = Project.diff(self.project.load_snapshot(1),
                            self.project.load_snapshot(2))
        self.assertTrue(any("r4" in line for line in diff))
        self.assertTrue(any("b4" in line for line in diff))
        self.assertTrue(any("T1·满载" in line and "可验收 → 需补证" in line
                            for line in diff))
        self.assertTrue(any("T2·接替·西区" in line and "需补证 → 可验收" in line
                            for line in diff))
        # m2 的 60 台安排因补遗失效
        minutes = {r.minute["id"]: r.validity for r in second.reviews}
        self.assertEqual(minutes["m2"], "已失效")
        self.assertTrue(any("m2" in line for line in diff))

    def test_ingest_rejects_unknown_directory(self):
        with self.assertRaises(ValueError):
            self.project.ingest("空", self.tmp)


if __name__ == "__main__":
    unittest.main()
