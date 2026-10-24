"""Current format/core-delivery fixtures; historical content is intentionally opaque."""
import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest
import zipfile

import audit_format_repair as audit


class FormatRepairTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name).resolve()
        self.root = self.base / "package"
        self.task = self.root / "workspace/harbor_task"
        for name in ("workspace", "expert_evidence", "optimization_evidence"):
            (self.root / name).mkdir(parents=True, exist_ok=True)
        (self.task / "environment/public_dev").mkdir(parents=True)
        (self.task / "environment/public_dev/dev.csv").write_text("feature,target\n1,2\n")
        (self.task / "tests").mkdir()
        (self.task / "instruction.md").write_text("Optimize the candidate method. Public Dev is available; private evaluation is injected only into Verifier.")
        (self.task / "task.toml").write_text('artifacts=["/workspace/solution"]\n[environment]\ncpus=2\ngpus=0\n[verifier]\nenvironment_mode="separate"\n')
        (self.task / "environment/Dockerfile").write_text("FROM python@sha256:" + "a" * 64 + "\nWORKDIR /workspace\nCOPY public_dev /workspace/public_dev\n")
        (self.task / "tests/test.sh").write_text('#!/bin/bash\npython /tests/evaluate.py --submission /workspace/solution\n')
        (self.task / "tests/evaluate.py").write_text('from pathlib import Path\n# Fixed author metric and frozen grading implementation.\n# Candidate files are input data, never imported as grader code.\ndef write_metric(metric):\n    Path("/logs/verifier/reward.txt").write_text(str(metric))\n')
        (self.task / "tests/hidden_supply.json").write_text('{"supply":"platform-injection","agent_access":false}')
        self.refs = {
            "F01": ["workspace/harbor_task/task.toml"],
            "F02": ["workspace/harbor_task/environment/Dockerfile"],
            "F03": ["workspace/harbor_task/tests/test.sh", "workspace/harbor_task/tests/evaluate.py"],
            "F04": ["workspace/harbor_task/task.toml", "workspace/harbor_task/tests/test.sh"],
            "F05": ["workspace/harbor_task/environment/Dockerfile", "workspace/harbor_task/tests/hidden_supply.json"],
            "F06": ["workspace/harbor_task/task.toml"],
            "F07": ["workspace/harbor_task/tests/evaluate.py"],
        }

    def tearDown(self):
        self.temporary.cleanup()

    def review(self, resolve=False):
        result = {"schema_version": 1, "stage": "format_repair", "task_type": "cpu",
                  "checks": [{"id": key, "status": "pass", "summary": "Current core implementation and delivery contract were read and verified.",
                              "evidence": self.refs[key], "resolutions": []} for key in audit.CHECKS]}
        if resolve:
            scan = audit.inventory(self.root, result)
            for observation in scan["semantic_observations"]:
                row = next(row for row in result["checks"] if row["id"] == observation["owner"])
                refs = [ref for ref in observation["evidence"] if (self.root / ref).is_file()]
                row["resolutions"].append({"observation_id": observation["observation_id"],
                    "summary": "Reviewer read current source and mapped this dynamic/public expression to the declared contract.",
                    "evidence": refs or row["evidence"]})
        return result

    def assess(self, review=None, resolve=True):
        return audit.assess(self.root, review if review is not None else self.review(resolve))

    def row(self, result, key):
        return next(row for row in result["checks"] if row["id"] == key)

    def test_valid_single_dockerfile_reuse_and_tests_upload_pass(self):
        result = self.assess()
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertEqual(result["stage"], "format_repair")
        self.assertEqual(result["platform_runtime_status"], "not_executed")
        self.assertFalse(result["task_code_executed"])
        self.assertFalse((self.task / "tests/Dockerfile").exists())

    def test_no_review_is_workflow_error_and_generates_template(self):
        result = audit.assess(self.root)
        self.assertEqual(result["decision"], "ERROR")
        self.assertEqual(result["code"], "REVIEW_NOT_PROVIDED")
        self.assertFalse(result["is_task_rejection"])
        self.assertEqual(len(result["review_template"]["checks"]), 7)

    def test_null_or_extended_old_trajectory_states_do_not_block(self):
        (self.root / "expert_evidence/trajectory.json").write_text(json.dumps({"rounds": [{"time": None, "status": "infra_invalid"}, {"status": "custom_extension", "score": None}]}))
        (self.root / "expert_evidence/run_summary.json").write_text('{broken old JSON retained as original history')
        (self.root / "optimization_evidence/old_A100_result.json").write_text('{"gpu":"A100","old_score":0.1}')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_large_array_log_bare_reference_is_legal(self):
        log = self.root / "expert_evidence/array_log.json"
        log.write_text('["' + "x" * (5 * 1024 * 1024) + '"]')
        review = self.review()
        review["checks"][0]["evidence"].append("expert_evidence/array_log.json")
        self.assertEqual(self.assess(review)["decision"], "PASS_WITH_WAIVERS")

    def test_large_high_compression_array_log_zip_is_legal(self):
        (self.root / "expert_evidence/array_log.json").write_text('["' + "x" * (5 * 1024 * 1024) + '"]')
        archive = self.base / "complete.zip"
        with zipfile.ZipFile(archive, "w", zipfile.ZIP_DEFLATED) as stream:
            for path in self.root.rglob("*"):
                stream.write(path, path.relative_to(self.root).as_posix())
        review_path = self.base / "review.json"
        review_path.write_text(json.dumps(self.review()))
        out = self.base / "result"
        self.assertEqual(audit.main([str(archive), "--review", str(review_path), "--out-dir", str(out)]), 0)
        self.assertEqual(json.loads((out / "report.json").read_text())["decision"], "PASS_WITH_WAIVERS")

    def test_no_old_nop_hash_resource_model_proofs_are_required(self):
        self.assertFalse(list((self.root / "expert_evidence").iterdir()))
        self.assertFalse(list((self.root / "optimization_evidence").iterdir()))
        result = self.assess()
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS")
        self.assertTrue(result["platform_followup_pending"])

    def test_historical_agent_dev_fitting_is_not_current_author_fault(self):
        (self.root / "expert_evidence/old_session.json").write_text('{"issue":"Agent tuned against Dev evaluator", "score_status":"invalid", "failure_stage":"grader"}')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_digest_base_bash_root_seccomp_are_platform_matters(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace("cpus=2", 'cpus=2\nroot=true\nseccomp="platform-defined"'))
        result = self.assess()
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS")
        text = audit.render(result)
        self.assertIn("平台后续事项", text)
        self.assertNotIn("INCOMPLETE", text)

    def test_missing_current_core_file_cannot_be_overridden_by_review(self):
        (self.task / "instruction.md").unlink()
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL")
        self.assertEqual(self.row(result, "F01")["status"], "fail")

    def test_invalid_toml_is_current_format_fail(self):
        (self.task / "task.toml").write_text('[broken')
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL", result)
        self.assertTrue(any(item["code"] == "TOML_PARSE" for item in result["current_findings"]))

    def test_missing_copy_source_cannot_be_handwritten_pass(self):
        (self.task / "environment/Dockerfile").write_text('FROM python:3.11\nCOPY absent.txt /workspace/absent.txt\n')
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL", result)
        self.assertTrue(any("COPY_SOURCE_MISSING" in item["code"] for item in result["current_findings"]))

    def test_dynamic_copy_requires_real_current_semantic_review(self):
        (self.task / "environment/Dockerfile").write_text('FROM python:3.11\nARG SOURCE=public_dev\nCOPY ${SOURCE} /workspace/public_dev\n')
        result = self.assess(self.review(resolve=False))
        self.assertEqual(result["decision"], "ERROR")
        self.assertEqual(result["code"], "CURRENT_SEMANTIC_REVIEW_REQUIRED")
        self.assertFalse(result["is_task_rejection"])
        self.assertEqual(self.assess(self.review(resolve=True))["decision"], "PASS_WITH_WAIVERS")

    def test_compose_only_current_selected_directories_are_blocked(self):
        (self.root / "expert_evidence/old-compose.yaml").write_text('services: {}')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")
        (self.task / "environment/docker-compose.yml").write_text('services: {}')
        self.assertEqual(self.assess()["decision"], "FAIL")

    def test_current_storage_and_no_network_configuration_must_be_fixed(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace("cpus=2", 'cpus=2\nstorage_mb=100\nnetwork_mode="no-network"'))
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL")
        self.assertTrue({"STORAGE_UNSUPPORTED", "NETWORK_UNSUPPORTED"} <= {item["code"] for item in result["current_findings"]})

    def test_separate_still_required(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('environment_mode="separate"', 'environment_mode="same"'))
        self.assertEqual(self.assess()["decision"], "FAIL")

    def test_artifacts_uncovered_current_submission_is_fail(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('artifacts=["/workspace/solution"]', 'artifacts=[]'))
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL")
        self.assertTrue(any(item["code"] == "ARTIFACTS_UNCOVERED" for item in result["current_findings"]))

    def test_default_artifacts_and_source_objects_are_legal(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('artifacts=["/workspace/solution"]', 'artifacts=[]'))
        script = self.task / "tests/test.sh"
        script.write_text(script.read_text().replace("/workspace/solution", "/logs/artifacts"))
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")
        path.write_text(path.read_text().replace('artifacts=[]', 'artifacts=[{source="/logs/artifacts",destination="host-run"}]'))
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_artifact_host_destination_does_not_remap_candidate_path(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('artifacts=["/workspace/solution"]', 'artifacts=[{source="/workspace/other",destination="/workspace/solution"}]'))
        self.assertEqual(self.assess()["decision"], "FAIL")

    def test_gpu_target_requires_h20_l20_but_old_card_logs_are_ignored(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('gpus=0', 'gpus=1\ngpu_types=["RTX4090"]'))
        review = self.review()
        review["task_type"] = "gpu"
        self.assertEqual(self.assess(review)["decision"], "FAIL")
        path.write_text(path.read_text().replace('gpu_types=["RTX4090"]', 'gpu_types=["H20"]'))
        self.assertEqual(self.assess(review)["decision"], "PASS_WITH_WAIVERS")

    def test_cpu_task_cannot_add_gpu(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('gpus=0', 'gpus=1\ngpu_types=["H20"]'))
        self.assertEqual(self.assess()["decision"], "FAIL")

    def test_hidden_can_be_injected_and_shared_tests_can_be_public(self):
        (self.task / "environment/public_dev/tests").mkdir()
        (self.task / "environment/public_dev/tests/evaluate_dev.py").write_text('def public_metric(): return 1\n')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")
        self.assertFalse((self.task / "tests/hidden_assets").exists())

    def test_private_name_alone_requires_semantic_review_not_automatic_failure(self):
        (self.task / "environment/hidden_assets").mkdir()
        (self.task / "environment/hidden_assets/public_helpers.py").write_text('def public_helper(): return 1')
        path = self.task / "environment/Dockerfile"
        path.write_text(path.read_text() + 'COPY hidden_assets /workspace/shared_public_helpers\n')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_confirmed_current_private_exposure_is_fail(self):
        (self.task / "environment/hidden_assets").mkdir()
        (self.task / "environment/hidden_assets/private_cases.json").write_text('{"private":true}')
        path = self.task / "environment/Dockerfile"
        path.write_text(path.read_text() + 'COPY hidden_assets /workspace/private_cases\n')
        review = self.review(resolve=True)
        row = next(row for row in review["checks"] if row["id"] == "F05")
        for resolution in row["resolutions"]:
            resolution["confirmed_private_exposure"] = True
            resolution["summary"] = "Reviewer confirmed actual private cases enter the Agent image."
        self.assertEqual(self.assess(review)["decision"], "FAIL")

    def test_f07_current_author_grader_fault_is_not_exempted(self):
        review = self.review()
        row = next(row for row in review["checks"] if row["id"] == "F07")
        row.update(status="fail", summary="Current grader accepts a candidate-supplied forged reward.",
                   remediation="Restore author-owned metric computation and frozen grader.", acceptance_evidence="Current source rejects candidate score injection.")
        result = self.assess(review)
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn(row["remediation"], audit.render(result))

    def test_invalid_or_incomplete_review_is_tool_error_not_expert_reject(self):
        for mutation in ("missing", "unknown_status", "empty_reason"):
            review = self.review()
            if mutation == "missing":
                review["checks"].pop()
            elif mutation == "unknown_status":
                review["checks"][0]["status"] = "manual"
            else:
                review["checks"][0]["summary"] = ""
            result = self.assess(review)
            self.assertEqual(result["decision"], "ERROR")
            self.assertFalse(result["is_task_rejection"])

    def test_review_evidence_can_be_large_array_without_schema_validation(self):
        path = self.root / "expert_evidence/old_array.json"
        path.write_text('[1, 2, {"status":"infra_invalid","time":null}]')
        review = self.review()
        review["checks"][0]["evidence"].append('expert_evidence/old_array.json#/2/status')
        self.assertEqual(self.assess(review)["decision"], "PASS_WITH_WAIVERS")

    def test_current_file_and_review_are_never_written(self):
        review = self.review()
        original = copy.deepcopy(review)
        before = {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()}
        self.assess(review)
        self.assertEqual(review, original)
        self.assertEqual(before, {str(path): path.read_bytes() for path in self.root.rglob('*') if path.is_file()})

    def test_cli_no_review_writes_error_and_disabled_template(self):
        out = self.base / "output"
        self.assertEqual(audit.main([str(self.root), '--out-dir', str(out)]), 2)
        report = json.loads((out / "report.json").read_text())
        self.assertEqual(report["code"], "REVIEW_NOT_PROVIDED")
        self.assertTrue((out / "review_template.json").is_file())
        self.assertNotIn("INCOMPLETE", (out / "report.txt").read_text())

    def test_zip_traversal_is_input_error_not_task_failure(self):
        archive = self.base / "unsafe.zip"
        with zipfile.ZipFile(archive, 'w') as stream:
            stream.writestr('../outside.txt', 'bad')
        out = self.base / "unsafe-output"
        self.assertEqual(audit.main([str(archive), '--out-dir', str(out)]), 2)
        report = json.loads((out / 'report.json').read_text())
        self.assertEqual(report['decision'], 'ERROR')
        self.assertFalse(report['is_task_rejection'])

    def test_ordinary_outer_zip_folder_is_supported(self):
        destination = self.base / "wrapped"
        shutil.copytree(self.root, destination / 'outer-task')
        review = self.review()
        for row in review['checks']:
            row['evidence'] = ['outer-task/' + value for value in row['evidence']]
        result = audit.assess(destination, review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)

    def test_direct_task_root_needs_no_research_folder_names(self):
        review = self.review()
        for row in review['checks']:
            row['evidence'] = [value.removeprefix('workspace/harbor_task/') for value in row['evidence']]
        result = audit.assess(self.task, review)
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertEqual(result['task_root'], '.')

    def test_standard_workspace_wrapper_without_legacy_research_dirs_is_valid(self):
        shutil.rmtree(self.root / 'expert_evidence')
        shutil.rmtree(self.root / 'optimization_evidence')
        self.assertEqual(self.assess()['decision'], 'PASS_WITH_WAIVERS')

    def test_known_missing_test_entry_is_fail_even_with_derived_observation(self):
        (self.task / 'tests/Dockerfile').write_text('FROM python:3.11\nCOPY . /tests\n')
        (self.task / 'tests/test.sh').unlink()
        review = self.review(resolve=False)
        next(row for row in review['checks'] if row['id'] == 'F03')['evidence'] = ['workspace/harbor_task/tests/evaluate.py']
        result = self.assess(review)
        self.assertEqual(result['decision'], 'FAIL', result)
        self.assertTrue(result['review_diagnostics'])

    def test_primary_filenames_nonblocking_notes_and_expert_only_current_fixes(self):
        (self.task / 'environment/Dockerfile').write_text('FROM python:3.11\nCOPY missing-file /workspace/missing-file\n')
        result = self.assess()
        out = self.base / 'reports'
        audit.write_report(result, out)
        for suffix in ('json', 'txt', 'md'):
            self.assertTrue((out / ('format_report.' + suffix)).is_file())
        self.assertTrue(all(item['blocking'] is False for item in result['platform_followup_pending']))
        self.assertTrue(all(item['blocking'] is False for item in result['historical_rules_not_checked']))
        expert = (out / 'return_to_expert.txt').read_text()
        self.assertIn('missing-file', expert)
        self.assertIn('整改', expert)
        self.assertNotIn('平台后续', expert)
        self.assertNotIn('历史轨迹', expert)
        self.assertNotIn('ICM', expert)

    def test_pass_expert_note_has_no_platform_or_history_checklist(self):
        result = self.assess()
        out = self.base / 'reports'
        audit.write_report(result, out)
        self.assertEqual((out / 'return_to_expert.txt').read_text(), '本轮结论：PASS_WITH_WAIVERS。无需当前格式返修。\n')

    def test_cli_review_can_share_output_directory_under_nonoutput_name(self):
        out = self.base / 'reports'
        out.mkdir()
        review_path = out / 'format_review.json'
        review_path.write_text(json.dumps(self.review()))
        before = review_path.read_bytes()
        code = audit.main([str(self.root), '--review', str(review_path), '--out-dir', str(out)])
        self.assertEqual(code, 0)
        self.assertEqual(review_path.read_bytes(), before)
        self.assertTrue((out / 'format_report.json').exists())

    def test_cli_refuses_overwriting_review_template_input(self):
        out = self.base / 'reports'
        out.mkdir()
        review_path = out / 'review_template.json'
        review_path.write_text(json.dumps(self.review()))
        before = review_path.read_bytes()
        with self.assertRaises(SystemExit):
            audit.main([str(self.root), '--review', str(review_path), '--out-dir', str(out)])
        self.assertEqual(before, review_path.read_bytes())


if __name__ == '__main__':
    unittest.main()
