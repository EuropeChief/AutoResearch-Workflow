#!/usr/bin/env python3
"""Codex/Pi 共用的 AutoResearch 新流程与阶段编排统一入口。"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import FlowError, Registry, TaskStore, _read_json, _canonical_digest, _require
from autoresearch_flow.experiments import FAILED_RUN_STATUSES, ExperimentBook, baseline_check, score_check
from autoresearch_flow.experiment_runner import ExperimentRunner
from autoresearch_flow.runtime import Runtime
from autoresearch_flow.w4_evidence import DeliveryEvidence
from autoresearch_flow.w4_package import DeliveryPackage, check_package
from autoresearch_flow.stages import StageFlow
from autoresearch_flow.pca_contract import check_task, check_execution_receipt, check_stability
from autoresearch_flow.policies import policy_status
from autoresearch_flow.task_git import TaskGit


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=f"AutoResearch 新流程统一入口（{FLOW_VERSION}）")
    parser.add_argument("--format", choices=("text", "json"), default="text", help="输出格式；机器调用建议 json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("version", help="显示工具版本")

    rules = commands.add_parser("rules", help="中央规则包")
    rules_actions = rules.add_subparsers(dest="rules_action", required=True)
    rules_actions.add_parser("check", help="只读检查规则目录、来源哈希与 QA 映射")
    rule_show = rules_actions.add_parser("show", help="按规则或子步骤显示要求、到期位置和原文来源；不判通过")
    selection = rule_show.add_mutually_exclusive_group(required=True)
    selection.add_argument("--id", dest="rule_id")
    selection.add_argument("--step")
    environment = commands.add_parser("environment", help="PCA 双镜像结构/实跑证据检查，不执行 Harbor 或 QA")
    env_actions = environment.add_subparsers(dest="environment_action", required=True)
    stability = env_actions.add_parser("verify-stability", help="可选只读诊断：核已有 12h 记录，不启动容器、不写通过收据")
    stability.add_argument("--task-root", type=Path, required=True, help="记录及其原始证据的范围根；最终交付时为包根")
    stability.add_argument("--file", type=Path, required=True)
    stability.add_argument("--agent-image", required=True, help="实际已验证的 Agent 镜像不可变标识")
    for name in ("check", "verify-record"):
        command = env_actions.add_parser(name)
        command.add_argument("--harbor-task", type=Path, required=True)
        if name == "verify-record":
            command.add_argument("--task-root", type=Path, required=True)
            command.add_argument("--file", type=Path, required=True)
            command.add_argument("--final", action="store_true")
            command.add_argument("--score-contract", type=Path, help="独立的评分合同 JSON；非完整标注 JSON")
            command.add_argument("--best-method", type=Path)

    task = commands.add_parser("task", help="题目状态")
    task_actions = task.add_subparsers(dest="task_action", required=True)
    task_init = task_actions.add_parser("init", help="显式初始化已有题目目录，不运行题目")
    task_init.add_argument("--task-root", type=Path, required=True)
    task_init.add_argument("--task-id", required=True)
    task_init.add_argument("--confirm-init", action="store_true", help="必须明确确认写入新的状态目录")
    task_check = task_actions.add_parser("check", help="只读检查题目状态与锁定来源")
    task_check.add_argument("--task-root", type=Path, required=True)
    policy = task_actions.add_parser("policy", help="只读显示当前任务冻结政策和实现能力")
    policy.add_argument("--task-root", type=Path, required=True)
    duration = task_actions.add_parser("duration-set", help="阶段4.1、prepare之前，凭证据显式冻结10h/非训练7h政策")
    duration.add_argument("--task-root", type=Path, required=True)
    duration.add_argument("--file", type=Path, required=True)
    duration.add_argument("--confirm-duration", action="store_true")
    for name in ("git-status", "git-setup", "git-preview", "git-checkpoint"):
        command = task_actions.add_parser(name, help="题目范围 Git 管理，不 push、不清理用户改动")
        command.add_argument("--task-root", type=Path, required=True)
        if name == "git-setup":
            command.add_argument("--repository-root", type=Path, required=True)
            command.add_argument("--confirm-git", action="store_true")
        if name == "git-preview":
            command.add_argument("--path", action="append", required=True)
        if name == "git-checkpoint":
            command.add_argument("--file", type=Path, required=True)
            command.add_argument("--message", required=True)
            command.add_argument("--confirm-commit", action="store_true")
    configure = task_actions.add_parser("configure", help="登记题目类型和适配入口")
    configure.add_argument("--task-root", type=Path, required=True)
    configure.add_argument("--file", type=Path, required=True)
    stage = commands.add_parser("stage", help="六阶段状态、证据登记、冻结与返修")
    actions = stage.add_subparsers(dest="stage_action", required=True)
    for name in ("status", "check", "template", "record", "finish", "reopen", "ref"):
        command = actions.add_parser(name)
        command.add_argument("--task-root", type=Path, required=True)
        if name in {"check", "template", "reopen"}:
            command.add_argument("--step", required=True)
        if name == "check":
            command.add_argument("--file", type=Path)
        if name == "finish":
            command.add_argument("--stage", choices=tuple(str(i) for i in range(1, 7)), required=True)
        if name in {"record", "finish", "reopen"}:
            command.add_argument("--file", type=Path, required=True)
        if name == "ref":
            command.add_argument("--path", action="append", required=True)
    experiment = commands.add_parser("experiment", help="正式协议、运行登记与统计")
    actions = experiment.add_subparsers(dest="experiment_action", required=True)
    for name in ("lock", "extend", "start", "finish", "report", "baseline-check", "score-check", "execute"):
        command = actions.add_parser(name)
        command.add_argument("--task-root", type=Path, required=True)
        if name in {"lock", "extend", "start", "finish", "baseline-check", "score-check"}:
            command.add_argument("--file", type=Path, required=True)
        if name in {"extend", "report", "baseline-check", "score-check"}:
            command.add_argument("--protocol", required=True)
        if name == "finish":
            command.add_argument("--run-id", required=True)
        if name == "baseline-check":
            command.add_argument("--phase", type=int, choices=(2, 3), required=True)
        if name == "report":
            command.add_argument("--role", choices=("baseline", "reference", "best_method"))
        if name == "execute":
            command.add_argument("--plan", type=Path, required=True)
            command.add_argument("--retry-infra", action="append", default=[], metavar="RUN_ID",
                                 help="显式重试本队列已登记的外部异常；不允许重试方法失败")
    runtime = commands.add_parser("runtime", help="Codex 双轨启动、预检、原始日志与计时")
    actions = runtime.add_subparsers(dest="runtime_action", required=True)
    for name in ("prepare", "check", "preflight", "run", "resume", "finalize", "recover", "status", "exclude"):
        command = actions.add_parser(name)
        command.add_argument("--task-root", type=Path, required=True)
        if name in {"prepare", "exclude"}:
            command.add_argument("--file", type=Path, required=True)
        if name != "prepare":
            command.add_argument("--track", choices=("codex", "seed"), required=True)
        if name == "preflight":
            command.add_argument("--allow-live", action="store_true")
        if name == 'finalize':
            command.add_argument('--confirm-final-score', action='store_true')
        if name in {"run", "resume"}:
            command.add_argument("--budget-seconds", type=int, required=True)
            command.add_argument("--confirm-cost", action="store_true")
    delivery = commands.add_parser("delivery", help="Agent 轨迹整理、最终方法、包与独立 QA 交接")
    actions = delivery.add_subparsers(dest="delivery_action", required=True)
    for name in ("trajectory-finalize", "trajectory-review", "best-select", "best-verify",
                 "build", "check", "archive", "form", "qa-handoff", "qa-bind"):
        command = actions.add_parser(name)
        if name != "check":
            command.add_argument("--task-root", type=Path, required=True)
        if name in {"trajectory-finalize", "trajectory-review"}:
            command.add_argument("--track", choices=("codex", "seed"), required=True)
        if name in {"trajectory-review", "best-select", "best-verify", "build", "form"}:
            command.add_argument("--file", type=Path, required=True)
        if name == "trajectory-finalize":
            command.add_argument("--file", type=Path, help="可选的逐行修订记录 JSON；缺省为原样整理")
        if name in {"check", "archive", "form", "qa-handoff", "qa-bind"}:
            command.add_argument("--package-root", type=Path, required=True)
        if name == "archive":
            command.add_argument("--name", required=True, help="完整包语义化英文名称，不含题号")
            command.add_argument("--file", type=Path, help="6.5 checks 对象；未提供项仅复用已登记的有效引用")
            command.add_argument("--max-part-bytes", type=int, default=290_000_000)
        if name == "qa-bind":
            command.add_argument("--report", type=Path, required=True)
    return parser

def _emit(payload: dict, output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
        return
    print(f"{payload['action']}: {payload['status']}")
    if "task_id" in payload:
        print(f"题目：{payload['task_id']}；当前阶段：{payload.get('current_stage')}")
    if "rule_count" in payload:
        print(f"规则：{payload['rule_count']} 条；质检映射：{payload.get('coverage_count', 0)} 项")
    if "changed_rules" in payload:
        print(f"变更规则：{', '.join(payload['changed_rules']) or '无'}；受影响阶段：{payload['affected_stages']}")
    for issue in payload.get("issues", []):
        print(f"- {issue['code']}: {issue['message']}" if isinstance(issue, dict) else f"- {issue}")
    if payload["action"].startswith(("rules.show", "environment.", "experiment.", "runtime.", "delivery.", "stage.", "task.configure", "task.policy", "task.git")):
        print(json.dumps({key: value for key, value in payload.items() if key not in {"action", "issues"}}, ensure_ascii=False, indent=2))
    if payload.get("next_action"):
        print(f"下一步：{payload['next_action']}")


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    action = args.command if args.command == "version" else f"{args.command}.{getattr(args, 'environment_action', None) or getattr(args, 'rules_action', None) or getattr(args, 'task_action', None) or getattr(args, 'experiment_action', None) or getattr(args, 'runtime_action', None) or getattr(args, 'delivery_action', None) or getattr(args, 'stage_action', None)}"
    try:
        if args.command == "environment":
            if args.environment_action == 'verify-record' and args.final:
                root = args.task_root.resolve()
                _require(args.best_method is not None and args.score_contract is not None
                         and all(p.resolve().is_relative_to(root) for p in
                                 (args.harbor_task, args.file, args.best_method, args.score_contract)),
                         'PACKAGE_EVIDENCE_BOUNDARY', '最终验收所读任务、候选、记录及评分合同须位于指定包根内')
            if args.environment_action == "verify-stability":
                _require(args.file.resolve().is_relative_to(args.task_root.resolve()),
                         "PACKAGE_EVIDENCE_BOUNDARY", "稳定性记录须在指定证据根内")
                result = check_stability(args.task_root.resolve(), _read_json(args.file), expected_image=args.agent_image)
            else:
                result = check_task(args.harbor_task) if args.environment_action == "check" else check_execution_receipt(
                    args.task_root, _read_json(args.file), args.harbor_task, final=args.final,
                    frozen_scoring=args.score_contract is not None,
                    score_contract_sha256=_canonical_digest(_read_json(args.score_contract)) if args.score_contract else None,
                    best_method=args.best_method)
            payload = {"action": action, **result}
        elif args.command == "stage":
            flow = StageFlow(args.task_root)
            if args.stage_action == "status":
                result = flow.status()
            elif args.stage_action == "check":
                result = flow.check(args.step, _read_json(args.file) if args.file else None)
            elif args.stage_action == "template":
                result = flow.template(args.step)
            elif args.stage_action == "record":
                result = flow.record(_read_json(args.file))
            elif args.stage_action == "finish":
                result = flow.finish(args.stage, _read_json(args.file))
            elif args.stage_action == "ref":
                result = flow.reference(args.path)
            else:
                result = flow.reopen(args.step, _read_json(args.file))
            payload = {"action": action, **result}
        elif args.command == "delivery":
            if args.delivery_action == "check":
                result = check_package(args.package_root)
            elif args.delivery_action == "trajectory-finalize":
                result = DeliveryEvidence(args.task_root).finalize_trajectory(
                    args.track, _read_json(args.file) if args.file else None)
            elif args.delivery_action == "trajectory-review":
                result = DeliveryEvidence(args.task_root).review_trajectory(args.track, _read_json(args.file))
            elif args.delivery_action == "best-select":
                result = DeliveryEvidence(args.task_root).snapshot_best(_read_json(args.file))
            elif args.delivery_action == "best-verify":
                result = DeliveryEvidence(args.task_root).verify_best(_read_json(args.file))
            elif args.delivery_action == "build":
                result = DeliveryPackage(args.task_root).build(_read_json(args.file))
            elif args.delivery_action == "archive":
                result = DeliveryPackage(args.task_root).archive(args.package_root, args.max_part_bytes,
                    name=args.name, checks=_read_json(args.file) if args.file else None)
            elif args.delivery_action == "form":
                result = DeliveryPackage(args.task_root).form(args.package_root, _read_json(args.file))
            elif args.delivery_action == "qa-handoff":
                result = DeliveryPackage(args.task_root).qa_handoff(args.package_root)
            else:
                result = DeliveryPackage(args.task_root).qa_bind(args.package_root, args.report)
            payload = {"action": action, **result}
        elif args.command == "runtime":
            runtime = Runtime(args.task_root)
            if args.runtime_action == "prepare":
                result = runtime.prepare(_read_json(args.file))
            elif args.runtime_action == "check":
                result = runtime.check(args.track)
            elif args.runtime_action == "preflight":
                result = runtime.preflight(args.track, args.allow_live)
            elif args.runtime_action in {"run", "resume"}:
                result = runtime.run(args.track, args.budget_seconds, resume=args.runtime_action == "resume", confirm_cost=args.confirm_cost)
            elif args.runtime_action == 'finalize':
                result = runtime.finalize(args.track, args.confirm_final_score)
            elif args.runtime_action == "recover":
                result = runtime.recover(args.track)
            elif args.runtime_action == "exclude":
                result = runtime.exclude(args.track, _read_json(args.file))
            else:
                result = runtime.status(args.track)
            payload = {"action": action, **result}
        elif args.command == "experiment":
            book = ExperimentBook(args.task_root)
            value = _read_json(args.file) if hasattr(args, "file") else None
            if args.experiment_action == "lock":
                result = {"status": "locked", **book.lock(value)}
            elif args.experiment_action == "extend":
                result = book.extend(args.protocol, value)
            elif args.experiment_action == "start":
                result = book.start(value)
            elif args.experiment_action == "finish":
                result = book.finish(args.run_id, value)
            elif args.experiment_action == "report":
                result = book.report(args.protocol, (args.role,) if args.role else ("baseline", "reference"))
            elif args.experiment_action == "execute":
                result = ExperimentRunner(args.task_root).execute(_read_json(args.plan), retry_of=args.retry_infra)
            elif args.experiment_action == "baseline-check":
                result = baseline_check(book, args.protocol, value, args.phase)
            else:
                result = score_check(book, args.protocol, value)
            payload = {"action": action, **result}
        elif args.command == "version":
            payload = {"action": action, "status": "ok", "flow_version": FLOW_VERSION}
        elif args.command == "rules" and args.rules_action == "show":
            payload = {"action": action, **Registry().show(rule_id=args.rule_id, step=args.step)}
        elif args.command == "rules":
            registry = Registry()
            issues = registry.check_sources()
            payload = {
                "action": action,
                "status": "ok" if not issues else "blocked",
                "flow_version": FLOW_VERSION,
                "rule_count": len(registry.catalog["rules"]),
                "coverage_count": len(registry.catalog["coverage"]),
                "issues": issues,
                "next_action": "检查来源版本和哈希；不能在来源漂移时初始化题目" if issues else "规则包结构可读；这不是逐条语义复核或真实题目质检",
            }
        elif args.task_action.startswith("git-"):
            vcs = TaskGit(args.task_root)
            if args.task_action == "git-status":
                result = vcs.status()
            elif args.task_action == "git-setup":
                result = vcs.setup(args.repository_root, confirm=args.confirm_git)
            elif args.task_action == "git-preview":
                result = vcs.preview(args.path)
            else:
                result = vcs.checkpoint(_read_json(args.file), args.message, confirm=args.confirm_commit)
            payload = {"action": action, **result}
        elif args.task_action == "policy":
            from autoresearch_flow.duration import snapshot
            payload = {"action": action, **policy_status(TaskStore(args.task_root)._load()), "duration_snapshot": snapshot(args.task_root)}
        elif args.task_action == "duration-set":
            from autoresearch_flow.duration import select
            payload = {"action": action, **select(args.task_root, _read_json(args.file), confirm=args.confirm_duration)}
        elif args.task_action == "configure":
            payload = {"action": action, **StageFlow(args.task_root).configure(_read_json(args.file))}
        elif args.task_action == "init":
            if not args.confirm_init:
                raise FlowError("CONFIRMATION_REQUIRED", "初始化会写入题目目录；请审查目录后显式加入 --confirm-init")
            registry = Registry()
            store = TaskStore(args.task_root)
            state = store.initialize(registry, args.task_id)
            payload = {"action": action, "status": "initialized", "task_id": state["task_id"], "current_stage": state["current_stage"], "state_path": str(store.state_path), "next_action": "先 task git-status 确认范围并建立初始检查点，再登记 1.1 来源与输入；初始化不等于阶段通过"}
        elif args.task_action == "check":
            checked = TaskStore(args.task_root).check()
            payload = {"action": action, "status": "ok" if not checked["issues"] else "blocked", **checked, "next_action": "来源漂移时核对并恢复该任务锁定版本，不覆盖来源锁" if checked["issues"] else "状态合同有效；仍需执行当前阶段的实际门禁"}
    except FlowError as exc:
        _emit({"action": action, "status": "blocked", "issues": [{"code": exc.code, "message": exc.message}], "next_action": "按错误说明修复；不要绕过来源锁或静默初始化"}, args.format)
        return 2
    _emit(payload, args.format)
    return 2 if payload["status"] in FAILED_RUN_STATUSES | {"blocked", "needs_review", "recorded_invalid"} else 0


if __name__ == "__main__":
    sys.exit(main())
