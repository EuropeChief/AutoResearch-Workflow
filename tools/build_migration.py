"""Build and round-trip validate a relocatable workflow release archive."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tarfile
import tempfile

FLOW = Path(__file__).resolve().parents[1]
ROOT = FLOW.parent
sys.path.insert(0, str(FLOW))
from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import _sha256


def _run(command, cwd):
    result = subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=180,
                            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"})
    if result.returncode:
        raise RuntimeError(f"{command}:\n{(result.stdout + result.stderr)[-6000:]}")
    return result.stdout + result.stderr


def _payload():
    acceptance = json.loads((FLOW / "release/acceptance.json").read_text())
    if acceptance.get("version") != FLOW_VERSION or not acceptance.get("release_ready"):
        raise RuntimeError("release/acceptance.json is not a ready record for this version")
    manifest = json.loads((FLOW / "release/source_manifest.json").read_text())
    if manifest.get("version") != FLOW_VERSION:
        raise RuntimeError("source manifest version mismatch")
    expected = {entry["path"]: entry["sha256"] for entry in manifest["files"]}
    for relative, digest in expected.items():
        path = ROOT / relative
        if not path.is_file() or path.is_symlink() or _sha256(path) != digest:
            raise RuntimeError(f"source manifest drift: {relative}")
    for path in sorted((FLOW / "release").rglob("*")):
        if path.is_file() and "__pycache__" not in path.parts:
            expected[str(path.relative_to(ROOT))] = _sha256(path)
    return expected


def _write_archive(path, prefix, files):
    with path.open("xb") as raw, gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped:
        with tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive:
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
    args = parser.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    prefix = f"autoresearch-workflow-{FLOW_VERSION}"
    archive = args.output_dir / f"{prefix}-migration.tar.gz"
    validation_path = args.output_dir / f"{prefix}-migration-validation.json"
    checksum_path = args.output_dir / f"{archive.name}.sha256"
    for target in (archive, validation_path, checksum_path):
        if target.exists():
            raise RuntimeError(f"refusing to overwrite release artifact: {target}")
    files = _payload()
    _write_archive(archive, prefix, files)
    with tempfile.TemporaryDirectory(prefix="autoresearch-migration-") as temporary:
        temporary_root = Path(temporary)
        with tarfile.open(archive, "r:gz") as package:
            package.extractall(temporary_root, filter="data")
        extracted = temporary_root / prefix
        for relative, digest in files.items():
            target = extracted / relative
            if not target.is_file() or _sha256(target) != digest:
                raise RuntimeError(f"round-trip mismatch: {relative}")
        commands = [
            [sys.executable, "AutoResearch新流程/cli.py", "--format", "json", "rules", "check"],
            [sys.executable, "-m", "unittest", "discover", "-s", "AutoResearch新流程/tests", "-v"],
        ]
        checks = []
        for command in commands:
            output = _run(command, extracted)
            checks.append({"command": command, "exit_code": 0, "output_tail": output[-2000:]})
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    validation = {"archive": archive.name, "version": FLOW_VERSION, "sha256": digest,
                  "bytes": archive.stat().st_size, "payload_files": len(files),
                  "roundtrip_file_hashes": "passed", "checks": checks,
                  "model_calls": 0, "docker_images_included": False,
                  "pilot_runs_included": False, "credentials_included": False}
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n")
    checksum_path.write_text(f"{digest}  {archive.name}\n")
    print(json.dumps({"status": "built", **{k: validation[k] for k in
          ("archive", "sha256", "bytes", "payload_files")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
