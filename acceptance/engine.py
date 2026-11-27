"""验收项推导与逐供应商覆盖评估。

评估规则要点：

- 每个供应商分别判断，不用一家的承诺补另一家的缺项；
- 同一句需求拆出的每个场景（平时/满载、东区/西区）各自核对，一个
  场景的高指标不盖另一个场景的缺项；
- 宣传与意向不作为验收依据；需采购方另选的项目未经确认不当作默认；
- 附件沿用的工况与限定（负载上限、测区、窗口、启用条件）随证据带出；
- 正文与附件组合才满足一个场景时，核对需求书是否允许跨接入方式组合，
  以及切换前后的触发条件与统计窗口是否一致；
- 不出总体分数，每个验收项单独给结论、理由、证据位置与待澄清问题。
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .model import (
    CONFLICT,
    COVERED,
    DEFAULT,
    GAP,
    INTENT,
    MARKETING,
    NEEDS_CONFIRMATION,
    NEEDS_EVIDENCE,
    OPTIONAL,
    STATUS_RANK,
    VERIFIABLE,
    Boundary,
    Clause,
    Commitment,
    Coverage,
    Evidence,
    Item,
    Metric,
    MetricResult,
    Premise,
    Question,
)
from .units import GE, fmt_comparator, fmt_quantity


def derive_items(baseline, boundaries: dict[str, Boundary]) -> list[Item]:
    """条款 × 场景 × 条件表范围 → 验收项。"""
    items: list[Item] = []
    for clause_id in sorted(baseline.clauses):
        clause = baseline.clauses[clause_id]
        boundary = boundaries.get(clause.facility)
        boundary_scopes = boundary.scopes if boundary else []
        area_scopes = [s for s in boundary_scopes if s not in clause.scenarios]
        for scenario in sorted(clause.scenarios):
            sreq = clause.scenarios[scenario]
            metrics = {indicator: _merge_caliber(metric, boundary)
                       for indicator, metric in sreq.metrics.items()}
            scopes = area_scopes if area_scopes else [None]
            for scope in scopes:
                item_id = f"{clause_id}·{scenario}" + (f"·{scope}" if scope else "")
                sources = [metric.source for metric in sreq.metrics.values()]
                sources += [c.source for c in sreq.conditions if c.source]
                items.append(Item(
                    item_id=item_id, clause_id=clause_id, scenario=scenario,
                    facility=clause.facility, scope=scope, metrics=metrics,
                    conditions=list(sreq.conditions), sources=sources))
    return items


def _merge_caliber(metric: Metric, boundary: Boundary | None) -> Metric:
    if boundary is None:
        return metric
    extra = boundary.calibers.get(metric.indicator)
    if extra is None:
        return metric
    caliber = metric.caliber
    merged = type(caliber)(
        kind=caliber.kind or extra.kind,
        percentile=caliber.percentile or extra.percentile,
        window=caliber.window or extra.window,
        note=caliber.note or extra.note,
    )
    return Metric(metric.indicator, metric.comparator, metric.value, merged, metric.source)


@dataclass
class _MetricEval:
    status: str
    reasons: list[str] = field(default_factory=list)
    evidence: list[Evidence] = field(default_factory=list)
    premises: list[Premise] = field(default_factory=list)
    questions: list[Question] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)


def evaluate_supplier(supplier: str, items: list[Item], commitments: list[Commitment],
                      clauses: dict[str, Clause],
                      boundaries: dict[str, Boundary]) -> list[Coverage]:
    coverages: list[Coverage] = []
    for item in items:
        coverages.append(_evaluate_item(supplier, item, commitments,
                                        clauses.get(item.clause_id),
                                        boundaries.get(item.facility)))
    return coverages


def _evaluate_item(supplier: str, item: Item, commitments: list[Commitment],
                   clause: Clause | None, boundary: Boundary | None) -> Coverage:
    relevant = [c for c in commitments
                if c.supplier == supplier and c.facility == item.facility
                and (c.scenario is None or c.scenario == item.scenario)
                and (item.scope is None or c.scope is None or c.scope == item.scope)]
    coverage = Coverage(supplier=supplier, item=item, status=COVERED)
    for indicator, required in item.metrics.items():
        result = _evaluate_metric(supplier, item, indicator, required, relevant,
                                  clause, boundary)
        coverage.metric_results.append(MetricResult(indicator, result.status,
                                                    list(result.reasons)))
        coverage.evidence.extend(result.evidence)
        coverage.premises.extend(result.premises)
        coverage.questions.extend(result.questions)
        coverage.notes.extend(result.notes)
        coverage.reasons.extend(result.reasons)
    # 无指标承诺但有关联说明（如“另提供独立接入服务”）
    for commitment in relevant:
        if commitment.metric is None and commitment.status == VERIFIABLE \
                and commitment.reference is None:
            if commitment.availability == OPTIONAL:
                coverage.notes.append(
                    f"{commitment.doc_id}「{commitment.source.excerpt}」属需采购方另选项目，"
                    "未经确认不作为默认依据")
            else:
                coverage.notes.append(
                    f"{commitment.doc_id}「{commitment.source.excerpt}」未给出指标数值")
    coverage.status = _worst(r.status for r in coverage.metric_results)
    coverage.premises.extend(_item_premises(item, clause, boundary, coverage))
    coverage.evidence = _dedupe_evidence(coverage.evidence)
    coverage.premises = _dedupe_premises(coverage.premises)
    return coverage


def _dedupe_evidence(evidence: list[Evidence]) -> list[Evidence]:
    seen: set[tuple] = set()
    out: list[Evidence] = []
    for entry in evidence:
        key = (entry.commitment.doc_id, entry.role)
        if key not in seen:
            seen.add(key)
            out.append(entry)
    return out


def _dedupe_premises(premises: list[Premise]) -> list[Premise]:
    seen: set[str] = set()
    out: list[Premise] = []
    for premise in premises:
        if premise.key not in seen:
            seen.add(premise.key)
            out.append(premise)
    return out


def _worst(statuses) -> str:
    return max(statuses, key=lambda s: STATUS_RANK[s])


def _evaluate_metric(supplier: str, item: Item, indicator: str, required: Metric,
                     relevant: list[Commitment], clause: Clause | None,
                     boundary: Boundary | None) -> _MetricEval:
    result = _MetricEval(status=COVERED)
    candidates = [c for c in relevant if c.metric and c.metric.indicator == indicator]
    verifiable = [c for c in candidates if c.status == VERIFIABLE]
    intents = [c for c in candidates if c.status == INTENT]
    marketing = [c for c in candidates if c.status == MARKETING]
    for commitment in marketing:
        result.notes.append(
            f"{commitment.doc_id}「{commitment.source.excerpt}」为宣传数据，不作为验收依据")
    for commitment in intents:
        result.notes.append(
            f"{commitment.doc_id}「{commitment.source.excerpt}」为意向，尚未签入验收")
    for commitment in [c for c in verifiable if c.availability == OPTIONAL]:
        result.notes.append(
            f"{commitment.doc_id}「{commitment.source.excerpt}」属需采购方另选项目，"
            "未经确认不作为默认依据")

    requirement_text = required.describe()
    if not verifiable:
        result.status = NEEDS_EVIDENCE if (intents or marketing) else GAP
        if intents:
            result.reasons.append(f"{indicator}仅有意向（{intents[0].doc_id}），无可验收承诺")
            result.questions.append(Question(
                "供应商", f"【{supplier}·{item.label()}】{intents[0].doc_id} 的"
                f"「{intents[0].source.excerpt}」尚未签入验收，请{supplier}提交"
                f"{requirement_text}的可验收承诺。"))
        elif marketing:
            result.reasons.append(f"{indicator}仅有宣传数据（{marketing[0].doc_id}）")
            result.questions.append(Question(
                "供应商", f"【{supplier}·{item.label()}】{marketing[0].doc_id} 的"
                f"「{marketing[0].source.excerpt}」为宣传数据，请{supplier}提交"
                f"{requirement_text}的可验收承诺。"))
        else:
            result.reasons.append(f"{indicator}无承诺")
            result.questions.append(Question(
                "供应商", f"【{supplier}·{item.label()}】缺少{requirement_text}的承诺，"
                f"请{supplier}补充。"))
        return result

    defaults = [c for c in verifiable if c.availability == DEFAULT]
    optionals = [c for c in verifiable if c.availability == OPTIONAL]
    if not defaults:
        effective = _select_effective(optionals, item)
        result.status = NEEDS_CONFIRMATION
        value_note = _value_note(effective, required)
        enable = _enable_text(effective, boundary)
        result.reasons.append(
            f"{indicator}仅有需采购方另选的承诺（{effective[0].doc_id}）{value_note}")
        result.evidence.extend(Evidence(c, "主证据") for c in effective)
        result.questions.append(Question(
            "采购方", f"【{supplier}·{item.label()}】{effective[0].doc_id} 的承诺"
            f"（{effective[0].source.excerpt}）以{enable}为生效条件，属需采购方另选项目。"
            f"请采购方确认是否选用；未经确认不列入默认验收。"))
        result.premises.extend(_enable_premises(effective, boundary))
        return result

    effective = _select_effective(defaults, item)
    result.evidence.extend(Evidence(c, "主证据") for c in effective)
    result.evidence.extend(_chain_evidence(effective, relevant))

    # 数值核对
    missing = [c for c in effective if c.metric.value is None]
    if missing:
        result.status = NEEDS_EVIDENCE
        result.reasons.append(f"{missing[0].doc_id} 未给出{indicator}数值")
        result.questions.append(Question(
            "供应商", f"【{supplier}·{item.label()}】{missing[0].doc_id} 的承诺未给出"
            f"{indicator}数值，请{supplier}明确{requirement_text}。"))
        return result
    failed = [c for c in effective if not _satisfies(c.metric, required)]
    if failed:
        commitment = failed[0]
        result.status = CONFLICT
        result.reasons.append(
            f"{commitment.doc_id} 承诺{commitment.metric.describe()}，"
            f"与需求{requirement_text}冲突")
        result.questions.append(Question(
            "供应商", f"【{supplier}·{item.label()}】{commitment.doc_id} 承诺"
            f"「{commitment.source.excerpt}」，与需求{requirement_text}冲突，"
            f"请{supplier}确认是否调整方案或承诺。"))
        return result
    result.reasons.append(
        f"{effective[0].doc_id} 承诺{effective[0].metric.describe()}，"
        f"数值达到需求{required.indicator} {fmt_comparator(required.comparator)} "
        f"{fmt_quantity(required.value)}")

    # 统计口径核对
    problem = _caliber_problem(required.caliber, effective[0].metric.caliber)
    if problem:
        result.status = NEEDS_EVIDENCE
        result.reasons.append(
            f"{effective[0].doc_id} 口径（{effective[0].metric.caliber.describe()}）"
            f"与验收口径（{required.caliber.describe()}）不一致：{problem}")
        result.questions.append(Question(
            "供应商", f"【{supplier}·{item.label()}】{effective[0].doc_id} 的{indicator}"
            f"为{effective[0].metric.caliber.describe()}，与验收口径"
            f"{required.caliber.describe()}不一致。请{supplier}确认窗口内最低值"
            f"是否满足{requirement_text}。"))
        return result
    if effective[0].metric.caliber.kind is None and required.caliber.kind is not None:
        result.premises.append(Premise(
            f"口径继承/{indicator}",
            f"{effective[0].doc_id} 未声明{indicator}口径，按验收口径"
            f"（{required.caliber.describe()}）列入前提",
            required.source.doc_id))

    # 工况核对：承诺负载上限不得低于需求工况
    required_load = _condition_value(item.conditions, "load")
    for commitment in effective:
        cap = _condition_value(commitment.conditions, "load_cap")
        if required_load and cap and cap.value < required_load.value:
            rule = _rule_text(boundary, "load_no_substitute")
            result.status = NEEDS_EVIDENCE
            result.reasons.append(
                f"{commitment.doc_id} 承诺上限 {fmt_quantity(cap)}，"
                f"需求工况 {fmt_quantity(required_load)}{'；' + rule if rule else ''}")
            result.questions.append(Question(
                "供应商", f"【{supplier}·{item.label()}】{commitment.doc_id} 承诺上限"
                f"{fmt_quantity(cap)}，需求工况为{fmt_quantity(required_load)}"
                f"{'，' + rule if rule else ''}。请{supplier}提交该工况下"
                f"{requirement_text}的可验收承诺。"))
            return result
        load = _condition_value(commitment.conditions, "load")
        if required_load and load and load.value < required_load.value:
            result.status = NEEDS_EVIDENCE
            result.reasons.append(
                f"{commitment.doc_id} 承诺负载 {fmt_quantity(load)}，"
                f"低于需求工况 {fmt_quantity(required_load)}")
            result.questions.append(Question(
                "供应商", f"【{supplier}·{item.label()}】{commitment.doc_id} 承诺负载"
                f"{fmt_quantity(load)}，低于需求工况{fmt_quantity(required_load)}，"
                f"请{supplier}补充承诺。"))
            return result

    # 启用条件核对
    enable_conditions = [cond for c in effective for cond in c.conditions
                         if cond.kind == "enable"]
    if enable_conditions:
        result.status = NEEDS_CONFIRMATION
        result.reasons.append(
            f"{effective[0].doc_id} 以「{enable_conditions[0].text}」为生效条件")
        result.questions.append(Question(
            "采购方", f"【{supplier}·{item.label()}】{effective[0].doc_id} 的承诺以"
            f"「{enable_conditions[0].text}」为生效条件，请采购方确认是否满足；"
            f"未经确认不列入默认验收。"))
        result.premises.extend(_enable_premises(effective, boundary))
        return result

    result.premises.extend(_combination_premise(effective, result.evidence, clause,
                                                supplier, item, result))
    return result


def _select_effective(pool: list[Commitment], item: Item) -> list[Commitment]:
    """同一指标取最新有效承诺：范围精确的优先，同范围取最新发布。"""
    specific = [c for c in pool if c.scope is not None and c.scope == item.scope]
    general = [c for c in pool if c.scope is None]
    group = specific or general
    if not group:
        return []
    latest = max(c.issued for c in group)
    return [c for c in group if c.issued == latest]


def _chain_evidence(effective: list[Commitment],
                    relevant: list[Commitment]) -> list[Evidence]:
    """正文“按附件执行”等指针与范围澄清，随主证据一起带出。"""
    docs = {c.doc_id for c in effective}
    chain: list[Evidence] = []
    for commitment in relevant:
        if commitment.reference == "see_attachment" and set(commitment.resolved) & docs:
            chain.append(Evidence(commitment, "指针"))
        if commitment.reference == "scope_clarification" and set(commitment.resolved) & docs:
            chain.append(Evidence(commitment, "支持"))
    return chain


def _satisfies(offered: Metric, required: Metric) -> bool:
    if offered.value is None or required.value is None:
        return False
    if required.comparator == GE:
        return offered.value.value >= required.value.value
    return offered.value.value <= required.value.value


def _value_note(effective: list[Commitment], required: Metric) -> str:
    if not effective or effective[0].metric.value is None or required.value is None:
        return ""
    if _satisfies(effective[0].metric, required):
        return f"，数值本身满足（{effective[0].metric.describe()}）"
    return f"，且数值不满足（{effective[0].metric.describe()} vs 需求{required.describe()}）"


def _caliber_problem(required, offered) -> str | None:
    if required.kind is None or offered.kind is None:
        return None
    if required.kind == "percentile":
        if offered.kind == "percentile" and offered.percentile == required.percentile:
            return None
        return f"承诺为{offered.describe()}"
    if required.kind == "minimum":
        if offered.kind == "minimum":
            if required.window and offered.window \
                    and required.window.value != offered.window.value:
                return (f"统计窗口不一致（承诺 {fmt_quantity(offered.window)}，"
                        f"要求 {fmt_quantity(required.window)}）")
            return None
        return f"承诺为{offered.describe()}"
    return None


def _condition_value(conditions, kind):
    for condition in conditions:
        if condition.kind == kind and condition.value is not None:
            return condition.value
    return None


def _rule_text(boundary: Boundary | None, kind: str) -> str:
    if boundary is None:
        return ""
    for rule in boundary.rules:
        if rule.kind == kind:
            return f"{boundary.doc_id} 明确：{rule.text}"
    return ""


def _enable_text(effective: list[Commitment], boundary: Boundary | None) -> str:
    for commitment in effective:
        for condition in commitment.conditions:
            if condition.kind == "enable":
                return f"「{condition.text}」"
    return "采购方另选"


def _enable_premises(effective: list[Commitment], boundary: Boundary | None) -> list[Premise]:
    premises: list[Premise] = []
    for commitment in effective:
        for condition in commitment.conditions:
            if condition.kind == "enable":
                premises.append(Premise(
                    f"启用条件/{condition.text}",
                    f"生效条件：{condition.text}（{commitment.doc_id}）",
                    commitment.doc_id))
    if boundary is not None:
        for rule in boundary.rules:
            if rule.kind == "enable_unconfirmed":
                premises.append(Premise(
                    f"现场确认/{boundary.doc_id}",
                    f"{boundary.doc_id}：{rule.text}", boundary.doc_id))
    return premises


def _combination_premise(effective: list[Commitment], evidence: list[Evidence],
                         clause: Clause | None, supplier: str, item: Item,
                         result: _MetricEval) -> list[Premise]:
    """正文与附件组合才满足时，核对需求书是否允许跨接入方式组合。"""
    docs = {e.commitment.doc_id for e in evidence}
    if clause is None or clause.combination.source is None or len(docs) < 2:
        return []
    parts = []
    if clause.combination.allow_different_access:
        parts.append("需求允许主、备使用不同接入")
    elif clause.combination.allow_backup:
        parts.append("需求允许使用约定备接入")
    if clause.combination.same_area_window:
        parts.append("接替期间同一测区与统计窗口不变")
    if not parts:
        result.questions.append(Question(
            "采购方", f"【{supplier}·{item.label()}】证据跨多份材料（{'、'.join(sorted(docs))}），"
            "需求书未明确是否允许跨接入方式组合，请确认。"))
        return []
    source = clause.combination.source
    return [Premise(f"组合/{item.clause_id}",
                    "；".join(parts) + f"（{source.doc_id}）", source.doc_id)]


def _item_premises(item: Item, clause: Clause | None, boundary: Boundary | None,
                   coverage: Coverage) -> list[Premise]:
    """随验收项带出的工况与限定：窗口、触发、负载、起算点、共享切换约束。"""
    premises: list[Premise] = []
    if coverage.status not in (COVERED, NEEDS_CONFIRMATION):
        return premises
    for indicator, metric in item.metrics.items():
        if metric.caliber.window is not None and boundary is not None:
            premises.append(Premise(
                f"窗口/{indicator}",
                f"{indicator}统计窗口 {fmt_quantity(metric.caliber.window)}"
                f"（{boundary.doc_id}）", boundary.doc_id))
    for condition in item.conditions:
        if condition.kind == "trigger":
            premises.append(Premise(
                f"触发/{condition.text}", f"触发条件：{condition.text}"
                f"（{condition.source.doc_id}）", condition.source.doc_id))
        elif condition.kind == "load" and condition.value is not None:
            premises.append(Premise(
                f"工况/{item.scenario}", f"{item.scenario}工况 "
                f"{fmt_quantity(condition.value)}（{condition.source.doc_id}）",
                condition.source.doc_id))
        elif condition.kind == "timing":
            premises.append(Premise(
                f"起算/{condition.text}", f"{condition.text}"
                f"（{condition.source.doc_id}）", condition.source.doc_id))
    for evidence in coverage.evidence:
        for condition in evidence.commitment.conditions:
            if condition.kind == "load_cap" and condition.value is not None:
                premises.append(Premise(
                    f"承诺上限/{evidence.commitment.doc_id}",
                    f"供应商承诺上限 {fmt_quantity(condition.value)}"
                    f"（{evidence.commitment.doc_id}）", evidence.commitment.doc_id))
    if item.scope:
        premises.append(Premise(f"测区/{item.scope}", f"测区：{item.scope}",
                                item.sources[0].doc_id if item.sources else ""))
    if boundary is not None:
        for rule in boundary.rules:
            if rule.kind == "shared_switch":
                premises.append(Premise(
                    f"共享切换/{boundary.doc_id}",
                    f"{boundary.doc_id}：{rule.text}", boundary.doc_id))
    return premises


def evaluate_all(suppliers: list[str], items: list[Item],
                 commitments: list[Commitment], clauses: dict[str, Clause],
                 boundaries: dict[str, Boundary]) -> dict[str, list[Coverage]]:
    """各家应答分别判断，互不借用承诺。"""
    return {supplier: evaluate_supplier(supplier, items, commitments, clauses, boundaries)
            for supplier in suppliers}
