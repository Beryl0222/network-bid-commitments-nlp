"""会议纪要的当时判断回查与失效原因。

每条纪要按发出时间重建当时有效的需求基线与供应商材料，重新评估
相关验收项，再与现行评估对比：补遗调整工况、供应商澄清改变例外
归属时，受影响验收项的结论变化与变更原因逐条列出。已发送纪要的
当时判断保留依据文书与文字位置，可回查。
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

from .boundaries import area_facility_map
from .engine import derive_items, evaluate_supplier
from .model import COVERED, Boundary
from .replies import parse_replies
from .terms import Baseline


@dataclass
class MinuteReview:
    minute: dict
    arranged: list[str]                      # 纪要实际安排的验收项
    related: list[str]                       # 与依据文书相关的全部验收项
    as_of: dict[str, str]                    # 当时的结论
    current: dict[str, str]                  # 现行的结论
    events: list[str] = field(default_factory=list)   # 纪要之后的变更
    validity: str = ""
    suggestion: str = ""
    basis: list[tuple[str, str, str]] = field(default_factory=list)  # (编号, 类型, 摘录)


def review_minutes(minutes: list[dict], terms_rows: list[dict],
                   replies_rows: list[dict],
                   boundaries: dict[str, Boundary]) -> list[MinuteReview]:
    return [_review(minute, terms_rows, replies_rows, boundaries)
            for minute in sorted(minutes, key=lambda m: (m["time"], m["id"]))]


def _review(minute: dict, terms_rows: list[dict], replies_rows: list[dict],
            boundaries: dict[str, Boundary]) -> MinuteReview:
    date = minute["time"][:10]
    vendor = minute["vendor"]
    area_facility = area_facility_map(boundaries)
    baseline_then = Baseline.build(terms_rows, as_of=date)
    commits_then = parse_replies(replies_rows, as_of=date, area_facility=area_facility)
    items_then = derive_items(baseline_then, boundaries)
    cov_then = {c.item.item_id: c for c in evaluate_supplier(
        vendor, items_then, commits_then, baseline_then.clauses, boundaries)}
    baseline_now = Baseline.build(terms_rows)
    commits_now = parse_replies(replies_rows, area_facility=area_facility)
    items_now = derive_items(baseline_now, boundaries)
    cov_now = {c.item.item_id: c for c in evaluate_supplier(
        vendor, items_now, commits_now, baseline_now.clauses, boundaries)}

    basis_ids = set(minute["basis"])
    related = _related_items(basis_ids, cov_then, cov_now, baseline_then, baseline_now)
    arranged = [item_id for item_id in related
                if _mentions(minute["notes"], cov_now.get(item_id, cov_then.get(item_id)).item)]
    if not arranged:
        arranged = list(related)

    review = MinuteReview(
        minute=minute, arranged=arranged, related=related,
        as_of={i: cov_then[i].status for i in related if i in cov_then},
        current={i: cov_now[i].status for i in related if i in cov_now},
        basis=_basis_excerpts(minute, terms_rows, replies_rows))
    review.events = _events(date, vendor, arranged, cov_now, baseline_now,
                            replies_rows, commits_now)
    review.validity, review.suggestion = _judge(minute, review)
    return review


def _related_items(basis_ids, cov_then, cov_now, baseline_then, baseline_now) -> list[str]:
    related: set[str] = set()
    for coverages, baseline in ((cov_then, baseline_then), (cov_now, baseline_now)):
        for item_id, coverage in coverages.items():
            clause = baseline.clauses.get(coverage.item.clause_id)
            if clause and any(event.doc_id in basis_ids for event in clause.history):
                related.add(item_id)
            if any(ev.commitment.doc_id in basis_ids for ev in coverage.evidence):
                related.add(item_id)
            if any(src.doc_id in basis_ids for src in coverage.item.sources):
                related.add(item_id)
    return sorted(related)


def _mentions(notes: str, item) -> bool:
    words = [item.facility, item.scenario]
    if item.scope:
        words.append(item.scope)
    return any(word and word in notes for word in words)


def _basis_excerpts(minute, terms_rows, replies_rows) -> list[tuple[str, str, str]]:
    excerpts: list[tuple[str, str, str]] = []
    for doc_id in minute["basis"]:
        for row in terms_rows:
            if row["id"] == doc_id:
                excerpts.append((doc_id, row["type"], _clip(row["text"])))
        for row in replies_rows:
            if row["id"] == doc_id:
                excerpts.append((doc_id, f"{row['supplier']}·{row['part']}",
                                 _clip(row["prose"])))
    return excerpts


def _clip(text: str, limit: int = 60) -> str:
    return text if len(text) <= limit else text[:limit] + "…"


def _events(date: str, vendor: str, arranged: list[str], cov_now, baseline_now,
            replies_rows: list[dict], commits_now) -> list[str]:
    events: list[str] = []
    clause_ids = {cov_now[item_id].item.clause_id for item_id in arranged if item_id in cov_now}
    for clause_id in sorted(clause_ids):
        clause = baseline_now.clauses.get(clause_id)
        if clause is None:
            continue
        for event in clause.history:
            if event.issued > date:
                events.append(f"{event.doc_id}（{event.issued}）：{event.summary}")
    facilities = {cov_now[item_id].item.facility for item_id in arranged if item_id in cov_now}
    # 文书涉及的设施按解析后的承诺定位（澄清可能只写区域、不写设施名）
    doc_facilities: dict[str, set[str]] = {}
    for commitment in commits_now:
        if commitment.facility:
            doc_facilities.setdefault(commitment.doc_id, set()).add(commitment.facility)
    for row in sorted(replies_rows, key=lambda r: (r["issued"], r["id"])):
        if row["supplier"] == vendor and row["issued"] > date \
                and doc_facilities.get(row["id"], set()) & facilities:
            events.append(f"{row['id']}（{row['part']}，{row['issued']}）："
                          f"{_clip(row['prose'], 40)}")
    return events


def _judge(minute: dict, review: MinuteReview) -> tuple[str, str]:
    then = review.as_of
    now = review.current
    broken = [i for i in review.arranged
              if then.get(i) == COVERED and now.get(i) != COVERED]
    changed = [i for i in review.arranged if then.get(i) != now.get(i)]
    notes_tokens = set(re.findall(r"\d+\s*(?:台|毫秒|秒|分钟|小时|Mbps)", minute["notes"]))
    invalidated = any(
        token.replace(" ", "") in event.replace(" ", "")
        for event in review.events for token in notes_tokens)
    if broken or invalidated:
        reasons = "；".join(review.events) if review.events else "依据材料已变更"
        return "已失效", f"原安排依据已变更（{reasons}），需按现行基线重新组织。"
    if changed:
        label = "草稿需更新" if minute["state"] == "draft" else "部分需更新"
        items = "、".join(changed)
        return label, f"验收项 {items} 的结论已有变化，请复核后更新纪要。"
    return "继续有效", "安排所依据的条款与承诺未发生影响结论的变化。"
