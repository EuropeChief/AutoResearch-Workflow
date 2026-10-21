from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import zipfile


SCRIPT = Path(__file__).with_name("audit_task.py")
SPEC = importlib.util.spec_from_file_location("autoresearch_audit_task", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
AUDIT = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = AUDIT
SPEC.loader.exec_module(AUDIT)


class AuditTaskTests(unittest.TestCase):
    def run_cli(self, source, out, *options):
        return subprocess.run([sys.executable, str(SCRIPT), str(source), "--out-dir", str(out), *options],
                              capture_output=True, text=True, timeout=30)

    def test_duplicate_policy_options_are_rejected_before_dispatch(self):
        variants = [("--policy", "strict", "--policy", "precheck"),
                    ("--policy", "precheck", "--policy", "strict"),
                    ("--policy=strict", "--policy=precheck"),
                    ("--policy=precheck", "--policy", "strict"),
                    ("--pol", "strict", "--policy=implementation"),
                    ("--policy", "strict", "--policy=strict")]
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "task"
            source.mkdir()
            for index, options in enumerate(variants):
                with self.subTest(options=options):
                    out = base / f"report-{index}"
                    actual = self.run_cli(source, out, *options)
                    self.assertEqual(actual.returncode, 2)
                    self.assertIn("--policy may be supplied only once", actual.stderr)
                    self.assertFalse(out.exists())

    def test_default_implementation_and_precheck_alias_stay_consistent(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "task"
            source.mkdir()
            for index, options in enumerate(((), ("--policy", "precheck"), ("--policy=implementation",))):
                with self.subTest(options=options):
                    out = base / f"report-{index}"
                    actual = self.run_cli(source, out, *options)
                    self.assertEqual(actual.returncode, 0, actual.stderr)
                    report = json.loads((out / "report.json").read_text())
                    self.assertEqual(report["schema_version"], 6)
                    self.assertEqual(report["policy"]["name"], "implementation")
                    self.assertEqual(report["summary"]["decision"], "INCOMPLETE")

    def test_single_strict_policy_still_uses_explicit_legacy_mode(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "task"
            source.mkdir()
            (source / "harbor_task").mkdir()
            actual = self.run_cli(source, base / "report", "--policy=strict")
            self.assertEqual(actual.returncode, 0, actual.stderr)
            report = json.loads((base / "report/report.json").read_text())
            self.assertEqual(report["policy"]["name"], "strict")
            self.assertEqual(report["schema_version"], 1)

    def test_input_boundary_distinguishes_zip_invalid_zip_unsupported_and_missing(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            self.assertEqual(AUDIT.inspect_source_kind(base), "directory")
            valid = base / "valid.zip"
            with zipfile.ZipFile(valid, "w") as archive:
                archive.writestr("instruction.md", "Synthetic input only")
            self.assertEqual(AUDIT.inspect_source_kind(valid), "zip")
            tar = base / "task.tar"
            tar.write_bytes(b"synthetic non-ZIP")
            with self.assertRaisesRegex(ValueError, "Unsupported input format.*directory or ZIP"):
                AUDIT.inspect_source_kind(tar)
            invalid = base / "broken.zip"
            invalid.write_bytes(b"PK broken")
            with self.assertRaisesRegex(ValueError, "Invalid or unreadable ZIP"):
                AUDIT.inspect_source_kind(invalid)
            with self.assertRaisesRegex(ValueError, "Input path does not exist"):
                AUDIT.inspect_source_kind(base / "missing")

    def test_unreadable_input_does_not_become_unsupported_format(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "input.zip"
            path.write_bytes(b"synthetic")
            with patch.object(Path, "open", side_effect=PermissionError("input access denied")):
                with self.assertRaisesRegex(PermissionError, "input access denied"):
                    AUDIT.inspect_source_kind(path)
            with patch.object(AUDIT.os, "scandir", side_effect=PermissionError("directory access denied")):
                with self.assertRaisesRegex(PermissionError, "directory access denied"):
                    AUDIT.inspect_source_kind(Path(temporary))

    def test_strict_unsupported_input_gives_actionable_boundary_without_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "task.tar.gz"
            source.write_bytes(b"synthetic non-ZIP")
            out = base / "report"
            actual = self.run_cli(source, out, "--policy", "strict")
            self.assertEqual(actual.returncode, 2)
            self.assertIn("Unsupported input format", actual.stderr)
            self.assertIn("Safely extract", actual.stderr)
            self.assertIn("extracted directory", actual.stderr)
            self.assertNotIn("does not exist", actual.stderr)
            self.assertFalse(out.exists())

    def test_strict_unsupported_zip_compression_fails_without_traceback_or_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            source = base / "unsupported-compression.zip"
            with zipfile.ZipFile(source, "w") as archive:
                archive.writestr("instruction.md", "Synthetic input only")
            raw = bytearray(source.read_bytes())
            for signature, offset in ((b"PK\x03\x04", 8), (b"PK\x01\x02", 10)):
                position = raw.index(signature) + offset
                raw[position:position + 2] = (99).to_bytes(2, "little")
            source.write_bytes(raw)
            out = base / "report"
            actual = self.run_cli(source, out, "--policy", "strict")
            self.assertEqual(actual.returncode, 2)
            self.assertIn("audit failed safely", actual.stderr)
            self.assertNotIn("Traceback", actual.stderr)
            self.assertFalse(out.exists())

    def test_markdown_report_has_21_item_verdict_table(self) -> None:
        checks = [
            {
                "id": f"QA{index:02d}",
                "title": f"check {index}",
                "status": "warn" if index == 1 else "pass",
                "severity": "high",
                "summary": f"reason {index}",
                "evidence": [f"file{index}:1"],
                "remediation": "fix",
            }
            for index in range(1, 22)
        ]
        report = {
            "summary": {
                "decision": "PRECHECK-PASS",
                "counts": {"pass": 20, "fail": 0, "warn": 1, "manual": 0},
                "blockers": 0,
            },
            "source": {"path": "/tmp/task.zip", "file_count": 1},
            "policy": {"name": "precheck", "adjustments": []},
            "checks": checks,
            "extra_checks": [],
            "assumptions": [],
            "limitations": [],
        }
        markdown = AUDIT.render_markdown(report)
        self.assertIn("## 质检清单逐项结论", markdown)
        self.assertIn("| 1 | QA01 | check 1 | ⚠️ 有条件通过 | reason 1 |", markdown)
        self.assertIn("| 21 | QA21 | check 21 | ✅ 通过 | reason 21 |", markdown)
        self.assertEqual(sum(f"| QA{index:02d} |" in markdown for index in range(1, 22)), 21)

    def test_checklist_verdict_is_strict_when_requested(self) -> None:
        self.assertEqual(AUDIT.checklist_verdict("warn", "precheck"), "⚠️ 有条件通过")
        self.assertEqual(AUDIT.checklist_verdict("warn", "strict"), "❌ 不通过")
        self.assertEqual(AUDIT.checklist_verdict("manual", "precheck"), "⏳ 待人工复核")

    def test_precheck_downgrades_content_and_compliance_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = AUDIT.directory_facts(root)
            auditor = AUDIT.Auditor(root, root, facts, policy="precheck")
            auditor.checks = [
                AUDIT.Check("QA01", "one", "fail", "high", "", [], ""),
                AUDIT.Check("QA07", "two", "fail", "blocker", "", [], ""),
                AUDIT.Check("QA11", "three", "pass", "high", "", [], ""),
            ]
            auditor.apply_policy()
            self.assertEqual(
                [item.status for item in auditor.checks],
                ["warn", "warn", "pass"],
            )
            self.assertEqual([item.severity for item in auditor.checks], ["high", "high", "high"])
            self.assertEqual(
                [item["id"] for item in auditor.policy_adjustments],
                ["QA01", "QA07"],
            )

    def test_precheck_preserves_unsafe_archive_failure(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = AUDIT.directory_facts(root)
            auditor = AUDIT.Auditor(root, root, facts, policy="precheck")
            auditor.extra = [
                AUDIT.Check("EX09", "archive", "fail", "blocker", "", [], ""),
            ]
            auditor.apply_policy()
            self.assertEqual(auditor.extra[0].status, "fail")
            self.assertEqual(auditor.extra[0].severity, "blocker")
            self.assertFalse(auditor.policy_adjustments)

    def test_strict_policy_preserves_failures(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            facts = AUDIT.directory_facts(root)
            auditor = AUDIT.Auditor(root, root, facts, policy="strict")
            auditor.checks = [
                AUDIT.Check("QA01", "one", "fail", "high", "", [], ""),
            ]
            auditor.apply_policy()
            self.assertEqual(auditor.checks[0].status, "fail")
            self.assertFalse(auditor.policy_adjustments)

    def test_simple_toml_fallback(self) -> None:
        parsed = AUDIT.parse_simple_toml(
            '[task]\nmetric_direction = "maximize"\ntime_limit_seconds = 7200\n'
            '[resources]\nnetwork_access = false\ngpu_count = 1\n'
        )
        self.assertEqual(parsed["task"]["metric_direction"], "maximize")
        self.assertEqual(parsed["task"]["time_limit_seconds"], 7200)
        self.assertFalse(parsed["resources"]["network_access"])

    def test_simple_toml_fallback_tolerates_multiline_values(self) -> None:
        parsed = AUDIT.parse_simple_toml(
            '[task]\nname = "demo"\ndescription = """line one \\\n+line two"""\n'
            '[entrypoint]\ngrader_script = "tests/grader.py"\n'
            '[scoring]\ndeterministic = true\n'
            '[protected]\npaths = [\n  "grade.py",\n  "model/",\n]\n'
        )
        self.assertEqual(parsed["entrypoint"]["grader_script"], "tests/grader.py")
        self.assertTrue(parsed["scoring"]["deterministic"])
        self.assertEqual(parsed["protected"]["paths"], ["grade.py", "model/"])

    def test_zip_path_traversal_is_rejected_before_extraction(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            base = Path(temporary)
            archive_path = base / "bad.zip"
            destination = base / "out"
            destination.mkdir()
            with zipfile.ZipFile(archive_path, "w") as archive:
                archive.writestr("../escape.txt", "unsafe")
            facts = AUDIT.safe_extract_zip(archive_path, destination)
            self.assertTrue(facts.unsafe_entries)
            self.assertFalse((base / "escape.txt").exists())

    def test_unflagged_utf8_zip_filename_is_recovered(self) -> None:
        expected = "训练证据说明.md"
        info = zipfile.ZipInfo(expected.encode("utf-8").decode("cp437"))
        info.flag_bits = 0
        self.assertEqual(AUDIT.decoded_zip_name(info), expected)

    def test_workspace_location_ignores_macos_metadata_tree(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            real_workspace = root / "workspace"
            (real_workspace / "harbor_task").mkdir(parents=True)
            (root / "__MACOSX" / "workspace" / "harbor_task").mkdir(parents=True)
            self.assertEqual(AUDIT.locate_workspace(root), real_workspace)

    def test_formal_trajectory_jsonl(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            path = root / "expert_evidence" / "trajectory.json"
            path.parent.mkdir(parents=True)
            records = [
                {
                    "trial": trial,
                    "method": "baseline" if trial == 0 else "candidate",
                    "status": "ok",
                    "score": float(trial),
                    "score_direction": "maximize",
                    "score_metric": "normalized_hidden_score",
                    "failure_reason": None,
                }
                for trial in range(2)
            ]
            path.write_text(
                "".join(json.dumps(record) + "\n" for record in records),
                encoding="utf-8",
            )
            facts = AUDIT.directory_facts(root)
            auditor = AUDIT.Auditor(root, root, facts)
            valid, note = auditor.validate_trajectory("expert_evidence/trajectory.json")
            self.assertTrue(valid, note)


if __name__ == "__main__":
    unittest.main()
