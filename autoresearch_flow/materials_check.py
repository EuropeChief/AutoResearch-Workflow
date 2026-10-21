"""Package-only structural and numeric checks, never a scientific QA verdict."""
from __future__ import annotations

import math
import re
import statistics
import tomllib
from datetime import datetime
from pathlib import Path

from .common import _sha256, _canonical_digest, FlowError
from .experiment_data import raw_value, quality_passed, normalize, minimum_repeats
from .materials_io import bundled, files, inside, reference, read_object, issue, WORK_NAMES, SECRET_NAMES
from .materials_trajectory import check_rounds
from .runtime_events import effective_seconds

TRACKS = ("codex", "seed")
EXPERT_FILES = ("专家作业说明文档.md", "expert_annotation.json", "run_summary.json")
HEADINGS = ("Goal", "Task Setting", "Objective and Metrics", "Allowed Scope", "Hard Boundaries",
            "Submission Instructions", "Workflow & Iteration", "Completion Criteria")
VALID_RESULTS = {"COMPLETE", "COMPLETED", "SUCCESS", "SUCCEEDED", "VALID", "OK"}


class Inspection:
    def __init__(self, root):
        self.root = Path(root).resolve()
        self.issues, self.pending, self.notes = [], [], []
        self.records = {}
        self.task_id = None

    def problem(self, code, path, message, *, review=False):
        issue(self.issues, code, path, message, level="review" if review else "error")

    def guard(self, path, function):
        try:
            return function()
        except (FlowError, ValueError, TypeError, KeyError, AttributeError, OSError) as exc:
            self.problem(getattr(exc, "code", "FIELD_ERROR"), path, str(exc))
            return None

    def json(self, name):
        return self.guard(name, lambda: read_object(inside(self.root, name)))

    def required(self, condition, code, path, text):
        if not condition:
            self.problem(code, path, text)

    def refs(self, value, path):
        """Digest references are evidence; raw Trial runtime paths stay unchanged."""
        if isinstance(value, dict):
            if path.endswith(".method"):
                return  # Method directories/file inventories are checked by result(), not file refs.
            if "path" in value and "sha256" in value:
                self.guard(path, lambda: reference(self.root, value, nonempty=False))
            else:
                for key, item in value.items():
                    self.refs(item, path + "." + key)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                self.refs(item, f"{path}[{i}]")


def finite(value):
    return type(value) in (int, float) and math.isfinite(value)


def close(actual, expected):
    return finite(actual) and expected is not None and math.isclose(actual, expected, rel_tol=1e-8, abs_tol=1e-8)


def annotation(c):
    path = "expert_evidence/expert_annotation.json"
    a = c.json(path)
    if a is None:
        return None
    for key in ("task_id", "research_direction", "optimization_surface"):
        c.required(isinstance(a.get(key), str) and bool(a[key].strip()), "ANNOTATION_FIELD", path + "." + key, "须为非空字符串")
    c.required(a.get("task_type") in {"S1", "S2", "S3"}, "ANNOTATION_FIELD", path + ".task_type", "须为 S1/S2/S3")
    s = a.get("score_contract", {})
    c.required(isinstance(s, dict), "ANNOTATION_FIELD", path + ".score_contract", "须为对象")
    if not isinstance(s, dict):
        return a
    for key in ("metric", "split", "protocol"):
        c.required(isinstance(s.get(key), str) and bool(s[key].strip()), "ANNOTATION_FIELD", path + ".score_contract." + key, "须为非空字符串")
    c.required(s.get("direction") in {"maximize", "minimize"}, "METRIC_DIRECTION", path, "原始指标方向须明确")
    for key in ("baseline", "reference", "upper_bound"):
        val = s.get(key, {})
        c.required(isinstance(val, dict) and finite(val.get("raw_value")), "ANCHOR_FIELD", path + ".score_contract." + key, "须有有限 raw_value")
    if all(isinstance(s.get(k), dict) and finite(s[k].get("raw_value")) for k in ("baseline", "reference", "upper_bound")):
        b, r, u = (s[k]["raw_value"] for k in ("baseline", "reference", "upper_bound"))
        score = c.guard(path, lambda: normalize(r, b, u, s.get("direction")))
        if score is not None:
            c.required(close(s["baseline"].get("normalized_score"), 0), "ANCHOR_SCORE", path, "Baseline 归一化应为 0")
            c.required(close(s["reference"].get("normalized_score"), score), "ANCHOR_SCORE", path, "Reference 分数与 B/R/U 公式不一致")
            c.required(0.15 <= score <= 0.8, "REFERENCE_RANGE", path, "Reference 正式归一化超出 [0.15,0.8]")
        c.required(s["upper_bound"].get("source") in {"estimated_attainable_upper_bound", "metric_ceiling"}, "ANCHOR_FIELD", path + ".score_contract.upper_bound.source", "须声明 U 来源")
    iso = a.get("isolation", {})
    c.required(isinstance(iso, dict) and iso.get("reference_visible_to_agent") is False
               and iso.get("hidden_assets_visible_to_agent") is False, "ISOLATION_DECLARATION", path + ".isolation", "须声明 Reference/Hidden 不可见")
    c.required(not any(k in a for k in ("approved", "audit_passed")), "OFFICIAL_APPROVAL", path, "专家文件不能自称官方审核通过")
    return a


