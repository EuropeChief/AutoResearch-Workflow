"""Build and round-trip validate a relocatable workflow release archive."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
import re
import subprocess
import sys
import tarfile
import tempfile
from pathlib import Path

FLOW = Path(__file__).resolve().parents[1]
ROOT = FLOW
sys.path.insert(0, str(FLOW))
from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import _sha256
from tools.release_check import payload_files, release_files


def _run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=180,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}, check=False)
    if result.returncode:
        raise RuntimeError(f"{command}:\n{(result.stdout + result.stderr)[-6000:]}")
    return result.stdout + result.stderr


def _payload(*, preview=False):
    acceptance = json.loads((FLOW / "release/acceptance.json").read_text())
    if (acceptance.get("version") != FLOW_VERSION
            or (not preview and acceptance.get("release_ready") is not True)):
        raise RuntimeError("release/acceptance.json is not a ready record for this version")
    if acceptance.get("status") not in {"contracts_passed", "released"}:
        raise RuntimeError("No successful contract check for this version")
    manifest = json.loads((FLOW / "release/source_manifest.json").read_text())
    if manifest.get("version") != FLOW_VERSION:
        raise RuntimeError("source manifest version mismatch")
    if (acceptance.get("source_manifest_sha256") != _sha256(FLOW / "release/source_manifest.json")
            or acceptance.get("package_revision") != manifest.get("package_revision")):
        raise RuntimeError("source manifest is stale or not bound to the acceptance record")
    expected = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    current = {str(p.relative_to(ROOT)): _sha256(p) for p in payload_files(FLOW)}
    if current != expected or len(expected) != len(manifest["files"]):
        raise RuntimeError("source manifest drift or stale file scope; rerun release_check")
    for path in release_files(FLOW):
        expected[str(path.relative_to(ROOT))] = _sha256(path)
    return expected


def _write_archive(path, prefix, files):
    with (path.open("xb") as raw,
          gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped,
          tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive):
        for relative in sorted(files):
            source = ROOT / relative
            data = source.read_bytes()
            info = tarfile.TarInfo(f"{prefix}/{relative}")
            info.size = len(data)
            info.mode = source.stat().st_mode & 0o777
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "deliverables")
    parser.add_argument("--preview", action="store_true",
                        help="round-trip an offline-checked working tree; NOT a release")
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"autoresearch-workflow-{FLOW_VERSION}"
    if args.preview:
        revision = json.loads((FLOW / "rules/manifest.json").read_text()).get("package_revision", "working")
        if not isinstance(revision, str) or not re.fullmatch(r"[A-Za-z0-9.-]+", revision):
            raise RuntimeError("invalid package revision")
        prefix += f"-{revision}-preview"
    archive = args.output_dir / f"{prefix}-migration.tar.gz"
    validation_path = args.output_dir / f"{prefix}-migration-validation.json"
    checksum_path = args.output_dir / f"{archive.name}.sha256"
    for target in (archive, validation_path, checksum_path):
        if target.exists():
            raise RuntimeError(f"refusing to overwrite release artifact: {target}")
    files = _payload(preview=args.preview)
    _write_archive(archive, prefix, files)
    with tempfile.TemporaryDirectory(prefix="autoresearch-migration-") as temporary:
        temporary_root = Path(temporary)
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(temporary_root, filter="data")
        extracted = temporary_root / prefix
        if (extracted / "AutoResearch新流程设计").exists():
            raise RuntimeError("design archive unexpectedly included")
        for relative, digest in files.items():
            target = extracted / relative
            if not target.is_file() or _sha256(target) != digest:
                raise RuntimeError(f"round-trip mismatch: {relative}")
        commands = [
            [sys.executable, "cli.py", "--format", "json", "rules", "check"],
            [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
        ]
        checks = []
        for command in commands:
            output = _run(command, extracted)
            checks.append({"command": command, "exit_code": 0, "output_tail": output[-2000:]})
    if files != _payload(preview=args.preview):
        raise RuntimeError("inputs changed while building archive; validation not issued")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    validation = {"archive": archive.name, "version": FLOW_VERSION, "sha256": digest,
                  "artifact_kind": "unreleased_preview" if args.preview else "release",
                  "release_ready": not args.preview,
                  "bytes": archive.stat().st_size, "payload_files": len(files),
                  "roundtrip_file_hashes": "passed", "checks": checks,
                  "model_calls": 0, "docker_images_included": False,
                  "pilot_runs_included": False, "credentials_included": False,
                  "design_archive_included": False}
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n")
    checksum_path.write_text(f"{digest}  {archive.name}\n")
    print(json.dumps({"status": "preview_built" if args.preview else "built", **{k: validation[k] for k in
          ("archive", "sha256", "bytes", "payload_files")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
