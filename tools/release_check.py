"""Maintainer release checks; no Docker/model/task QA invocation.

Run once per tool release, not as a mandatory per-task test suite.
"""
import argparse
import ast
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from pathlib import Path
from urllib.parse import unquote

FLOW = Path(__file__).resolve().parents[1]
ROOT = FLOW
sys.path.insert(0, str(FLOW))
from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import Registry, _atomic_json, _sha256, _utc_now

# This is a deployment allowlist, not a recursive copy of the maintainer's workspace.
SOURCE_DIRECTORIES = {"autoresearch_flow", "rules", "templates", "model_profiles",
                      "skills", "tests", "tools", "pilots", "sources", "docs"}
GENERATED_DIRECTORIES = {"__pycache__", "runs", "build", "release", "runtime",
                         "tmp", "venv", "node_modules"}
SPECIAL_FILES = {"Dockerfile", ".gitignore", ".gitattributes"}
SNAPSHOT_DOCUMENTS = {Path("rules/provenance/PCA_RULE_ALIGNMENT.md")}


def distributable_name(name):
    if name.startswith(".") and name not in SPECIAL_FILES:
        return False
    if re.search(r"(?:auth|credential|secret|token).*\.json$", name, re.IGNORECASE):
        return False
    return Path(name).suffix not in {".pyc", ".pyo", ".log", ".sock"}


def source_name(name):
    return distributable_name(name) and (Path(name).suffix in {".py", ".md", ".toml", ".json", ".sh", ".yaml", ".yml"}
                                        or name in SPECIAL_FILES)


def live_release_evidence():
    """Validate the bounded real evidence used to release the reusable tool."""
    from autoresearch_flow.core import FlowError
    from autoresearch_flow.harbor_runtime import final_snapshot
    from autoresearch_flow.runtime import Runtime
    from autoresearch_flow.trajectory import validate_round

    transfer_path = FLOW / "pilots/pca_cpu/runs/harbor-20260930T091303597138Z/report.json"
    transfer = json.loads(transfer_path.read_text())
    assert transfer["status"] == "harbor_transfer_probe_passed"
    assert transfer["trial"]["reward"] == 1 and transfer["trial"]["mode"] == "separate"
    candidate_hash = transfer["trial"]["candidate_sha256"]
    artifact = next(entry for entry in transfer["evidence"]
                    if entry["path"].endswith("artifacts/workspace/solution/method.py"))
    assert candidate_hash == artifact["sha256"]

    pilot_root = FLOW / "pilots/pca_cpu/runs/runtime02"
    runtime = Runtime(pilot_root)
    runtime._load()
    state_path = runtime.directory / "seed/state.json"
    state = json.loads(state_path.read_text())
    formal = [segment for segment in state["segments"] if segment["phase"] == "formal"]
    assert state["active"] is None and state["thread_id"]
    assert any(segment["status"] == "completed" for segment in formal)
    assert all(segment.get("thread_id") in (None, state["thread_id"]) for segment in formal)
    trajectory = runtime.directory / "seed/formal/output/trajectory.jsonl"
    rows = [json.loads(line) for line in trajectory.read_text().splitlines()]
    assert rows
    for number, row in enumerate(rows, 1):
        validate_round(row, number)
    jobs = list((runtime.directory / "seed/harbor").glob("*/job.json"))
    assert jobs and all(json.loads(path.read_text())["verifier"]["disable"] for path in jobs)
    assert not (runtime.directory / "seed/harbor/final_attempt.json").exists()
    try:
        final_snapshot(runtime, "seed")
    except FlowError as error:
        assert error.code == "FINAL_NOT_READY"
    else:
        raise AssertionError("bounded pilot must not pass the 10-hour final gate")
    return {
        "harbor_transfer_report": {"path": str(transfer_path.relative_to(ROOT)),
                                   "sha256": _sha256(transfer_path)},
        "seed_state": {"path": str(state_path.relative_to(ROOT)), "sha256": _sha256(state_path)},
        "seed_trajectory": {"path": str(trajectory.relative_to(ROOT)),
                            "sha256": _sha256(trajectory), "rounds": len(rows)},
        "same_thread": True, "completed_formal_segment": True,
        "final_gate_rejected_short_pilot": True, "hidden_queries": 0,
    }