def summary(c, a, trajectories):
    path = "expert_evidence/run_summary.json"
    s = c.json(path)
    if s is None:
        return None
    c.required(isinstance(s.get("task_id"), str) and (a is None or s["task_id"] == a.get("task_id")), "TASK_ID", path + ".task_id", "题目 ID 与 annotation 不一致/缺失")
    for key in ("status", "image"):
        c.required(isinstance(s.get(key), str) and bool(s[key].strip()), "SUMMARY_FIELD", path + "." + key, "须为非空字符串；image 为 Agent 镜像")
    c.required(s.get("status") not in {"approved", "audit_passed"}, "OFFICIAL_APPROVAL", path, "不能声称官方已审核")
    ex = s.get("fast_iteration_exception", {})
    c.required(isinstance(ex, dict) and type(ex.get("used")) is bool, "DURATION_POLICY", path, "须声明 fast_iteration_exception.used")
    used = isinstance(ex, dict) and ex.get("used") is True
    if isinstance(ex,dict):
        c.required(all(k in ex for k in ("used","non_training","short_iterations","rollable_proved","evidence"))
                   and all(ex.get(k) is None or type(ex[k]) is bool for k in ("non_training","short_iterations"))
                   and type(ex.get("rollable_proved")) is bool and isinstance(ex.get("evidence"),str),
                   "DURATION_POLICY", path+".fast_iteration_exception", "资格/闭环布尔值及证据字符串类型不完整")
    if used:
        c.required(all(ex.get(k) is True for k in ("non_training", "short_iterations", "rollable_proved"))
                   and isinstance(ex.get("evidence"), str) and bool(ex["evidence"].strip()), "DURATION_POLICY", path, "7h例外须有全部资格和证据说明")
    else:
        c.required(isinstance(ex, dict) and all(ex.get(k) in (False, None) for k in ("non_training", "short_iterations")),
                   "DURATION_POLICY", path, "未用例外时资格应为 false/null")
    executions = s.get("agent_execution")
    c.required(isinstance(executions, list) and len(executions) == 2, "SUMMARY_AGENTS", path, "须有两组独立 Agent")
    if isinstance(executions, list):
        seen = set()
        for i, row in enumerate(executions):
            loc = f"{path}.agent_execution[{i}]"
            if not isinstance(row, dict):
                c.problem("SUMMARY_FIELD", loc, "须为对象")
                continue
            track = row.get('track', TRACKS[i] if i < len(TRACKS) else None)
            c.required(track in TRACKS and track not in seen
                       and isinstance(row.get('model'), str) and bool(row['model'].strip())
                       and isinstance(row.get('runtime'), str) and bool(row['runtime'].strip()),
                       "SUMMARY_MODEL", loc, "须如实记录两轨模型/runtime；不限制示例型号")
            seen.add(track)
            c.required(finite(row.get("duration_hours")) and row["duration_hours"] >= (7 if used else 10), "DURATION_SHORT", loc + ".duration_hours", "各轨净有效时长不足适用下限")
            count = row.get("effective_rounds")
            c.required(type(count) is int and count > 0 and (not used or count >= 3), "SUMMARY_ROUNDS", loc, "有效方法轮数不合法或7h闭环不足")
            if track in trajectories and type(count) is int:
                c.required(count <= len(trajectories[track].get("rounds", [])), "SUMMARY_ROUNDS", loc, "有效轮数超过实际轨迹轮数")
            c.required(finite(row.get("typical_round_minutes")) and row["typical_round_minutes"] > 0, "SUMMARY_FIELD", loc + ".typical_round_minutes", "须为实际正数")
    val = s.get("validation", {})
    c.required(isinstance(val, dict) and all(type(val.get(k)) is bool for k in ("baseline_passed", "reference_passed", "optimization_evidence_complete", "best_method_rerun_passed")),
               "SUMMARY_VALIDATION", path, "validation 四项须为布尔值")
    if isinstance(val, dict) and any(x is False for x in val.values()):
        c.problem("SUMMARY_VALIDATION", path, "声明仍有未通过自验项")
    return s


