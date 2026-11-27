"""数量、单位与中文数字的解析。"""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from acceptance.units import cn_number, fmt_quantity, parse_quantities


class CnNumberTest(unittest.TestCase):
    def test_arabic_and_decimal(self):
        self.assertEqual(cn_number("20"), 20)
        self.assertEqual(cn_number("0.018"), 0.018)
        self.assertEqual(cn_number("0.05"), 0.05)

    def test_chinese(self):
        self.assertEqual(cn_number("两"), 2)
        self.assertEqual(cn_number("一"), 1)
        self.assertEqual(cn_number("十"), 10)
        self.assertEqual(cn_number("十五"), 15)
        self.assertEqual(cn_number("二十"), 20)

    def test_invalid(self):
        self.assertIsNone(cn_number(""))
        self.assertIsNone(cn_number("abc"))


class QuantityTest(unittest.TestCase):
    def test_time_normalization(self):
        (q,) = parse_quantities("不超过20毫秒")
        self.assertEqual((q.kind, q.value), ("time", 0.02))
        (q,) = parse_quantities("P95 RTT ≤ 0.018 s")
        self.assertAlmostEqual(q.value, 0.018)
        (q,) = parse_quantities("试验需持续两小时")
        self.assertEqual(q.value, 7200)
        (q,) = parse_quantities("保持独立90分钟")
        self.assertEqual(q.value, 5400)

    def test_rate_normalization(self):
        (q,) = parse_quantities("不低于0.05 Gbps")
        self.assertEqual((q.kind, q.value), ("rate", 50.0))
        (q,) = parse_quantities("平均50 Mbps")
        self.assertEqual(q.value, 50.0)

    def test_count(self):
        (q,) = parse_quantities("满载指40台终端同时工作")
        self.assertEqual((q.kind, q.value), ("count", 40.0))

    def test_span_points_to_source(self):
        text = "服务保证45秒内接替"
        (q,) = parse_quantities(text)
        self.assertEqual(text[q.start:q.end], "45秒")

    def test_format(self):
        (q,) = parse_quantities("0.018 s")
        self.assertEqual(fmt_quantity(q), "18 毫秒")
        (q,) = parse_quantities("两小时")
        self.assertEqual(fmt_quantity(q), "2 小时")
        (q,) = parse_quantities("连续10分钟")
        self.assertEqual(fmt_quantity(q), "10 分钟")


if __name__ == "__main__":
    unittest.main()
