"""Build and round-trip validate a relocatable workflow release archive."""
from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import re
import sys
import tarfile
import tempfile
from pathlib import Path

FLOW = Path(__file__).resolve().parents[1]
ROOT = FLOW
sys.path.insert(0, str(FLOW))
from autoresearch_flow import FLOW_VERSION
from autoresearch_flow.core import _sha256
from tools.release_check import check_documents, payload_files, release_files, runtime_smoke, source_snapshot
from tools.release_evidence import validate_evidence


def _payload(*, preview=False, evidence_manifest=None):
    acceptance = json.loads((FLOW / "release/acceptance.json").read_text())
    if (acceptance.get("schema_version") != 2 or acceptance.get("version") != FLOW_VERSION
            or (not preview and acceptance.get("release_ready") is not True)):
        raise RuntimeError("release/acceptance.json is not a ready record for this version")
    if acceptance.get("status") not in {"contracts_passed", "released"}:
        raise RuntimeError("No successful contract check for this version")
    manifest = json.loads((FLOW / "release/source_manifest.json").read_text())
    if manifest.get("schema_version") != 2 or manifest.get("version") != FLOW_VERSION:
        raise RuntimeError("source manifest version mismatch")
    if (acceptance.get("source_manifest_sha256") != _sha256(FLOW / "release/source_manifest.json")
            or acceptance.get("package_revision") != manifest.get("package_revision")):
        raise RuntimeError("source manifest is stale or not bound to the acceptance record")
    files = payload_files(FLOW)
    expected = {entry["path"]: {"sha256": entry["sha256"], "mode": entry.get("mode")} for entry in manifest["files"]}
    current = {e.pop('path'): e for e in source_snapshot(files, FLOW)}
    if current != expected or len(expected) != len(manifest["files"]):
        raise RuntimeError("source manifest drift or stale file scope; rerun release_check")
    if not preview:
        if evidence_manifest is None or acceptance.get('status') != 'released':
            raise RuntimeError('formal archive requires explicit --evidence-manifest and released acceptance')
        verified = validate_evidence(evidence_manifest, FLOW, files)
        if verified != acceptance.get('release_evidence'):
            raise RuntimeError('release evidence changed or is not bound to acceptance')
    for entry in source_snapshot(release_files(FLOW), FLOW):
        expected[entry.pop('path')] = entry
    return expected


def _write_archive(path, prefix, files):
    with (path.open("xb") as raw,
          gzip.GzipFile(filename="", mode="wb", fileobj=raw, mtime=0) as zipped,
          tarfile.open(fileobj=zipped, mode="w", format=tarfile.PAX_FORMAT) as archive):
        for relative in sorted(files):
            source = ROOT / relative
            data = source.read_bytes()
            if source.is_symlink() or hashlib.sha256(data).hexdigest() != files[relative]['sha256']:
                raise RuntimeError(f'input changed before archiving: {relative}')
            mode = source.stat().st_mode & 0o777
            if mode != files[relative]['mode']:
                raise RuntimeError(f'input permissions changed before archiving: {relative}')
            info = tarfile.TarInfo(f"{prefix}/{relative}")
            info.size = len(data)
            info.mode = mode
            info.mtime = 0
            info.uid = info.gid = 0
            info.uname = info.gname = "root"
            archive.addfile(info, io.BytesIO(data))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "deliverables")
    parser.add_argument("--preview", action="store_true",
                        help="round-trip an offline-checked working tree; NOT a release")
    parser.add_argument('--evidence-manifest', type=Path, help='same reviewed evidence used by release_check --release')
    args = parser.parse_args()
    if args.preview == bool(args.evidence_manifest):
        parser.error('formal archive requires --evidence-manifest; preview must not claim live acceptance')
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
    files = _payload(preview=args.preview, evidence_manifest=args.evidence_manifest)
    _write_archive(archive, prefix, files)
    with tempfile.TemporaryDirectory(prefix="autoresearch-migration-") as temporary:
        temporary_root = Path(temporary)
        with tarfile.open(archive, "r:gz") as package:
            def owned_file(info, destination):
                if not info.isfile() or not info.name.startswith(prefix+'/'):
                    raise RuntimeError('unexpected archive member')
                relative = info.name[len(prefix)+1:]
                if relative not in files or info.mode != files[relative]['mode']:
                    raise RuntimeError('archive member path/permissions mismatch')
                # data_filter checks paths and rejects unsafe member kinds.
                # Restore the known source's ordinary rwx bits, which its
                # default group-write stripping would otherwise discard.
                safe = tarfile.data_filter(info, destination)
                return safe.replace(mode=files[relative]['mode'])
            package.extractall(temporary_root, filter=owned_file)
        extracted = temporary_root / prefix
        if (extracted / "AutoResearch新流程设计").exists():
            raise RuntimeError("design archive unexpectedly included")
        actual = {p.relative_to(extracted).as_posix() for p in extracted.rglob('*') if p.is_file()}
        if actual != set(files):
            raise RuntimeError('round-trip file set mismatch')
        for relative, record in files.items():
            target = extracted / relative
            if (not target.is_file() or target.is_symlink() or _sha256(target) != record['sha256']
                    or target.stat().st_mode & 0o777 != record['mode']):
                raise RuntimeError(f"round-trip mismatch: {relative}")
        if any((extracted / name).exists() for name in ("tests", "pilots", "tools", "local", "docs/maintenance")):
            raise RuntimeError("development/private files unexpectedly included")
        check_documents([extracted / relative for relative in files], extracted)
        checks = runtime_smoke(extracted)
    if files != _payload(preview=args.preview, evidence_manifest=args.evidence_manifest):
        raise RuntimeError("inputs changed while building archive; validation not issued")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    validation = {"archive": archive.name, "version": FLOW_VERSION, "sha256": digest,
                  "artifact_kind": "unreleased_preview" if args.preview else "release",
                  "release_ready": not args.preview,
                  "bytes": archive.stat().st_size, "payload_files": len(files),
                  "roundtrip_file_hashes": "passed", "roundtrip_permissions": "passed", "checks": checks,
                  "model_calls": 0, "docker_images_included": False,
                  "pilot_runs_included": False, "credentials_included": False,
                  "development_tests_included": False, "maintenance_records_included": False,
                  "design_archive_included": False}
    validation_path.write_text(json.dumps(validation, ensure_ascii=False, indent=2) + "\n")
    checksum_path.write_text(f"{digest}  {archive.name}\n")
    print(json.dumps({"status": "preview_built" if args.preview else "built", **{k: validation[k] for k in
          ("archive", "sha256", "bytes", "payload_files")}}, ensure_ascii=False))


if __name__ == "__main__":
    main()
