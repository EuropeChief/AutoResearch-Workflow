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


def dispatch(args):
    if args.materials_action=="trajectory":
        from .materials_trajectory import prepare
        return prepare(args.source, args.output, metric=read_object(args.metric) if args.metric else None,
                       observations=read_object(args.observations) if args.observations else None)
    if args.materials_action=="assemble":
        from .materials_assemble import assemble
        return assemble(read_object(args.sources), args.best_method, args.output_dir, source_root=args.sources.parent)
    from .materials_check import check
    return check(args.package_root)
