"""Synthetic accepted packages: no QA skill, Docker, GPU or model is run."""
import json
import hashlib
import shutil
import stat
import subprocess
import unittest
import zipfile
from pathlib import Path

import test_op02_stability as fixtures
from test_qa_contract import synthetic_report
from test_pca_contract import synthetic_nop
from autoresearch_flow.core import FlowError
from autoresearch_flow.w4_package import check_package
from autoresearch_flow.pca_contract import task_digest


class ArchiveTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.StabilityDeliveryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root, self.source = self.fx.root, self.fx.package
        self.delivery = self.fx.fx.package

    def test_same_snapshot_at_other_path_binds_without_rewriting_report(self):
        scan = self.root / "independent-qa-copy"
        shutil.copytree(self.source, scan)
        report = self.root / "independent-report.json"
        report.write_text(json.dumps(synthetic_report(scan)))
        original = report.read_bytes()
        bound = self.delivery.qa_bind(self.source, report)
        self.assertEqual(bound["status"], "attached_unreviewed")
        self.assertEqual(bound["scanned_path"], str(scan))
        self.assertEqual(bound["scanned_sha256"], check_package(self.source)["package_sha256"])
        self.assertEqual(report.read_bytes(), original)
        (scan / "workspace/harbor_task/tests/test.sh").chmod(0o755)
        with self.assertRaises(FlowError) as caught:
            self.delivery.qa_bind(self.source, report)
        self.assertEqual(caught.exception.code, "QA_SCOPE_MISMATCH")

    def test_permissions_change_invalidates_prior_qa(self):
        before = check_package(self.source)["package_sha256"]
        script = self.source / "workspace/harbor_task/tests/test.sh"
        script.chmod(0o755)
        self.assertNotEqual(check_package(self.source)["package_sha256"], before)
        with self.assertRaises(FlowError) as caught:
            self.delivery.qa_bind(self.source, self.root / "synthetic-qa.json")
        self.assertEqual(caught.exception.code, "QA_PACKAGE_DRIFT")

    def test_archive_requires_qa_review_and_real_package_execution_evidence(self):
        for missing in ("qa_review", "harbor_execution"):
            checks = dict(self.fx.checks)
            del checks[missing]
            with self.subTest(missing=missing), self.assertRaises(FlowError):
                self.delivery.archive(self.source, name="synthetic-benchmark", checks=checks)
        self.assertFalse((self.delivery.directory / "archives").exists())
        pointer = self.delivery.directory / "qa_binding_current.json"
        pointer.unlink()
        with self.assertRaises(FlowError):
            self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)
        self.assertFalse((self.delivery.directory / "archives").exists())

    def test_delivery_phases_do_not_close_stage_before_form(self):
        spec = {"step": "6.5", "checks": self.fx.checks}
        gate = self.fx.flow.check("6.5", spec)
        self.assertEqual(gate["machine_check"]["result"]["delivery_phase"], "qa_verified")
        with self.assertRaises(FlowError) as caught:
            self.fx.record()
        self.assertEqual(caught.exception.code, "DELIVERY_INCOMPLETE")
        self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)
        gate = self.fx.flow.check("6.5", spec)
        self.assertEqual(gate["machine_check"]["result"]["delivery_phase"], "archives_verified")
        with self.assertRaises(FlowError):
            self.fx.record()

    def test_three_archives_preserve_names_modes_scope_and_source(self):
        script = self.source / "workspace/harbor_task/tests/test.sh"
        script.chmod(0o755)
        # Keep the synthetic execution producer consistent with its final fixture.
        receipt = json.loads(self.fx.receipt.read_text())
        receipt["task_sha256"] = task_digest(self.source / "workspace/harbor_task")
        self.fx.receipt.write_text(json.dumps(receipt))
        self.fx.nop_receipt.write_text(json.dumps(synthetic_nop(self.source,
            self.source / "workspace/harbor_task")))
        self.fx.rebind()
        before = check_package(self.source)["package_sha256"]
        result = self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)
        self.assertEqual(result["status"], "archives_verified")
        self.assertEqual(set(result["archives"]), {"submission", "harbor_task", "optimization_evidence"})
        self.assertEqual(check_package(self.source)["package_sha256"], before)
        for role, prefix in (("submission", "synthetic-benchmark"), ("harbor_task", "harbor_task"),
                             ("optimization_evidence", "optimization_evidence")):
            item = result["archives"][role]
            path = Path(result["output_directory"]) / item["path"]
            with zipfile.ZipFile(path) as archive:
                self.assertIsNone(archive.testzip())
                self.assertTrue(all(n.startswith(prefix + "/") for n in archive.namelist()))
                if role == "submission":
                    chinese = archive.getinfo(prefix + "/expert_evidence/专家作业说明文档.md")
                    self.assertTrue(chinese.flag_bits & 0x800)
                    info = archive.getinfo(prefix + "/workspace/harbor_task/tests/test.sh")
                    self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o755)
                elif role == "harbor_task":
                    self.assertNotIn("reference", "/".join(archive.namelist()))
                    info = archive.getinfo("harbor_task/tests/test.sh")
                    self.assertEqual(stat.S_IMODE(info.external_attr >> 16), 0o755)
        repeated = self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)
        self.assertEqual(repeated["archives"], result["archives"])

    @unittest.skipUnless(shutil.which("unzip"), "independent Unix extractor is unavailable")
    def test_independent_unzip_round_trip_preserves_files_and_permissions(self):
        result = self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)
        out = Path(result["output_directory"])
        extracted = self.root / "extracted-archive"
        p = subprocess.run(["unzip", "-q", str(out / result["archives"]["submission"]["path"]),
                            "-d", str(extracted)], capture_output=True, text=True)
        self.assertEqual(p.returncode, 0, p.stderr)
        extracted = extracted / "synthetic-benchmark"
        expected = {p.relative_to(self.source) for p in self.source.rglob("*")}
        self.assertEqual({p.relative_to(extracted) for p in extracted.rglob("*")}, expected)
        for rel in [Path("."), *expected]:
            original, restored = self.source / rel, extracted / rel
            self.assertEqual(stat.S_IMODE(original.stat().st_mode), stat.S_IMODE(restored.stat().st_mode))
            if original.is_file():
                self.assertEqual(original.read_bytes(), restored.read_bytes())

    def test_split_boundary_reassembly_and_corruption_refusal(self):
        # A lower test upload cap exercises the same public API without creating
        # a 300 MB fixture. The production default remains decimal 300 MB.
        first = self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)
        boundary = first["archives"]["submission"]["bytes"]
        equal = self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks,
                                      upload_limit_bytes=boundary, max_part_bytes=boundary)
        self.assertEqual(equal["archives"]["submission"]["parts"], [])
        split = self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks,
                                      upload_limit_bytes=boundary-1, max_part_bytes=512)
        out = Path(split["output_directory"])
        submission = split["archives"]["submission"]
        self.assertGreater(len(submission["parts"]), 1)
        restored = b"".join((out / p["path"]).read_bytes() for p in submission["parts"])
        self.assertEqual(hashlib.sha256(restored).hexdigest(), submission["sha256"])
        self.assertTrue(all(p["bytes"] <= 512 for p in submission["parts"]))
        self.assertTrue((out / submission["path"]).is_file())
        self.assertIn("字节拼接", (out / "上传说明.md").read_text())
        self.assertTrue((out / "SHA256SUMS.txt").is_file())
        (out / submission["parts"][0]["path"]).write_bytes(b"corrupt")
        pointer = self.delivery.directory / "archives_current.json"
        old = pointer.read_bytes()
        with self.assertRaises(FlowError):
            self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks,
                                  upload_limit_bytes=boundary-1, max_part_bytes=512)
        self.assertEqual(pointer.read_bytes(), old)

    def test_failed_or_unfinished_qa_cannot_be_archived(self):
        for condition in ("failed", "unfinished", "unresolved"):
            with self.subTest(condition=condition):
                report = synthetic_report(self.source)
                report["fixture_case"] = condition
                if condition == "failed":
                    report["summary"]["decision"] = "FAIL"
                    report["checks"][0].update(status="fail", remediation="repair", acceptance_evidence="new evidence")
                elif condition == "unfinished":
                    report["summary"]["decision"] = "INCOMPLETE"
                    report["review"]["completed"] = False
                path = self.root / (condition + "-qa.json")
                path.write_text(json.dumps(report))
                self.delivery.qa_bind(self.source, path)
                review = json.loads((self.root / "qa-review.json").read_text())
                review["report_sha256"] = hashlib.sha256(path.read_bytes()).hexdigest()
                if condition == "unresolved":
                    review["unresolved_local_items"] = ["needs repair"]
                review_path = self.root / (condition + "-review.json")
                review_path.write_text(json.dumps(review))
                checks = {**self.fx.checks, "qa_review": self.fx.fx.ref(review_path)}
                with self.assertRaises(FlowError):
                    self.delivery.archive(self.source, name="synthetic-benchmark", checks=checks)
        self.assertFalse((self.delivery.directory / "archives").exists())


if __name__ == "__main__":
    unittest.main()