def prior_live_evidence():
    """Reuse unchanged runtime evidence for a QA-only update, never relabel it new."""
    previous = json.loads((FLOW / "release/acceptance.json").read_text())
    manifest = json.loads((FLOW / "release/source_manifest.json").read_text())
    assert previous.get("release_ready") is True and previous.get("version") == FLOW_VERSION
    live = previous.get("bounded_live_evidence")
    assert isinstance(live, dict) and live, "No released live evidence to reuse"
    expected = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    excluded = {"qa_contract.py", "w4_package.py", "stages.py"}
    runtime_files = [p for p in (FLOW / "autoresearch_flow").glob("*.py") if p.name not in excluded]
    runtime_files += list((FLOW / "model_profiles").glob("*.toml"))
    runtime_files += [FLOW / "templates/agent-prompt.zh.md"]
    for path in runtime_files:
        relative = str(path.relative_to(ROOT))
        assert expected.get(relative) == _sha256(path), f"Runtime changed; cannot reuse live evidence: {relative}"
    for key in ("harbor_transfer_report", "seed_state", "seed_trajectory"):
        ref = live[key]
        path = (ROOT / ref["path"]).resolve()
        assert path.is_relative_to(ROOT) and _sha256(path) == ref["sha256"], f"Historical evidence changed: {key}"
    return {**live, "reuse": {"basis": "QA-only change; runtime sources and raw evidence unchanged",
                             "original_acceptance_at": live.get("reuse", {}).get("original_acceptance_at", previous["at"]),
                             "new_live_run": False}}


def source_files(flow=None):
    flow = FLOW if flow is None else flow
    files = []
    for directory, children, names in os.walk(flow):
        children[:] = sorted(c for c in children if not c.startswith(".")
                             and c not in GENERATED_DIRECTORIES
                             and (Path(directory) != flow or c in SOURCE_DIRECTORIES))
        for child in children:
            if (Path(directory) / child).is_symlink():
                raise ValueError(f"Unexpected source symlink: {Path(directory) / child}")
        for name in sorted(names):
            path = Path(directory) / name
            if not source_name(name):
                continue
            if Path(directory) == flow and path.suffix != ".md" and name not in SPECIAL_FILES | {"cli.py"}:
                continue
            if path.is_symlink():
                raise ValueError(f"Unexpected source symlink: {path}")
            files.append(path)
    return sorted(files)


def payload_files(flow=None):
    """One self-contained workflow root; never parent directories or secrets."""
    flow = FLOW if flow is None else flow
    registry = Registry(flow)
    assert registry.check_sources() == [], "Rule sources drifted"
    files = source_files(flow)
    # Locked assets (including tutorial ZIP attachments) are allowed explicitly,
    # not by accepting arbitrary archives found in the maintainer's workspace.
    files.extend(flow / ref["path"] for ref in registry.manifest["bundled_files"])
    for p in files:
        p.relative_to(flow)
        assert p.is_file() and not p.is_symlink(), p
    return sorted(set(files))


def check_documents(files):
    links = 0
    for path in files:
        if path.suffix == ".py":
            ast.parse(path.read_text(), filename=str(path))
        elif path.suffix == ".json":
            json.loads(path.read_text())
        elif path.suffix == ".toml":
            tomllib.loads(path.read_text())
        elif (path.suffix == ".md" and path.relative_to(FLOW) not in SNAPSHOT_DOCUMENTS
              and not path.relative_to(FLOW).parts[:2] in {
                  ("skills", "autoresearch-task-qa"), ("skills", "autoresearch-baseline-quality")}):
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if target.startswith(("http:", "https:", "#", "mailto:")):
                    continue
                target = unquote(target.split("#")[0].strip("<>"))
                assert (path.parent / target).exists(), (path, target)
                links += 1
    return links


def release_files(flow=None):
    """Small release receipts/history, never caches, symlinks or live runs."""
    flow = FLOW if flow is None else flow
    files = []
    for directory, children, names in os.walk(flow / "release"):
        children[:] = sorted(c for c in children if not c.startswith(".")
                             and c not in GENERATED_DIRECTORIES)
        for child in children:
            assert not (Path(directory) / child).is_symlink(), child
        for name in names:
            p = Path(directory) / name
            if p.suffix in {".json", ".md"} and source_name(name):
                assert p.is_file() and not p.is_symlink(), p
                files.append(p)
    return sorted(files)


