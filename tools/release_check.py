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
                            text=True, timeout=120, check=False)
    output = result.stdout + result.stderr
    if result.returncode:
        raise RuntimeError(f"{command}:\n{output[-6000:]}")
    return output


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
    all_files = payload_files()
    checked_files = source_snapshot(all_files)
    live = validate_evidence(args.evidence_manifest, FLOW, all_files) if args.release else None
    native = run([sys.executable, "-m", "unittest", "discover", "-s", str(FLOW / "tests"), "-v"], ROOT)
    with tempfile.TemporaryDirectory(prefix="ar-release-relocation-") as temporary:
        root = Path(temporary)
        for source in all_files + release_files():
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
        cli = [sys.executable, str(relocated_flow / "cli.py"), "--format", "json"]
        run(cli + ["rules", "check"], root)
        help_output = run([sys.executable, str(relocated_flow / "cli.py"), "--help"], root)
        for capability in ("materials", "package", "harbor", "runtime"):
            assert capability in help_output, f"relocated CLI omitted {capability}"
        # A fresh release smoke must exercise only stateless entry points.  In
        # particular it must not create the retired .autoresearch-flow ledger.
        run([sys.executable, str(relocated_flow / "cli.py"), "materials", "--help"], root)
        run([sys.executable, str(relocated_flow / "cli.py"), "package", "--help"], root)
        run([sys.executable, str(relocated_flow / "cli.py"), "harbor", "--help"], root)
        assert not (root / ".autoresearch-flow").exists(), "release smoke created legacy state"
    report = {"schema_version": 2, "status": "released" if args.release else "contracts_passed",
              "release_ready": args.release,
              "pending": [] if args.release else ["独立新会话入口试用暂缓；正式发行包尚未验收"],
              "at": _utc_now(), "version": FLOW_VERSION, "qa_revision": registry.manifest.get("qa_revision"),
              "package_revision": registry.manifest.get("package_revision"),
              "python": sys.version.split()[0], "rule_count": len(registry.catalog["rules"]),
              "qa_coverage_count": len(registry.catalog["coverage"]), "checked_links": links,
              "native_tests": re.search(r"Ran (\d+) tests", native).group(1),
              "relocated_tests": re.search(r"Ran (\d+) tests", isolated).group(1),
              "relocation_without_host_config_or_auth": True,
              "relocation_without_design_or_pilot_runs": True,
              "fresh_cli_capabilities": True,
              "model_calls": 0, "scope": "tool contracts, not scientific or platform acceptance"}
    if live:
        assert live == validate_evidence(args.evidence_manifest, FLOW, all_files), "Evidence changed during validation"
        report["release_evidence"] = live
    release = FLOW / "release"
    release.mkdir(exist_ok=True)
    assert checked_files == source_snapshot(payload_files()), "Sources changed during validation"
    preserve_receipts(release)
    _atomic_json(release / "source_manifest.json", {
        "schema_version": 2, "version": FLOW_VERSION, "package_revision": registry.manifest.get("package_revision"),
        "scope": "source and locked rule dependencies; excludes design archive, generated release reports and local pilot/build data",
        "files": checked_files})
    report["source_manifest_sha256"] = _sha256(release / "source_manifest.json")
    _atomic_json(release / "acceptance.json", report)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
