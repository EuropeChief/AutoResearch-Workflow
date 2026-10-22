"""Synthetic original-v0.3.10 integration tests; never run submitted programs."""
import copy
import json
from pathlib import Path
import tempfile
import unittest

import implementation_review as qa
import legacy_migration_waiver as waiver
import task_fingerprint as fp
import test_implementation_review as fixtures


class LegacyMigrationWaiverTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ImplementationReviewTests()
        self.fixture.setUp()
        self.root = self.fixture.root.resolve()
        self.review = self.fixture.review()
        waiver.by_id(self.review["checks"], "QA17").update(
            remediation="Resolve the identified Harbor child finding.",
            acceptance_evidence="Reviewed current format and appropriate existing evidence.")
        self.rebuild()

    def tearDown(self):
        self.fixture.tearDown()

    def rebuild(self):
        self.report = qa.apply_review(qa.build_report(self.root, self.root, qa.inventory(self.root)), copy.deepcopy(self.review), self.root)

    def sync_bindings(self):
        path = self.root / "expert_evidence/run_summary.json"
        data = json.loads(path.read_text())
        digest = fp.fingerprint(self.root)["task_content_sha256"]
        for index, item in enumerate(data["agent_execution"]):
            binding = item["task_binding"]
            binding["task_content_sha256"] = digest
            binding["trajectory_sha256"] = fp.sha256_file(self.root / self.review["overview"]["trajectories"][index]["source_path"])
        path.write_text(json.dumps(data))

    def gpu_gap(self, types='["H20"]', comparison="unverified"):
        with (self.root / "task.toml").open("a") as stream:
            stream.write('\n[environment]\ngpus=1\ngpu_types=' + types + '\n')
        resources = self.review["resource_review"]
        resources["hardware_review"].update(task_type="gpu", score_comparability=comparison, affects_formal_scores=True)
        for row in resources["runs"]:
            row.update(gpu_count=1, gpu_type="H20")
        self.sync_bindings()
        self.rebuild()

    def no_nop(self):
        for target in ("H05", "H06"):
            row = waiver.by_id(self.review["harbor"]["checks"], target)
            row.update(status="not_applicable", summary="The legacy standard did not require this Trial record.", evidence=[])
        self.rebuild()

    def old_round_schema(self):
        for index in range(2):
            path = self.root / self.review["overview"]["trajectories"][index]["source_path"]
            path.write_text(json.dumps({"duration_seconds": 43200, "rounds": [{"round": 1, "method_summary": "Historical method description."}]}))
        self.sync_bindings()
        self.rebuild()

    def manual_qa(self, target, summary="Only new proof is missing."):
        row = waiver.by_id(self.review["checks"], target)
        row.update(status="manual", summary=summary, remediation="Review the newly introduced proof requirement.", acceptance_evidence="Existing legacy materials and migration review.")

    def manifest(self, targets):
        ledger = waiver.collect_findings(self.report, self.review, self.root)
        result = {"schema_version": 2, "profile": waiver.PROFILE, "enabled": True, "reviewer": "synthetic auditor",
                  "strict_report_sha256": "report-sha", "review_sha256": "review-sha",
                  "reviewer_context": {**{key: True for key in waiver.CONTEXT_ASSERTIONS},
                      "summary": "Synthetic previously accepted legacy task; format/config migration only in requested scopes.",
                      "evidence": ["instruction.md"]}, "requests": []}
        for target, codes in targets.items():
            row = waiver.target_row(self.report, target)
            protected = {**{key: True for key in waiver.PROTECTED_ASSERTIONS}, "other_substantive_causes": [],
                         "network_change_is_platform_migration_only": True, "no_confirmed_historical_score_contamination": True,
                         "complete_build_materials_present": True, "platform_internal_image_work_pending": True,
                         "current_trial_not_legacy_requirement": True, "no_confirmed_failed_trial": True,
                         "historical_runs_genuinely_independent": True, "target_selection_is_h20_l20": True,
                         "no_other_gpu_selected": True}
            request = {"target": target, "original_status": row["status"], "summary_sha256": waiver.summary_sha256(row),
                       "all_blocking_reasons_covered": True, "protected_review": protected,
                       "causes": [{"code": code, "summary": "Synthetic newly introduced migration requirement only.", "evidence": ["instruction.md"]} for code in codes],
                       "coverage": [], "gpu_selection_review": {"selected_gpu_type": "H20", "summary": "Existing platform selection agreement.", "evidence": ["task.toml"]},
                       "metadata_gaps": [{"requirement": "max_reasoning_level_record", "state": "missing_evidence_only", "legacy_required": False,
                           "summary": "Legacy run did not have the newly required reasoning-level proof.", "evidence": ["expert_evidence/run_summary.json"]}]}
            for item in ledger:
                if target not in item["owners"]:
                    continue
                code = next((code for code in codes if code in item["eligible_causes"]), codes[0])
                request["coverage"].append({"key": item["key"], "status": item["status"], "summary_sha256": item["summary_sha256"],
                    "cause": code, "summary": "Synthetic per-atom migration causality checked.", "evidence": ["instruction.md"]})
            result["requests"].append(request)
        return result

    def assess(self, manifest=None, trusted=True):
        return waiver.assess(self.report, self.review, manifest, self.root, "report-sha", "review-sha", worksheet_outside_artifact=trusted)

    def test_disabled_keeps_original_pass(self):
        result = self.assess()
        self.assertEqual(result["decision"], "PASS")
        self.assertFalse(result["waiver_applied"])

    def test_legacy_without_nop_is_eligible_without_snapshot_or_hash(self):
        self.no_nop()
        result = self.assess(self.manifest({"H06": ["new_current_trial_requirement"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertFalse(result["this_run_executed_harbor"])
        self.assertTrue(any(item["cause"] == "new_current_trial_requirement" for item in result["platform_followup_pending"]))

    def test_legacy_two_field_round_schema_can_be_waived(self):
        self.old_round_schema()
        result = self.assess(self.manifest({"QA18": ["new_trajectory_schema_gap"], "QA21": ["new_trajectory_schema_gap"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_missing_old_method_summary_cannot_be_waived(self):
        self.old_round_schema()
        path = self.root / "trajectory_a.json"
        data = json.loads(path.read_text())
        del data["rounds"][0]["method_summary"]
        path.write_text(json.dumps(data))
        self.sync_bindings()
        self.rebuild()
        result = self.assess(self.manifest({"QA18": ["new_trajectory_schema_gap"], "QA21": ["new_trajectory_schema_gap"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_missing_new_task_binding_is_eligible(self):
        (self.root / "expert_evidence/run_summary.json").write_text('{"agent_execution": []}')
        self.rebuild()
        result = self.assess(self.manifest({"QA21": ["new_task_binding_requirement"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_corrupt_existing_binding_json_is_not_new_hash_gap(self):
        (self.root / "expert_evidence/run_summary.json").write_text('{"broken":')
        self.rebuild()
        result = self.assess(self.manifest({"QA15": ["new_resource_evidence_gap"], "QA21": ["new_task_binding_requirement"]}))
        self.assertNotEqual(result["decision"], "PASS_WITH_WAIVERS")
        self.assertFalse(any(item["target"] == "QA21" for item in result["accepted"]))

    def test_new_resource_evidence_gap_no_new_measurement_required(self):
        self.review["resource_review"].pop("runs")
        self.rebuild()
        result = self.assess(self.manifest({"QA15": ["new_resource_evidence_gap"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_actual_gpu_record_gap_can_be_waived(self):
        self.gpu_gap()
        result = self.assess(self.manifest({target: ["target_gpu_record_gap"] for target in ("G03", "QA03", "QA13", "QA15")}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_no_gpu_gap_cannot_use_gpu_cause(self):
        self.manual_qa("QA13")
        self.rebuild()
        result = self.assess(self.manifest({"QA13": ["target_gpu_record_gap"]}))
        self.assertEqual(result["decision"], "INCOMPLETE")
        self.assertFalse(result["accepted"])

    def test_original_semantic_failure_remains_even_if_another_scope_is_waived(self):
        self.no_nop()
        row = waiver.by_id(self.review["checks"], "QA18")
        row.update(status="fail", summary="Confirmed Hidden access invalidated the Agent run.", remediation="Repair invalid run.", acceptance_evidence="Valid independent evidence.")
        self.rebuild()
        result = self.assess(self.manifest({"QA18": ["new_trajectory_schema_gap"], "H06": ["new_current_trial_requirement"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(any(item["target"] == "QA18" for item in result["accepted"]))
        self.assertTrue(any(item["target"] == "H06" for item in result["accepted"]))

    def test_g03_bad_numbers_cannot_be_migration(self):
        self.gpu_gap()
        comparison = self.review["overview"]["baseline_reference"]
        for row in comparison["paired_runs"]:
            row["reference"] = row["baseline"]
        comparison.update(reference_mean=10.0)
        self.rebuild()
        result = self.assess(self.manifest({"G03": ["target_gpu_record_gap"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_network_after_policy_removal_can_be_waived_without_new_guard_or_run(self):
        self.review["harbor"]["capability_review"]["outcome"] = "network_fallback"
        self.rebuild()
        result = self.assess(self.manifest({"QA05": ["unsupported_network_policy_transition"], "H02": ["unsupported_network_policy_transition"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertTrue(any(item["cause"] == "unsupported_network_policy_transition" for item in result["platform_followup_pending"]))

    def test_current_unsupported_network_field_still_needs_format_repair(self):
        with (self.root / "task.toml").open("a") as stream:
            stream.write('\n[environment]\nnetwork_mode="no-network"\n')
        self.sync_bindings()
        self.rebuild()
        result = self.assess(self.manifest({"QA05": ["unsupported_network_policy_transition"], "H02": ["unsupported_network_policy_transition"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_current_compose_cannot_be_hidden_by_image_waiver(self):
        (self.root / "environment/compose.yaml").write_text('services: {}\n')
        self.sync_bindings()
        self.rebuild()
        result = self.assess(self.manifest({"H03": ["internal_image_preparation_pending"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_internal_image_only_manual_gap_with_build_source(self):
        row = waiver.by_id(self.review["harbor"]["checks"], "H03")
        row.update(status="manual", summary="Internal image preparation and actual image selection pending.")
        parent = waiver.by_id(self.review["checks"], "QA17")
        parent.update(remediation="Platform prepares the internal image.", acceptance_evidence="Current platform image and Trial later.")
        self.rebuild()
        result = self.assess(self.manifest({"H03": ["internal_image_preparation_pending"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_copy_source_missing_is_not_an_internal_image_gap(self):
        (self.root / "environment/Dockerfile").write_text('FROM python:3.11\nCOPY absent_file /app/absent_file\n')
        self.sync_bindings()
        self.rebuild()
        result = self.assess(self.manifest({"H03": ["internal_image_preparation_pending"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_current_target_estimate_over_limit_is_not_new_evidence_gap(self):
        resources = self.review["resource_review"]
        resources["estimate"] = {**resources["runs"][0], "score_seconds": 9000,
                                 "basis": "Explicit current CPU target estimate, not an old GPU observation."}
        self.rebuild()
        result = self.assess(self.manifest({"QA15": ["new_resource_evidence_gap"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])
        self.assertTrue(any(item["key"] == "resource/current_target_estimate/score_seconds" for item in result["remaining_findings"]))

    def test_historical_other_gpu_observation_is_not_assumed_current_target_excess(self):
        self.gpu_gap()
        resources = self.review["resource_review"]
        resources["estimate"] = {**resources["runs"][0], "gpu_type": "RTX4090", "score_seconds": 9000,
                                 "basis": "Historical RTX4090 observation; no target-card rerun claimed."}
        self.rebuild()
        result = self.assess(self.manifest({target: ["target_gpu_record_gap"] for target in ("G03", "QA03", "QA13", "QA15")}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_valid_prebuilt_source_image_does_not_require_new_dockerfile(self):
        (self.root / "environment/Dockerfile").unlink()
        with (self.root / "task.toml").open("a") as stream:
            stream.write('\n[environment]\ndocker_image="registry.example.test/project/source:v4"\n')
        self.review["harbor"]["checks"][2].update(status="manual", summary="Source image exists; internal import and selection pending.", evidence=["task.toml", "tests/Dockerfile"])
        self.sync_bindings()
        self.rebuild()
        manifest = self.manifest({"H03": ["internal_image_preparation_pending"]})
        request = manifest["requests"][0]
        request["protected_review"]["valid_prebuilt_source_image_present"] = True
        request["source_image_review"] = {"source_image": "registry.example.test/project/source:v4",
            "summary": "Existing reproducible source image, dependencies and assets were manually reviewed; internal import remains pending.", "evidence": ["task.toml", "instruction.md"]}
        result = self.assess(manifest)
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_new_platform_validation_dependency_uses_passing_old_numerics(self):
        self.no_nop()
        for target in ("QA03", "QA13"):
            self.manual_qa(target, "Old numerical evidence passes; new platform applicability is pending.")
        gate = waiver.by_id(self.review["content_gates"]["checks"], "G03")
        gate.update(status="manual", reason_code="NEW_PLATFORM_PENDING", summary="Old protocol is valid; new platform applicability needs later validation.",
                    remediation="Platform validates later.", acceptance_evidence="Existing old evidence and later platform validation.")
        self.rebuild()
        targets = {target: ["new_standard_validation_dependency"] for target in ("G03", "QA03", "QA13")}
        targets["H06"] = ["new_current_trial_requirement"]
        result = self.assess(self.manifest(targets))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_new_run_metadata_missing_proof_is_eligible(self):
        self.manual_qa("QA18")
        self.manual_qa("QA21")
        self.rebuild()
        result = self.assess(self.manifest({target: ["new_trajectory_run_metadata_gap"] for target in ("QA18", "QA21")}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_true_non_independent_runs_are_not_metadata_gap(self):
        row = waiver.by_id(self.review["checks"], "QA18")
        row.update(status="fail", summary="Two reports are copies of one actual run.", remediation="Repair genuine independence.", acceptance_evidence="Independent actual runs.")
        self.rebuild()
        result = self.assess(self.manifest({"QA18": ["new_trajectory_run_metadata_gap"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_mixed_gpu_candidates_with_h20_selection_are_compatible(self):
        self.gpu_gap(types='["H20", "RTX4090"]', comparison="same_hardware")
        result = self.assess(self.manifest({"H02": ["gpu_candidate_list_compatibility"], "QA15": ["gpu_candidate_list_compatibility"]}))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)

    def test_only_unsupported_gpu_or_selected_other_gpu_is_not_compatible(self):
        self.gpu_gap(types='["RTX4090"]', comparison="same_hardware")
        result = self.assess(self.manifest({"H02": ["gpu_candidate_list_compatibility"], "QA15": ["gpu_candidate_list_compatibility"]}))
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_selected_other_gpu_is_not_compatible(self):
        self.gpu_gap(types='["H20", "RTX4090"]', comparison="same_hardware")
        manifest = self.manifest({"H02": ["gpu_candidate_list_compatibility"], "QA15": ["gpu_candidate_list_compatibility"]})
        for request in manifest["requests"]:
            request["gpu_selection_review"]["selected_gpu_type"] = "RTX4090"
        result = self.assess(manifest)
        self.assertEqual(result["decision"], "FAIL")
        self.assertFalse(result["accepted"])

    def test_no_new_schema_gap_cannot_hide_manual_reason(self):
        self.manual_qa("QA18", "Some unrelated original review is unfinished.")
        self.rebuild()
        result = self.assess(self.manifest({"QA18": ["new_trajectory_schema_gap"]}))
        self.assertEqual(result["decision"], "INCOMPLETE")
        self.assertFalse(result["accepted"])

    def test_worksheet_must_be_outside_submission(self):
        self.no_nop()
        result = self.assess(self.manifest({"H06": ["new_current_trial_requirement"]}), trusted=False)
        self.assertFalse(result["accepted"])
        self.assertTrue(any("outside" in item["reason"] for item in result["rejected"]))

    def test_stale_report_review_and_atom_bindings_are_not_accepted(self):
        self.no_nop()
        for field in ("strict_report_sha256", "review_sha256", "atom"):
            with self.subTest(field=field):
                manifest = self.manifest({"H06": ["new_current_trial_requirement"]})
                if field == "atom":
                    manifest["requests"][0]["coverage"][0]["summary_sha256"] = "stale"
                else:
                    manifest[field] = "stale"
                self.assertFalse(self.assess(manifest)["accepted"])

    def test_coverage_cannot_skip_a_compound_atom(self):
        self.no_nop()
        manifest = self.manifest({"H06": ["new_current_trial_requirement"]})
        manifest["requests"][0]["coverage"] = []
        self.assertFalse(self.assess(manifest)["accepted"])

    def test_extra_substantive_cause_keeps_original_failure(self):
        self.no_nop()
        manifest = self.manifest({"H06": ["new_current_trial_requirement"]})
        manifest["requests"][0]["protected_review"]["other_substantive_causes"] = ["Actual grading exception remains."]
        self.assertFalse(self.assess(manifest)["accepted"])

    def test_whole_qa17_request_is_forbidden(self):
        self.no_nop()
        result = self.assess(self.manifest({"QA17": ["new_current_trial_requirement"]}))
        self.assertFalse(result["accepted"])
        self.assertTrue(any("derived" in item["reason"] for item in result["rejected"]))

    def test_remaining_original_repair_and_acceptance_are_faithful(self):
        self.no_nop()
        row = waiver.by_id(self.review["checks"], "QA01")
        row.update(status="fail", summary="Allowed Scope is incomplete.", remediation="Complete editable-file boundaries.", acceptance_evidence="Actual stated scope and frozen scoring files.")
        self.rebuild()
        result = self.assess(self.manifest({"H06": ["new_current_trial_requirement"]}))
        self.assertEqual(result["decision"], "FAIL")
        text = waiver.render(result)
        self.assertIn(row["remediation"], text)
        self.assertIn(row["acceptance_evidence"], text)
        self.assertTrue(any(item["target"] == "H06" for item in result["accepted"]))

    def test_forged_report_is_incomplete(self):
        self.report["checks"][0]["summary"] = "Altered after strict review."
        result = self.assess()
        self.assertEqual(result["decision"], "INCOMPLETE")
        self.assertTrue(result["integrity_issues"])

    def test_template_does_not_enable_or_attest_migration(self):
        self.no_nop()
        template = waiver.review_template(self.report, self.review, self.root, "report-sha", "review-sha")
        self.assertFalse(template["enabled"])
        self.assertTrue(all(template["reviewer_context"][key] is False for key in waiver.CONTEXT_ASSERTIONS))

    def test_cli_preserves_all_inputs_and_writes_four_reports(self):
        self.no_nop()
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            strict = base / "strict"
            strict.mkdir()
            report_path, review_path, worksheet = strict / "report.json", strict / "review.json", base / "worksheet.json"
            report_path.write_text(json.dumps(self.report))
            review_path.write_text(json.dumps(self.review))
            manifest = self.manifest({"H06": ["new_current_trial_requirement"]})
            manifest.update(strict_report_sha256=fp.sha256_file(report_path), review_sha256=fp.sha256_file(review_path))
            worksheet.write_text(json.dumps(manifest))
            paths = [report_path, review_path, worksheet, *[self.root / name for name in qa.inventory(self.root)]]
            before = {str(path): fp.sha256_file(path) for path in paths}
            out = base / "waiver-result"
            code = waiver.main(["--report", str(report_path), "--review", str(review_path), "--waiver", str(worksheet), "--artifact-root", str(self.root), "--out-dir", str(out)])
            self.assertEqual(code, 0)
            self.assertEqual(before, {str(path): fp.sha256_file(path) for path in paths})
            self.assertEqual({path.name for path in out.iterdir()}, {"waiver_report.json", "waiver_report.md", "waiver_report.txt", "waiver_return_to_expert.txt"})
            self.assertIn("平台后续验证", (out / "waiver_return_to_expert.txt").read_text())


if __name__ == "__main__":
    unittest.main()