def task(c, a):
    base = "workspace/harbor_task"
    t = c.guard(base + "/task.toml", lambda: tomllib.loads(inside(c.root, base + "/task.toml").read_text()))
    if not t:
        return None
    v = t.get("verifier", {})
    c.required(isinstance(v, dict) and v.get("environment_mode") == "separate", "VERIFIER_MODE", base + "/task.toml", "显式 separate 缺失/类型错误")
    for owner, env in (("environment", t.get("environment")), ("verifier.environment", v.get("environment", t.get("environment")) if isinstance(v, dict) else None)):
        c.required(isinstance(env, dict), "TASK_ENVIRONMENT", base + "/task.toml." + owner, "须提供独立环境对象")
        if isinstance(env, dict):
            for key in ("cpus", "memory_mb", "storage_mb", "gpus"):
                if key in env:
                    c.required(finite(env[key]) and env[key] >= 0 and (key != "gpus" or type(env[key]) is int), "TASK_RESOURCE", base + "/task.toml." + owner + "." + key, "资源值类型/范围错误")
    artifacts = t.get("artifacts")
    c.required(isinstance(artifacts, list) and bool(artifacts), "TASK_ARTIFACTS", base + "/task.toml.artifacts", "须声明实际候选/产物移交")
    if isinstance(artifacts, list):
        for i, entry in enumerate(artifacts):
            source = entry if isinstance(entry, str) else entry.get("source") if isinstance(entry, dict) else None
            c.required(isinstance(source, str) and source.startswith("/") and source not in {"/", "/workspace"}, "TASK_ARTIFACTS", f"{base}/task.toml.artifacts[{i}]", "须为明确候选源绝对路径，不是宽泛工作区")
    metadata = t.get("metadata", {})
    if a and isinstance(metadata, dict) and isinstance(a.get("score_contract"), dict):
        score = a["score_contract"]
        for key, expected in (("raw_metric", score.get("metric")), ("metric_direction", score.get("direction"))):
            if key in metadata:
                c.required(metadata[key] == expected, "TASK_METRIC", base + "/task.toml.metadata." + key, "与 annotation 不一致")
    docker = c.guard(base, lambda: bundled("docker_paths").inspect(c.root, base, t, {"profile": "harbor-environment-v1"}, require_separate=True))
    if docker:
        for finding in docker.get("findings", []):
            if finding.get("status") in {"fail", "manual"}:
                c.problem("DOCKER_" + finding.get("code", "PATH"), base, finding.get("message", finding.get("detail", str(finding))), review=finding["status"] == "manual")
    doc = c.guard(base + "/instruction.md", lambda: inside(c.root, base + "/instruction.md").read_text())
    if doc is not None:
        for heading in HEADINGS:
            match = re.search(r"(?im)^##\s+" + re.escape(heading) + r"\s*$", doc)
            if not match:
                c.problem("INSTRUCTION_SECTION", base + "/instruction.md", "缺教程标题或等价章节需核查：" + heading, review=True)
            else:
                body = re.split(r"(?m)^##\s", doc[match.end():], maxsplit=1)[0].strip()
                c.required(bool(body), "INSTRUCTION_EMPTY", base + "/instruction.md#" + heading, "章节无实际内容")
        if re.search(r"https?://(?:arxiv\.org|github\.com)/|arXiv\s*:\s*\d", doc, re.I):
            c.problem("INSTRUCTION_SOURCE", base + "/instruction.md", "题面含论文/arXiv/仓库来源线索")
        if re.search(r"<platform_task_id>|<Task Title>|TODO|待填写", doc):
            c.problem("PLACEHOLDER", base + "/instruction.md", "题面残留模板占位")
    c.pending.append("目标 Harbor schema/字段生效、实际调用与可见性由包内动态证据和独立 QA 核查")
    return t


