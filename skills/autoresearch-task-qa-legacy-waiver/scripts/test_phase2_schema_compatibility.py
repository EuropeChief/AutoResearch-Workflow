"""Current phase-2 format migration; no historical rerun requirements."""
import copy
import json
from pathlib import Path
import unittest

import audit_format_repair as audit
import test_audit_format_repair as fixtures


class Phase2SchemaCompatibilityTests(unittest.TestCase):
    setUp = fixtures.FormatRepairTests.setUp
    tearDown = fixtures.FormatRepairTests.tearDown
    review = fixtures.FormatRepairTests.review
    assess = fixtures.FormatRepairTests.assess
    row = fixtures.FormatRepairTests.row

    def config(self, content):
        (self.task / "task.toml").write_text(content)

    def codes(self, result):
        return {item["code"] for item in result["current_findings"]}

    def old_config(self):
        self.config('artifacts=["/workspace/solution"]\n[task]\nname="phase2"\n[resources]\ncpu_cores=16\nmemory_mb=65536\ngpu_count=1\ngpu_type="RTX4090"\nnetwork_access=false\n[verifier]\nenvironment_mode="separate"\n')

    def test_original_old_resource_schema_does_not_silently_get_cpu_defaults(self):
        self.old_config()
        review = self.review(resolve=True)
        review["task_type"] = "gpu"
        result = self.assess(review)
        self.assertEqual(result["decision"], "FAIL", result)
        self.assertTrue({"LEGACY_RESOURCE_SCHEMA_UNMAPPED", "GPU_REQUEST_MISSING"} <= self.codes(result))

    def test_old_cpu_resource_schema_also_requires_native_mapping(self):
        self.config('[resources]\ncpu_cores=16\nmemory_mb=64000\n[verifier]\nenvironment_mode="separate"\n')
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("LEGACY_RESOURCE_SCHEMA_UNMAPPED", self.codes(result))

    def test_metadata_nested_resources_are_not_live_old_schema(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text() + '[metadata.resources]\ngpu_count=1\ngpu_type="RTX4090"\nnetwork_access=false\n')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_unknown_old_notes_do_not_create_resource_mapping_requirement(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text() + '[resources]\nprevious_run_note="old package"\n')
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_old_resource_notes_alongside_valid_native_config_require_semantic_role(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text() + '[resources]\ngpu_count=1\ngpu_type="RTX4090"\nnetwork_access=false\n')
        pending = self.assess(self.review(resolve=False))
        self.assertEqual(pending["decision"], "ERROR")
        self.assertEqual(pending["code"], "CURRENT_SEMANTIC_REVIEW_REQUIRED")
        result = self.assess(self.review(resolve=True))
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertNotIn("NETWORK_UNSUPPORTED", self.codes(result))

    def test_explicit_gpu_task_with_only_zero_native_gpu_still_fails(self):
        review = self.review(resolve=True)
        review["task_type"] = "gpu"
        result = self.assess(review)
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("GPU_REQUEST_MISSING", self.codes(result))

    def test_native_h20_mapping_can_keep_historical_old_gpu_fields(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('gpus=0', 'gpus=1\ngpu_types=["H20"]') + '[resources]\ngpu_count=1\ngpu_type="RTX4090"\nnetwork_access=false\n')
        review = self.review(resolve=True)
        review["task_type"] = "gpu"
        self.assertEqual(self.assess(review)["decision"], "PASS_WITH_WAIVERS")

    def test_actual_native_network_flag_is_still_a_current_format_fault(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('cpus=2', 'cpus=2\nnetwork_access=false') + '[resources]\ngpu_count=0\n')
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("NETWORK_UNSUPPORTED", self.codes(result))

    def add_old_entrypoints(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text() + '[entrypoint]\nsolution_script="solution/old_solve.sh"\ngrader_script="tests/old_grader.py"\ntest_script="tests/old_test.sh"\n')

    def inactive_entrypoint_review(self):
        review = self.review(resolve=False)
        review["legacy_entrypoint_inactive"] = {"summary": "Current native tests/test.sh replaces the old teaching metadata; no active caller uses old paths.",
            "evidence": ["workspace/harbor_task/task.toml", "workspace/harbor_task/tests/test.sh"]}
        return self.resolve(review)

    def resolve(self, review):
        for row in review["checks"]:
            row["resolutions"] = []
        for item in audit.inventory(self.root, review)["semantic_observations"]:
            row = next(row for row in review["checks"] if row["id"] == item["owner"])
            refs = [ref for ref in item["evidence"] if (self.root / ref).is_file()]
            row["resolutions"].append({"observation_id": item["observation_id"], "summary": "Read native source and verified actual replacement/invocation/mapping.", "evidence": refs or row["evidence"]})
        return review

    def test_live_old_entrypoints_are_not_silently_dropped(self):
        self.add_old_entrypoints()
        result = self.assess()
        self.assertEqual(result["decision"], "FAIL")
        self.assertTrue(any("ENTRY_MISSING" in code or "CANONICAL_ENTRY_MISMATCH" in code for code in self.codes(result)))

    def test_evidenced_inactive_old_entrypoints_are_not_mechanical_failures(self):
        self.add_old_entrypoints()
        result = self.assess(self.inactive_entrypoint_review())
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertNotIn("entrypoint", audit.inventory(self.root, self.inactive_entrypoint_review())["config"])

    def test_inactive_entrypoint_requires_existing_source_evidence(self):
        self.add_old_entrypoints()
        review = self.review()
        review["legacy_entrypoint_inactive"] = {"summary": "replaced", "evidence": ["missing-proof.txt"]}
        result = self.assess(review)
        self.assertEqual(result["decision"], "ERROR")
        self.assertEqual(result["code"], "REVIEW_EVIDENCE")

    def test_inactive_entrypoint_cannot_replace_absent_native_test_wrapper(self):
        self.add_old_entrypoints()
        (self.task / "tests/test.sh").unlink()
        review = self.review()
        review["legacy_entrypoint_inactive"] = {"summary": "claimed replacement", "evidence": ["workspace/harbor_task/task.toml"]}
        result = self.assess(review)
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("LEGACY_ENTRYPOINT_REPLACEMENT_MISSING", self.codes(result))

    def adapter_review(self):
        review = self.review(resolve=False)
        review["task_type"] = "gpu"
        review["config_adapter"] = {"entrypoint": "workspace/harbor_task/adapt.py",
            "effective_task": "workspace/harbor_task/native_task.toml", "summary": "Existing launch script invokes the adapter and selects the supplied native config.",
            "evidence": ["workspace/harbor_task/launch.sh", "workspace/harbor_task/native_task.toml"]}
        return self.resolve(review)

    def setup_adapter(self):
        self.old_config()
        (self.task / "native_task.toml").write_text('artifacts=["/workspace/solution"]\n[environment]\ncpus=2\ngpus=1\ngpu_types=["H20"]\n[verifier]\nenvironment_mode="separate"\n')
        (self.task / "adapt.py").write_text('# Reads legacy schema and emits the supplied native_task.toml; reviewed only, never executed.\n')
        (self.task / "launch.sh").write_text('python adapt.py --target native_task.toml\nharbor run --task-config native_task.toml\n')

    def test_existing_real_adapter_target_is_semantically_reviewed_not_executed(self):
        self.setup_adapter()
        before = {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()}
        result = self.assess(self.adapter_review())
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertFalse(result["task_code_executed"])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.root.rglob('*') if p.is_file()})

    def test_adapter_target_still_must_meet_current_native_gpu_rules(self):
        self.setup_adapter()
        path = self.task / "native_task.toml"
        path.write_text(path.read_text().replace('H20', 'RTX4090'))
        result = self.assess(self.adapter_review())
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("GPU_TARGET", self.codes(result))

    def test_adapter_target_legacy_resources_are_not_a_mapping(self):
        self.setup_adapter()
        (self.task / "native_task.toml").write_text((self.task / "task.toml").read_text())
        result = self.assess(self.adapter_review())
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("LEGACY_RESOURCE_SCHEMA_UNMAPPED", self.codes(result))

    def test_adapter_does_not_silently_remove_still_used_old_entrypoint(self):
        self.setup_adapter()
        self.add_old_entrypoints()
        result = self.assess(self.adapter_review())
        self.assertEqual(result["decision"], "FAIL")
        self.assertTrue(any("ENTRY_MISSING" in code for code in self.codes(result)))

    def test_resource_only_adapter_can_replace_inactive_legacy_entrypoint(self):
        self.setup_adapter()
        self.add_old_entrypoints()
        review = self.adapter_review()
        review['legacy_entrypoint_inactive'] = {
            'summary': 'Adapter only maps resources; launch selects native_task.toml and actual tests/test.sh, never old entrypoint values.',
            'evidence': ['workspace/harbor_task/adapt.py', 'workspace/harbor_task/launch.sh', 'workspace/harbor_task/tests/test.sh']}
        result = self.assess(self.resolve(review))
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertNotIn('entrypoint', audit.inventory(self.root, review)['config'])

    def test_actual_adapter_literal_legacy_call_cannot_be_hidden_by_inactive_note(self):
        self.setup_adapter()
        self.add_old_entrypoints()
        (self.task / 'adapt.py').write_text('import subprocess\nsubprocess.run(["python", "tests/old_grader.py"], check=True)\n')
        review = self.adapter_review()
        review['legacy_entrypoint_inactive'] = {
            'summary': 'Claim that all old entrypoints are unused.',
            'evidence': ['workspace/harbor_task/adapt.py', 'workspace/harbor_task/launch.sh']}
        result = self.assess(self.resolve(review))
        self.assertEqual(result['decision'], 'FAIL', result)
        self.assertTrue(any('ENTRY_MISSING' in code for code in self.codes(result)))
        self.assertEqual(audit.inventory(self.root, review)['config']['entrypoint'], {'grader_script': 'tests/old_grader.py'})

    def test_adapter_comment_mentioning_old_path_is_not_an_executable_dependency(self):
        self.setup_adapter()
        self.add_old_entrypoints()
        (self.task / 'adapt.py').write_text('# Historical grader tests/old_grader.py is unused.\nprint("old path tests/old_grader.py is not used")\n')
        review = self.adapter_review()
        review['legacy_entrypoint_inactive'] = {
            'summary': 'Existing source and native launch establish replacement.',
            'evidence': ['workspace/harbor_task/adapt.py', 'workspace/harbor_task/launch.sh']}
        self.assertEqual(self.assess(self.resolve(review))['decision'], 'PASS_WITH_WAIVERS')

    def test_arbitrary_run_method_is_not_assumed_to_execute_legacy_script(self):
        self.setup_adapter()
        self.add_old_entrypoints()
        (self.task / 'adapt.py').write_text('recorder.run("tests/old_grader.py")  # Records a history label, not a process call.\n')
        review = self.adapter_review()
        review['legacy_entrypoint_inactive'] = {
            'summary': 'Existing source records a label only; actual native launch uses tests/test.sh.',
            'evidence': ['workspace/harbor_task/adapt.py', 'workspace/harbor_task/launch.sh']}
        self.assertEqual(self.assess(self.resolve(review))['decision'], 'PASS_WITH_WAIVERS')

    def test_python_c_m_and_later_argv_legacy_labels_are_not_script_positions(self):
        self.setup_adapter()
        self.add_old_entrypoints()
        (self.task / 'native_helper.py').write_text('import sys\nprint(sys.argv[1:])\n')
        commands = [
            ['python', '-c', 'import sys; print(sys.argv[1])', 'tests/old_grader.py'],
            ['python', '-m', 'native_helper', 'tests/old_grader.py'],
            ['python', 'native_helper.py', 'tests/old_grader.py'],
        ]
        for command in commands:
            with self.subTest(command=command):
                (self.task / 'adapt.py').write_text('import subprocess\nsubprocess.run(' + repr(command) + ', check=True)\n')
                review = self.adapter_review()
                review['legacy_entrypoint_inactive'] = {
                    'summary': 'Existing adapter only prints the historical path as argv data; native entry replaces the old one.',
                    'evidence': ['workspace/harbor_task/adapt.py', 'workspace/harbor_task/launch.sh', 'workspace/harbor_task/native_helper.py']}
                result = self.assess(self.resolve(review))
                self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
                self.assertNotIn('entrypoint', audit.inventory(self.root, review)['config'])

    def test_adapter_cannot_be_just_a_boolean_claim(self):
        self.old_config()
        review = self.review()
        review["config_adapter"] = {"exists": True}
        result = self.assess(review)
        self.assertEqual(result["decision"], "ERROR")
        self.assertEqual(result["code"], "REVIEW_CONFIG_ADAPTER")

    def test_current_task_root_custom_context_cannot_bypass_native_format(self):
        (self.task / "tests/public.py").write_text('def dev_metric(): return 1\n')
        (self.task / "environment/Dockerfile").write_text('FROM python:3.11\nCOPY tests/public.py /workspace/public.py\n')
        review = self.review()
        review["path_contract"] = {"profile": "custom", "build_context": "workspace/harbor_task", "dockerfile": "workspace/harbor_task/environment/Dockerfile", "runtime_task_root": "/workspace", "profile_basis": "old teaching example", "adapter_evidence": ["workspace/harbor_task/task.toml"]}
        result = self.assess(review)
        self.assertEqual(result["decision"], "FAIL")
        self.assertIn("NATIVE_BUILD_CONTEXT_REQUIRED", self.codes(result))
        self.assertTrue(any("COPY_SOURCE_MISSING" in code for code in self.codes(result)))

    def test_prebuilt_selection_does_not_fail_unused_old_recipe_context(self):
        path = self.task / "task.toml"
        path.write_text(path.read_text().replace('[environment]', '[environment]\ndocker_image="docker.io/example/existing:v1"'))
        (self.task / "environment/Dockerfile").write_text('FROM python:3.11\nCOPY tests/old_public.py /workspace/old_public.py\n')
        review = self.review()
        review["path_contract"] = {"profile": "custom", "build_context": "workspace/harbor_task", "runtime_task_root": "/workspace"}
        result = self.assess(review)
        self.assertEqual(result["decision"], "PASS_WITH_WAIVERS", result)
        self.assertTrue(any(item["code"] == "UNUSED_LEGACY_BUILD_RECIPE" and item["blocking"] is False for item in result["platform_observations"]))

    def test_equivalent_public_dev_directory_under_environment_is_valid(self):
        path = self.task / "environment/public_dev"
        path.rename(path.with_name('public_eval'))
        dockerfile = self.task / "environment/Dockerfile"
        dockerfile.write_text(dockerfile.read_text().replace('public_dev', 'public_eval'))
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")

    def test_prebuilt_image_ignores_unused_dockerfile_without_from(self):
        path = self.task / 'task.toml'
        path.write_text(path.read_text().replace('[environment]', '[environment]\ndocker_image="docker.io/example/existing:v1"'))
        (self.task / 'environment/Dockerfile').write_text('# Old unused recipe\nCOPY old-absent-source /workspace/old\n')
        result = self.assess()
        self.assertEqual(result['decision'], 'PASS_WITH_WAIVERS', result)
        self.assertNotIn('DOCKERFILE_FROM', self.codes(result))

    def test_selected_source_recipe_without_from_is_fail_and_checked_once(self):
        (self.task / 'environment/Dockerfile').write_text('WORKDIR /workspace\nCOPY public_dev /workspace/public_dev\n')
        result = self.assess()
        self.assertEqual(result['decision'], 'FAIL', result)
        findings = [item for item in result['current_findings'] if item['code'] == 'DOCKERFILE_FROM']
        self.assertEqual(len(findings), 1, findings)

    def test_agent_prebuilt_still_checks_selected_verifier_recipe_without_from(self):
        path = self.task / 'task.toml'
        path.write_text(path.read_text().replace('[environment]', '[environment]\ndocker_image="docker.io/example/existing:v1"'))
        (self.task / 'environment/Dockerfile').write_text('# Unused recipe without FROM\n')
        (self.task / 'tests/Dockerfile').write_text('WORKDIR /tests\nCOPY . /tests\n')
        result = self.assess()
        self.assertEqual(result['decision'], 'FAIL', result)
        findings = [item for item in result['current_findings'] if item['code'] == 'DOCKERFILE_FROM']
        self.assertEqual(len(findings), 1, findings)
        self.assertEqual(findings[0]['evidence'], ['workspace/harbor_task/tests/Dockerfile'])

    def test_multi_source_same_line_observations_and_template_are_unique(self):
        directory = self.task / "environment/tests"
        directory.mkdir()
        for name in ('grader.py', 'metrics.py', 'security.py'):
            (directory / name).write_text('# Public Dev helper\n')
        (self.task / "environment/Dockerfile").write_text('FROM python:3.11\nCOPY tests/grader.py tests/metrics.py tests/security.py /workspace/tests/\n')
        scan = audit.inventory(self.root)
        ids = [item['observation_id'] for item in scan['semantic_observations']]
        self.assertEqual(len(ids), len(set(ids)))
        template = audit.review_template(scan)
        template_ids = [item['observation_id'] for row in template['checks'] for item in row['resolutions']]
        self.assertEqual(len(template_ids), len(set(template_ids)))
        self.assertEqual(self.assess()["decision"], "PASS_WITH_WAIVERS")


if __name__ == '__main__':
    unittest.main()
