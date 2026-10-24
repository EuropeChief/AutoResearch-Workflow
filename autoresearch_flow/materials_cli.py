"""Independent material operations; no stage, review ledger or Runtime required."""
from pathlib import Path
from .materials_io import read_object


def add_commands(commands):
    materials = commands.add_parser("materials", help="独立轨迹整理、按来源组包、包内只读格式检查")
    actions = materials.add_subparsers(dest="materials_action", required=True)
    p = actions.add_parser("trajectory", help="Agent 自写 JSONL/JSON 整理为 rounds 根对象")
    p.add_argument("--source", type=Path, required=True)
    p.add_argument("--output", type=Path, required=True)
    p.add_argument("--metric", type=Path, help="实际 direction/split，可核最佳标记")
    p.add_argument("--observations", type=Path, help="已有按轮次索引的 raw_value/direction/split，用于核原始分数")
    p = actions.add_parser("assemble", help="少量真实路径映射组包，不默选最终方法")
    p.add_argument("--sources", type=Path, required=True)
    p.add_argument("--best-method", type=Path, required=True)
    p.add_argument("--output-dir", type=Path, required=True)
    p = actions.add_parser("check", help="仅以指定最终包为取证边界，输出格式问题，不运行 QA")
    p.add_argument("--package-root", type=Path, required=True)
    p = actions.add_parser("precheck", help="项目方格式前检，保留原报告及当前时点解释")
    p.add_argument("--package-root", type=Path, required=True, help="三目录包根或最终归档")
    p.add_argument("--output-dir", type=Path, required=True, help="包外新报告目录")
    p.add_argument("--phase", choices=("before_research", "final"), default="final")
    p.add_argument("--task-kind", choices=("auto", "cpu", "gpu"), default="auto")
    p = actions.add_parser("fingerprint", help="只读计算官方四项输入指纹，不证明历史运行归属")
    p.add_argument("--harbor-task", type=Path, required=True)
    p = actions.add_parser("legacy-qa-check", help="复算指定旧题 standard-waiver.5 完整审查与逐原因豁免")
    p.add_argument("--package-root", type=Path, required=True)
    p.add_argument("--report", type=Path, required=True, help="原标准 standard/report.json，保留相邻 inventory.json")
    p.add_argument("--review", type=Path, required=True, help="原标准审核底稿，对应官方 --standard-review")
    p.add_argument("--worksheet", type=Path, required=True, help="含 standard_resolutions 的 legacy_review.json")
    p.add_argument("--result", type=Path, required=True, help="官方完整 report.json；不接受格式子报告或旧 waiver_report.json")


def dispatch(args):
    if args.materials_action == "legacy-qa-check":
        from .legacy_qa import validate_legacy_qa
        return {"status": "legacy_qa_verified", **validate_legacy_qa(
            args.package_root, args.report, args.review,
            args.worksheet, args.result, require_pass=True)}
    if args.materials_action == "precheck":
        from .package_precheck import check
        return check(args.package_root, args.output_dir, phase=args.phase, task_kind=args.task_kind)
    if args.materials_action == "fingerprint":
        from .task_binding import fingerprint
        return {"status": "fingerprinted", **fingerprint(args.harbor_task)}
    if args.materials_action=="trajectory":
        from .materials_trajectory import prepare
        return prepare(args.source, args.output, metric=read_object(args.metric) if args.metric else None,
                       observations=read_object(args.observations) if args.observations else None)
    if args.materials_action=="assemble":
        from .materials_assemble import assemble
        return assemble(read_object(args.sources), args.best_method, args.output_dir, source_root=args.sources.parent)
    from .materials_check import check
    return check(args.package_root)