def result(c, path, role, seed, metric, training):
    record = c.json(path)
    if record is None:
        return None
    c.records[(role, seed)] = record
    for key in bundled("submission_format").REQUIRED_RESULT_FIELDS:
        c.required(key in record, "RESULT_FIELD", path + "." + key, "缺正式十二字段")
    if "task_id" in record and c.task_id:
        c.required(record["task_id"]==c.task_id, "TASK_ID", path+".task_id", "逐次结果属于另一题")
    c.required(type(record.get("seed")) is int and record["seed"] == seed, "RESULT_SEED", path + ".seed", "seed 与目录/声明不一致")
    c.required(record.get("role") == role, "RESULT_ROLE", path + ".role", "role 与目录不一致")
    c.required(isinstance(record.get("schema_version"), (str, int)) and not isinstance(record.get("schema_version"), bool), "RESULT_FIELD", path + ".schema_version", "须为版本字符串或整数")
    for key in ("method", "protocol", "execution", "metrics", "quality_gate", "artifacts"):
        c.required(isinstance(record.get(key), dict), "RESULT_FIELD", path + "." + key, "须为对象")
    c.required(isinstance(record.get("task_type"), str) and bool(record["task_type"].strip()), "RESULT_FIELD", path + ".task_type", "须声明任务类型")
    c.refs(record, path)
    c.required(str(record.get("status")).upper() in VALID_RESULTS, "RESULT_INVALID", path + ".status", "正式结果无效/未完成；保留失败原件但不能计入完整结论")
    c.required(quality_passed(record), "RESULT_QUALITY", path + ".quality_gate", "质量门未通过/未知")
    e = record.get("execution", {})
    if isinstance(e, dict):
        for key in ("command", "started_at", "finished_at", "exit_code"):
            val = e.get(key)
            c.required(key in e and (val is not None or bool(e.get("missing_reason") or e.get("missing_metadata_reason"))), "RESULT_EXECUTION", path + ".execution." + key, "须记真实值或 null 及缺失解释")
        command = e.get("command")
        if command is not None:
            c.required(isinstance(command,str) and bool(command.strip())
                       or isinstance(command,list) and bool(command) and all(isinstance(x,str) and x for x in command),
                       "RESULT_EXECUTION", path+".execution.command", "命令须为非空字符串或参数数组")
        stamps = []
        for key in ("started_at","finished_at"):
            if e.get(key) is not None:
                value = e[key]
                stamp = c.guard(path+".execution."+key,
                                lambda value=value: datetime.fromisoformat(value.replace("Z","+00:00")) if isinstance(value,str) else (_ for _ in ()).throw(ValueError("时间须为字符串")))
                if stamp:
                    stamps.append(stamp)
        if len(stamps)==2:
            c.guard(path+".execution",lambda: c.required(stamps[1]>=stamps[0], "RESULT_EXECUTION", path+".execution", "结束时间早于开始"))
        duration = e.get("duration_seconds",e.get("wall_clock_seconds"))
        c.required(duration is not None and finite(duration) and duration>=0 or duration is None
                   and bool(e.get("missing_reason") or e.get("missing_metadata_reason")),
                   "RESULT_EXECUTION", path+".execution.duration_seconds", "缺实际有限耗时或 null 缺失说明")
        if e.get("exit_code") is not None:
            c.required(type(e["exit_code"]) is int and e["exit_code"] == 0, "RESULT_EXECUTION", path, "正式有效结果退出码须成功")
    method = record.get("method", {})
    if isinstance(method, dict):
        source = method.get("path", method.get("source_path"))
        if source:
            actual = c.guard(path + ".method.path", lambda: inside(c.root, source, directory=None, nonempty=False))
            if actual and actual.is_file():
                c.required(method.get("sha256", method.get("source_sha256")) == _sha256(actual),
                           "RESULT_METHOD", path+".method", "源码文件与其哈希不一致")
        else:
            c.problem("RESULT_METHOD", path, "缺包内实际源码路径")
        digest = method.get("sha256", method.get("source_sha256"))
        c.required(isinstance(digest, str) and bool(re.fullmatch(r"[0-9a-f]{64}", digest)), "RESULT_METHOD", path, "缺有效源码 SHA-256")
        if isinstance(method.get("files"), dict) and source:
            c.required(_canonical_digest(method["files"]) == digest, "RESULT_METHOD", path, "方法清单与源码指纹矛盾")
            for name, sha in method["files"].items():
                c.guard(path + ".method.files." + name, lambda name=name, sha=sha: reference(c.root, {"path": str(Path(source)/name), "sha256": sha}, nonempty=False))
    parent = str(Path(path).parent)
    c.guard(parent + "/run.log", lambda: inside(c.root, parent + "/run.log"))
    artifacts = record.get("artifacts", {})
    if isinstance(artifacts, dict):
        for key, ref in artifacts.items():
            if isinstance(ref, (dict, str)) and (isinstance(ref, str) or "path" in ref):
                c.guard(path + ".artifacts." + key, lambda ref=ref: reference(c.root, ref))
    train = record.get("training")
    if training:
        c.required(isinstance(train, dict), "RESULT_TRAINING", path + ".training", "训练型须有实际训练信息")
        if isinstance(train, dict) and "origin" in train:
            c.required(train["origin"] in {"initialization", "declared_pretrained"}, "RESULT_TRAINING", path + ".training.origin", "须为独立初始化或已声明预训练")
            if train["origin"]=="declared_pretrained":
                c.required(bool(record.get("protocol", {}).get("pretrained")), "RESULT_TRAINING", path, "未在协议声明共享预训练起点")
        model_dir = parent + "/model"
        meta = c.json(model_dir + "/artifact.json")
        c.guard(model_dir + "/reload.log", lambda: inside(c.root, model_dir + "/reload.log"))
        model_ref = artifacts.get("model") if isinstance(artifacts, dict) else None
        model = c.guard(path + ".artifacts.model", lambda: reference(c.root, model_ref))
        if model and meta:
            for key, expected in (("role", role), ("seed", seed), ("sha256", _sha256(model)), ("size_bytes", model.stat().st_size)):
                c.required(meta.get(key) == expected, "MODEL_BINDING", model_dir + "/artifact.json." + key, "模型元信息与实际模型/逐次结果不一致")
            c.required(meta.get("method_sha256") == method.get("sha256", method.get("source_sha256")), "MODEL_BINDING", model_dir + "/artifact.json.method_sha256", "模型方法哈希不一致")
            c.required(isinstance(meta.get("format"), str) and bool(meta["format"]), "MODEL_FIELD", model_dir + "/artifact.json.format", "缺实际模型格式")
            c.required(meta.get("reload_passed") is True, "MODEL_RELOAD", model_dir + "/artifact.json", "缺成功独立重载状态")
            raw = c.guard(path, lambda: raw_value(record, metric))
            tolerance = record.get("protocol", {}).get("reload_tolerance", 0)
            c.required(finite(meta.get("reload_metric")) and raw is not None and finite(tolerance)
                       and tolerance>=0 and abs(meta["reload_metric"]-raw)<=max(tolerance,1e-8),
                       "MODEL_RELOAD", model_dir + "/artifact.json.reload_metric", "重载复评分缺失或超出实际协议容差")
    else:
        c.required(train == "NOT_APPLICABLE" or isinstance(train, dict) and train.get("status") == "NOT_APPLICABLE", "RESULT_TRAINING", path + ".training", "非训练须声明 NOT_APPLICABLE")
        c.required(not (c.root/parent/"model").exists(), "EMPTY_MODEL", parent, "非训练无需模型目录")
    return c.guard(path + ".metrics", lambda: raw_value(record, metric))


