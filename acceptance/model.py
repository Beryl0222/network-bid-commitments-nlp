"""需求条款、承诺、验收项与覆盖结论的数据结构。"""
from __future__ import annotations

from dataclasses import dataclass, field

from .units import Quantity, fmt_comparator, fmt_quantity

# 指标
LATENCY = "时延"
RECOVERY = "恢复时间"
THROUGHPUT = "吞吐"
INDEPENDENCE = "独立时长"
INDICATORS = (LATENCY, RECOVERY, THROUGHPUT, INDEPENDENCE)

# 承诺行文状态
VERIFIABLE = "可验收承诺"
INTENT = "意向"
MARKETING = "宣传"
NOTE = "说明"

# 承诺可用性
DEFAULT = "默认"
OPTIONAL = "需采购方另选"

# 覆盖结论
COVERED = "可验收"
NEEDS_EVIDENCE = "需补证"
CONFLICT = "承诺冲突"
NEEDS_CONFIRMATION = "需采购方确认"
GAP = "无承诺"

# 结论严重程度（用于多指标验收项取最差结论）
STATUS_RANK = {
    COVERED: 0,
    NEEDS_CONFIRMATION: 1,
    NEEDS_EVIDENCE: 2,
    GAP: 3,
    CONFLICT: 4,
}


@dataclass(frozen=True)
class SourceRef:
    """证据在原始文书中的位置，用于按原文回查。"""

    doc_id: str
    kind: str  # 需求书/补遗/答疑/正文/附件/条件/澄清/条件表/纪要
    start: int
    end: int
    excerpt: str

    def locate(self) -> str:
        return f"{self.doc_id}（{self.kind}）字符 {self.start}–{self.end}"


@dataclass
class Caliber:
    """统计口径：分位、峰值、均值、窗口内最低值，以及统计窗口。"""

    kind: str | None = None  # percentile/peak/average/minimum
    percentile: int | None = None
    window: Quantity | None = None
    note: str | None = None

    def describe(self) -> str:
        parts: list[str] = []
        if self.kind == "percentile":
            parts.append(f"P{self.percentile}")
        elif self.kind == "peak":
            parts.append("峰值")
        elif self.kind == "average":
            parts.append("均值")
        elif self.kind == "minimum":
            parts.append("窗口内最低值")
        if self.window is not None:
            parts.append(f"窗口 {fmt_quantity(self.window)}")
        if self.note:
            parts.append(self.note)
        return "，".join(parts) if parts else "未声明"


@dataclass
class Metric:
    """一个指标要求或承诺：比较符号 + 归一化数值 + 统计口径。"""

    indicator: str
    comparator: str  # "le" | "ge"
    value: Quantity | None
    caliber: Caliber
    source: SourceRef

    def describe(self) -> str:
        if self.value is None:
            return f"{self.indicator}（未给出数值）"
        text = f"{self.indicator} {fmt_comparator(self.comparator)} {fmt_quantity(self.value)}"
        caliber = self.caliber.describe()
        if caliber != "未声明":
            text += f"（{caliber}）"
        return text


@dataclass
class Condition:
    """随证据一起带出的工况或限定。"""

    kind: str  # load/load_cap/enable/timing/trigger/access/scope/rule
    text: str
    value: Quantity | None = None
    source: SourceRef | None = None


@dataclass
class CombinationRule:
    """需求书对主/备接入组合的约定。"""

    allow_backup: bool = False
    allow_different_access: bool = False
    same_area_window: bool = False
    source: SourceRef | None = None


@dataclass
class ClauseEvent:
    """条款的一次定义或更正，用于纪要回查时说明变更原因。"""

    doc_id: str
    issued: str
    summary: str
    source: SourceRef | None = None


@dataclass
class ScenarioReq:
    scenario: str
    metrics: dict[str, Metric] = field(default_factory=dict)
    conditions: list[Condition] = field(default_factory=list)


@dataclass
class Clause:
    clause_id: str
    facility: str
    scenarios: dict[str, ScenarioReq] = field(default_factory=dict)
    combination: CombinationRule = field(default_factory=CombinationRule)
    history: list[ClauseEvent] = field(default_factory=list)


@dataclass
class Commitment:
    """供应商材料中的一条承诺（或宣传/意向/说明）。"""

    supplier: str
    part: str  # 正文/附件/条件/澄清
    doc_id: str
    issued: str
    heading: str
    facility: str | None
    scenario: str | None
    scope: str | None
    access: str | None
    metric: Metric | None
    status: str
    availability: str
    conditions: list[Condition] = field(default_factory=list)
    reference: str | None = None       # 如 see_attachment
    resolved: list[str] = field(default_factory=list)  # 指代/引用解析到的文书编号
    source: SourceRef | None = None


@dataclass
class Boundary:
    """项目实办边界：验收范围划分、统计窗口与现场确认记录。"""

    doc_id: str
    facility: str
    scopes: list[str]
    calibers: dict[str, Caliber] = field(default_factory=dict)
    expected: dict[str, Quantity] = field(default_factory=dict)
    rules: list[Condition] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


@dataclass
class Item:
    """验收项：条款 × 场景 × 范围，是覆盖评估与验收安排的最小单位。"""

    item_id: str
    clause_id: str
    scenario: str
    facility: str
    scope: str | None
    metrics: dict[str, Metric]
    conditions: list[Condition]
    sources: list[SourceRef]

    def label(self) -> str:
        parts = [self.clause_id, self.facility, self.scenario]
        if self.scope:
            parts.append(self.scope)
        return " · ".join(parts)


@dataclass
class Evidence:
    commitment: Commitment
    role: str  # 主证据/组合/支持/指针


@dataclass
class Premise:
    """验收前提；key 相同的前提在多个验收项之间共享。"""

    key: str
    text: str
    source: str


@dataclass
class Question:
    audience: str  # 供应商/采购方
    text: str


@dataclass
class MetricResult:
    indicator: str
    status: str
    reasons: list[str] = field(default_factory=list)


@dataclass
class Coverage:
    """一个供应商在一个验收项上的覆盖结论。"""

    supplier: str
    item: Item
    status: str
    metric_results: list[MetricResult] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    premises: list[Premise] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
