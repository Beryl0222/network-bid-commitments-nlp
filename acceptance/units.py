"""数量、单位、中文数字与比较符号的解析和归一化。

所有时间量归一为秒、速率归一为 Mbps、负载归一为台，比较只在归一化
之后进行，避免 “0.05 Gbps” 与 “50 Mbps”、“0.018 s” 与 “20 毫秒”
这类写法差异影响判断。
"""
from __future__ import annotations

import re
from dataclasses import dataclass

CN_DIGITS = {
    "零": 0, "一": 1, "二": 2, "两": 2, "三": 3, "四": 4,
    "五": 5, "六": 6, "七": 7, "八": 8, "九": 9,
}


def cn_number(text: str) -> float | None:
    """解析阿拉伯数字（含小数）或 0–99 的中文数字，无法解析时返回 None。"""
    text = text.strip()
    if not text:
        return None
    if text.isdigit():
        return int(text)
    try:
        return float(text)
    except ValueError:
        pass
    if "十" in text:
        left, _, right = text.partition("十")
        if left and left not in CN_DIGITS:
            return None
        if right and right not in CN_DIGITS:
            return None
        tens = CN_DIGITS[left] if left else 1
        ones = CN_DIGITS[right] if right else 0
        return tens * 10 + ones
    return CN_DIGITS.get(text)


TIME_TO_SECONDS = {
    "毫秒": 0.001, "ms": 0.001,
    "秒": 1.0, "s": 1.0,
    "分钟": 60.0, "分": 60.0,
    "小时": 3600.0,
}
RATE_TO_MBPS = {"Mbps": 1.0, "Gbps": 1000.0}
COUNT_UNITS = {"台"}

_NUMBER = r"(?:\d+(?:\.\d+)?|[零一二两三四五六七八九十]+)"
_UNIT = r"(?:Mbps|Gbps|毫秒|分钟|小时|秒|分|ms|s|台)"
QUANTITY_RE = re.compile(rf"(?P<num>{_NUMBER})\s*(?P<unit>{_UNIT})")


@dataclass(frozen=True)
class Quantity:
    """归一化后的数量。value 的单位由 kind 决定：time→秒，rate→Mbps，count→台。"""

    kind: str  # "time" | "rate" | "count"
    value: float
    unit: str  # 归一化单位："秒" | "Mbps" | "台"
    raw: str   # 原文片段，如 "0.05 Gbps"
    start: int = 0
    end: int = 0

    def shift(self, offset: int) -> "Quantity":
        return Quantity(self.kind, self.value, self.unit, self.raw,
                        self.start + offset, self.end + offset)


def parse_quantities(text: str, base: int = 0) -> list[Quantity]:
    """找出文本中全部数量，span 为相对 base 的偏移。"""
    out: list[Quantity] = []
    for match in QUANTITY_RE.finditer(text):
        number = cn_number(match.group("num"))
        unit = match.group("unit")
        if number is None:
            continue
        if unit in TIME_TO_SECONDS:
            kind, value, norm = "time", number * TIME_TO_SECONDS[unit], "秒"
        elif unit in RATE_TO_MBPS:
            kind, value, norm = "rate", number * RATE_TO_MBPS[unit], "Mbps"
        elif unit in COUNT_UNITS:
            kind, value, norm = "count", float(number), "台"
        else:  # pragma: no cover - 正则已限定单位集合
            continue
        out.append(Quantity(kind, value, norm, match.group(0),
                            base + match.start(), base + match.end()))
    return out


def fmt_quantity(quantity: Quantity) -> str:
    """按惯用单位展示归一化数量。"""
    if quantity.kind == "time":
        seconds = quantity.value
        if seconds < 1:
            return f"{seconds * 1000:g} 毫秒"
        if seconds < 60:
            return f"{seconds:g} 秒"
        if seconds % 3600 == 0:
            return f"{seconds / 3600:g} 小时"
        if seconds % 60 == 0:
            return f"{seconds / 60:g} 分钟"
        return f"{seconds:g} 秒"
    if quantity.kind == "rate":
        return f"{quantity.value:g} Mbps"
    return f"{quantity.value:g} 台"


LE = "le"
GE = "ge"

_COMPARATOR_TEXT = {LE: "≤", GE: "≥"}


def fmt_comparator(comparator: str) -> str:
    return _COMPARATOR_TEXT[comparator]
