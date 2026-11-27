"""需求书、答疑与补遗 → 现行需求基线。

terms.jsonl 中的记录按 issued 顺序构成更正链：首条为需求书，后续
答疑/补遗按正文约束逐条更正。未更正的同号条款继续有效。基线保留
每一次定义与更正（ClauseEvent），供纪要回查时说明变更原因；传入
as_of 可重建某一日期时的有效基线。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .model import (
    Clause,
    ClauseEvent,
    Condition,
    Metric,
    ScenarioReq,
    SourceRef,
)
from .parsing import (
    SegmentContext,
    bind_metrics,
    detect_facility,
    detect_scenarios,
    make_ref,
    split_segments,
)
from .units import Quantity

CLAUSE_HEAD_RE = re.compile(r"T\d+(?:\s*和\s*T\d+)*")
CLAUSE_ID_RE = re.compile(r"T\d+")


@dataclass
class Baseline:
    clauses: dict[str, Clause] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)  # 未解析、需人工处理的更正句
    applied: list[str] = field(default_factory=list)  # 已应用的文书编号

    @classmethod
    def build(cls, rows: list[dict], as_of: str | None = None) -> "Baseline":
        baseline = cls()
        ordered = sorted(rows, key=lambda row: (row["issued"], row["id"]))
        for row in ordered:
            if as_of is not None and row["issued"] > as_of:
                continue
            if row["type"] == "requirements":
                baseline._parse_requirements(row)
            else:
                baseline._parse_amendment(row)
            baseline.applied.append(row["id"])
        return baseline

    # ---- 需求书 ----

    def _parse_requirements(self, row: dict) -> None:
        text = row["text"]
        for clause_ids, start, end, chunk in split_clause_chunks(text):
            if len(clause_ids) != 1:
                self.notes.append(f"{row['id']}：未能归并的联合条款「{chunk}」")
                continue
            clause_id = clause_ids[0]
            facility = detect_facility(chunk)
            clause = Clause(clause_id=clause_id, facility=facility or "")
            ctx = SegmentContext(facility=facility)
            for seg_start, seg_end, segment in split_segments(chunk):
                abs_start, abs_end = start + seg_start, start + seg_end
                ref = make_ref(row["id"], row["type"], abs_start, abs_end, text)
                if self._requirement_keyword_rules(clause, segment, ref):
                    continue
                ctx.update(segment)
                scenarios = detect_scenarios(segment)
                if ctx.scenario and not scenarios:
                    scenarios = [ctx.scenario]
                for draft in bind_metrics(segment, ctx):
                    targets = scenarios or ([ctx.scenario] if ctx.scenario else [])
                    for scenario in targets:
                        sreq = clause.scenarios.setdefault(scenario, ScenarioReq(scenario))
                        sreq.metrics[draft.indicator] = Metric(
                            draft.indicator, draft.comparator, draft.value,
                            draft.caliber, ref)
            clause.history.append(ClauseEvent(
                row["id"], row["issued"], f"定义 {clause_id}（{clause.facility}）",
                make_ref(row["id"], row["type"], start, end, text)))
            self.clauses[clause_id] = clause

    def _requirement_keyword_rules(self, clause: Clause, segment: str,
                                   ref: SourceRef) -> bool:
        """需求书正文中的非指标句：负载定义、接入组合、触发条件等。"""
        load = re.search(r"满载指\s*(\d+)\s*台", segment)
        if load:
            quantity = Quantity("count", float(load.group(1)), "台", load.group(0))
            sreq = clause.scenarios.setdefault("满载", ScenarioReq("满载"))
            sreq.conditions.append(Condition("load", f"满载指 {load.group(1)} 台终端同时工作",
                                             quantity, ref))
            return True
        if "可使用主接入或约定备接入" in segment:
            clause.combination.allow_backup = True
            clause.combination.source = ref
            return True
        if "不可用时" in segment or "不可用" in segment and "接替" not in segment:
            sreq = clause.scenarios.setdefault("接替", ScenarioReq("接替"))
            sreq.conditions.append(Condition("trigger", "主链路不可用", None, ref))
            return False  # 同句可能还有指标（如“在60秒内恢复”），继续解析
        if "施工期间" in segment:
            sreq = clause.scenarios.setdefault("施工期间", ScenarioReq("施工期间"))
            sreq.conditions.append(Condition("timing", "有线施工期间", None, ref))
            return False
        return False

    # ---- 答疑与补遗 ----

    def _parse_amendment(self, row: dict) -> None:
        text = row["text"]
        for clause_ids, start, end, chunk in split_clause_chunks(text):
            for seg_start, seg_end, segment in split_segments(chunk):
                ref = make_ref(row["id"], row["type"], start + seg_start,
                               start + seg_end, text)
                self._apply_amendment_segment(row, clause_ids, segment, ref)

    def _apply_amendment_segment(self, row: dict, clause_ids: list[str],
                                 segment: str, ref: SourceRef) -> None:
        load = re.search(r"改为\s*(\d+)\s*台", segment)
        if load:
            for clause_id in clause_ids:
                clause = self.clauses.get(clause_id)
                if clause is None:
                    continue
                sreq = clause.scenarios.get("满载")
                old = next((c for c in (sreq.conditions if sreq else [])
                            if c.kind == "load"), None)
                if sreq is None:
                    continue
                new_value = float(load.group(1))
                sreq.conditions = [c for c in sreq.conditions if c.kind != "load"]
                sreq.conditions.append(Condition(
                    "load", f"满载试验改为 {load.group(1)} 台终端",
                    Quantity("count", new_value, "台", load.group(0)), ref))
                summary = (f"{clause_id} 满载工况由 {old.value.value:g} 台改为 "
                           f"{new_value:g} 台") if old and old.value else (
                    f"{clause_id} 满载工况定为 {new_value:g} 台")
                clause.history.append(ClauseEvent(row["id"], row["issued"], summary, ref))
            return
        if "允许主、备使用不同接入" in segment:
            for clause_id in clause_ids:
                clause = self.clauses.get(clause_id)
                if clause is None:
                    continue
                clause.combination.allow_different_access = True
                clause.combination.source = ref
                clause.history.append(ClauseEvent(
                    row["id"], row["issued"],
                    f"{clause_id} 允许主、备使用不同接入，接替期间同一测区与统计窗口不变",
                    ref))
            return
        if "同一测区与统计窗口不变" in segment:
            for clause_id in clause_ids:
                clause = self.clauses.get(clause_id)
                if clause is None:
                    continue
                clause.combination.same_area_window = True
                clause.combination.source = clause.combination.source or ref
            return
        if "从业务恢复起算" in segment:
            for clause_id in clause_ids:
                clause = self.clauses.get(clause_id)
                if clause is None:
                    continue
                for sreq in clause.scenarios.values():
                    sreq.conditions.append(Condition(
                        "timing", "时长自业务恢复起算", None, ref))
                clause.history.append(ClauseEvent(
                    row["id"], row["issued"], f"{clause_id} 时长自业务恢复起算", ref))
            return
        if "由园区划定" in segment:
            for clause_id in clause_ids:
                clause = self.clauses.get(clause_id)
                if clause is None:
                    continue
                for sreq in clause.scenarios.values():
                    sreq.conditions.append(Condition("note", segment, None, ref))
            return
        if re.search(r"照旧|不变", segment):
            return  # 明确维持现状，无需改动（放在具体规则之后，避免吞掉“窗口不变”）
        self.notes.append(f"{row['id']}：未解析的更正句「{segment}」，需人工处理")


def split_clause_chunks(text: str) -> list[tuple[list[str], int, int, str]]:
    """按条款号（T1、T2……）切分正文，返回（条款号列表, 起, 止, 片段）。"""
    heads = list(CLAUSE_HEAD_RE.finditer(text))
    chunks: list[tuple[list[str], int, int, str]] = []
    for index, head in enumerate(heads):
        end = heads[index + 1].start() if index + 1 < len(heads) else len(text)
        chunk = text[head.start():end]
        chunks.append((CLAUSE_ID_RE.findall(head.group()), head.start(), end, chunk))
    return chunks
