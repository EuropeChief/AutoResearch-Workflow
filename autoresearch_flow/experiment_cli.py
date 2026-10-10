"""CLI glue for independent experimental operations."""
from pathlib import Path
import argparse

from .common import _read_json
from .experiment_data import summarize, write_summary
from .experiment_run import run


def add_commands(actions):
    runner = actions.add_parser("run", help="独立运行方法/协议，不初始化题目或登记账本")
    runner.add_argument("--method", type=Path, required=True, help="只含实际源码/配置的文件或目录")
    runner.add_argument("--protocol", type=Path, required=True)
    runner.add_argument("--output-dir", type=Path, required=True)
    runner.add_argument("--role", default="exploration")
    runner.add_argument("--resume", action="store_true", help="验证并跳过完成项；失败重试保留旧 attempt")
    runner.add_argument("--gpu", action="append", default=[], help="已授权 GPU 索引或完整 UUID；可重复指定")
    runner.add_argument("--gpus-per-run", type=int, default=1)
    runner.add_argument("--jobs", type=int, default=1)
    runner.add_argument("--cpu-threads", type=int)
    runner.add_argument("--timeout-seconds", type=float, help="可选单次作业超时；无整组默认超时")
    runner.add_argument("launch_command", nargs=argparse.REMAINDER, help="-- 后接实际命令及参数")
    summary = actions.add_parser("summarize", help="只读统计已有逐次结果，不运行方法")
    summary.add_argument("--results", type=Path, nargs="+", required=True)
    summary.add_argument("--protocol", type=Path, help="结果未含协议时提供实际协议")
    summary.add_argument("--score-contract", type=Path, help="可选 upper_bound 与 rationale；不自动估 U")
    summary.add_argument("--evidence-root", type=Path, help="已有包内 artifacts 的相对路径基准")
    summary.add_argument("--output-dir", type=Path, help="可选写 comparison_summary.json 和 summary.md 的新位置")


def dispatch(args):
    if args.experiment_action == "run":
        command = args.launch_command
        if command[:1] == ["--"]:
            command = command[1:]
        return run(args.method, _read_json(args.protocol), args.output_dir, command,
                   role=args.role, resume=args.resume, gpu_ids=args.gpu, jobs=args.jobs,
                   gpus_per_run=args.gpus_per_run, cpu_threads=args.cpu_threads,
                   timeout_seconds=args.timeout_seconds)
    report = summarize(args.results, protocol_value=_read_json(args.protocol) if args.protocol else None,
                       score_contract=_read_json(args.score_contract) if args.score_contract else None,
                       evidence_root=args.evidence_root)
    if args.output_dir:
        write_summary(report, args.output_dir)
    return report
