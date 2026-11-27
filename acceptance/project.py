"""项目容器：需求包接入、评估快照与对比。

一个项目可先后接入多个需求包（如初轮材料、会后补充包），在同一
项目里重新比对。每次评估落一份快照，记录当时材料清单与各验收项
结论，快照之间可对比，说明哪些验收安排因新材料而不再有效。
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from .boundaries import area_facility_map, parse_boundaries
from .engine import derive_items, evaluate_all
from .minutes import MinuteReview, review_minutes
from .model import Coverage
from .replies import parse_replies
from .terms import Baseline

KNOWN_STEMS = ("terms", "replies", "conditions", "minutes")


@dataclass
class Evaluation:
    baseline: Baseline
    boundaries: dict
    commitments: list
    items: list
    coverage: dict[str, list[Coverage]]
    reviews: list[MinuteReview]
    materials: dict[str, list[dict]] = field(default_factory=dict)


class Project:
    def __init__(self, root):
        self.root = Path(root)
        self.state_path = self.root / "state.json"
        if not self.state_path.exists():
            raise FileNotFoundError(f"{self.root} 不是评估项目（缺少 state.json）")
        self.state = json.loads(self.state_path.read_text(encoding="utf-8"))

    @classmethod
    def init(cls, root) -> "Project":
        root = Path(root)
        (root / "packages").mkdir(parents=True, exist_ok=True)
        (root / "snapshots").mkdir(exist_ok=True)
        state = {"created": date.today().isoformat(), "packages": [], "snapshots": []}
        (root / "state.json").write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")
        return cls(root)

    def _save(self) -> None:
        self.state_path.write_text(
            json.dumps(self.state, ensure_ascii=False, indent=2), encoding="utf-8")

    # ---- 需求包 ----

    def ingest(self, name: str, materials_dir) -> dict[str, int]:
        """接入一个需求包；编号跨包冲突时拒绝并说明。"""
        materials_dir = Path(materials_dir)
        found: dict[str, list[dict]] = {}
        for stem in KNOWN_STEMS:
            path = materials_dir / f"{stem}.jsonl"
            if path.exists():
                rows = [json.loads(line) for line in
                        path.read_text(encoding="utf-8").splitlines() if line.strip()]
                if rows:
                    found[stem] = rows
        if not found:
            raise ValueError(f"{materials_dir} 中未找到可接入的资料（{KNOWN_STEMS}）")
        existing = self.materials()
        for stem, rows in found.items():
            have = {row["id"] for row in existing[stem]}
            clash = have & {row["id"] for row in rows}
            if clash:
                raise ValueError(
                    f"需求包 {name} 的 {stem} 编号与已接入材料冲突：{sorted(clash)}")
        target = self.root / "packages" / name
        if target.exists():
            raise ValueError(f"需求包 {name} 已接入过")
        target.mkdir()
        for stem, rows in found.items():
            lines = [json.dumps(row, ensure_ascii=False) for row in rows]
            (target / f"{stem}.jsonl").write_text("\n".join(lines) + "\n", encoding="utf-8")
        self.state["packages"].append({
            "name": name, "ingested": date.today().isoformat(),
            "files": {stem: len(rows) for stem, rows in found.items()}})
        self._save()
        return {stem: len(rows) for stem, rows in found.items()}

    def materials(self) -> dict[str, list[dict]]:
        merged: dict[str, list[dict]] = {stem: [] for stem in KNOWN_STEMS}
        for package in self.state["packages"]:
            package_dir = self.root / "packages" / package["name"]
            for stem in KNOWN_STEMS:
                path = package_dir / f"{stem}.jsonl"
                if path.exists():
                    for line in path.read_text(encoding="utf-8").splitlines():
                        if line.strip():
                            row = json.loads(line)
                            row["_package"] = package["name"]
                            merged[stem].append(row)
        return merged

    # ---- 评估 ----

    def evaluate(self, label: str | None = None) -> Evaluation:
        materials = self.materials()
        baseline = Baseline.build(materials["terms"])
        boundaries = parse_boundaries(materials["conditions"])
        commitments = parse_replies(materials["replies"],
                                    area_facility=area_facility_map(boundaries))
        items = derive_items(baseline, boundaries)
        suppliers = sorted({row["supplier"] for row in materials["replies"]})
        coverage = evaluate_all(suppliers, items, commitments,
                                baseline.clauses, boundaries)
        reviews = review_minutes(materials["minutes"], materials["terms"],
                                 materials["replies"], boundaries)
        evaluation = Evaluation(baseline, boundaries, commitments, items,
                                coverage, reviews, materials)
        self._snapshot(evaluation, label)
        return evaluation

    def _snapshot(self, evaluation: Evaluation, label: str | None) -> None:
        seq = len(self.state["snapshots"]) + 1
        snapshot = {
            "seq": seq,
            "label": label or f"评估 {seq}",
            "created": date.today().isoformat(),
            "manifest": {
                stem: sorted(row["id"] for row in evaluation.materials[stem])
                for stem in KNOWN_STEMS if evaluation.materials[stem]
            },
            "coverage": {
                supplier: {
                    coverage.item.item_id: {
                        "status": coverage.status,
                        "evidence": sorted({e.commitment.doc_id
                                            for e in coverage.evidence}),
                        "questions": len(coverage.questions),
                    }
                    for coverage in coverages
                }
                for supplier, coverages in evaluation.coverage.items()
            },
            "minutes": {review.minute["id"]: review.validity
                        for review in evaluation.reviews},
        }
        path = self.root / "snapshots" / f"{seq}.json"
        path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2),
                        encoding="utf-8")
        self.state["snapshots"].append(
            {"seq": seq, "label": snapshot["label"], "created": snapshot["created"]})
        self._save()

    def load_snapshot(self, seq: int) -> dict:
        path = self.root / "snapshots" / f"{seq}.json"
        return json.loads(path.read_text(encoding="utf-8"))

    @staticmethod
    def diff(older: dict, newer: dict) -> list[str]:
        """两份快照间的结论变化，用于说明验收安排为何不再有效。"""
        lines: list[str] = []
        for stem in KNOWN_STEMS:
            added = sorted(set(newer["manifest"].get(stem, []))
                           - set(older["manifest"].get(stem, [])))
            if added:
                lines.append(f"新材料（{stem}）：{ '、'.join(added) }")
        suppliers = sorted(set(older["coverage"]) | set(newer["coverage"]))
        for supplier in suppliers:
            old_items = older["coverage"].get(supplier, {})
            new_items = newer["coverage"].get(supplier, {})
            for item_id in sorted(set(old_items) | set(new_items)):
                before = old_items.get(item_id, {}).get("status", "（无）")
                after = new_items.get(item_id, {}).get("status", "（无）")
                if before != after:
                    evidence = new_items.get(item_id, {}).get("evidence", [])
                    lines.append(f"{supplier} {item_id}：{before} → {after}"
                                 f"（证据：{'、'.join(evidence) or '无'}）")
        for minute_id in sorted(set(older["minutes"]) | set(newer["minutes"])):
            before = older["minutes"].get(minute_id, "（无）")
            after = newer["minutes"].get(minute_id, "（无）")
            if before != after:
                lines.append(f"纪要 {minute_id}：{before} → {after}")
        return lines
