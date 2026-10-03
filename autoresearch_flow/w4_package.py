"""W4 immutable handoff package, package-only checks, and independent QA binding.

This module checks format and evidence references. It does not run the QA skill or
certify scientific validity, hidden scores, or platform approval.
"""
from __future__ import annotations

import hashlib
import math
import re
import shutil
import stat
import tempfile
import tomllib
import zipfile
from pathlib import Path

from .core import FlowError, TaskStore, _atomic_json, _canonical_digest, _read_json, _require, _sha256, _utc_now
from .experiments import ExperimentBook, evidence
from .runtime import Runtime, TRACKS
from .w4_evidence import DeliveryEvidence, _copy_tree, _files, _safe_tree, _reject_local_profiles
from .trajectory import validate_round
from .pca_contract import check_task
from .qa_contract import validate_qa_report, check_exposure_manifest


EXPERT_FILES = {"专家作业说明文档.md", "best_method", "expert_annotation.json",
                "run_summary.json", "trajectory_codex.json", "trajectory_seed.json"}
OPT_FILES = {"训练证据说明.md", "baseline_runs", "reference_runs", "comparison_summary.json"}


def package_snapshot(root: Path) -> list[dict]:
    """Portable content + path + mode identity, including empty directories."""
    _require(root.is_dir() and not root.is_symlink(), "PACKAGE_MISSING", "提交包目录不存在")
    entries = []
    for path in [root, *sorted(root.rglob("*"))]:
        _require(not path.is_symlink() and (path.is_file() or path.is_dir()),
                 "PACKAGE_SYMLINK", "提交包只允许普通文件和目录，不含链接/设备/套接字")
        item = {"path": path.relative_to(root).as_posix(), "mode": stat.S_IMODE(path.stat().st_mode),
                "type": "directory" if path.is_dir() else "file"}
        if path.is_file():
            item.update(sha256=_sha256(path), bytes=path.stat().st_size)
        entries.append(item)
    return entries


def _tree_digest(root: Path) -> str:
    return _canonical_digest(package_snapshot(root))


def _zip_name(prefix, row):
    name = prefix if row["path"] == "." else prefix + "/" + row["path"]
    return name + "/" if row["type"] == "directory" else name


def _write_zip(root, path, prefix):
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as out:
        for row in package_snapshot(root):
            info = zipfile.ZipInfo(_zip_name(prefix, row), date_time=(1980, 1, 1, 0, 0, 0))
            info.create_system = 3
            kind = stat.S_IFDIR if row["type"] == "directory" else stat.S_IFREG
            info.external_attr = (kind | row["mode"]) << 16
            info.compress_type = zipfile.ZIP_DEFLATED
            if row["type"] == "directory":
                info.external_attr |= 0x10
                out.writestr(info, b"")
            else:
                with (root / row["path"]).open("rb") as source, out.open(info, "w", force_zip64=True) as target:
                    shutil.copyfileobj(source, target, length=1024 * 1024)


def _verify_zip(root, path, prefix):
    """Stream-decompress every member; verify CRC, bytes, paths and Unix modes."""
    _require(path.is_file() and not path.is_symlink(), "ARCHIVE_INVALID", "ZIP 缺失或为链接")
    expected = {_zip_name(prefix, row): row for row in package_snapshot(root)}
    with zipfile.ZipFile(path) as archive:
        members = archive.infolist()
        _require(len(members) == len(expected) and {m.filename for m in members} == set(expected),
                 "ARCHIVE_INVALID", "ZIP 文件/目录集合与接受包不符")
        for member in members:
            row = expected[member.filename]
            _require(stat.S_IMODE(member.external_attr >> 16) == row["mode"] and member.create_system == 3,
                     "ARCHIVE_INVALID", "ZIP 丢失 Unix 权限")
            _require(member.filename.isascii() or member.flag_bits & 0x800,
                     "ARCHIVE_INVALID", "非 ASCII 文件名未使用 UTF-8 标志")
            digest = hashlib.sha256()
            with archive.open(member) as data:
                while block := data.read(1024 * 1024):
                    digest.update(block)
            if row["type"] == "file":
                _require(digest.hexdigest() == row["sha256"] and member.file_size == row["bytes"],
                         "ARCHIVE_INVALID", "ZIP 解包内容与源文件不同")
    return {"path": path.name, "sha256": _sha256(path), "bytes": path.stat().st_size, "prefix": prefix,
            "parts": [], "upload": "single_zip"}


def _split_zip(path, maximum, limit):
    if path.stat().st_size <= limit:
        return
    with path.open("rb") as source:
        number = 1
        while source.tell() < path.stat().st_size:
            with path.with_name(f"{path.name}.part{number:03d}").open("xb") as part:
                remaining = maximum
                while remaining and (block := source.read(min(remaining, 1024 * 1024))):
                    part.write(block)
                    remaining -= len(block)
            number += 1