def comparison(c, a):
    path = "optimization_evidence/comparison_summary.json"
    data = c.json(path)
    if data is None:
        return None
    p = data.get("evaluation_protocol", data.get("protocol"))
    if not isinstance(p, dict):
        c.problem("COMPARISON_PROTOCOL", path, "缺实际 evaluation_protocol/protocol")
        return data
    metric = data.get("metric")
    if not isinstance(metric, dict):
        c.problem("COMPARISON_METRIC", path, "metric 须为含 name/direction 的对象")
        return data
    metric = {**metric, "unit": metric.get("unit", "")}
    c.required(metric.get("direction") in {"maximize", "minimize"}, "COMPARISON_METRIC", path, "缺原始方向")
    training = p.get("training")
    c.required(type(training) is bool and p.get("evaluation_mode") in {"random", "deterministic"}, "COMPARISON_PROTOCOL", path, "须声明训练适用性及随机/确定性")
    seeds = data.get("seeds")
    if not isinstance(seeds, list) or not seeds or any(type(x) is not int or x < 0 for x in seeds) or len(set(seeds)) != len(seeds):
        c.problem("COMPARISON_SEEDS", path, "正式 seed 列表须为不重复非负整数")
        return data
    if "seeds" in p:
        c.required(p["seeds"] == seeds, "COMPARISON_SEEDS", path, "protocol 与 summary 声明 seed 不同")
    if type(training) is bool and p.get("evaluation_mode") in {"random", "deterministic"}:
        c.required(len(seeds) >= minimum_repeats(p), "COMPARISON_REPEAT", path, "正式次数不足当前口径")
    values = {}
    for role in ("baseline", "reference"):
        directory = c.root/"optimization_evidence"/(role+"_runs")
        dirs = {x.name for x in directory.iterdir() if x.is_dir()} if directory.is_dir() else set()
        c.required(dirs == {f"seed_{s}" for s in seeds}, "COMPARISON_SEEDS", str(directory.relative_to(c.root)), "目录与完整正式 seed 集不符")
        values[role] = {}
        for seed in seeds:
            name = f"optimization_evidence/{role}_runs/seed_{seed}/result.json"
            raw = result(c, name, role, seed, metric, training)
            if raw is not None:
                values[role][seed] = raw
    protocols = [r.get("protocol") for (role, _), r in c.records.items() if role in {"baseline", "reference"}]
    c.required(bool(protocols) and all(x==protocols[0] for x in protocols), "RESULT_PROTOCOL", path, "B/R 各 seed 实际协议不一致")
    if protocols and "metric" in protocols[0] and isinstance(protocols[0]["metric"], dict):
        c.required(protocols[0] == p, "RESULT_PROTOCOL", path, "逐次实际协议与汇总声明不同")
    if metric.get("direction") in {"minimize", "maximize"} and all(len(v)==len(seeds) for v in values.values()):
        sign = 1 if metric["direction"]=="maximize" else -1
        means = {k: statistics.mean(v.values()) for k, v in values.items()}
        std = {k: statistics.stdev(v.values()) if len(v)>1 else None for k, v in values.items()}
        delta = sign*(means["reference"]-means["baseline"])
        computed = {"baseline_mean": means["baseline"], "reference_mean": means["reference"],
                    "baseline_sample_std": std["baseline"], "reference_sample_std": std["reference"],
                    "mean_paired_improvement": delta, "relative_improvement": delta/abs(means["baseline"]) if means["baseline"] else None,
                    "baseline_sigma_multiple": delta/std["baseline"] if std["baseline"] else None,
                    "paired_run_count": len(seeds)}
        claimed = data.get("statistics", {})
        c.required(isinstance(claimed, dict), "COMPARISON_STATISTICS", path, "statistics 须为对象")
        if isinstance(claimed, dict):
            for key, expected in computed.items():
                c.required(key in claimed and (claimed[key] is None if expected is None else close(claimed[key], expected)), "COMPARISON_STATISTICS", path+".statistics."+key, "与逐次原始值复算不一致/缺失")
        pairs = data.get("paired_results")
        if isinstance(pairs, list):
            c.required(all(isinstance(x,dict) and type(x.get("seed")) is int for x in pairs)
                       and len({x["seed"] for x in pairs if isinstance(x,dict) and "seed" in x})==len(pairs),
                       "COMPARISON_PAIRS", path, "配对列表须有唯一真实 seed")
            pairs = {str(x["seed"]):x for x in pairs if isinstance(x,dict) and type(x.get("seed")) is int}
        c.required(isinstance(pairs, dict) and set(pairs)=={str(x) for x in seeds}, "COMPARISON_PAIRS", path, "缺全部逐 seed 配对结果")
        if isinstance(pairs, dict):
            for seed in seeds:
                pair = pairs.get(str(seed), {})
                for key, expected in (("baseline", values["baseline"][seed]), ("reference", values["reference"][seed]), ("paired_improvement", sign*(values["reference"][seed]-values["baseline"][seed]))):
                    c.required(isinstance(pair, dict) and close(pair.get(key), expected), "COMPARISON_PAIRS", f"{path}.paired_results.{seed}.{key}", "与原始配对值不符")
        if a and isinstance(a.get("score_contract"), dict):
            s = a["score_contract"]
            c.required(metric.get("name")==s.get("metric") and metric.get("direction")==s.get("direction"), "COMPARISON_METRIC", path, "与 annotation 指标/方向不同")
            if "split" in data:
                c.required(data["split"]==s.get("split"), "COMPARISON_SPLIT", path, "与 annotation split 不同")
            for role in means:
                c.required(isinstance(s.get(role), dict) and close(s[role].get("raw_value"), means[role]), "COMPARISON_ANCHOR", path, "annotation 锚点不是完整正式均值："+role)
        data["_computed"] = computed
        rule = data.get("significance_rule", {})
        stochastic = p.get("evaluation_mode")=="random"
        passed = delta>0 and (not stochastic or std["baseline"] is not None and delta>=3*std["baseline"])
        c.required(isinstance(rule, dict) and rule.get("passed") is passed,
                   "COMPARISON_SIGNIFICANCE", path+".significance_rule", "改善/3σ 判定与原始值不一致")
        if stochastic:
            c.required(isinstance(rule, dict) and rule.get("required_baseline_sigma_multiple")==3,
                       "COMPARISON_SIGNIFICANCE", path+".significance_rule", "随机协议须使用3σ基线标准差")
    for ref in data.get("source_results", []):
        if isinstance(ref, dict):
            c.guard(path+".source_results", lambda ref=ref: reference(c.root, ref))
    c.required(data.get("status")=="COMPLETE", "COMPARISON_STATUS", path, "正式汇总未完成")
    doc = c.guard("workspace/harbor_task/instruction.md", lambda: inside(c.root, "workspace/harbor_task/instruction.md").read_text())
    if doc is not None and p.get("evaluation_mode")=="random":
        c.required(bool(re.search(r"seed|随机种子", doc, re.I)) and bool(re.search(r"3\s*[σσΣ]|3\s*(?:sigma|standard deviations)|三倍.*标准差", doc, re.I)),
                   "INSTRUCTION_THRESHOLD", "workspace/harbor_task/instruction.md", "随机任务须在题面声明 seed 与有效提升阈值；仅证据协议不够")
    return data


