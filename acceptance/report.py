"""覆盖意见、验收安排与待澄清问题的文本输出。

输出按“可交工程组的验收项 / 需问清的问题 / 纪要回查”组织，逐条
给出证据位置与适用理由，不汇总为总体分数。
"""
from __future__ import annotations

from .model import (
    COVERED,
    INTENT,
    MARKETING,
    Coverage,
)
from .project import Evaluation


def render_report(evaluation: Evaluation, supplier: str | None = None) -> str:
    sections = [render_baseline(evaluation)]
    suppliers = [supplier] if supplier else sorted(evaluation.coverage)
    for name in suppliers:
        sections.append(render_supplier(evaluation, name))
    sections.append(render_arrangements(evaluation, suppliers))
    sections.append(render_questions(evaluation, suppliers))
    sections.append(render_minutes(evaluation))
    sections.append(render_non_commitments(evaluation, suppliers))
    return "\n\n".join(section for section in sections if section)


def render_baseline(evaluation: Evaluation) -> str:
    lines = ["## 一、现行需求基线"]
    for clause_id in sorted(evaluation.baseline.clauses):
        clause = evaluation.baseline.clauses[clause_id]
        lines.append(f"### {clause_id} {clause.facility}")
        for scenario in sorted(clause.scenarios):
            sreq = clause.scenarios[scenario]
            metrics = "；".join(metric.describe() for metric in sreq.metrics.values())
            conditions = "；".join(c.text for c in sreq.conditions)
            lines.append(f"- 场景「{scenario}」：{metrics or '（无指标）'}"
                         + (f"；条件：{conditions}" if conditions else ""))
        if clause.combination.source:
            rule = clause.combination
            parts = []
            if rule.allow_different_access:
                parts.append("允许主、备使用不同接入")
            elif rule.allow_backup:
                parts.append("可使用主接入或约定备接入")
            if rule.same_area_window:
                parts.append("接替期间同一测区与统计窗口不变")
            lines.append(f"- 接入组合：{'；'.join(parts)}（{rule.source.doc_id}）")
        for event in clause.history:
            lines.append(f"- 沿革：{event.doc_id}（{event.issued}）{event.summary}")
    if evaluation.baseline.notes:
        lines.append("- 未解析内容（需人工处理）：")
        for note in evaluation.baseline.notes:
            lines.append(f"  - {note}")
    return "\n".join(lines)


def render_supplier(evaluation: Evaluation, supplier: str) -> str:
    lines = [f"## 二、供应商覆盖意见：{supplier}"]
    for coverage in evaluation.coverage.get(supplier, []):
        lines.append(f"### {coverage.item.label()} — {coverage.status}")
        lines.append(f"- 需求：{_requirement_text(coverage)}")
        if coverage.evidence:
            lines.append("- 证据：")
            for evidence in coverage.evidence:
                commitment = evidence.commitment
                lines.append(
                    f"  - [{evidence.role}] {commitment.doc_id}（{commitment.part}）"
                    f"「{commitment.source.excerpt}」"
                    f"（{commitment.source.locate()}）")
        if coverage.reasons:
            lines.append("- 适用理由：" + "；".join(coverage.reasons))
        if coverage.premises:
            lines.append("- 验收前提：")
            for premise in coverage.premises:
                lines.append(f"  - {premise.text}")
        if coverage.notes:
            lines.append("- 备注：")
            for note in coverage.notes:
                lines.append(f"  - {note}")
        if coverage.questions:
            lines.append("- 待澄清：")
            for question in coverage.questions:
                lines.append(f"  - （问{question.audience}）{question.text}")
    return "\n".join(lines)


def _requirement_text(coverage: Coverage) -> str:
    parts = [metric.describe() for metric in coverage.item.metrics.values()]
    text = "；".join(parts)
    sources = sorted({src.locate() for src in coverage.item.sources})
    return f"{text}（依据：{'；'.join(sources)}）"


def render_arrangements(evaluation: Evaluation, suppliers: list[str]) -> str:
    lines = ["## 三、可交工程组安排的验收项"]
    shared: dict[str, list[str]] = {}
    any_covered = False
    for supplier in suppliers:
        coverages = evaluation.coverage.get(supplier, [])
        covered = [c for c in coverages if c.status == COVERED]
        if not covered:
            continue
        any_covered = True
        lines.append(f"### {supplier}")
        for coverage in covered:
            evidence = "、".join(sorted({e.commitment.doc_id for e in coverage.evidence}))
            lines.append(f"- {coverage.item.label()}（证据：{evidence}）")
            for premise in coverage.premises:
                lines.append(f"  - 前提：{premise.text}")
                shared.setdefault(premise.key, []).append(
                    f"{supplier}/{coverage.item.item_id}")
    if not any_covered:
        lines.append("（当前没有可确认的验收项）")
    shared = {key: items for key, items in shared.items() if len(items) > 1}
    if shared:
        lines.append("### 共享前提（同一前提覆盖多个验收项）")
        for key, items in sorted(shared.items()):
            lines.append(f"- {key}：{'、'.join(sorted(set(items)))}")
    return "\n".join(lines)


def render_questions(evaluation: Evaluation, suppliers: list[str]) -> str:
    lines = ["## 四、需问清的问题（不作总体评分，逐项澄清）"]
    number = 0
    for supplier in suppliers:
        questions = [q for c in evaluation.coverage.get(supplier, [])
                     for q in c.questions]
        if not questions:
            continue
        lines.append(f"### {supplier}")
        for question in questions:
            number += 1
            lines.append(f"{number}. （问{question.audience}）{question.text}")
    if number == 0:
        lines.append("（无）")
    return "\n".join(lines)


def render_minutes(evaluation: Evaluation) -> str:
    lines = ["## 五、会议纪要回查与变更"]
    if not evaluation.reviews:
        lines.append("（无纪要）")
        return "\n".join(lines)
    for review in evaluation.reviews:
        minute = review.minute
        state = {"sent": "已发送", "draft": "草稿"}.get(minute["state"], minute["state"])
        lines.append(f"### {minute['id']} · {minute['vendor']} · {minute['time']} · "
                     f"{state} — 现行状态：{review.validity}")
        lines.append(f"- 纪要原文：「{minute['notes']}」")
        lines.append("- 当时依据：")
        for doc_id, kind, excerpt in review.basis:
            lines.append(f"  - {doc_id}（{kind}）「{excerpt}」")
        if review.as_of:
            then = "；".join(f"{item}={status}"
                             for item, status in sorted(review.as_of.items()))
            lines.append(f"- 当时判断：{then}")
        now = "；".join(f"{item}={status}" for item, status in sorted(review.current.items()))
        lines.append(f"- 现行判断：{now}")
        if review.events:
            lines.append("- 纪要之后的变更：")
            for event in review.events:
                lines.append(f"  - {event}")
        lines.append(f"- 处置建议：{review.suggestion}")
    return "\n".join(lines)


def render_non_commitments(evaluation: Evaluation, suppliers: list[str]) -> str:
    lines = ["## 六、宣传与意向（不作为验收依据）"]
    found = False
    for commitment in evaluation.commitments:
        if suppliers and commitment.supplier not in suppliers:
            continue
        if commitment.status in (MARKETING, INTENT):
            found = True
            lines.append(f"- {commitment.supplier} {commitment.doc_id}"
                         f"（{commitment.part}，{commitment.status}）"
                         f"「{commitment.source.excerpt}」"
                         f"（{commitment.source.locate()}）")
    if not found:
        lines.append("（无）")
    return "\n".join(lines)