def preserve_receipts(release):
    """Keep the prior pair byte-for-byte before replacing current receipts."""
    names = ("acceptance.json", "source_manifest.json")
    present = [release / name for name in names if (release / name).exists()]
    if not present:
        return
    assert all(p.is_file() and not p.is_symlink() for p in present), "Unsafe prior receipts"
    key = "-".join(_sha256(p)[:16] for p in present)
    history = release / "history" / key
    history.mkdir(parents=True, exist_ok=True)
    for source in present:
        destination = history / source.name
        if destination.exists():
            assert destination.read_bytes() == source.read_bytes(), "Historical receipt collision"
        else:
            with destination.open("xb") as stream:
                stream.write(source.read_bytes())


def run(command, cwd):
    environment = dict(os.environ)
    environment.pop("PYTHONPATH", None)
    environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = subprocess.run(command, cwd=cwd, env=environment, capture_output=True,
                            text=True, timeout=120, check=False)
    output = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError(f"{command}:\n{output[-6000:]}")
    return output


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true",
                        help="after all checks, mark this version ready and bind bounded live evidence")
    parser.add_argument("--reuse-prior-live", action="store_true",
                        help="for a QA-only release, verify and reuse unchanged prior runtime evidence")
    args = parser.parse_args()
    if args.reuse_prior_live and not args.release:
        parser.error("--reuse-prior-live requires --release")
    registry = Registry(FLOW)
    assert registry.check_sources() == [], "Rule sources drifted"
    files = source_files()
    links = check_documents(files)
    all_files = payload_files()
    checked_files = [{"path": str(p.relative_to(ROOT)), "sha256": _sha256(p)} for p in all_files]
    native = run([sys.executable, "-m", "unittest", "discover", "-s", str(FLOW / "tests"), "-v"], ROOT)
    with tempfile.TemporaryDirectory(prefix="ar-release-relocation-") as temporary:
        root = Path(temporary)
        for source in all_files + release_files():
            target = root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        relocated_flow = root
        assert not (root / "config.toml").exists()
        assert not (root / "auth.json").exists()
        assert not (root / "AutoResearch新流程设计").exists()
        # Link validation must also run outside the original design workspace.
        relocated_check = [sys.executable, "-c",
                           ("from tools.release_check import source_files, check_documents; "
                            "check_documents(source_files())")]
        run(relocated_check, relocated_flow)
        isolated = run([sys.executable, "-m", "unittest", "discover", "-s", str(relocated_flow / "tests"), "-v"], root)
        task = root / "new-task"
        task.mkdir()
        cli = [sys.executable, str(relocated_flow / "cli.py"), "--format", "json"]
        run(cli + ["rules", "check"], task)
        run(cli + ["task", "init", "--task-root", str(task), "--task-id", "release-smoke", "--confirm-init"], task)
        run(cli + ["task", "check", "--task-root", str(task)], task)
        state = json.loads(run(cli + ["stage", "status", "--task-root", str(task)], task))
        assert state["current_stage"] == "1"
    live = (prior_live_evidence() if args.reuse_prior_live else live_release_evidence()) if args.release else None
    report = {"status": "released" if args.release else "contracts_passed",
              "release_ready": args.release,
              "pending": [] if args.release else ["维护者最终发布及新版迁移包"],
              "at": _utc_now(), "version": FLOW_VERSION, "qa_revision": registry.manifest.get("qa_revision"),
              "package_revision": registry.manifest.get("package_revision"),
              "python": sys.version.split()[0], "rule_count": len(registry.catalog["rules"]),
              "qa_coverage_count": len(registry.catalog["coverage"]), "checked_links": links,
              "native_tests": re.search(r"Ran (\d+) tests", native).group(1),
              "relocated_tests": re.search(r"Ran (\d+) tests", isolated).group(1),
              "relocation_without_host_config_or_auth": True,
              "relocation_without_design_or_pilot_runs": True,
              "fresh_cli_init_and_resume_status": True,
              "model_calls": 0, "scope": "tool contracts, not scientific or platform acceptance"}
    if live:
        report["bounded_live_evidence"] = live
    release = FLOW / "release"
    release.mkdir(exist_ok=True)
    assert checked_files == [{"path": str(p.relative_to(ROOT)), "sha256": _sha256(p)}
                             for p in payload_files()], "Sources changed during validation"
    preserve_receipts(release)
    _atomic_json(release / "source_manifest.json", {
        "version": FLOW_VERSION, "package_revision": registry.manifest.get("package_revision"),
        "scope": "source and locked rule dependencies; excludes design archive, generated release reports and local pilot/build data",
        "files": checked_files})
    report["source_manifest_sha256"] = _sha256(release / "source_manifest.json")
    _atomic_json(release / "acceptance.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