def duration(c, s):
    name = next((x for x in ("expert_evidence/timing.json", "expert_evidence/duration_evidence.json") if (c.root/x).is_file()), None)
    if not name:
        c.pending.append("未识别可程序复算的净时长记录；核包内现有运行/时长材料，不从首尾或预算猜时长")
        return
    d = c.json(name)
    if not d or not isinstance(d.get("tracks"), dict):
        c.problem("DURATION_EVIDENCE", name, "tracks 须为对象")
        return
    identities = []
    declared = {x.get('track', TRACKS[i]): x for i, x in enumerate(s.get('agent_execution', [])[:2]) if isinstance(x, dict)}
    for track in TRACKS:
        row = d["tracks"].get(track)
        if not isinstance(row, dict):
            c.problem("DURATION_EVIDENCE", name+"."+track, "缺该轨真实区间")
            continue
        identity = row.get("thread_id", row.get("session_id"))
        c.required(isinstance(identity, str) and bool(identity), "DURATION_SESSION", name+"."+track, "缺独立原会话标识")
        identities.append(identity)
        intervals, excluded = row.get("intervals"), row.get("exclusions", [])
        if not isinstance(intervals, list) or not intervals or not isinstance(excluded, list):
            c.problem("DURATION_INTERVAL", name, "缺活动/扣除区间")
            continue
        c.refs(row, name+"."+track)
        logs = row.get("timing_logs", row.get("logs"))
        c.required(isinstance(logs, list) and bool(logs), "DURATION_LOG", name+"."+track, "缺可核运行日志")
        if isinstance(logs, list):
            for ref in logs:
                c.guard(name, lambda ref=ref: reference(c.root, ref))
        pairs = []
        for entry in excluded:
            if not isinstance(entry, dict) or not {"start", "end"}<=entry.keys():
                c.problem("DURATION_INTERVAL", name, "扣除须标明 start/end")
                continue
            c.required(bool(entry.get("reason") or entry.get("evidence")), "DURATION_EXCLUSION", name, "扣除须有原因/证据")
            pairs.append([entry["start"], entry["end"]])
        seconds = c.guard(name, lambda: effective_seconds(intervals, pairs))
        if seconds is not None:
            claimed = declared.get(track, {}).get("duration_hours")
            c.required(finite(claimed) and abs(seconds-claimed*3600)<=1, "DURATION_TOTAL", name+"."+track, "可复算净时长与 run_summary 不符")
            if "effective_seconds" in row:
                c.required(close(row["effective_seconds"], seconds), "DURATION_TOTAL", name, "记录净时长与区间复算不符")
    c.required(len(identities)==2 and len(set(str(x) for x in identities))==2, "DURATION_SESSION", name, "两轨会话必须独立")


