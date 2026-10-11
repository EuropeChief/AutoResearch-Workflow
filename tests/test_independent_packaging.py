"""Synthetic PASS contracts only; no QA workflow, models or tasks are run."""

import copy
import datetime as dt
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from test_qa_contract import synthetic_report

from autoresearch_flow.archive_io import (
    _verify_upload,
    _verify_zip,
    _write_zip,
    package_snapshot,
)
from autoresearch_flow.common import FlowError, _canonical_digest, _sha256
from autoresearch_flow.package_delivery import package

FLOW = Path(__file__).resolve().parents[1]
NOTES = """## 研究子方向
合成机制测试
## 优化面介绍
合成方法空间
## Baseline 描述
合成朴素方法
## Reference 描述
合成参考方法
## 小规模试跑结论
根据双轨前期真实记录总结；本测试仅为合成文字，不是实际试跑证据。
"""


class IndependentPackagingTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ar-package-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "final-package"
        for name in (
            "workspace/harbor_task",
            "workspace/reference",
            "expert_evidence",
            "optimization_evidence",
        ):
            (self.root / name).mkdir(parents=True)
        self.put("workspace/harbor_task/run.sh", "#!/bin/sh\nexit 0\n")
        (self.root / "workspace/harbor_task/run.sh").chmod(0o755)
        self.put(
            "workspace/harbor_task/禁止执行.py",
            "raise RuntimeError('packaging must not run me')\n",
        )
        self.put("workspace/reference/main.py", "# SYNTHETIC reference\n")
        self.put("expert_evidence/专家作业说明文档.md", NOTES)
        self.put("optimization_evidence/证据.txt", "SYNTHETIC contract only\n")
        self.annotation = {
            "task_id": "synthetic",
            "score_contract": {
                "metric": "error",
                "direction": "minimize",
                "split": "dev",
                "protocol": "v1",
                "baseline": {"raw_value": 12, "normalized_score": 0},
                "reference": {"raw_value": 8, "normalized_score": 2 / 3},
                "upper_bound": {"raw_value": 6},
            },
        }
        self.comparison = {
            "status": "COMPLETE",
            "metric": {"name": "error", "direction": "minimize", "unit": "pp"},
            "split": "dev",
            "seeds": [1, 2, 3],
            "statistics": {"baseline_mean": 12, "reference_mean": 8},
        }
        self.put("expert_evidence/expert_annotation.json", json.dumps(self.annotation))
        self.put(
            "optimization_evidence/comparison_summary.json", json.dumps(self.comparison)
        )
        self.qa_dir = self.base / "independent-qa"
        self.qa_dir.mkdir()
        self.report_path = self.qa_dir / "report.json"
        self.report = synthetic_report(self.root)
        self.freeze_report()

    def put(self, name, text):
        p = self.root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(text, encoding="utf-8")

    def freeze_report(self, scan=None):
        scan = scan or self.root
        self.report["source"]["path"] = str(scan)
        self.report["workspace_root"] = str(scan)
        self.report["generated_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        self.report_path.write_text(json.dumps(self.report), encoding="utf-8")
        (self.qa_dir / "inventory.json").write_text(
            json.dumps(
                {
                    "root": str(scan),
                    "files": sorted(
                        str(p.relative_to(scan)) for p in scan.rglob("*") if p.is_file()
                    ),
                }
            )
        )

    def run_package(self, output="attachments", **kwargs):
        return package(self.root, self.report_path, self.base / output, **kwargs)

    def test_three_zips_form_and_readonly_without_state(self):
        before = package_snapshot(self.root)
        report = self.report_path.read_bytes()
        result = self.run_package()
        self.assertEqual(result["status"], "packaged")
        self.assertEqual(
            set(result["archives"]),
            {"submission", "harbor_task", "optimization_evidence"},
        )
        self.assertEqual(result["form"]["status"], "complete")
        out = Path(result["output_directory"])
        self.assertFalse((out / "archives.json").exists())
        self.assertFalse((out / "form.json").exists())
        self.assertFalse((self.root / ".autoresearch").exists())
        self.assertEqual(package_snapshot(self.root), before)
        self.assertEqual(self.report_path.read_bytes(), report)
        for role in result["archives"]:
            entry = result["archives"][role]
            with zipfile.ZipFile(out / entry["path"]) as z:
                self.assertIsNone(z.testzip())
                self.assertTrue(
                    all(n.startswith(entry["prefix"] + "/") for n in z.namelist())
                )
                if role == "submission":
                    n = entry["prefix"] + "/expert_evidence/专家作业说明文档.md"
                    self.assertTrue(z.getinfo(n).flag_bits & 0x800)
                    s = z.getinfo(entry["prefix"] + "/workspace/harbor_task/run.sh")
                    self.assertEqual(stat.S_IMODE(s.external_attr >> 16), 0o755)
                else:
                    self.assertFalse(any("expert_evidence" in n for n in z.namelist()))
        text = (out / "填表信息.md").read_text()
        self.assertIn("原始指标", text)
        self.assertIn("12", text)
        self.assertIn("0.6666666667", text)
        self.assertEqual(text.count("\n## "), 7)
        self.assertNotIn("reviewer", text)

    def test_packaging_never_demands_stage_approvals_or_preflight(self):
        with patch("autoresearch_flow.preflight.Preflight.check",
                   side_effect=AssertionError("No stage gate before packaging")), \
             patch("autoresearch_flow.task_workspace.TaskWorkspace.read_decisions",
                   side_effect=AssertionError("No historical approval lookup")):
            self.assertEqual(self.run_package()["status"], "packaged")
        self.assertFalse((self.root / ".autoresearch").exists())

    def test_copy_scanned_by_qa_is_compared_by_content_and_modes(self):
        scan = self.base / "qa-copy"
        shutil.copytree(self.root, scan)
        self.freeze_report(scan)
        result = self.run_package()
        self.assertEqual(result["qa"]["correspondence"], "identical_scanned_copy")
        self.put("workspace/harbor_task/run.sh", "changed\n")
        with self.assertRaises(FlowError) as e:
            self.run_package("second")
        self.assertEqual(e.exception.code, "QA_SCOPE_MISMATCH")

    def test_failed_collector_unfinished_and_wrong_schema_never_write_outputs(self):
        for key in ("failure", "collector", "schema", "nop", "manual"):
            r = copy.deepcopy(self.report)
            if key == "failure":
                r["summary"]["decision"] = "FAIL"
            if key == "collector":
                r["review"]["completed"] = False
            if key == "schema":
                r["schema_version"] = 3
            if key == "nop":
                r["harbor"]["trial_evidence"] = None
            if key == "manual":
                r["checks"][0].update(
                    status="manual", remediation="fix", acceptance_evidence="proof"
                )
            self.report_path.write_text(json.dumps(r))
            with self.subTest(key=key), self.assertRaises(FlowError):
                self.run_package(key)
            self.assertFalse((self.base / key).exists())

    def test_same_path_drift_deleted_inventory_and_unknown_version_are_rejected(self):
        self.put("workspace/harbor_task/run.sh", "edited after QA\n")
        # Set an observed post-report mtime explicitly: some kernels cache ctime
        # within a clock tick, making sub-millisecond edits nondeterministic.
        stamp = dt.datetime.fromisoformat(self.report["generated_at"]).timestamp() + 1
        os.utime(self.root / "workspace/harbor_task/run.sh", (stamp, stamp))
        with self.assertRaises(FlowError) as e:
            self.run_package()
        self.assertEqual(e.exception.code, "QA_VERSION_UNVERIFIED")
        self.freeze_report()
        (self.root / "workspace/harbor_task/run.sh").unlink()
        with self.assertRaises(FlowError):
            self.run_package()
        self.freeze_report()
        (self.qa_dir / "inventory.json").unlink()
        with self.assertRaises(FlowError) as e:
            self.run_package()
        self.assertEqual(e.exception.code, "QA_VERSION_UNVERIFIED")

    def test_bad_boundary_existing_output_and_missing_required_directory(self):
        user_file = self.base / "user-file"
        user_file.write_text("do not overwrite")
        for out in (self.root / "attachments", user_file):
            with self.subTest(out=str(out)), self.assertRaises(FlowError):
                package(self.root, self.report_path, out)
        self.assertFalse((self.root / "attachments").exists())
        (self.root / "workspace/reference").rename(self.root / "workspace/no-reference")
        with self.assertRaises(FlowError):
            self.run_package()

    def test_links_never_followed(self):
        outside = self.base / "not-in-package.txt"
        outside.write_text("PRIVATE OUTSIDE")
        (self.root / "expert_evidence/linked").symlink_to(outside)
        self.freeze_report()
        with self.assertRaises(FlowError):
            self.run_package()
        self.assertFalse((self.base / "attachments").exists())

    def test_split_boundary_cap_adjustment_reassembly_and_corruption(self):
        self.put("optimization_evidence/random.bin", os.urandom(4096).hex())
        self.freeze_report()
        first = self.run_package("first")
        boundary = first["archives"]["submission"]["bytes"]
        equal = self.run_package(
            "equal", upload_limit_bytes=boundary, part_bytes=boundary
        )
        self.assertFalse(equal["archives"]["submission"]["parts"])
        split = self.run_package(
            "split", upload_limit_bytes=boundary - 1, part_bytes=512
        )
        out = Path(split["output_directory"])
        s = split["archives"]["submission"]
        rebuilt = b"".join((out / p["path"]).read_bytes() for p in s["parts"])
        self.assertEqual(rebuilt, (out / s["path"]).read_bytes())
        self.assertTrue(all(p["bytes"] <= 512 for p in s["parts"]))
        (out / s["parts"][0]["path"]).write_bytes(b"bad")
        with self.assertRaises(FlowError):
            _verify_upload(out / s["path"], {**s, "parts": []}, 512, boundary - 1)
        # No permanent 300 MB ceiling; small fixture still stays a single ZIP.
        high = self.run_package("high", upload_limit_bytes=400_000_000)
        self.assertFalse(high["archives"]["submission"]["parts"])

    def test_source_change_during_archive_has_no_final_success_directory(self):
        from autoresearch_flow import package_delivery

        original = package_delivery._write_zip

        def change(*args, **kwargs):
            original(*args, **kwargs)
            self.put("expert_evidence/new.txt", "concurrent change")

        with (
            patch.object(package_delivery, "_write_zip", side_effect=change),
            self.assertRaises(FlowError),
        ):
            self.run_package()
        self.assertFalse((self.base / "attachments").exists())
        self.assertFalse(
            any(p.name.startswith(".ar-package-") for p in self.base.iterdir())
        )

    def test_form_notes_optional_missing_fields_do_not_block_and_conflict_does(self):
        self.put("expert_evidence/专家作业说明文档.md", "合成说明，无可提取概述。")
        self.freeze_report()
        r = self.run_package("partial")
        self.assertEqual(r["form"]["status"], "pending")
        self.assertIn("小规模试跑结论", r["form"]["missing"])
        self.assertTrue((Path(r["output_directory"]) / "填表信息.md").exists())
        notes = self.base / "notes.md"
        notes.write_text(NOTES)
        done = self.run_package("notes", form_notes=notes)
        self.assertEqual(done["form"]["status"], "complete")
        self.annotation["score_contract"]["baseline"]["raw_value"] = 123
        self.put("expert_evidence/expert_annotation.json", json.dumps(self.annotation))
        self.freeze_report()
        with self.assertRaises(FlowError) as e:
            self.run_package("bad-mean")
        self.assertEqual(e.exception.code, "FORM_SOURCE_CONFLICT")

    def test_explicit_digest_algorithm_must_match_and_unknown_algorithm_not_guessed(
        self,
    ):
        self.report["source"]["package_digest"] = {
            "algorithm": "sha256-canonical-package-snapshot-v1",
            "value": _canonical_digest(package_snapshot(self.root)),
        }
        (self.qa_dir / "inventory.json").unlink()
        self.report_path.write_text(json.dumps(self.report))
        self.assertEqual(
            self.run_package("digest")["qa"]["correspondence"], "reported_tree_digest"
        )
        self.report["source"]["package_digest"]["value"] = "0" * 64
        self.report_path.write_text(json.dumps(self.report))
        with self.assertRaises(FlowError):
            self.run_package("wrong")
        self.report["source"]["package_digest"]["algorithm"] = "unknown-sha256"
        self.report_path.write_text(json.dumps(self.report))
        with self.assertRaises(FlowError) as e:
            self.run_package("unknown")
        self.assertEqual(e.exception.code, "QA_VERSION_UNVERIFIED")

    def test_qa_zip_hash_and_contents_bind_without_extraction(self):
        scanned = self.base / "scanned.zip"
        _write_zip(self.root, scanned, "synthetic-research")
        self.report["source"] = {
            "path": str(scanned),
            "kind": "zip",
            "sha256": _sha256(scanned),
        }
        self.report_path.write_text(json.dumps(self.report))
        self.assertEqual(self.run_package("zip")["qa"]["correspondence"], "scanned_zip")
        self.put("workspace/reference/main.py", "# different method\n")
        with self.assertRaises(FlowError):
            self.run_package("different")
        with scanned.open("ab") as f:
            f.write(b"changed archive")
        with self.assertRaises(FlowError):
            self.run_package("changed-zip")

    @unittest.skipUnless(shutil.which("unzip"), "unzip unavailable")
    def test_independent_unzip_restores_mode_unicode_empty_dirs(self):
        (self.root / "expert_evidence/空目录").mkdir()
        self.freeze_report()
        r = self.run_package(name="方法证据")
        out = Path(r["output_directory"])
        z = out / r["archives"]["submission"]["path"]
        dest = self.base / "extracted"
        p = subprocess.run(
            ["unzip", "-q", str(z), "-d", str(dest)],
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(
            package_snapshot(dest / "方法证据"), package_snapshot(self.root)
        )

    def test_name_and_sizes_safe_and_cli_has_no_legacy_imports(self):
        for opts in (
            {"name": "../escape"},
            {"name": "harbor_task"},
            {"name": "bad\nname"},
            {"part_bytes": 0},
            {"upload_limit_bytes": True},
            {"upload_limit_bytes": 512, "part_bytes": 513},
        ):
            with self.subTest(opts=opts), self.assertRaises(FlowError):
                self.run_package(**opts)
        code = """import sys,cli
rc=cli.main(['--format','json','package','--package-root',sys.argv[1],'--qa-report',sys.argv[2],'--output-dir',sys.argv[3]])
assert 'autoresearch_flow.core' not in sys.modules
assert 'autoresearch_flow.runtime' not in sys.modules
assert 'autoresearch_flow.experiments' not in sys.modules
raise SystemExit(rc)
"""
        p = subprocess.run(
            [
                sys.executable,
                "-c",
                code,
                str(self.root),
                str(self.report_path),
                str(self.base / "cli"),
            ],
            cwd=FLOW,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
        self.assertEqual(json.loads(p.stdout)["status"], "packaged")

    def test_malformed_nested_facts_and_numeric_disagreement_are_not_hidden_as_missing_prose(
        self,
    ):
        for mutation in (
            "stats",
            "evaluation_protocol",
            "role",
            "nan",
            "normalized",
            "split",
        ):
            c = copy.deepcopy(self.comparison)
            a = copy.deepcopy(self.annotation)
            if mutation == "stats":
                c["statistics"] = []
            if mutation == "evaluation_protocol":
                c["evaluation_protocol"] = None
                c.pop("seeds")
            if mutation == "role":
                a["score_contract"]["baseline"] = []
            if mutation == "nan":
                c["statistics"]["baseline_mean"] = float("nan")
            if mutation == "normalized":
                a["score_contract"]["reference"]["normalized_score"] = 0.8
            if mutation == "split":
                c["split"] = "different"
            self.put("expert_evidence/expert_annotation.json", json.dumps(a))
            self.put("optimization_evidence/comparison_summary.json", json.dumps(c))
            self.freeze_report()
            with self.subTest(mutation=mutation), self.assertRaises(FlowError):
                self.run_package(mutation)
            self.assertFalse((self.base / mutation).exists())

    def test_maximize_zero_baseline_and_negative_reference_scores_remain_unclipped(
        self,
    ):
        a = self.annotation["score_contract"]
        a.update(direction="maximize")
        a["baseline"] = {"raw_value": 0, "normalized_score": 0}
        a["reference"] = {"raw_value": -2, "normalized_score": -1}
        a["upper_bound"] = {"raw_value": 2}
        self.comparison["metric"]["direction"] = "maximize"
        self.comparison["statistics"].update(baseline_mean=0, reference_mean=-2)
        self.put("expert_evidence/expert_annotation.json", json.dumps(self.annotation))
        self.put(
            "optimization_evidence/comparison_summary.json", json.dumps(self.comparison)
        )
        self.freeze_report()
        r = self.run_package()
        text = Path(r["form"]["path"]).read_text()
        self.assertIn("归一化分数：-1", text)
        # Packaging trusts the complete QA decision, not a new science threshold.
        self.assertEqual(r["status"], "packaged")

    def test_default_name_removes_task_number_explicit_name_can_override(self):
        new = self.base / "ToB-999"
        self.root.rename(new)
        self.root = new
        self.freeze_report()
        r = self.run_package()
        self.assertEqual(r["archives"]["submission"]["prefix"], "research-submission")
        r = self.run_package("explicit", name="User-999-override")
        self.assertEqual(r["archives"]["submission"]["prefix"], "User-999-override")

    def test_existing_output_is_preserved_and_invalid_cli_has_clean_diagnostic(self):
        out = self.base / "existing"
        out.mkdir()
        (out / "user.txt").write_text("user content")
        r = self.run_package("existing")
        self.assertTrue(Path(r["output_directory"]).is_relative_to(out))
        self.assertEqual((out / "user.txt").read_text(), "user content")
        self.report["policy"] = []
        self.report_path.write_text(json.dumps(self.report))
        p = subprocess.run(
            [
                sys.executable,
                "cli.py",
                "--format",
                "json",
                "package",
                "--package-root",
                str(self.root),
                "--qa-report",
                str(self.report_path),
                "--output-dir",
                str(self.base / "bad-cli"),
            ],
            cwd=FLOW,
            capture_output=True,
            text=True,
            check=False,
        )
        self.assertEqual(p.returncode, 2)
        self.assertEqual(json.loads(p.stdout)["code"], "QA_REPORT_SCHEMA")
        self.assertNotIn("Traceback", p.stderr)

    def test_existing_parent_creates_distinct_result_batches_without_receipts(self):
        first = self.run_package("existing-parent")
        second = self.run_package("existing-parent")
        third = self.run_package("existing-parent")
        # First call can use a new leaf; further calls choose new children,
        # never overwrite the first batch's actual attachments.
        self.assertNotEqual(second["output_directory"], third["output_directory"])
        out = Path(first["output_directory"])
        self.assertTrue((out / first["archives"]["submission"]["path"]).is_file())
        self.assertFalse(any(p.name == "archives.json" for p in out.rglob("*")))

    def test_normal_qa_zip_can_use_implicit_directories(self):
        scan = self.base / "file-only.zip"
        with zipfile.ZipFile(scan, "w") as z:
            for p in self.root.rglob("*"):
                if p.is_file():
                    z.write(p, "research/" + p.relative_to(self.root).as_posix())
        self.report["source"] = {
            "kind": "zip",
            "path": str(scan),
            "sha256": _sha256(scan),
        }
        self.report_path.write_text(json.dumps(self.report))
        r = self.run_package()
        self.assertEqual(r["qa"]["correspondence"], "scanned_zip")

    def test_symlink_member_type_crc_corruption_and_malformed_qa_zip_fail_cleanly(self):
        good = self.base / "original.zip"
        _write_zip(self.root, good, "research")
        bad = self.base / "bad-type.zip"
        with zipfile.ZipFile(good) as src, zipfile.ZipFile(bad, "w") as dst:
            for info in src.infolist():
                if info.filename.endswith("run.sh"):
                    info.external_attr = (stat.S_IFLNK | 0o755) << 16
                dst.writestr(info, src.read(info.filename))
        with self.assertRaises(FlowError):
            _verify_zip(self.root, bad, "research")
        crc_bad = self.base / "crc-bad.zip"
        with zipfile.ZipFile(crc_bad, "w", compression=zipfile.ZIP_STORED) as z:
            for p in self.root.rglob("*"):
                if p.is_file():
                    z.write(p, "research/" + p.relative_to(self.root).as_posix())
        with zipfile.ZipFile(crc_bad) as z:
            member = z.getinfo("research/workspace/reference/main.py")
            offset = (
                member.header_offset
                + 30
                + len(member.filename.encode("utf-8"))
                + len(member.extra)
            )
        with crc_bad.open("r+b") as f:
            f.seek(offset)
            first = f.read(1)
            f.seek(offset)
            f.write(bytes([first[0] ^ 1]))
        self.report["source"] = {
            "kind": "zip",
            "path": str(crc_bad),
            "sha256": _sha256(crc_bad),
        }
        self.report_path.write_text(json.dumps(self.report))
        with self.assertRaises(FlowError) as e:
            self.run_package("crc-bad")
        self.assertEqual(e.exception.code, "QA_VERSION_UNVERIFIED")
        # The report SHA must not allow a malformed ZIP to escape as traceback.
        bad.write_text("not a ZIP")
        self.report["source"] = {
            "kind": "zip",
            "path": str(bad),
            "sha256": _sha256(bad),
        }
        self.report_path.write_text(json.dumps(self.report))
        with self.assertRaises(FlowError):
            self.run_package()

    def test_large_expert_document_only_leaves_form_pending(self):
        self.put("expert_evidence/专家作业说明文档.md", "合成长说明" * 50000)
        self.freeze_report()
        r = self.run_package()
        self.assertEqual(r["form"]["status"], "pending")
        self.assertTrue(r["archives"])
        self.assertTrue(any("较大" in s for s in r["form"]["notes"]))

    def test_tutorial_research_direction_field_and_huge_numbers(self):
        self.put(
            "expert_evidence/专家作业说明文档.md",
            NOTES.replace("## 研究子方向\n合成机制测试\n", ""),
        )
        self.annotation["research_direction"] = "教程字段中的实际方向"
        self.put("expert_evidence/expert_annotation.json", json.dumps(self.annotation))
        self.freeze_report()
        r = self.run_package("direction")
        self.assertIn("教程字段中的实际方向", Path(r["form"]["path"]).read_text())
        self.comparison["statistics"]["baseline_mean"] = 10**1000
        self.put(
            "optimization_evidence/comparison_summary.json", json.dumps(self.comparison)
        )
        self.freeze_report()
        with self.assertRaises(FlowError) as e:
            self.run_package("large-number")
        self.assertEqual(e.exception.code, "FORM_SOURCE_CONFLICT")

    def test_all_seed_declarations_must_agree_and_be_valid(self):
        for bad in (
            {"formal_aggregates": {"seeds": [1, 1]}, "seeds": None},
            {"evaluation_protocol": {"seeds": [1, 2, 4]}},
            {"formal_aggregates": {"seeds": [False, 2, 3]}},
        ):
            c = copy.deepcopy(self.comparison)
            c.update(bad)
            self.put("optimization_evidence/comparison_summary.json", json.dumps(c))
            self.freeze_report()
            with self.subTest(bad=bad), self.assertRaises(FlowError):
                self.run_package()

    def test_report_parent_alias_cannot_smuggle_a_report_from_inside_source(self):
        inner = self.root / "expert_evidence/report.json"
        inner.write_text(json.dumps(self.report))
        alias = self.base / "alias"
        alias.symlink_to(self.root / "expert_evidence", target_is_directory=True)
        with self.assertRaises(FlowError) as e:
            package(self.root, alias / "report.json", self.base / "attachments")
        self.assertEqual(e.exception.code, "QA_SCOPE_MISMATCH")


if __name__ == "__main__":
    unittest.main()
