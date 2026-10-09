"""Small explicit native scoring entry, with no legacy task state."""
from pathlib import Path


def add_commands(commands):
    parser = commands.add_parser("harbor", help="原生双镜像 NOP/冻结候选评分；不启动轨迹或选择方法")
    actions = parser.add_subparsers(dest="harbor_action", required=True)
    p = actions.add_parser("run", help="保留原生 Trial，并核实际 artifacts/reward")
    p.add_argument("--harbor-task", type=Path, required=True)
    p.add_argument("--harbor-python", type=Path, required=True, help="已安装 Harbor 0.23.0 的 Python")
    p.add_argument("--output-dir", type=Path, required=True)
    p.add_argument("--candidate", type=Path, help="明确选定、含必要模型/配置的候选；不传即原生 nop")
    p.add_argument("--gpu-id", action="append", help="当前已授权的显式 GPU；CPU 不传")
    p.add_argument("--allow-live", action="store_true", help="在已有 Docker/评分/资源授权范围内实际执行")
    p.add_argument("--timeout-seconds", type=int, help="仅有界短验收使用；默认沿题包时限，不限制整组复评为2h")
    p = actions.add_parser("inspect", help="只读复核已有原生原件与版本绑定，不重新评分")
    p.add_argument("--run-dir", type=Path, required=True)
    p.add_argument("--harbor-task", type=Path, help="可选核当前题包是否仍与原件一致")
    p.add_argument("--candidate", type=Path, help="可选核当前候选；NOP 不可指定")


def dispatch(args):
    if args.harbor_action == "inspect":
        from .harbor_native import inspect_run
        report = inspect_run(args.run_dir, task=args.harbor_task, candidate=args.candidate)
        record = args.run_dir / "report.json"
    else:
        from .harbor_native import run
        report = run(args.harbor_task, args.output_dir, harbor_python=args.harbor_python,
                     candidate=args.candidate, gpu_ids=args.gpu_id, allow_live=args.allow_live,
                     timeout=args.timeout_seconds)
        record = args.output_dir / "report.json"
    # Full file inventories belong in the preserved record, not every Agent turn.
    return {**{key: report[key] for key in ("status", "mode", "rewards", "coverage", "trial_dir",
                                          "harbor_exit_code", "error", "source_binding") if key in report},
            "record": str(record.resolve())}
