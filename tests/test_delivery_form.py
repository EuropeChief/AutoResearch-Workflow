"""Accepted synthetic facts only; no scientific results or QA are fabricated."""
import json
import subprocess
import sys
import unittest
from pathlib import Path

import test_op02_stability as fixtures
from autoresearch_flow.core import FlowError
from autoresearch_flow.w4_package import check_package


class FormTests(unittest.TestCase):
    def setUp(self):
        self.fx = fixtures.StabilityDeliveryTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.delivery, self.source = self.fx.fx.package, self.fx.package

    def archive(self):
        return self.delivery.archive(self.source, name="synthetic-benchmark", checks=self.fx.checks)

    def test_six_fields_after_archives_from_package_facts_and_stage_closure(self):
        with self.assertRaises(FlowError):
            self.delivery.form(self.source, self.fx.form_spec())
        result = self.archive()
        before = check_package(self.source)["package_sha256"]
        form = self.delivery.form(self.source, self.fx.form_spec())
        self.assertEqual(form["status"], "form_ready")
        path = Path(result["output_directory"]) / "填表信息.md"
        text = path.read_text()
        self.assertEqual(sum(line.startswith("## ") for line in text.splitlines()), 6)
        for expected in ("研究子方向", "优化面介绍", "Baseline 描述", "Baseline 分数",
                         "Reference 描述", "Reference 分数", "0.1", "0.2", "0.5", "dev", "n=3", "越大越好"):
            self.assertIn(expected, text)
        self.assertEqual(check_package(self.source)["package_sha256"], before)
        self.assertEqual(self.fx.record()["gate"]["delivery_phase"], "form_ready")
        self.assertEqual(self.delivery.form(self.source, self.fx.form_spec()), form)

    def test_edited_form_is_not_overwritten_or_still_marked_ready(self):
        out = Path(self.archive()["output_directory"])
        self.delivery.form(self.source, self.fx.form_spec())
        path = out / "填表信息.md"
        path.write_text(path.read_text() + "\n人工修订：保留此文字\n")
        before = path.read_bytes()
        with self.assertRaises(FlowError):
            self.delivery.form(self.source, self.fx.form_spec())
        self.assertEqual(before, path.read_bytes())
        result = self.fx.flow.check("6.5", {"checks": self.fx.checks})
        self.assertEqual(result["status"], "blocked")

    def test_aggregate_conflict_or_missing_source_refuses_form(self):
        self.archive()
        spec = self.fx.form_spec()
        spec["baseline_description"]["sources"] = []
        with self.assertRaises(FlowError):
            self.delivery.form(self.source, spec)
        spec = self.fx.form_spec()
        spec["reference_description"]["sources"] = spec["baseline_description"]["sources"]
        with self.assertRaises(FlowError):
            self.delivery.form(self.source, spec)
        summary = self.source / "optimization_evidence/comparison_summary.json"
        data = json.loads(summary.read_text())
        data["formal_aggregates"]["baseline"]["mean"] = 0.15
        summary.write_text(json.dumps(data))
        self.fx.rebind()
        self.archive()
        with self.assertRaises(FlowError) as caught:
            self.delivery.form(self.source, self.fx.form_spec())
        self.assertEqual(caught.exception.code, "FORM_SOURCE_CONFLICT")

    def test_cli_archive_then_form_in_same_external_directory(self):
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        inputs = self.fx.root / "delivery-input.json"
        def run(action, *args):
            p = subprocess.run([sys.executable, str(cli), "--format", "json", "delivery", action,
                "--task-root", str(self.fx.root), "--package-root", str(self.source), "--file", str(inputs),
                *args], capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stdout + p.stderr)
            return json.loads(p.stdout)
        inputs.write_text(json.dumps(self.fx.checks))
        archive = run("archive", "--name", "synthetic-benchmark")
        self.assertEqual(archive["upload_limit_bytes"], 300_000_000)
        self.assertEqual(archive["max_part_bytes"], 290_000_000)
        inputs.write_text(json.dumps(self.fx.form_spec()))
        form = run("form")
        self.assertEqual(form["status"], "form_ready")
        self.assertEqual(Path(form["path"]).parent, Path(archive["output_directory"]))

    def test_repack_requires_new_qa_and_refreshes_external_form_binding(self):
        old_archive = self.archive()
        old_form = self.delivery.form(self.source, self.fx.form_spec())
        old_text = Path(old_form["path"]).read_bytes()
        doc = self.source / "expert_evidence/专家作业说明文档.md"
        doc.write_text(doc.read_text() + "\n合成说明修订，不改方法\n")
        with self.assertRaises(FlowError):
            self.archive()
        self.fx.rebind()  # New independent report fixture for the new package.
        new_archive = self.archive()
        new_form = self.delivery.form(self.source, self.fx.form_spec())
        self.assertNotEqual(old_archive["package_sha256"], new_archive["package_sha256"])
        self.assertNotEqual(old_form["archives_sha256"], new_form["archives_sha256"])
        self.assertEqual(Path(old_form["path"]).read_bytes(), old_text)
        self.assertEqual(Path(new_form["path"]).parent, Path(new_archive["output_directory"]))


if __name__ == "__main__":
    unittest.main()
