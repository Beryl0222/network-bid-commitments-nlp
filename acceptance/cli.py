"""命令行入口：python3 -m acceptance <命令>。"""
from __future__ import annotations

import argparse
import sys

from .project import Project
from .report import render_minutes, render_report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="acceptance",
        description="接入服务技术应答的承诺提取、条款覆盖与验收安排")
    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init", help="创建项目目录")
    p_init.add_argument("--project", required=True)

    p_ingest = sub.add_parser("ingest", help="接入一个需求包")
    p_ingest.add_argument("--project", required=True)
    p_ingest.add_argument("--name", required=True)
    p_ingest.add_argument("--dir", required=True)

    p_eval = sub.add_parser("evaluate", help="重新比对并落一份快照")
    p_eval.add_argument("--project", required=True)
    p_eval.add_argument("--label", default=None)

    p_report = sub.add_parser("report", help="输出条款覆盖意见")
    p_report.add_argument("--project", required=True)
    p_report.add_argument("--supplier", default=None)

    p_minutes = sub.add_parser("minutes", help="输出纪要回查与变更")
    p_minutes.add_argument("--project", required=True)

    p_snaps = sub.add_parser("snapshots", help="列出评估快照")
    p_snaps.add_argument("--project", required=True)

    p_diff = sub.add_parser("diff", help="对比两份快照")
    p_diff.add_argument("--project", required=True)
    p_diff.add_argument("--a", type=int, required=True)
    p_diff.add_argument("--b", type=int, required=True)

    args = parser.parse_args(argv)
    try:
        if args.command == "init":
            project = Project.init(args.project)
            print(f"已创建项目：{project.root}")
            return 0
        project = Project(args.project)
        if args.command == "ingest":
            files = project.ingest(args.name, args.dir)
            detail = "、".join(f"{stem} {count} 条" for stem, count in files.items())
            print(f"已接入需求包 {args.name}：{detail}")
            return 0
        if args.command == "evaluate":
            evaluation = project.evaluate(label=args.label)
            items = len(evaluation.items)
            suppliers = "、".join(sorted(evaluation.coverage))
            print(f"评估完成：{items} 个验收项；供应商：{suppliers}")
            return 0
        if args.command == "report":
            print(render_report(project.evaluate(), supplier=args.supplier))
            return 0
        if args.command == "minutes":
            print(render_minutes(project.evaluate()))
            return 0
        if args.command == "snapshots":
            for snap in project.state["snapshots"]:
                print(f"{snap['seq']}. {snap['label']}（{snap['created']}）")
            return 0
        if args.command == "diff":
            older = project.load_snapshot(args.a)
            newer = project.load_snapshot(args.b)
            lines = Project.diff(older, newer)
            print("\n".join(lines) if lines else "两份快照结论一致")
            return 0
    except (ValueError, FileNotFoundError) as error:
        print(f"错误：{error}", file=sys.stderr)
        return 2
    return 1


if __name__ == "__main__":
    sys.exit(main())
