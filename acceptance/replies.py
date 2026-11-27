"""供应商正文/附件/条件/澄清 → 分类承诺。

行文状态分为可验收承诺、意向、宣传与说明：含“有望/尚未签入”的为
意向，只有峰值/点测而无保证字样的为宣传，均不作为验收依据。可用性
区分默认与需采购方另选：另选项未经确认不当作合同默认启用。

同一份材料内的“相同上限/同正文口径/均值口径”等指代在供应商全部
材料解析完后统一解析；“按附件执行”等引用解析到同供应商的附件。
每条承诺保留原文位置，解析不了的指代保留为说明，不静默丢弃。
"""
from __future__ import annotations

import re

from .model import (
    DEFAULT,
    INTENT,
    MARKETING,
    NOTE,
    OPTIONAL,
    RECOVERY,
    THROUGHPUT,
    INDEPENDENCE,
    VERIFIABLE,
    Commitment,
    Condition,
    Metric,
)
from .parsing import (
    SegmentContext,
    bind_metrics,
    detect_facility,
    detect_scope,
    make_ref,
    split_segments,
)
from .units import Quantity, parse_quantities

INTENT_WORDS = ("有望", "尚未签入", "预计", "力争")
GUARANTEE_WORDS = ("承诺", "保证", "须", "需", "提供", "纳入默认", "默认包含")
MARKETING_WORDS = ("峰值", "点测", "实测")
OPTIONAL_WORDS = ("可额外选择", "另选", "增值", "客户选择")

_ANAPHORA = {
    "same_level": ("相同上限", "相同水平"),
    "same_as_main": ("同正文口径",),
    "main_average": ("均值口径",),
}

_DEFAULT_SCENARIO = {
    RECOVERY: "接替",
    THROUGHPUT: "接替",
    INDEPENDENCE: "施工期间",
}


def parse_replies(rows: list[dict], as_of: str | None = None,
                  area_facility: dict[str, str] | None = None) -> list[Commitment]:
    """解析全部供应商材料，按供应商分组处理以支持跨材料指代。

    area_facility 给出区域（东区/西区等）所属设施（来自条件表），
    用于定位“西区的无线接替……”这类只写区域、不写设施名的句子。
    """
    commitments: list[Commitment] = []
    suppliers = sorted({row["supplier"] for row in rows})
    for supplier in suppliers:
        own = [row for row in rows if row["supplier"] == supplier]
        own.sort(key=lambda row: (row["issued"], row["id"]))
        mine: list[Commitment] = []
        for row in own:
            if as_of is not None and row["issued"] > as_of:
                continue
            mine.extend(_parse_reply(row, area_facility or {}))
        _resolve_anaphora(mine)
        _resolve_pointers(mine)
        commitments.extend(mine)
    return commitments


def _parse_reply(row: dict, area_facility: dict[str, str]) -> list[Commitment]:
    text = row["prose"]
    kind = row["part"]
    out: list[Commitment] = []
    ctx = SegmentContext()
    for seg_start, seg_end, segment in split_segments(text):
        ref = make_ref(row["id"], kind, seg_start, seg_end, text)
        facility = detect_facility(segment)
        if facility and facility != ctx.facility:
            ctx.scope, ctx.scenario, ctx.access = None, None, None
            ctx.pending.clear()
        ctx.update(segment)
        scope_word = detect_scope(segment)
        if scope_word and not facility and area_facility.get(scope_word):
            ctx.facility = area_facility[scope_word]

        if re.search(r"附件.*指(?:东区|西区)", segment):
            out.append(_bare(row, ctx, ref, status=NOTE,
                             reference="scope_clarification", scope=detect_scope(segment)))
            continue
        if re.search(r"按附件执行|见附件", segment):
            out.append(_bare(row, ctx, ref, reference="see_attachment"))
            continue
        cap = re.search(r"上限为\s*(\d+)\s*台", segment)
        if cap:
            condition = Condition("load_cap", f"上限为 {cap.group(1)} 台终端",
                                  Quantity("count", float(cap.group(1)), "台", cap.group(0)), ref)
            for commitment in out:
                if commitment.facility == ctx.facility:
                    commitment.conditions.append(condition)
            continue
        if re.fullmatch(r"\d+\s*台(?:终端)?", segment):
            load = re.match(r"(\d+)", segment)
            condition = Condition("load", f"{load.group(1)} 台",
                                  Quantity("count", float(load.group(1)), "台", segment), ref)
            for commitment in out:
                if commitment.facility == ctx.facility and commitment.scenario is None:
                    commitment.scenario = "满载"
                if commitment.facility == ctx.facility:
                    commitment.conditions.append(condition)
            continue
        anaphora = _detect_anaphora(segment)
        if anaphora:
            placeholder = _bare(row, ctx, ref, reference=f"anaphora:{anaphora}")
            if any(word in segment for word in INTENT_WORDS):
                placeholder.status = INTENT
            for quantity in _counts(segment):
                placeholder.conditions.append(Condition("load", quantity.raw, quantity, ref))
                placeholder.scenario = placeholder.scenario or "满载"
            out.append(placeholder)
            continue
        enable = re.search(r"在客户选择(.+?)时生效", segment)
        if enable:
            for commitment in out:
                if commitment.facility == ctx.facility:
                    commitment.availability = OPTIONAL
                    commitment.conditions.append(
                        Condition("enable", f"在客户选择{enable.group(1)}时生效", None, ref))
            continue
        if any(word in segment for word in INTENT_WORDS) and not _has_metric_words(segment):
            for commitment in out:
                if commitment.facility == ctx.facility:
                    commitment.status = INTENT
            continue

        drafts = bind_metrics(segment, ctx)
        if not drafts:
            if re.search(r"可额外选择|另选", segment) or "提供" in segment:
                out.append(_bare(row, ctx, ref))
            continue
        for draft in drafts:
            scenario = ctx.scenario or _DEFAULT_SCENARIO.get(draft.indicator)
            out.append(Commitment(
                supplier=row["supplier"], part=kind, doc_id=row["id"],
                issued=row["issued"], heading=row["heading"],
                facility=ctx.facility, scenario=scenario, scope=ctx.scope,
                access=ctx.access,
                metric=Metric(draft.indicator, draft.comparator, draft.value,
                              draft.caliber, ref),
                status=_classify(segment), availability=_availability(segment),
                source=ref))
    return _expand_scopes(out)


