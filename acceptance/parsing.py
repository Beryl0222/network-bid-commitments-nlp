"""分句、设施/场景/口径识别与指标绑定（需求与应答共用）。

解析是基于规则表的确定性解析：每个被识别的要素都记录它在原文中的
字符位置，识别不了的内容保留为未解析记录，绝不静默丢弃。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import (
    INDEPENDENCE,
    LATENCY,
    RECOVERY,
    THROUGHPUT,
    Caliber,
    Metric,
    SourceRef,
)
from .units import GE, LE, Quantity, cn_number, parse_quantities

DEFAULT_FACILITIES = ("晾场库", "检验仓", "主库")  # 长名优先，避免子串误配

SEGMENT_RE = re.compile(r"[。；，]")
WINDOW_RE = re.compile(r"(?:连续|前)\s*(\d+|[零一二两三四五六七八九十]+)\s*分钟")
PERCENTILE_RE = re.compile(r"P\s?(\d{2})")


def split_segments(text: str) -> list[tuple[int, int, str]]:
    """按句号、分号、逗号分句，保留每句在原文中的字符位置。"""
    segments: list[tuple[int, int, str]] = []
    start = 0
    for match in SEGMENT_RE.finditer(text):
        _append(segments, text, start, match.start())
        start = match.end()
    _append(segments, text, start, len(text))
    return segments


def _append(segments: list, text: str, start: int, end: int) -> None:
    raw = text[start:end]
    stripped = raw.strip()
    if not stripped:
        return
    lead = len(raw) - len(raw.lstrip())
    segments.append((start + lead, start + lead + len(stripped), stripped))


def detect_facility(segment: str, facilities=DEFAULT_FACILITIES) -> str | None:
    for facility in facilities:
        if facility in segment:
            return facility
    return None


def detect_facilities(text: str, facilities=DEFAULT_FACILITIES) -> set[str]:
    return {facility for facility in facilities if facility in text}


def detect_scope(segment: str) -> str | None:
    if "两区" in segment:
        return "两区"
    for scope in ("东区", "西区", "全仓"):
        if scope in segment:
            return scope
    return None


def detect_scenarios(segment: str) -> list[str]:
    scenarios: list[str] = []
    if "平时" in segment:
        scenarios.append("平时")
    if "满载" in segment:
        scenarios.append("满载")
    if "施工" in segment:
        scenarios.append("施工期间")
    return scenarios


def detect_access(segment: str) -> str | None:
    if "有线旁路" in segment:
        return "有线旁路"
    if "无线" in segment:
        return "无线"
    if "备接入" in segment:
        return "备接入"
    if "移动接入" in segment:
        return "移动接入"
    if "有线" in segment:
        return "有线"
    return None


def detect_caliber(segment: str) -> Caliber:
    caliber = Caliber()
    percentile = PERCENTILE_RE.search(segment)
    if percentile:
        caliber.kind = "percentile"
        caliber.percentile = int(percentile.group(1))
    if "峰值" in segment or "点测" in segment:
        caliber.kind = "peak"
    if "平均" in segment or "均值" in segment:
        caliber.kind = "average"
    if "最低" in segment:
        caliber.kind = "minimum"
    window = WINDOW_RE.search(segment)
    if window:
        minutes = cn_number(window.group(1))
        if minutes is not None:
            caliber.window = Quantity("time", minutes * 60.0, "秒",
                                      window.group(0), window.start(), window.end())
    if caliber.window is not None and caliber.kind is None:
        if re.search(r"不低于|至少|最低", segment):
            caliber.kind = "minimum"
    return caliber


def _is_window(quantity: Quantity, segment: str) -> bool:
    return any(m.start() <= quantity.start < m.end() for m in WINDOW_RE.finditer(segment))


def detect_comparator(segment: str, indicator: str) -> str:
    if re.search(r"不超过|以内|≤|<|最高", segment):
        return LE
    if re.search(r"内\s*(?:恢复|接替)", segment):
        return LE
    if re.search(r"不低于|至少|最低|≥|>|持续|保持|达", segment):
        return GE
    return LE if indicator in (LATENCY, RECOVERY) else GE


@dataclass
class MetricDraft:
    """bind_metrics 的中间结果，span 相对所在分句。"""

    indicator: str
    comparator: str
    value: Quantity | None
    caliber: Caliber


@dataclass
class SegmentContext:
    """跨分句携带的上下文：设施、场景、范围、接入方式与待补值指标。"""

    facility: str | None = None
    scenario: str | None = None
    scope: str | None = None
    access: str | None = None
    pending: set[str] = field(default_factory=set)

    def update(self, segment: str, facilities=DEFAULT_FACILITIES) -> None:
        facility = detect_facility(segment, facilities)
        if facility:
            self.facility = facility
        scope = detect_scope(segment)
        if scope:
            self.scope = scope
        access = detect_access(segment)
        if access:
            self.access = access
        scenarios = detect_scenarios(segment)
        if scenarios:
            self.scenario = scenarios[-1]
        if re.search(r"接替|不可用", segment):
            self.scenario = "接替"
            self.pending.update({RECOVERY, THROUGHPUT})
        if re.search(r"独立|施工", segment):
            self.scenario = self.scenario or "施工期间"
            self.pending.add(INDEPENDENCE)


def bind_metrics(segment: str, ctx: SegmentContext) -> list[MetricDraft]:
    """把分句中的数量绑定到指标上。

    指标缺失时按上下文继承：接替场景下裸时间量视为恢复时间、裸速率
    视为吞吐；含“保持/持续/独立”的时间量视为独立时长。
    """
    drafts: list[MetricDraft] = []
    quantities = parse_quantities(segment)
    time_qs = [q for q in quantities if q.kind == "time" and not _is_window(q, segment)]
    rate_qs = [q for q in quantities if q.kind == "rate"]
    caliber = detect_caliber(segment)

    has_latency = bool(re.search(r"时延|RTT", segment))
    has_independence = bool(re.search(r"独立|持续|保持", segment))
    has_recovery = bool(re.search(r"接替|恢复", segment)) and not has_independence
    has_throughput_word = "吞吐" in segment

    if has_latency and time_qs:
        quantity = time_qs.pop(0)
        drafts.append(MetricDraft(LATENCY, detect_comparator(segment, LATENCY),
                                  quantity, caliber))
    if has_independence and time_qs:
        quantity = time_qs.pop(0)
        drafts.append(MetricDraft(INDEPENDENCE, detect_comparator(segment, INDEPENDENCE),
                                  quantity, Caliber()))
    if rate_qs and (has_throughput_word or has_recovery
                    or ctx.scenario == "接替"
                    or caliber.kind in ("peak", "average", "minimum")):
        for quantity in rate_qs:
            drafts.append(MetricDraft(THROUGHPUT, detect_comparator(segment, THROUGHPUT),
                                      quantity, caliber))
        rate_qs = []
    if has_recovery and time_qs:
        quantity = time_qs.pop(0)
        drafts.append(MetricDraft(RECOVERY, detect_comparator(segment, RECOVERY),
                                  quantity, Caliber()))
    # 上下文继承：接替场景下的裸数量（如“保证55秒和55 Mbps”）
    if ctx.scenario == "接替" and not (has_latency or has_independence):
        if time_qs and RECOVERY in ctx.pending:
            quantity = time_qs.pop(0)
            drafts.append(MetricDraft(RECOVERY, detect_comparator(segment, RECOVERY),
                                      quantity, Caliber()))
        if rate_qs and THROUGHPUT in ctx.pending:
            for quantity in rate_qs:
                drafts.append(MetricDraft(THROUGHPUT,
                                          detect_comparator(segment, THROUGHPUT),
                                          quantity, caliber))
    return drafts


def make_ref(doc_id: str, kind: str, start: int, end: int, text: str) -> SourceRef:
    return SourceRef(doc_id, kind, start, end, text[start:end])
