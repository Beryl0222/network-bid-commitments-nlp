"""项目实办边界（conditions.jsonl）：验收范围、统计窗口与确认记录。

条件表给出同一工况下验收怎么划范围、指标按什么窗口统计，以及哪些
启用条件现场尚未确认。解析不了的明细保留为备注，随验收项带出。
"""
from __future__ import annotations

import re

from .model import INDEPENDENCE, LATENCY, THROUGHPUT, Boundary, Condition
from .parsing import detect_caliber
from .units import parse_quantities

_SCOPE_SUFFIX_RE = re.compile(r"(均需|需|均应).*$")


def parse_boundaries(rows: list[dict]) -> dict[str, Boundary]:
    boundaries: dict[str, Boundary] = {}
    for row in rows:
        calibers: dict = {}
        expected: dict = {}
        caliber = detect_caliber(row["interval"])
        if "吞吐" in row["interval"]:
            if caliber.kind is None and caliber.window is not None:
                caliber.kind = "minimum"
            calibers[THROUGHPUT] = caliber
        elif caliber.kind == "percentile":
            calibers[LATENCY] = caliber
        else:
            quantities = parse_quantities(row["interval"])
            if quantities:
                expected[INDEPENDENCE] = quantities[0]
        rules, notes = _parse_detail(row["detail"])
        boundaries[row["facility"]] = Boundary(
            doc_id=row["id"],
            facility=row["facility"],
            scopes=_parse_scopes(row["scope"]),
            calibers=calibers,
            expected=expected,
            rules=rules,
            notes=notes,
        )
    return boundaries


def _parse_scopes(text: str) -> list[str]:
    text = _SCOPE_SUFFIX_RE.sub("", text)
    return [part for part in re.split(r"[和、，]", text) if part]


_SCENARIO_WORDS = {"平时", "满载", "接替", "施工期间"}


def area_facility_map(boundaries: dict[str, Boundary]) -> dict[str, str]:
    """条件表中的区域范围（东区/西区/全仓）→ 所属设施，供应答解析定位。"""
    mapping: dict[str, str] = {}
    for boundary in boundaries.values():
        for scope in boundary.scopes:
            if scope not in _SCENARIO_WORDS:
                mapping[scope] = boundary.facility
    return mapping


def _parse_detail(text: str) -> tuple[list[Condition], list[str]]:
    rules: list[Condition] = []
    notes: list[str] = []
    for segment in re.split(r"[。；]", text):
        segment = segment.strip()
        if not segment:
            continue
        load = re.search(r"(\d+)台试验不能用(\d+)台的结论代替", segment)
        if load:
            rules.append(Condition("load_no_substitute", segment))
            continue
        if "共享同一次切换" in segment:
            rules.append(Condition("shared_switch", segment))
            continue
        unconfirmed = re.search(r"没有(.+?)的确认记录", segment)
        if unconfirmed:
            rules.append(Condition("enable_unconfirmed", segment))
            continue
        notes.append(segment)
    return rules, notes