def _expand_scopes(commitments: list[Commitment]) -> list[Commitment]:
    """“两区”承诺展开为东区、西区两条，便于按范围分别核对。"""
    import dataclasses

    expanded: list[Commitment] = []
    for commitment in commitments:
        if commitment.scope == "两区":
            for scope in ("东区", "西区"):
                expanded.append(dataclasses.replace(
                    commitment, scope=scope, conditions=list(commitment.conditions)))
        else:
            expanded.append(commitment)
    return expanded


def _bare(row: dict, ctx: SegmentContext, ref, status: str = VERIFIABLE,
          reference: str | None = None, scope: str | None = None) -> Commitment:
    return Commitment(
        supplier=row["supplier"], part=row["part"], doc_id=row["id"],
        issued=row["issued"], heading=row["heading"],
        facility=ctx.facility, scenario=ctx.scenario,
        scope=scope if scope is not None else ctx.scope, access=ctx.access,
        metric=None, status=status, availability=_availability(ref.excerpt),
        reference=reference, source=ref)


def _detect_anaphora(segment: str) -> str | None:
    for kind, words in _ANAPHORA.items():
        if any(word in segment for word in words):
            return kind
    return None


def _counts(segment: str) -> list[Quantity]:
    return [q for q in parse_quantities(segment) if q.kind == "count"]


def _has_metric_words(segment: str) -> bool:
    return bool(re.search(r"时延|RTT|吞吐|接替|恢复|独立|持续|保持", segment))


def _classify(segment: str) -> str:
    if any(word in segment for word in INTENT_WORDS):
        return INTENT
    if any(word in segment for word in GUARANTEE_WORDS):
        return VERIFIABLE
    if any(word in segment for word in MARKETING_WORDS):
        return MARKETING
    return VERIFIABLE


def _availability(segment: str) -> str:
    if any(word in segment for word in OPTIONAL_WORDS):
        return OPTIONAL
    return DEFAULT


def _resolve_anaphora(mine: list[Commitment]) -> None:
    """解析相同上限/同正文口径/均值口径等指代，解析不了保留为说明。"""
    for placeholder in [c for c in mine if (c.reference or "").startswith("anaphora:")]:
        kind = placeholder.reference.split(":", 1)[1]
        earlier = [c for c in mine if c.metric is not None and c is not placeholder
                   and _position(c) <= _position(placeholder)]
        target = None
        if kind == "same_level":
            candidates = [c for c in earlier if c.facility == placeholder.facility]
            target = candidates[-1] if candidates else None
        elif kind == "same_as_main":
            candidates = [c for c in earlier if c.facility == placeholder.facility
                          and c.part == "正文"]
            target = candidates[-1] if candidates else None
        elif kind == "main_average":
            candidates = [c for c in earlier if c.facility == placeholder.facility
                          and c.part == "正文" and c.metric.indicator == THROUGHPUT]
            target = candidates[-1] if candidates else None
        if target is None:
            placeholder.reference = None
            placeholder.status = NOTE
            placeholder.conditions.append(Condition(
                "note", "指代未能解析，需人工核对", None, placeholder.source))
            continue
        source = placeholder.source
        placeholder.metric = Metric(target.metric.indicator, target.metric.comparator,
                                    target.metric.value, target.metric.caliber, source)
        placeholder.resolved = [target.doc_id]
        placeholder.reference = None
        if placeholder.scenario is None:
            placeholder.scenario = _DEFAULT_SCENARIO.get(target.metric.indicator)
        if placeholder.status != INTENT:
            placeholder.status = target.status if target.status != INTENT else VERIFIABLE


def _position(commitment: Commitment) -> tuple:
    start = commitment.source.start if commitment.source else 0
    return (commitment.issued, commitment.doc_id, start)


def _resolve_pointers(mine: list[Commitment]) -> None:
    """把“按附件执行”与范围澄清解析到同供应商的附件材料。"""
    attachments = sorted({c.doc_id for c in mine if c.part == "附件"})
    attachment_facilities = sorted({c.facility for c in mine
                                    if c.part == "附件" and c.facility})
    for commitment in mine:
        if commitment.reference == "see_attachment":
            commitment.resolved = list(attachments)
        elif commitment.reference == "scope_clarification":
            commitment.resolved = list(attachments)
            if commitment.facility is None and attachment_facilities:
                commitment.facility = attachment_facilities[0]
