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
from tools.release_evidence import validate_evidence

# This is a deployment allowlist, not a recursive copy of the maintainer's workspace.
SOURCE_DIRECTORIES = {"autoresearch_flow", "rules", "templates", "model_profiles",
                      "skills", "tests", "tools", "pilots", "sources", "docs"}
GENERATED_DIRECTORIES = {"__pycache__", "runs", "results", "build", "release", "runtime",
                         "tmp", "venv", "node_modules"}
SPECIAL_FILES = {"Dockerfile", ".gitignore", ".gitattributes", ".dockerignore"}
SNAPSHOT_DOCUMENTS = {Path("rules/provenance/PCA_RULE_ALIGNMENT.md")}
RUNTIME_DIRECTORIES = {"autoresearch_flow", "rules", "skills", "sources", "model_profiles"}
RUNTIME_DOCUMENTS = {"README.md", "START_HERE.md", "AGENTS.md", "MAINTAINING.md", "RELEASE.md",
                     "docs/stages.md", "docs/experiments.md", "docs/materials.md", "docs/packaging.md",
                     "docs/runtime.md", "docs/harbor.md", "docs/preflight.md", "docs/troubleshooting.md"}
RUNTIME_TEMPLATES = {"README.md", "agent-prompt.zh.md", "runtime.example.json",
                     "delivery-form.example.json", "materials-sources.example.json",
                     "nop-execution.example.json", "harbor-execution.example.json",
                     "expert-annotation.example.json", "run-summary.example.json",
                     "research-notes.example.md", "change-note.example.md",
                     "decision-log.example.md", "preflight-inputs.example.json"}


def distributable_name(name):
    if name.startswith(".") and name not in SPECIAL_FILES:
        return False
    if re.search(r"(?:auth|credential|secret|token).*\.json$", name, re.IGNORECASE):
        return False
    return Path(name).suffix not in {".pyc", ".pyo", ".log", ".sock"}


def source_name(name):
    return distributable_name(name) and (Path(name).suffix in {".py", ".md", ".toml", ".json", ".sh", ".yaml", ".yml"}
                                        or name in SPECIAL_FILES)


def source_snapshot(files, flow=None):
    flow = FLOW if flow is None else flow
    return [{"path": p.relative_to(flow).as_posix(), "sha256": _sha256(p),
             "mode": p.stat().st_mode & 0o777} for p in files]


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
            if path.relative_to(flow).parts[0] == "model_profiles" and path.relative_to(flow).as_posix() not in {
                    "model_profiles/codex.example.toml", "model_profiles/seed.example.toml"}:
                continue
            if Path(directory) == flow and path.suffix != ".md" and name not in SPECIAL_FILES | {"cli.py"}:
                continue
            if path.is_symlink():
                raise ValueError(f"Unexpected source symlink: {path}")
            files.append(path)
    return sorted(files)


def development_files(flow=None):
    """Maintainer sources and locked originals, including tests and fixtures."""
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


def payload_files(flow=None):
    """Minimal runtime deployment; development files remain in the Git repository."""
    flow = FLOW if flow is None else flow
    files = []
    for path in development_files(flow):
        relative = path.relative_to(flow)
        name = relative.as_posix()
        if relative.parts[:2] in {("rules", "history"), ("rules", "provenance")}:
            continue
        if (relative.parts[0] in RUNTIME_DIRECTORIES or name in RUNTIME_DOCUMENTS
                or name in {"cli.py", ".gitignore", ".gitattributes"}
                or (relative.parts[0] == "templates" and relative.name in RUNTIME_TEMPLATES)):
            files.append(path)
    return files


def check_documents(files, flow=None):
    flow = FLOW if flow is None else flow
    links = 0
    for path in files:
        if path.suffix == ".py":
            ast.parse(path.read_text(), filename=str(path))
        elif path.suffix == ".json":
            json.loads(path.read_text())
        elif path.suffix == ".toml":
            tomllib.loads(path.read_text())
        elif (path.suffix == ".md" and path.relative_to(flow) not in SNAPSHOT_DOCUMENTS
              and path.relative_to(flow).parts[:2] != ("docs", "maintenance")
              and not path.relative_to(flow).parts[:2] in {
                  ("skills", "autoresearch-task-qa"), ("skills", "autoresearch-baseline-quality")}):
            for target in re.findall(r"\]\(([^)]+)\)", path.read_text()):
                if target.startswith(("http:", "https:", "#", "mailto:")):
                    continue
                target = unquote(target.split("#")[0].strip("<>"))
                assert (path.parent / target).exists(), (path, target)
                links += 1
    return links


def release_files(flow=None):
    """Only the current receipt pair ships; local history stays in Git/on disk."""
    flow = FLOW if flow is None else flow
    files = []
    release = flow / 'release'
    assert not release.is_symlink(), 'Unsafe release receipt directory'
    for name in ('acceptance.json', 'source_manifest.json'):
        p = release / name
        if p.exists() or p.is_symlink():
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
                            text=True, timeout=240, check=False)
    output = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError(f"{command}:\n{output[-6000:]}")
    return output


