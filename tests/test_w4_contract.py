"""W4 synthetic contracts; no GPU, Docker, API calls, or real QA skill execution."""
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoresearch_flow.core import FlowError, Registry, TaskStore, _canonical_digest, _sha256
from autoresearch_flow.runtime import Runtime
from autoresearch_flow.w4_evidence import DeliveryEvidence
from autoresearch_flow.w4_package import DeliveryPackage, check_package
from test_pca_contract import round_record
from test_qa_contract import synthetic_report


class DeliveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-w4-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        TaskStore(self.root).initialize(Registry(), "synthetic")
        self.ev = DeliveryEvidence(self.root)
        self.package = DeliveryPackage(self.root)
        self.runtime = Runtime(self.root)
        for track, summary, method in (("codex", "改变更新规则", "codex"), ("seed", "改变参数分组", "seed")):
            output = self.runtime.directory / track / "formal" / "output"
            (output / "best_method").mkdir(parents=True)
            (output / "trajectory.jsonl").write_text(
                json.dumps(round_record(summary=summary), ensure_ascii=False) + "\n", encoding="utf-8")
            (output / "best_method" / "method.py").write_text(f"# {method}\n", encoding="utf-8")
            log = self.runtime.directory / track / "logs" / "segment-1" / "events.jsonl"
            log.parent.mkdir(parents=True)
            log.write_text(json.dumps({"method": summary, "score": 0.4}) + "\n")
        self.status_patch = patch.object(Runtime, "status", side_effect=lambda track: {
            "active": None, "thread_id": f"thread-{track}", "effective_seconds_before_content_review": 37800})
        self.state_patch = patch.object(Runtime, "_state", side_effect=lambda track: {
            "segments": [{"segment_id": "segment-1", "phase": "formal"}]})
        self.status_patch.start()
        self.state_patch.start()
        self.addCleanup(self.status_patch.stop)
        self.addCleanup(self.state_patch.stop)

    def ref(self, path):
        path = Path(path)
        return {"path": str(path.relative_to(self.root)), "sha256": _sha256(path)}

    def prepare_trajectories(self):
        for track in ("codex", "seed"):
            self.ev.finalize_trajectory(track)
            log = self.runtime.directory / track / "logs" / "segment-1" / "events.jsonl"
            self.ev.review_trajectory(track, {"reviewer": "expert", "rounds": [
                {"round": 1, "consistent": True, "evidence": [{"ref": self.ref(log), "locator": "line 1"}]}]})

    def prepare_best(self):
        self.prepare_trajectories()
        c = self.root / "codex-result.json"
        s = self.root / "seed-result.json"
        c.write_text(json.dumps({"status": "succeeded", "score": 0.4}))
        s.write_text(json.dumps({"status": "succeeded", "score": 0.5}))
        snapshot = self.ev.snapshot_best({"selected_track": "seed", "rationale": "同口径较高",
            "candidate_results": {"codex": {"result": self.ref(c)}, "seed": {"result": self.ref(s)}}})
        method_hash = _canonical_digest(sorted(snapshot["method_files"], key=lambda x: x["path"]))
        clean = self.root / "clean.json"
        clean.write_text(json.dumps({"status": "succeeded", "score": 0.5,
            "method_sha256": method_hash, "execution": {"exit_code": 0, "command": ["evaluate"],
            "started_at": "t1", "finished_at": "t2"}}))
        log = self.root / "clean.log"
        log.write_text("clean rerun passed\n")
        best_report = {"status": "ok", "protocol_sha256": "p", "experiment_sha256": "e-best",
                       "groups": {"best_method": {"method_sha256": method_hash, "mean": 0.5}}}
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", return_value=best_report):
            self.ev.verify_best({"protocol_id": "p1", "clean_result": self.ref(clean), "clean_log": self.ref(log),
                                 "reviewer": "expert", "rationale": "干净快照真实重跑"})
        return best_report

    def prepare_package_sources(self):
        workspace = self.root / "draft-workspace"
        (workspace / "harbor_task").mkdir(parents=True)
        (workspace / "reference").mkdir()
        (workspace / "harbor_task" / "environment").mkdir()
        (workspace / "harbor_task" / "tests").mkdir()
        (workspace / "harbor_task" / "solution").mkdir()
        (workspace / "harbor_task" / "instruction.md").write_text("synthetic instruction\n")
        (workspace / "harbor_task" / "environment" / "Dockerfile").write_text("FROM scratch\n")
        (workspace / "harbor_task" / "environment" / "starter").mkdir()
        (workspace / "harbor_task" / "environment" / "starter" / "method.py").write_text("# starter\n")
        (workspace / "harbor_task" / "tests" / "Dockerfile").write_text("FROM scratch\n")
        (workspace / "harbor_task" / "tests" / "test.sh").write_text("#!/bin/sh\npython /tests/grader.py\n")
        (workspace / "harbor_task" / "tests" / "grader.py").write_text("# synthetic\n")
        (workspace / "harbor_task" / "task.toml").write_text('artifacts = ["/workspace/solution"]\n[environment]\n[agent]\n[verifier]\nenvironment_mode = "separate"\n[verifier.environment]\n')
        (workspace / "reference" / "method.py").write_text("# reference\n")
        (workspace / "agent-view.txt").write_text("SYNTHETIC fixture: not real image evidence\\n")
        (workspace / "qa_exposure_manifest.json").write_text(json.dumps({
            "schema_version": 1,
            "agent_visible_paths": ["harbor_task/instruction.md", "harbor_task/environment/starter"],
            "agent_writable_paths": ["/workspace/solution"],
            "trusted_only_paths": ["harbor_task/tests", "reference"],
            "final_image_digest": "sha256:" + "a" * 64,
            "verifier_image_digest": "sha256:" + "b" * 64,
            "generated_agent_view_manifest": "agent-view.txt", "verified_as_uid": 1000}))
        opt = self.root / "draft-optimization"
        for role in ("baseline", "reference"):
            for seed in (1, 2, 3):
                directory = opt / f"{role}_runs" / f"seed_{seed}"
                (directory / "model").mkdir(parents=True)
                (directory / "result.json").write_text(json.dumps({"seed": seed, "metric": 0.1}))
                (directory / "run.log").write_text("training done\n")
                (directory / "model" / "weights.bin").write_bytes(b"model")
        (opt / "训练证据说明.md").write_text("正式三种子训练证据\n")
        (opt / "comparison_summary.json").write_text(json.dumps({"baseline_mean": 0.1, "reference_mean": 0.2}))
        doc = self.root / "专家作业说明文档.md"
        doc.write_text("合成题目、评分与隔离说明\n")
        annotation = self.root / "annotation.json"
        annotation.write_text(json.dumps({"task_id": "synthetic", "task_type": "S2",
            "research_direction": "synthetic", "optimization_surface": "optimizer rule",
            "score_contract": {"metric": "accuracy", "direction": "maximize", "split": "dev",
                "protocol": "p1", "baseline": {"raw_value": 0.1, "normalized_score": 0.0},
                "reference": {"raw_value": 0.2, "normalized_score": 0.5},
                "upper_bound": {"raw_value": 0.3, "source": "estimated_attainable_upper_bound"}},
            "isolation": {"reference_visible_to_agent": False, "hidden_assets_visible_to_agent": False}}))
        summary = self.root / "summary.json"
        summary.write_text(json.dumps({"task_id": "synthetic", "status": "pilot_required", "image": "synthetic:1",
            "agent_execution": [{"runtime": "Codex", "model": model, "duration_hours": 10.5,
                "effective_rounds": 1, "typical_round_minutes": 30} for model in ("GPT", "Seed")],
            "fast_iteration_exception": {"used": False, "non_training": None, "short_iterations": None, "rollable_proved": False, "evidence": ""},
            "validation": {"baseline_passed": True, "reference_passed": True,
                "optimization_evidence_complete": True, "best_method_rerun_passed": True}}))
        return {"protocol_id": "p1", "workspace_directory": str(workspace.relative_to(self.root)),
                "optimization_directory": str(opt.relative_to(self.root)),
                "expert_document": self.ref(doc), "expert_annotation": self.ref(annotation),
                "run_summary": self.ref(summary)}

    def test_support_paths_cannot_overwrite_or_escape(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        ref = spec['expert_document']
        for dest in ('.', '../x', 'raw/./log.txt', 'best_method/x'):
            spec['support_files'] = [{'source': ref, 'destination': dest}]
            with patch('autoresearch_flow.w4_evidence.ExperimentBook.report', side_effect=self.reports(best)), \
                 patch('autoresearch_flow.w4_package.ExperimentBook.report', side_effect=self.reports(best)):
                with self.assertRaises(FlowError): self.package.build(spec)

    def reports(self, best_report):
        def report(protocol, roles=("baseline", "reference")):
            if roles == ("best_method",):
                return best_report
            attempts, refs = [], {}
            for role in ("baseline", "reference"):
                for seed in (1, 2, 3):
                    run_id = f"{role}-{seed}"
                    attempts.append({"run_id": run_id, "role": role, "seed": seed,
                                     "status": "succeeded", "retry_of": None})
                    refs[run_id] = self.ref(self.root / "draft-optimization" /
                                            f"{role}_runs" / f"seed_{seed}" / "result.json")
            return {"status": "ok", "experiment_sha256": "e-br", "seeds": [1, 2, 3],
                    "evaluation_protocol": {"training": True, "evaluation_mode": "random", "high_variance": False, "seeds": [1, 2, 3]},
                    "attempts": attempts, "source_results": refs,
                    "groups": {"baseline": {"mean": 0.1}, "reference": {"mean": 0.2}}}
        return report

    def test_agent_jsonl_is_only_trajectory_source_and_requires_review(self):
        (self.runtime.directory / "codex" / "formal" / "output" / "trajectory.jsonl").unlink()
        with self.assertRaises(FlowError) as caught:
            self.ev.finalize_trajectory("codex")
        self.assertEqual(caught.exception.code, "TRAJECTORY_MISSING")
        self.ev.finalize_trajectory("seed")
        with self.assertRaises(FlowError):
            self.ev.current_review("seed")

    def test_correction_retains_original_and_hash(self):
        source = self.runtime.directory / "seed" / "formal" / "output" / "trajectory.jsonl"
        raw = source.read_bytes()
        log = self.runtime.directory / "seed" / "logs" / "segment-1" / "events.jsonl"
        result = self.ev.finalize_trajectory("seed", {"source_sha256": _sha256(source), "corrections": [{
            "line": 1, "raw_sha256": __import__("hashlib").sha256(raw.splitlines()[0]).hexdigest(),
            "replacement": round_record(summary="修正后的准确表述"),
            "reason": "纠正措辞", "evidence": [self.ref(log)]}]})
        version = self.ev.directory / "trajectories" / "seed" / result["version"]
        self.assertEqual((version / "source.jsonl").read_bytes(), raw)
        self.assertEqual(json.loads((version / "final.json").read_text())["rounds"][0]["method_summary"], "修正后的准确表述")

    def test_package_boundary_archive_and_old_qa_binding(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", side_effect=self.reports(best)), \
             patch("autoresearch_flow.w4_package.ExperimentBook.report", side_effect=self.reports(best)):
            built = self.package.build(spec)
        self.assertEqual(built["status"], "format_checked_not_qa")
        package_root = Path(built["package_path"])
        self.assertEqual({p.name for p in package_root.iterdir()}, {"workspace", "expert_evidence", "optimization_evidence"})
        self.assertFalse((package_root / "expert_evidence" / "best_method" / "selection.json").exists())
        self.assertEqual(check_package(package_root)["package_sha256"], built["package_sha256"])
        cli = subprocess.run([sys.executable, str(Path(__file__).resolve().parents[1] / "cli.py"),
                              "--format", "json", "delivery", "check", "--package-root", str(package_root)],
                             capture_output=True, text=True)
        self.assertEqual(cli.returncode, 0, cli.stderr)
        self.assertEqual(json.loads(cli.stdout)["status"], "format_checked_not_qa")
        archive1 = self.package.archive(package_root, max_part_bytes=100)
        archive2 = self.package.archive(package_root, max_part_bytes=100)
        self.assertEqual(archive1["archive_sha256"], archive2["archive_sha256"])
        self.assertTrue(archive1["parts"])
        self.assertEqual(b"".join(Path(part["path"]).read_bytes() for part in archive1["parts"]),
                         Path(archive1["archive"]).read_bytes())
        with zipfile.ZipFile(archive1["archive"]) as zipped:
            self.assertIn("expert_evidence/专家作业说明文档.md", zipped.namelist())
        handoff = self.package.qa_handoff(package_root)
        self.assertEqual(handoff["status"], "awaiting_independent_qa")
        report = self.root / "report.json"
        report.write_text(json.dumps(synthetic_report(package_root)))
        self.assertEqual(self.package.qa_bind(package_root, report)["status"], "attached_unreviewed")
        (package_root / "expert_evidence" / "专家作业说明文档.md").write_text("changed\n")
        with self.assertRaises(FlowError) as caught:
            self.package.qa_bind(package_root, report)
        self.assertEqual(caught.exception.code, "QA_PACKAGE_DRIFT")

    def test_package_rejects_unlinked_br_results(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        normal_report = self.reports(best)
        wrong = self.root / "wrong-result.json"
        wrong.write_text('{"seed":1,"metric":999}')

        def mismatched(protocol, roles=("baseline", "reference")):
            result = normal_report(protocol, roles)
            if roles != ("best_method",):
                result["source_results"]["baseline-1"] = self.ref(wrong)
            return result

        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", side_effect=mismatched), \
             patch("autoresearch_flow.w4_package.ExperimentBook.report", side_effect=mismatched):
            with self.assertRaises(FlowError) as caught:
                self.package.build(spec)
        self.assertEqual(caught.exception.code, "BR_PACKAGE_MISMATCH")

    def test_nontraining_deterministic_package_has_no_fake_model_requirement(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        # Reuse a built fixture; this change is confined to a temporary synthetic package.
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", side_effect=self.reports(best)):
            built = self.package.build(spec)
        root = Path(built["package_path"])
        comparison = root / "optimization_evidence" / "comparison_summary.json"
        value = json.loads(comparison.read_text())
        value["evaluation_protocol"] = {"training": False, "evaluation_mode": "deterministic",
                                        "high_variance": False, "seeds": [1]}
        comparison.write_text(json.dumps(value))
        for role in ("baseline", "reference"):
            runs = root / "optimization_evidence" / f"{role}_runs"
            shutil.rmtree(runs / "seed_2")
            shutil.rmtree(runs / "seed_3")
            shutil.rmtree(runs / "seed_1" / "model")
        self.assertEqual(check_package(root)["formal_seed_count"], 1)
        value["evaluation_protocol"]["evaluation_mode"] = "random"
        comparison.write_text(json.dumps(value))
        with self.assertRaises(FlowError):
            check_package(root)

    def test_training_package_still_requires_models(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", side_effect=self.reports(best)):
            built = self.package.build(spec)
        root = Path(built["package_path"])
        shutil.rmtree(root / "optimization_evidence" / "baseline_runs" / "seed_1" / "model")
        with self.assertRaises(FlowError) as caught:
            check_package(root)
        self.assertEqual(caught.exception.code, "OPT_SCHEMA")

    def test_extras_allowed_but_missing_or_exposed_private_assets_rejected(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", side_effect=self.reports(best)):
            root = Path(self.package.build(spec)["package_path"])
        (root / "additional-note.md").write_text("Useful synthetic support.")
        checked = check_package(root)
        self.assertEqual(checked["format_observations"][0]["classification"], "extra_allowed")
        manifest = root / "workspace/qa_exposure_manifest.json"
        data = json.loads(manifest.read_text())
        data["agent_visible_paths"].append("harbor_task")
        manifest.write_text(json.dumps(data))
        with self.assertRaises(FlowError) as caught: check_package(root)
        self.assertEqual(caught.exception.code, "EXPOSURE_OVERLAP")
        manifest.unlink()
        with self.assertRaises(FlowError) as caught: check_package(root)
        self.assertEqual(caught.exception.code, "EXPOSURE_MISSING")

    def test_qa_report_must_be_outside_package_and_current_schema(self):
        best = self.prepare_best()
        spec = self.prepare_package_sources()
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", side_effect=self.reports(best)):
            root = Path(self.package.build(spec)["package_path"])
        inside = root / "expert_evidence/report.json"
        inside.write_text(json.dumps(synthetic_report(root)))
        self.package.qa_handoff(root)
        with self.assertRaises(FlowError) as caught: self.package.qa_bind(root, inside)
        self.assertEqual(caught.exception.code, "QA_REPORT_BOUNDARY")
        outside = self.root / "old-report.json"
        outside.write_text(json.dumps({"source": {"path": str(root)}, "schema_version": 3}))
        with self.assertRaises(FlowError) as caught: self.package.qa_bind(root, outside)
        self.assertEqual(caught.exception.code, "QA_REPORT_SCHEMA")

    def test_missing_package_path_reports_flow_error(self):
        with self.assertRaises(FlowError) as caught:
            check_package(self.root / "does-not-exist")
        self.assertEqual(caught.exception.code, "PACKAGE_MISSING")


if __name__ == "__main__":
    unittest.main()
