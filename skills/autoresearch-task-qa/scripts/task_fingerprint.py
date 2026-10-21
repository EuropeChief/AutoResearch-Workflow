#!/usr/bin/env python3
"""Hash exactly the four frozen Harbor inputs; never execute task code."""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import stat

PROFILE = "harbor-task-inputs-v1"
COMPONENTS = ("environment", "task.toml", "tests", "instruction.md")


def sha256_file(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def fingerprint(task_root):
    """Canonical UTF-8 JSON of sorted path/type/hash records, independent of mtimes.

    Include empty directories and every hidden file. Permissions are deliberately
    excluded: ordinary ZIP extraction need not preserve them. Reject links and
    special files rather than silently following or omitting a frozen input.
    """
    task = Path(task_root).resolve()
    entries = []

    def visit(path):
        mode = path.lstat().st_mode
        relative = path.relative_to(task).as_posix()
        if stat.S_ISDIR(mode):
            entries.append({"path": relative, "type": "directory"})
            for child in sorted(path.iterdir(), key=lambda p: p.name):
                visit(child)
        elif stat.S_ISREG(mode):
            entries.append({"path": relative, "type": "file", "sha256": sha256_file(path)})
        else:
            raise ValueError(f"frozen input is a symlink or special file: {relative}")

    for name in COMPONENTS:
        path = task / name
        if not path.exists() and not path.is_symlink():
            raise ValueError(f"missing frozen input: {name}")
        if name in ("environment", "tests") and not path.is_dir():
            raise ValueError(f"frozen input must be a directory: {name}")
        if name in ("task.toml", "instruction.md") and not path.is_file():
            raise ValueError(f"frozen input must be a regular file: {name}")
        visit(path)
    entries.sort(key=lambda row: row["path"])
    payload = {"hash_profile": PROFILE, "entries": entries}
    canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return {"hash_profile": PROFILE, "task_content_sha256": hashlib.sha256(canonical).hexdigest(),
            "components": list(COMPONENTS), "file_count": sum(e["type"] == "file" for e in entries),
            "entries": entries}


def collect(task_root):
    if task_root is None:
        return {"status": "manual", "summary": "尚未唯一确定 Harbor task，无法计算四项指纹。"}
    try:
        result = fingerprint(task_root)
        return {**result, "status": "pass", "summary": "已重算四项输入指纹；这本身不证明历史运行使用了该版本。"}
    except (OSError, ValueError) as exc:
        return {"status": "manual", "summary": str(exc)}


def resolve_file(root, reference):
    if not isinstance(reference, str) or not reference:
        raise ValueError("binding references must be nonempty relative paths")
    relative = Path(reference)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"binding reference escapes bundle: {reference}")
    bundle = Path(root).resolve()
    path = bundle / relative
    if not path.resolve().is_relative_to(bundle) or path.is_symlink() or not path.is_file():
        raise ValueError(f"binding reference is not a regular bundle file: {reference}")
    # Host aliases above the selected root (for example macOS /var) are not
    # submitted links. Still reject every symlink within the bundle itself.
    if any((bundle / parent).is_symlink() for parent in relative.parents if parent != Path(".")):
        raise ValueError(f"binding reference has a symlink ancestor: {reference}")
    return path


def check_binding(root, current, trajectory_path, binding, semantic_review=None):
    """Compare the four-input hash recorded in run_summary; extra fields optional."""
    out = {"status": "manual", "basis": "missing", "authenticity_verified": False,
           "summary": "run_summary.json 未记录四项题包哈希；保留缺口提示，不单独阻断或要求补跑。", "evidence": []}
    from project_policy import advisory
    def warn(value):
        return advisory(value, "TASK_FINGERPRINT")
    if current.get("status") != "pass":
        return {**out, "basis": "fingerprint_unavailable", "summary": current["summary"]}
    if not isinstance(binding, dict):
        return warn(out)
    # A hash advisory must never hide a known association with another task/run.
    try:
        path = resolve_file(root, trajectory_path)
        named = binding.get("trajectory_path")
        if named is not None and resolve_file(root, named).resolve() != path.resolve():
            return {**out, "status": "fail", "basis": "trajectory_path_mismatch", "summary": "可选 trajectory_path 指向另一份轨迹；请核对绑定对应关系。"}
    except (OSError, ValueError, UnicodeError) as exc:
        return {**out, "basis": "unreadable_binding", "summary": str(exc)}
    if binding.get("hash_profile") != PROFILE:
        return warn({**out, "basis": "unsupported_profile", "summary": "run_summary 的 hash_profile 应为 harbor-task-inputs-v1；按项目通知保留提示。"})
    digest = binding.get("task_content_sha256")
    if digest is None:
        return warn({**out, "basis": "hash_missing"})
    if digest != current["task_content_sha256"]:
        return warn({**out, "basis": "task_hash_mismatch", "summary": "run_summary 记录的题包哈希与当前 environment/task.toml/tests/instruction.md 不一致；保留差异，不单独阻断或要求补跑。"})
    try:
        expected = binding.get("trajectory_sha256")
        if expected is not None and expected != sha256_file(path):
            return warn({**out, "basis": "trajectory_hash_mismatch", "summary": "可选轨迹 SHA-256 与提交文件不一致；保留实际差异提示。"})
        return {**out, "status": "pass", "basis": "summary_hash_matches",
                "summary": "run_summary 的四项题包哈希与当前包一致。", "evidence": [trajectory_path]}
    except (OSError, ValueError, UnicodeError) as exc:
        return {**out, "basis": "unreadable_binding", "summary": str(exc)}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("task_root", type=Path)
    parser.add_argument("--run-id", help="record a run-start fingerprint immediately before launching the runner")
    parser.add_argument("--out", type=Path, help="write a private record outside the four hashed inputs")
    args = parser.parse_args(argv)
    result = fingerprint(args.task_root)
    result.pop("entries")  # No private file names in the default record.
    if args.run_id:
        result.update(run_id=args.run_id, phase="run_start", recorded_at=datetime.now(timezone.utc).isoformat())
    rendered = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        target = args.out.resolve()
        task = args.task_root.resolve()
        if any(target == task / name or target.is_relative_to(task / name) for name in COMPONENTS):
            parser.error("--out must be outside the four hashed inputs")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")


if __name__ == "__main__":
    main()