def nop(c):
    results = []
    for path in (c.root/"expert_evidence").rglob("result.json"):
        value = c.guard(str(path.relative_to(c.root)), lambda path=path: read_object(path))
        if value and isinstance(value.get("agent_info"), dict) and value["agent_info"].get("name")=="nop":
            results.append(path)
    if not results:
        c.problem("NOP_MISSING", "expert_evidence", "缺当前题包同次 NOP Trial 原件")
        return
    for path in results:
        trial = path.parent
        reward = trial/"verifier/reward.json"
        if not reward.exists():
            reward = trial/"verifier/reward.txt"
        log = trial/"trial.log"
        if not log.exists():
            log = trial/"verifier/test-stdout.txt"
        refs = [str(x.relative_to(c.root)) for x in (trial/"config.json", path, reward, log)]
        actual = c.guard(str(path.relative_to(c.root)), lambda: bundled("harbor_review").validate_trial_evidence(c.root, refs, c.root/"workspace/harbor_task"))
        if actual:
            config = c.json(refs[0]) or {}
            recorded = (config.get("task") or {}).get("task_toml_sha256")
            digest = _sha256(c.root/"workspace/harbor_task/task.toml")
            if recorded==digest:
                c.notes.append("同次 NOP 原件一致，task.toml 哈希对应；镜像/实现版本及所覆盖分支仍须语义复核")
            else:
                c.pending.append("NOP 同次原件可解析；当前完整题包版本关联须核包内既有版本说明")


def best_retest(c, comp):
    base = "expert_evidence/best_method"
    best = c.guard(base, lambda: inside(c.root, base, directory=True))
    if not best:
        return
    snapshot = {p.relative_to(best).as_posix(): _sha256(p) for p in files(best)}
    c.required(bool(snapshot), "BEST_EMPTY", base, "最佳方法源码为空")
    declared = (comp or {}).get("seeds")
    matches = []
    for path in (c.root/"expert_evidence").rglob("result.json"):
        d = c.guard(str(path.relative_to(c.root)), lambda path=path: read_object(path))
        if not d or d.get("role")!="best_method":
            continue
        name = str(path.relative_to(c.root))
        method = d.get("method", {})
        if isinstance(method, dict) and isinstance(method.get("files"), dict):
            c.required(method["files"]==snapshot and method.get("sha256")==_canonical_digest(snapshot),
                       "BEST_BINDING", name+".method", "复验源码清单/哈希与最终 best_method 不同")
        elif isinstance(method, dict):
            source = c.guard(name+".method", lambda: inside(c.root, method.get("path", method.get("source_path")), directory=None))
            if source and source.is_dir():
                other = {p.relative_to(source).as_posix():_sha256(p) for p in files(source)}
                c.required(other==snapshot, "BEST_BINDING", name+".method", "实际复验源码与最终方法不同")
                c.pending.append("最终方法旧目录哈希算法未声明；源码内容已比较，仍核原始运行绑定")
            elif source and source.is_file():
                c.required(any(v==_sha256(source) for v in snapshot.values()), "BEST_BINDING", name+".method", "复验源码文件不属于最终方法")
                c.pending.append("最终方法仅绑定单源码文件；必要依赖/完整源码范围需语义确认")
        else:
            c.problem("BEST_BINDING", name+".method", "缺实际方法绑定")
        p = (comp or {}).get("evaluation_protocol", (comp or {}).get("protocol"))
        c.required(d.get("protocol")==p, "BEST_PROTOCOL", name+".protocol", "最终方法与 B/R 正式协议不同")
        seed = d.get("seed")
        if type(seed) is not int:
            c.problem("BEST_SEED", name, "复验缺真实 seed")
            continue
        result(c, name, "best_method", seed, (comp or {}).get("metric", {}), isinstance(p, dict) and p.get("training") is True)
        matches.append(seed)
    if not matches:
        c.problem("BEST_RETEST_MISSING", base, "未识别包内最终方法逐次复验；现有等价格式需明确对应并核查")
    elif isinstance(declared, list):
        c.required(len(matches)==len(set(matches)) and set(matches)==set(declared), "BEST_SEED", "expert_evidence", "最终方法须保留完整声明 seed，不能重复或缺项")