def _verify_upload(path, entry, maximum, limit):
    if entry["bytes"] <= limit:
        return entry
    combined = hashlib.sha256()
    parts = []
    for number in range(1, (entry["bytes"] + maximum - 1) // maximum + 1):
        part = path.with_name(f"{path.name}.part{number:03d}")
        expected = min(maximum, entry["bytes"] - (number - 1) * maximum)
        _require(part.is_file() and not part.is_symlink() and part.stat().st_size == expected,
                 "ARCHIVE_INVALID", "分卷缺失、大小不符或为链接")
        digest = hashlib.sha256()
        with part.open("rb") as source:
            while block := source.read(1024 * 1024):
                digest.update(block)
                combined.update(block)
        parts.append({"path": part.name, "sha256": digest.hexdigest(), "bytes": expected})
    _require(combined.hexdigest() == entry["sha256"], "ARCHIVE_INVALID", "分卷拼接哈希不等于完整 ZIP")
    return {**entry, "parts": parts, "upload": "byte_parts"}


def _archive_support(archives):
    checksums, instructions = [], ["# 上传说明", "", "完整 ZIP 保留用于本地归档。超过上传上限的 ZIP 只上传其全部分卷，不同时上传完整 ZIP。",
                                   "分卷为字节拼接格式，不是可分别解压的 ZIP 或原生多卷 ZIP。接收方按以下明确顺序重组后再解压。", ""]
    for role in ("submission", "harbor_task", "optimization_evidence"):
        entry = archives[role]
        for item in [entry, *entry["parts"]]:
            checksums.append(f'{item["sha256"]}  {item["path"]}')
        instructions.extend([f'## {entry["path"]}', ""])
        if entry["parts"]:
            names = " ".join(p["path"] for p in entry["parts"])
            instructions.extend(["```sh", f'cat {names} > {entry["path"]}', "```", ""])
        else:
            instructions.extend(["直接上传此 ZIP，无需拼接。", ""])
        instructions.extend([f'完整文件 SHA-256：`{entry["sha256"]}`。', ""])
    instructions.extend(["保留全部文件时可运行 `sha256sum -c SHA256SUMS.txt`。",
                         "中文文件名使用 UTF-8；Linux 解压建议 `unzip`，其读取 Unix 权限字段保留脚本可执行位。",
                         "`archives.json` 绑定独立 QA、源包快照及三份压缩包；这些材料均在提交包之外。", ""])
    return {"SHA256SUMS.txt": "\n".join(checksums) + "\n", "上传说明.md": "\n".join(instructions)}


def _archive_scopes(root, name):
    return {"submission": (root, name), "harbor_task": (root / "workspace/harbor_task", "harbor_task"),
            "optimization_evidence": (root / "optimization_evidence", "optimization_evidence")}


def _verify_archives(root, directory, manifest):
    scopes = _archive_scopes(root, manifest["name"])
    _require(set(manifest.get("archives", {})) == set(scopes), "ARCHIVE_INVALID", "必须且仅有三个归档范围")
    for role, (source, prefix) in scopes.items():
        path = directory / (prefix + ".zip")
        try:
            entry = _verify_zip(source, path, prefix)
        except (OSError, zipfile.BadZipFile, RuntimeError) as exc:
            raise FlowError("ARCHIVE_INVALID", "ZIP 损坏或无法读取") from exc
        entry = _verify_upload(path, entry, manifest["max_part_bytes"], manifest["upload_limit_bytes"])
        _require(entry == manifest["archives"][role], "ARCHIVE_DRIFT", "已有归档与当前源包/收据不同，禁止覆盖")
    for name, content in _archive_support(manifest["archives"]).items():
        path = directory / name
        _require(path.is_file() and not path.is_symlink() and path.read_text(encoding="utf-8") == content,
                 "ARCHIVE_DRIFT", "归档校验清单或上传说明发生变化")


def _trajectory(path: Path) -> int:
    value = _read_json(path)
    rows = value.get("rounds")
    _require(set(value) == {"rounds"} and isinstance(rows, list) and rows,
             "TRAJECTORY_SCHEMA", f"{path.name} 必须只有非空 rounds")
    for number, row in enumerate(rows, 1):
        validate_round(row, number)
    return len(rows)


def check_package(root: Path) -> dict:
    """Read only from the final package boundary; do not rescue missing evidence outside."""
    candidate = Path(root)
    _require(not candidate.is_symlink(), "PACKAGE_SYMLINK", "提交包根不能是符号链接")
    root = candidate.resolve()
    _require(root.is_dir(), "PACKAGE_MISSING", "提交包不是目录")
    _reject_local_profiles(root)
    _tree_digest(root)
    required_roots = {"workspace", "expert_evidence", "optimization_evidence"}
    _require(required_roots <= {p.name for p in root.iterdir()},
             "PACKAGE_ROOT_SCHEMA", "提交包缺少三个规定目录")
    extras = sorted(p.name for p in root.iterdir() if p.name not in required_roots)
    workspace, expert, opt = (root / name for name in ("workspace", "expert_evidence", "optimization_evidence"))
    _require(all(path.is_dir() for path in (workspace, expert, opt)), "PACKAGE_ROOT_SCHEMA", "顶层条目须为目录")
    _require({"harbor_task", "reference"} <= {p.name for p in workspace.iterdir()}
             and (workspace / "harbor_task").is_dir() and (workspace / "reference").is_dir(),
             "WORKSPACE_SCHEMA", "workspace 缺 harbor_task 或 reference")
    harbor = workspace / "harbor_task"
    check_task(harbor)
    exposure = check_exposure_manifest(workspace)
    _require(EXPERT_FILES <= {p.name for p in expert.iterdir()}, "EXPERT_SCHEMA", "expert_evidence 缺必交文件/目录")
    _require(OPT_FILES <= {p.name for p in opt.iterdir()}, "OPT_SCHEMA", "optimization_evidence 缺必交证据")
    _require((expert / "best_method").is_dir() and _files(root, expert / "best_method"),
             "BEST_METHOD_EMPTY", "best_method 为空")
    _require(not (expert / "best_method" / "selection.json").exists(), "INTERNAL_LEAK", "选择账本不可混入最终方法")
    for name in ("专家作业说明文档.md",):
        _require((expert / name).is_file() and (expert / name).read_text(encoding="utf-8").strip(),
                 "EXPERT_SCHEMA", f"{name} 为空")
    _require((opt / "训练证据说明.md").is_file() and (opt / "训练证据说明.md").read_text(encoding="utf-8").strip(),
             "OPT_SCHEMA", "训练证据说明为空")
    rounds = {track: _trajectory(expert / f"trajectory_{track}.json") for track in TRACKS}
    annotation = _read_json(expert / "expert_annotation.json")
    summary = _read_json(expert / "run_summary.json")
    comparison = _read_json(opt / "comparison_summary.json")
    _require(isinstance(annotation.get("task_id"), str) and annotation["task_id"]
             and annotation.get("task_type") in {"S1", "S2", "S3"}
             and all(isinstance(annotation.get(key), str) and annotation[key].strip()
                     for key in ("research_direction", "optimization_surface")),
             "ANNOTATION_SCHEMA", "expert_annotation 缺题目类型、方向或优化面")
    score = annotation.get("score_contract")
    _require(isinstance(score, dict) and score.get("direction") in {"maximize", "minimize"}
             and isinstance(score.get("metric"), str) and score["metric"]
             and isinstance(score.get("split"), str) and score["split"]
             and isinstance(score.get("protocol"), str) and score["protocol"],
             "ANNOTATION_SCHEMA", "score_contract 不完整")
    for anchor in ("baseline", "reference"):
        item = score.get(anchor)
        _require(isinstance(item, dict) and type(item.get("raw_value")) in (int, float)
                 and math.isfinite(item["raw_value"]) and type(item.get("normalized_score")) in (int, float)
                 and math.isfinite(item["normalized_score"]), "ANNOTATION_SCHEMA", f"{anchor} 锚点不完整")
    upper = score.get("upper_bound")
    _require(isinstance(upper, dict) and type(upper.get("raw_value")) in (int, float)
             and math.isfinite(upper["raw_value"])
             and upper.get("source") in {"estimated_attainable_upper_bound", "metric_ceiling"},
             "ANNOTATION_SCHEMA", "U 锚点不完整")
    baseline_raw = score["baseline"]["raw_value"]
    reference_raw = score["reference"]["raw_value"]
    upper_raw = upper["raw_value"]
    sign = 1 if score["direction"] == "maximize" else -1
    _require(sign * (upper_raw - baseline_raw) > 0 and sign * (reference_raw - baseline_raw) > 0,
             "ANCHOR_DIRECTION", "B/R/U 原始指标方向或锚点顺序不正确")
    normalized = (reference_raw - baseline_raw) / (upper_raw - baseline_raw)
    _require(abs(score["baseline"]["normalized_score"]) <= 1e-8
             and abs(score["reference"]["normalized_score"] - normalized) <= 0.005
             and 0.15 <= normalized <= 0.8,
             "ANCHOR_SCORE", "归一化锚点与线性评分口径或 Reference 区间不一致")
    isolation = annotation.get("isolation")
    _require(isinstance(isolation, dict) and isolation.get("reference_visible_to_agent") is False
             and isolation.get("hidden_assets_visible_to_agent") is False,
             "ANNOTATION_SCHEMA", "隔离声明缺失或不符合要求")
    _require(summary.get("task_id") == annotation["task_id"]
             and isinstance(summary.get("image"), str) and summary["image"]
             and isinstance(summary.get("status"), str) and summary["status"],
             "SUMMARY_SCHEMA", "run_summary 题目 ID、状态或镜像缺失")
    exception = summary.get("fast_iteration_exception")
    _require(isinstance(exception, dict) and type(exception.get("used")) is bool,
             "SUMMARY_SCHEMA", "须声明 fast_iteration_exception.used")
    from .policies import DURATION_SECONDS
    minimum_hours = DURATION_SECONDS["non_training_7h" if exception["used"] else "default_10h"] / 3600
    executions = summary.get("agent_execution")
    _require(isinstance(executions, list) and len(executions) == 2
             and all(isinstance(x, dict) and x.get("runtime") == "Codex"
                     and isinstance(x.get("model"), str) and x["model"]
                     and type(x.get("duration_hours")) in (int, float) and math.isfinite(x["duration_hours"])
                     and x["duration_hours"] >= minimum_hours
                     and type(x.get("effective_rounds")) is int and x["effective_rounds"] > 0
                     and type(x.get("typical_round_minutes")) in (int, float)
                     and math.isfinite(x["typical_round_minutes"]) and x["typical_round_minutes"] > 0 for x in executions),
             "SUMMARY_SCHEMA", "两组 Agent 的实际净时长/轮次记录不足冻结门槛或不完整")
    if exception["used"]:
        _require(all(exception.get(key) is True for key in ("non_training", "short_iterations", "rollable_proved"))
                 and isinstance(exception.get("evidence"), str) and exception["evidence"].strip(),
                 "SUMMARY_SCHEMA", "7h例外须明确全部资格和证据")
    else:
        _require(all(key in exception and exception[key] in (None, False) for key in ("non_training", "short_iterations")),
                 "SUMMARY_SCHEMA", "非例外任务资格字段须为空/false")
    validation = summary.get("validation")
    _require(isinstance(validation, dict) and all(validation.get(key) is True for key in
             ("baseline_passed", "reference_passed", "optimization_evidence_complete", "best_method_rerun_passed")),
             "SUMMARY_SCHEMA", "专家自验存在未通过项")
    _require(isinstance(comparison, dict) and comparison, "OPT_SCHEMA", "comparison_summary 为空")
    _require(not any(key in annotation for key in ("approved", "audit_passed"))
             and summary["status"] not in {"approved", "audit_passed"},
             "UNSUPPORTED_APPROVAL", "专家文件不得自称官方审核通过")
    protocol = comparison.get("evaluation_protocol")
    if exception["used"]:
        from .duration_delivery import check as check_duration_evidence
        check_duration_evidence(root, summary, protocol, score["protocol"])
    training, minimum, declared_seeds = True, 3, None  # Legacy training packages.
    if protocol is not None:
        _require(isinstance(protocol, dict) and type(protocol.get("training")) is bool
                 and protocol.get("evaluation_mode") in {"random", "deterministic"}
                 and type(protocol.get("high_variance", False)) is bool,
                 "OPT_SCHEMA", "evaluation_protocol 须声明训练型、随机性和高方差口径")
        training = protocol["training"]
        minimum = 5 if protocol.get("high_variance", False) else 3 if training or protocol["evaluation_mode"] == "random" else 1
        values = protocol.get("seeds")
        _require(isinstance(values, list) and len(values) >= minimum
                 and all(type(seed) is int and seed >= 0 for seed in values)
                 and len(set(values)) == len(values), "OPT_SCHEMA", "声明的正式 seed 数量/类型不合法")
        declared_seeds = {f"seed_{seed}" for seed in values}
    seed_sets = []
    for role in ("baseline", "reference"):
        directory = opt / f"{role}_runs"
        seeds = {p.name for p in directory.iterdir() if p.is_dir()}
        _require(len(seeds) >= minimum and all(name.startswith("seed_") for name in seeds)
                 and (declared_seeds is None or seeds == declared_seeds),
                 "OPT_SCHEMA", f"{role} 正式 seed 目录与声明协议不一致或不足 {minimum} 次")
        _require(all({"result.json", "run.log"} <= {p.name for p in (directory / seed).iterdir()}
                     for seed in seeds), "OPT_SCHEMA", f"{role} 缺结果或日志")
        if training:
            _require(all((directory / seed / "model").is_dir() and _files(root, directory / seed / "model")
                         for seed in seeds), "OPT_SCHEMA", f"{role} 训练型任务缺模型")
        for seed in seeds:
            _require(_read_json(directory / seed / "result.json")
                     and (directory / seed / "run.log").is_file()
                     and (directory / seed / "run.log").stat().st_size > 0,
                     "OPT_SCHEMA", f"{role}/{seed} 原始结果或训练日志为空")
        seed_sets.append(seeds)
    _require(seed_sets[0] == seed_sets[1], "OPT_SEED_MISMATCH", "Baseline/Reference 正式 seed 不成对")
    for path in root.rglob("*"):
        _require(path.name not in {".git", ".autoresearch-flow", "__pycache__"},
                 "INTERNAL_LEAK", "提交包含内部状态或构建缓存")
    return {"status": "format_checked_not_qa", "package_path": str(root),
            "package_sha256": _tree_digest(root), "trajectory_rounds": rounds,
            "formal_seed_count": len(seed_sets[0]), "file_count": len(_files(root, root)),
            "exposure": exposure,
            "format_observations": [{"path": name, "classification": "extra_allowed",
                "recommendation": "额外材料不单独判失败；由独立 QA 按内容复核保留、合并或归位。"}
                for name in extras]}


class DeliveryPackage:
    def __init__(self, task_root: Path):
        self.evidence = DeliveryEvidence(task_root)
        self.store = TaskStore(Path(task_root))
        self.root = self.store.task_root
        self.directory = self.store.state_dir / "delivery"

    def build(self, spec: dict) -> dict:
        _require(not self.store.check()["issues"], "SOURCE_DRIFT", "规则来源漂移")
        _require(isinstance(spec, dict) and isinstance(spec.get("protocol_id"), str),
                 "PACKAGE_SPEC", "须给正式协议 ID")
        best_dir, selection = self.evidence.current_best()
        verified = self.evidence.best_verification()
        _require(verified["protocol_id"] == spec["protocol_id"], "PROTOCOL_MISMATCH", "最佳方法与交付协议不同")
        report = ExperimentBook(self.root).report(spec["protocol_id"])
        _require(report["status"] in {"ok", "needs_review"}, "BR_EVIDENCE_INCOMPLETE", "B/R 正式证据不完整")
        workspace = _safe_tree(self.root, spec.get("workspace_directory"))
        optimization = _safe_tree(self.root, spec.get("optimization_directory"))
        source_files = {key: evidence(self.root, spec.get(key)) for key in
                        ("expert_document", "expert_annotation", "run_summary")}
        score = _read_json(source_files["expert_annotation"]).get("score_contract")
        _require(isinstance(score, dict), "ANNOTATION_SCHEMA", "expert_annotation 缺 score_contract 对象")
        metric = report.get("metric", {})
        identity = {"protocol": report.get("protocol_id"), "metric": metric.get("name"),
                    "direction": metric.get("direction"), "split": report.get("split")}
        _require(all(isinstance(v, str) and v and score.get(k) == v for k, v in identity.items())
                 and identity["protocol"] == spec["protocol_id"], "BR_METRIC_MISMATCH",
                 "W2 正式协议/指标/方向/split 缺失或与评分合同不一致；不得重新贴标签")
        support = spec.get("support_files", [])
        _require(isinstance(support, list), "PACKAGE_SPEC", "support_files 须为按需支撑证据列表")
        support_targets = set()
        for item in support:
            _require(isinstance(item, dict) and set(item) == {"source", "destination"},
                     "PACKAGE_SPEC", "支撑证据须有 source 引用与 expert_evidence 内相对 destination")
            evidence(self.root, item["source"])
            value = item["destination"]
            _require(isinstance(value, str) and value and Path(value).parts and not Path(value).is_absolute()
                     and ".." not in Path(value).parts and "\\" not in value
                     and Path(value).as_posix() == value and Path(value).parts[0] not in EXPERT_FILES
                     and not any(Path(value).is_relative_to(p) or Path(p).is_relative_to(value) for p in support_targets),
                     "PACKAGE_SPEC", "支撑证据不能越界、重复或覆盖必交文件")
            support_targets.add(value)
        for key in TRACKS:
            self.evidence.current_review(key)
        from .duration import snapshot as duration_snapshot
        duration = duration_snapshot(self.root)
        source_summary = _read_json(source_files["run_summary"])
        _require(source_summary.get("fast_iteration_exception", {}).get("used")
                 is (duration["policy"]["mode"] == "non_training_7h"),
                 "DURATION_MISMATCH", "摘要是否使用7h例外须与启动前冻结政策一致")
        source_manifest = {"schema_version": 1, "spec": spec, "duration_snapshot": duration,
                           "workspace": _files(self.root, workspace),
                           "optimization": _files(self.root, optimization),
                           "best_selection_sha256": _sha256(best_dir / "selection.json"),
                           "best_verification_sha256": _sha256(self.directory / "best_verifications" / (_read_json(self.directory / "best_verification_current.json")["version"] + ".json")),
                           "trajectories": {t: {"final": self.evidence.current_trajectory(t)[1]["final_sha256"],
                                               "review": _sha256(self.evidence.current_trajectory(t)[0].parent / "review.json")}
                                            for t in TRACKS},
                           "br_experiment_sha256": report["experiment_sha256"]}
        version = _canonical_digest(source_manifest)[:20]
        parent = self.directory / "packages"
        parent.mkdir(parents=True, exist_ok=True)
        target = parent / version
        if target.exists():
            manifest = _read_json(parent / f"{version}.manifest.json")
            checked = check_package(target)
            _require(checked["package_sha256"] == manifest["package_sha256"], "PACKAGE_DRIFT", "既有版本提交包被改动")
            return checked
        with tempfile.TemporaryDirectory(prefix=".w4-package-", dir=parent) as temporary:
            staging = Path(temporary)
            _copy_tree(workspace, staging / "workspace")
            _copy_tree(optimization, staging / "optimization_evidence")
            expert = staging / "expert_evidence"
            expert.mkdir()
            shutil.copy2(source_files["expert_document"], expert / "专家作业说明文档.md")
            shutil.copy2(source_files["expert_annotation"], expert / "expert_annotation.json")
            shutil.copy2(source_files["run_summary"], expert / "run_summary.json")
            for item in support:
                destination = expert / item["destination"]
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(evidence(self.root, item["source"]), destination)
                _require(_sha256(destination) == item["source"]["sha256"], "SUPPORT_DRIFT", "支撑证据复制期间变化")
            (expert / "best_method").mkdir()
            for ref in selection["snapshot_files"]:
                source = evidence(self.root, ref)
                relative = source.relative_to(best_dir)
                destination = expert / "best_method" / relative
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(source, destination)
            for track in TRACKS:
                trajectory, _ = self.evidence.current_trajectory(track)
                shutil.copy2(trajectory, expert / f"trajectory_{track}.json")
            protocol = report.get("evaluation_protocol")
            _require(isinstance(protocol, dict), "BR_EVIDENCE_LINK_MISSING", "W2 缺训练/评测协议元数据")
            summary_path = staging / "optimization_evidence" / "comparison_summary.json"
            comparison = _read_json(summary_path)
            _require("evaluation_protocol" not in comparison or comparison["evaluation_protocol"] == protocol,
                     "PROTOCOL_MISMATCH", "comparison_summary 与 W2 冻结协议不一致")
            comparison["evaluation_protocol"] = protocol
            comparison["formal_aggregates"] = {**identity,
                "seeds": report["seeds"], **{role: {"mean": report["groups"][role]["mean"], "n": report["groups"][role]["count"]}
                                            for role in ("baseline", "reference")}}
            _atomic_json(summary_path, comparison)
            if duration["policy"]["mode"] == "non_training_7h":
                from .duration_delivery import export as export_duration_evidence
                export_duration_evidence(self.root, staging, self.evidence, verified)
            result = check_package(staging)
            attempts = report.get("attempts")
            result_refs = report.get("source_results")
            _require(isinstance(attempts, list) and isinstance(result_refs, dict)
                     and isinstance(report.get("seeds"), list), "BR_EVIDENCE_LINK_MISSING",
                     "W2 报告缺正式逐次结果引用，不能核对交付证据")
            replaced = {a.get("retry_of") for a in attempts if a.get("retry_of")}
            for role in ("baseline", "reference"):
                selected = [a for a in attempts if a.get("role") == role and a.get("run_id") not in replaced]
                _require({a.get("seed") for a in selected} == set(report["seeds"]),
                         "BR_EVIDENCE_LINK_MISSING", f"{role} 正式 seed 引用不完整")
                for attempt in selected:
                    original = evidence(self.root, result_refs.get(attempt["run_id"]))
                    packaged = staging / "optimization_evidence" / f"{role}_runs" / f"seed_{attempt['seed']}" / "result.json"
                    _require(packaged.is_file() and _sha256(original) == _sha256(packaged),
                             "BR_PACKAGE_MISMATCH", f"{role} seed {attempt['seed']} 包内 result 与 W2 正式原始结果不同")
            annotation = _read_json(expert / "expert_annotation.json")
            summary = _read_json(expert / "run_summary.json")
            score = annotation["score_contract"]
            _require(score["protocol"] == spec["protocol_id"], "PROTOCOL_MISMATCH", "标注评分协议与正式协议不同")
            for role in ("baseline", "reference"):
                mean = report["groups"][role]["mean"]
                _require(abs(score[role]["raw_value"] - mean) <= 1e-6,
                         "ANCHOR_MISMATCH", f"{role} 锚点与同协议正式均值不一致")
            for track, row in zip(TRACKS, summary["agent_execution"]):
                status = Runtime(self.root).status(track)
                _require(row["duration_hours"] <= status["effective_seconds_before_content_review"] / 3600 + 0.02,
                         "DURATION_MISMATCH", f"{track} 填报有效时长超过可核台账")
                _require(row["effective_rounds"] <= result["trajectory_rounds"][track],
                         "ROUND_MISMATCH", f"{track} 填报有效轮次超过轨迹")
            _require(_files(self.root, workspace) == source_manifest["workspace"]
                     and _files(self.root, optimization) == source_manifest["optimization"],
                     "SOURCE_DRIFT", "组包期间源码或证据变化")
            staging.rename(target)
        _atomic_json(parent / f"{version}.manifest.json", {**source_manifest,
                     "package_sha256": _tree_digest(target), "created_at": _utc_now()})
        return check_package(target)

    def archive(self, package_root: Path, max_part_bytes: int = 290_000_000, *, name=None, checks=None,
                upload_limit_bytes: int = 300_000_000) -> dict:
        # Reuse the current read-only tutorial + independent-QA gate. It does not
        # require finish(6), run a QA skill, or advance a stage.
        from .stages import StageFlow
        root = Path(package_root).resolve()
        _require(root.is_relative_to(self.root), "PACKAGE_EVIDENCE_BOUNDARY", "归档仅接受本题目内最终目录")
        supplied = {**(checks or {}), "package_root": root.relative_to(self.root).as_posix()}
        gate = StageFlow(self.root).check("6.5", {"step": "6.5", "checks": supplied})
        _require(gate["status"] == "checked", "ARCHIVE_NOT_ACCEPTED", str(gate["issues"]))
        checked = gate["machine_check"]["result"]
        _require(isinstance(name, str) and re.fullmatch(r"[a-z][a-z0-9]*(?:-[a-z0-9]+)*", name)
                 and not re.search(r"(?:tob|auto|task|question|problem)-?\d", name),
                 "INVALID_ARCHIVE_NAME", "完整包须用语义化英文名称，不含题号；子仓名固定")
        _require(type(upload_limit_bytes) is int and 0 < upload_limit_bytes <= 300_000_000,
                 "INVALID_UPLOAD_LIMIT", "上传上限须为正整数且不超过 300,000,000 字节")
        _require(type(max_part_bytes) is int and 0 < max_part_bytes <= min(290_000_000, upload_limit_bytes),
                 "INVALID_PART_SIZE", "分卷大小须为正整数且不超过 290,000,000 字节")
        binding = {"schema_version": 1, "package_sha256": checked["package_sha256"],
                   "report_sha256": checked["report_sha256"], "qa_review_sha256": checked["qa_review_sha256"],
                   "name": name, "max_part_bytes": max_part_bytes, "upload_limit_bytes": upload_limit_bytes}
        parent = self.directory / "archives"
        parent.mkdir(exist_ok=True)
        directory = parent / (name + "-" + _canonical_digest(binding)[:16])
        scopes = _archive_scopes(root, name)
        if not directory.exists():
            with tempfile.TemporaryDirectory(prefix=".preparing-", dir=parent) as temporary:
                staging = Path(temporary)
                archives = {}
                for role, (source, prefix) in scopes.items():
                    path = staging / (prefix + ".zip")
                    _write_zip(source, path, prefix)
                    _split_zip(path, max_part_bytes, upload_limit_bytes)
                    archives[role] = _verify_upload(path, _verify_zip(source, path, prefix),
                                                    max_part_bytes, upload_limit_bytes)
                for filename, content in _archive_support(archives).items():
                    (staging / filename).write_text(content, encoding="utf-8")
                _require(_tree_digest(root) == binding["package_sha256"], "QA_PACKAGE_DRIFT", "压缩期间源包发生变化")
                _atomic_json(staging / "archives.json", {**binding, "archives": archives})
                staging.rename(directory)
        manifest = _read_json(directory / "archives.json")
        _require(all(manifest.get(k) == v for k, v in binding.items()), "ARCHIVE_DRIFT", "归档绑定发生变化")
        _verify_archives(root, directory, manifest)
        _atomic_json(self.directory / "archives_current.json", {"path": str((directory / "archives.json").relative_to(self.root)),
                     "sha256": _sha256(directory / "archives.json")})
        return {"status": "archives_verified", **manifest, "output_directory": str(directory)}

    def delivery_state(self, checked: dict) -> dict:
        """Read back external outputs for this exact QA-accepted version only."""
        pointer = self.directory / "archives_current.json"
        if not pointer.exists():
            return {"delivery_phase": "qa_verified"}
        ref = _read_json(pointer)
        path = evidence(self.root, ref)
        manifest = _read_json(path)
        if any(manifest.get(key) != checked[key] for key in
               ("package_sha256", "report_sha256", "qa_review_sha256")):
            return {"delivery_phase": "qa_verified"}
        _verify_archives(Path(checked["package_path"]), path.parent, manifest)
        result = {"delivery_phase": "archives_verified", "archives_manifest": ref,
                  "output_directory": str(path.parent)}
        if (path.parent / "form.json").exists():
            from .delivery_form import verify
            result.update(delivery_phase="form_ready", form=verify(Path(checked["package_path"]), path))
        return result

    def form(self, package_root: Path, spec: dict) -> dict:
        from .stages import StageFlow
        from .delivery_form import write
        root = Path(package_root).resolve()
        _require(root.is_relative_to(self.root), "PACKAGE_EVIDENCE_BOUNDARY", "填表仅接受本题目内最终目录")
        checks = {**spec.get("checks", {}), "package_root": root.relative_to(self.root).as_posix()}
        gate = StageFlow(self.root).check("6.5", {"checks": checks})
        _require(gate["status"] == "checked", "FORM_NOT_ACCEPTED", str(gate["issues"]))
        result = gate["machine_check"]["result"]
        _require(result["delivery_phase"] in {"archives_verified", "form_ready"},
                 "FORM_ARCHIVES_REQUIRED", "须先完成独立 QA 后的三包压缩与核验")
        path = evidence(self.root, result["archives_manifest"])
        form = write(root, path, spec)
        _require(_tree_digest(root) == result["package_sha256"], "QA_PACKAGE_DRIFT", "填表期间源包发生变化")
        return form

    def qa_handoff(self, package_root: Path) -> dict:
        checked = check_package(package_root)
        record = {"schema_version": 1, "package_path": checked["package_path"],
                  "package_sha256": checked["package_sha256"], "created_at": _utc_now(),
                  "qa_contract": {"skill_version": "0.3.1", "schema_version": 4,
                                  "policy_revision": "research-quality-v3", "skipped_checks": ["QA15"]},
                  "instruction": "请在独立新会话对 package_path 最终包只读运行当前 autoresearch-task-qa，并按路由审 Baseline；报告写包外。撤销旧 QA 口头豁免，QA15 按 Skill 固定跳过；H05/H06 无材料可按原文不适用。静态通过不替代教程端到端自验。"}
        parent = self.directory / "qa" / checked["package_sha256"]
        parent.mkdir(parents=True, exist_ok=True)
        path = parent / "handoff.json"
        if path.exists():
            existing = _read_json(path)
            _require(existing["package_path"] == checked["package_path"],
                     "QA_HANDOFF_DRIFT", "相同哈希的交接路径发生变化")
            record = existing
        else:
            _atomic_json(path, record)
        _atomic_json(self.directory / "qa_handoff_current.json",
                     {"package_sha256": checked["package_sha256"], "handoff_sha256": _sha256(path)})
        return {"status": "awaiting_independent_qa", **record}

    def qa_bind(self, package_root: Path, report_path: Path) -> dict:
        checked = check_package(package_root)
        pointer = _read_json(self.directory / "qa_handoff_current.json")
        handoff_path = self.directory / "qa" / pointer["package_sha256"] / "handoff.json"
        _require(handoff_path.is_file() and _sha256(handoff_path) == pointer["handoff_sha256"],
                 "QA_HANDOFF_DRIFT", "质检交接记录丢失或被改动")
        handoff = _read_json(handoff_path)
        _require(handoff["package_path"] == checked["package_path"]
                 and handoff["package_sha256"] == checked["package_sha256"],
                 "QA_PACKAGE_DRIFT", "质检交接对应的提交包已变化，须重新独立质检")
        raw_report = Path(report_path)
        _require(not raw_report.is_symlink(), "QA_REPORT_MISSING", "质检报告不能是符号链接")
        report = raw_report.resolve()
        _require(report.is_file() and report.stat().st_size > 0,
                 "QA_REPORT_MISSING", "独立质检报告不存在")
        _require(report.suffix == ".json", "QA_REPORT_FORMAT", "请绑定独立质检的机器可读 report.json")
        _require(not report.is_relative_to(Path(checked["package_path"])),
                 "QA_REPORT_BOUNDARY", "独立 QA 报告须保存在提交包之外")
        qa = _read_json(report)
        validate_qa_report(qa)
        source = qa.get("source")
        _require(isinstance(source, dict) and isinstance(source.get("path"), str),
                 "QA_SCOPE_MISMATCH", "质检报告未给明确扫描目录")
        scanned = Path(source["path"])
        _require(scanned.is_absolute() and not scanned.is_symlink() and scanned.is_dir(),
                 "QA_SCOPE_MISMATCH", "质检扫描目录须存在，才能核验异路径同快照")
        scanned_hash = _tree_digest(scanned)
        _require(scanned_hash == checked["package_sha256"], "QA_SCOPE_MISMATCH",
                 "质检扫描目录的路径集合、内容或权限与最终包不同")
        if source.get("sha256") is not None:
            _require(source["sha256"] == checked["package_sha256"], "QA_PACKAGE_DRIFT",
                     "质检报告记录的包哈希不匹配")
        record = {"schema_version": 1, "package_sha256": checked["package_sha256"],
                  "package_path": checked["package_path"], "report_path": str(report),
                  "scanned_path": str(scanned.resolve()), "scanned_sha256": scanned_hash,
                  "report_sha256": _sha256(report), "attached_at": _utc_now(),
                  "status": "attached_unreviewed"}
        directory = self.directory / "qa" / checked["package_sha256"] / "reports"
        directory.mkdir(parents=True, exist_ok=True)
        binding = directory / (record["report_sha256"] + ".json")
        if binding.exists():
            existing = _read_json(binding)
            _require(existing["report_path"] == str(report), "QA_REPORT_DRIFT", "同一质检报告哈希对应路径发生变化")
            record = existing
        else:
            _atomic_json(binding, record)
        _atomic_json(self.directory / "qa_binding_current.json",
                     {"package_sha256": checked["package_sha256"], "binding_sha256": _sha256(binding),
                      "report_sha256": record["report_sha256"]})
        return record