def runtime_smoke(flow):
    """Exercise the archive's real public entry without tests, a ledger or accounts."""
    cli = [sys.executable, str(flow / "cli.py")]
    checks = []
    commands = [cli + ["--format", "json", "rules", "check"], cli + ["--help"]]
    commands += [cli + [name, "--help"] for name in ("experiment", "materials", "package", "harbor", "runtime", "preflight")]
    for command in commands:
        output = run(command, flow)
        checks.append({"command": ["python3", "cli.py", *command[2:]], "exit_code": 0,
                       "output_tail": output[-1200:]})
    for capability in ("experiment", "materials", "package", "harbor", "runtime", "preflight"):
        assert capability in checks[1]["output_tail"], f"archive omitted {capability}"
    with tempfile.TemporaryDirectory(prefix="ar-smoke-task-") as temporary:
        task = Path(temporary)
        output = run(cli + ["--format", "json", "preflight", "--task-root", str(task), "--stage", "1"], flow)
        result = json.loads(output)
        assert result["ready"] is None and result["stage"] == 1, "advisory preflight changed behavior"
        checks.append({"command": ["python3", "cli.py", "--format", "json", "preflight", "--task-root", "<temporary-task>", "--stage", "1"],
                       "exit_code": 0, "scope": "missing-evidence advisory; no scientific acceptance"})
        output = run([sys.executable, "-m", "autoresearch_flow.task_workspace", "--task-root", str(task), "decisions"], flow)
        assert json.loads(output)["exists"] is False, "empty task gained an approval log"
        checks.append({"command": ["python3", "-m", "autoresearch_flow.task_workspace", "--task-root", "<temporary-task>", "decisions"],
                       "exit_code": 0, "scope": "read-only missing-log check"})
        assert not (task / ".autoresearch").exists() and not (task / ".autoresearch-flow").exists(), "archive smoke initialized a task"
    assert not (flow / ".autoresearch-flow").exists(), "archive smoke created a legacy ledger"
    return checks


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--release", action="store_true",
                        help="after all checks, mark this version ready and bind bounded live evidence")
    parser.add_argument("--evidence-manifest", type=Path,
                        help="explicit reviewed live/independent evidence with original source bindings")
    args = parser.parse_args()
    if args.release != bool(args.evidence_manifest):
        parser.error("--release requires --evidence-manifest; evidence is only used with --release")
    registry = Registry(FLOW)
    assert registry.check_sources() == [], "Rule sources drifted"
    files = source_files()
    links = check_documents(files)
    development = development_files()
    all_files = payload_files()
    checked_files = source_snapshot(all_files)
    checked_development = source_snapshot(development)
    live = validate_evidence(args.evidence_manifest, FLOW, all_files) if args.release else None
    native = run([sys.executable, "-m", "unittest", "discover", "-s", str(FLOW / "tests"), "-v"], ROOT)
    with tempfile.TemporaryDirectory(prefix="ar-release-relocation-") as temporary:
        root = Path(temporary)
        for source in development + release_files():
            target = root / source.relative_to(ROOT)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
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
    with tempfile.TemporaryDirectory(prefix="ar-runtime-relocation-") as temporary:
        root = Path(temporary)
        for source in all_files:
            target = root / source.relative_to(FLOW)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, target)
        assert all(not (root / name).exists() for name in ("tests", "pilots", "tools", "local", "config.toml", "auth.json"))
        assert not (root / "docs/maintenance").exists()
        check_documents([root / p.relative_to(FLOW) for p in all_files], root)
        smoke = runtime_smoke(root)
    report = {"schema_version": 2, "status": "released" if args.release else "contracts_passed",
              "release_ready": args.release,
              "pending": [] if args.release else ["离线合同已核；显式发布证据和正式归档尚未验收"],
              "at": _utc_now(), "version": FLOW_VERSION, "qa_revision": registry.manifest.get("qa_revision"),
              "package_revision": registry.manifest.get("package_revision"),
              "python": sys.version.split()[0], "rule_count": len(registry.catalog["rules"]),
              "qa_coverage_count": len(registry.catalog["coverage"]), "checked_links": links,
              "native_tests": re.search(r"Ran (\d+) tests", native).group(1),
              "relocated_tests": re.search(r"Ran (\d+) tests", isolated).group(1),
              "relocation_without_host_config_or_auth": True,
              "relocation_without_design_or_pilot_runs": True,
              "fresh_cli_capabilities": True,
              "runtime_payload_files": len(all_files), "development_files": len(development),
              "runtime_without_development_files": True, "runtime_smoke": smoke,
              "model_calls": 0, "scope": "tool contracts, not scientific or platform acceptance"}
    if live:
        assert live == validate_evidence(args.evidence_manifest, FLOW, all_files), "Evidence changed during validation"
        report["release_evidence"] = live
    release = FLOW / "release"
    release.mkdir(exist_ok=True)
    assert checked_files == source_snapshot(payload_files()), "Sources changed during validation"
    assert checked_development == source_snapshot(development_files()), "Development sources changed during validation"
    preserve_receipts(release)
    _atomic_json(release / "source_manifest.json", {
        "schema_version": 2, "version": FLOW_VERSION, "package_revision": registry.manifest.get("package_revision"),
        "scope": "runtime allowlist and locked originals; excludes development tests/tools/pilots/maintenance records and local assets",
        "files": checked_files})
    report["source_manifest_sha256"] = _sha256(release / "source_manifest.json")
    _atomic_json(release / "acceptance.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
