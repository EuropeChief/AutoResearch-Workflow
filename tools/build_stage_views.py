#!/usr/bin/env python3
"""生成或检查六阶段规则阅读视图。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from autoresearch_flow.stage_rules import StageRules


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="生成/检查 rules/stages 下的阶段规则视图")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="只检查，不写入派生视图")
    args = parser.parse_args(argv)

    rules = StageRules(args.root)
    issues = rules.validate(check_views=args.check)
    if issues and args.check:
        print(json.dumps({"status": "failed", "issues": issues}, ensure_ascii=False, indent=2))
        return 2
    if issues and not args.check:
        # 只要矩阵或来源本身无效就不能生成视图；缺少视图属于正常生成前状态。
        structural = [issue for issue in issues if issue["code"].startswith(("MATRIX", "STAGE", "CANONICAL", "OBLIGATION", "RULE_", "DEPENDENCY", "BLOCKING"))]
        if structural:
            print(json.dumps({"status": "failed", "issues": structural}, ensure_ascii=False, indent=2))
            return 2

    matrix = rules.load()
    written: list[str] = []
    for stage in matrix["stages"]:
        path = rules.root / stage["view_path"]
        path.parent.mkdir(parents=True, exist_ok=True)
        content = rules.render_stage(int(stage["id"]))
        if not args.check:
            path.write_text(content, encoding="utf-8")
        written.append(str(path.relative_to(rules.root)))

    if args.check:
        print(json.dumps({"status": "passed", "checked": written}, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"status": "generated", "written": written}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