def check(package_root):
    c = Inspection(package_root)
    inventory = c.guard(".", lambda: files(Path(package_root)))
    if inventory is None:
        return {"status": "issues_found", "issues": c.issues, "pending": c.pending}
    for path in inventory:
        rel = path.relative_to(c.root)
        if any(x in WORK_NAMES or x in SECRET_NAMES or x.endswith(".key") for x in rel.parts):
            c.problem("INTERNAL_OR_SECRET", rel, "工作状态/凭据不得进入最终包")
        if rel.parts[:2]==("expert_evidence", "best_method") and path.suffix in bundled("submission_format").MODEL_EXTENSIONS:
            c.problem("BEST_MODEL", rel, "best_method 只放代码/配置，模型归任务交付和证据")
        if rel.parts[:3]==("workspace", "harbor_task", "environment") and any(x in {"expert_evidence", "optimization_evidence", "reference", "hidden_assets"} for x in rel.parts[3:]):
            c.problem("PRIVATE_IN_AGENT_CONTEXT", rel, "疑似私有/专家材料位于 Agent 上下文，须结合 COPY/ignore/真实视图核查，不能只凭目录名判断", review=True)
    for name in ("workspace/harbor_task", "workspace/reference", "expert_evidence", "optimization_evidence", "expert_evidence/best_method"):
        c.guard(name, lambda name=name: inside(c.root, name, directory=True))
    for name in EXPERT_FILES:
        c.guard("expert_evidence/"+name, lambda name=name: inside(c.root, "expert_evidence/"+name))
    c.guard("optimization_evidence/训练证据说明.md", lambda: inside(c.root, "optimization_evidence/训练证据说明.md"))
    if all((c.root/name).is_dir() for name in ("workspace", "expert_evidence", "optimization_evidence")):
        official = c.guard(".", lambda: bundled("submission_format").collect(c.root))
        if official:
            for item in official["alignment_issues"]:
                c.problem(item["code"], item["path"], item["message"], review=item["code"]=="TRAJECTORY_STATUS_REVIEW")
            c.notes.extend(official.get("suggestions", []))
    a = c.guard("expert_evidence/expert_annotation.json", lambda: annotation(c))
    c.task_id = (a or {}).get("task_id")
    trajectories = {}
    contract = (a or {}).get("score_contract")
    metric = {"direction": contract.get("direction"), "split": contract.get("split")} if isinstance(contract, dict) else None
    summary_input = c.json('expert_evidence/run_summary.json') or {}
    executions = summary_input.get('agent_execution', [])
    names = {}
    if isinstance(executions, list):
        for i, row in enumerate(executions[:2]):
            if isinstance(row, dict):
                track = row.get('track', TRACKS[i])
                if track in TRACKS:
                    names[track] = row.get('trajectory_path', row.get('source_path'))
    excluded = {'trajectory_source_map.json', 'trajectory_source_index.json', 'trajectory_time_provenance.json'}
    discovered = sorted(p for p in (c.root / 'expert_evidence').glob('trajectory*.json') if p.name not in excluded)
    for i, track in enumerate(TRACKS):
        default = 'expert_evidence/trajectory_' + track + '.json'
        name = names.get(track) or (default if (c.root / default).is_file() else
                discovered[i].relative_to(c.root).as_posix() if len(discovered) == 2 else default)
        if not names.get(track) and name != default:
            c.pending.append('等价轨迹命名与模型/时长的对应需结合现有说明核对：' + name)
        c.required(name not in [v.get('_source_path') for v in trajectories.values()],
                   'TRAJECTORY_DUPLICATE', str(name), '两轨不能指向同一份轨迹')
        value = c.json(name)
        if value:
            c.issues.extend(check_rounds(value, name, metric=metric))
            trajectories[track] = {**value, '_source_path': name}
    s = c.guard("expert_evidence/run_summary.json", lambda: summary(c, a, trajectories))
    c.guard("workspace/harbor_task", lambda: task(c, a))
    comp = c.guard("optimization_evidence/comparison_summary.json", lambda: comparison(c, a))
    c.guard("expert_evidence/best_method", lambda: best_retest(c, comp))
    if s:
        c.guard("expert_evidence/run_summary.json", lambda: duration(c, s))
    if s and comp and isinstance(s.get("fast_iteration_exception"), dict) and s["fast_iteration_exception"].get("used") is True:
        p = comp.get("evaluation_protocol", comp.get("protocol", {}))
        c.required(isinstance(p, dict) and p.get("training") is False, "DURATION_POLICY", "expert_evidence/run_summary.json", "训练任务不能使用7h例外")
        c.pending.append("7h启动前资格、连续演进/后续方向和干净重跑需核包内实质证据")
    c.guard("expert_evidence", lambda: nop(c))
    for name in ("expert_evidence/evidence_index.json", "workspace/qa_exposure_manifest.json"):
        if (c.root/name).is_file():
            value = c.json(name)
            if value:
                c.refs(value, name)
    c.pending += ["轨迹原始指标/模型身份/合法性、叙述与当前优化面及旧题内容须结合包内日志实质审阅",
                  "最终 best_method 的源码/复验对应及训练重载真实性由证据审阅确认",
                  "优化面、Baseline 合理性及 U 依据由独立 QA 审查"]
    return {"status": "issues_found" if any(x["level"]=="error" for x in c.issues) else "format_checked_not_qa",
            "package_root": str(c.root), "issues": c.issues, "notes": c.notes, "pending": c.pending,
            "file_count": len(inventory), "computed_statistics": (comp or {}).get("_computed")}
