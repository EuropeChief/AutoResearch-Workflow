import copy
import json
import os
from pathlib import Path
import tempfile
import unittest

import implementation_review as qa
import resource_review
import task_fingerprint as fp
import trajectory_review as tr


def complete_integrity_fixture(root, overview):
    """Synthetic evidence for report contract tests, not real execution claims."""
    expert = root / "expert_evidence"
    expert.mkdir(exist_ok=True)
    current = fp.fingerprint(root)
    bindings, rows = [], []
    for index, trajectory in enumerate(overview):
        path = trajectory["source_path"]
        if not path:
            continue
        start = f"expert_evidence/start_{index}.json"
        session = f"expert_evidence/session_{index}.jsonl"
        run_id = f"synthetic-{index}"
        (root / start).write_text(json.dumps({"phase": "run_start", "recorded_at": "2026-10-06T00:00:00Z",
            "run_id": run_id, "hash_profile": fp.PROFILE, "task_content_sha256": current["task_content_sha256"]}))
        (root / session).write_text(json.dumps({"type": "response_item", "payload": {
            "type": "function_call", "name": "exec_command", "arguments": '{"cmd":"python local_method.py"}', "call_id": run_id}}) + "\n")
        bindings.append({"task_binding": {"hash_profile": fp.PROFILE, "task_content_sha256": current["task_content_sha256"],
            "run_id": run_id, "trajectory_path": path, "trajectory_sha256": fp.sha256_file(root / path), "start_record": start}})
        rows.append({"source_path": path, "score_status": "valid", "summary": "Synthetic fixture only.",
            "reviewed_sources": [path, session], "evidence": [path, start], "findings": [],
            "binding_review": {"status": "pass", "summary": "Synthetic runner association reviewed.", "evidence": [start, session]},
            "behavior_review": {"status": "pass", "summary": "Synthetic local-only call reviewed.", "evidence": [session]},
            "score_review": {"status": "pass", "summary": "Synthetic score source reviewed.", "evidence": [path]}})
    (expert / "run_summary.json").write_text(json.dumps({"agent_execution": bindings}))
    return {"trajectories": rows}


def complete_resources_fixture():
    return {"status": "pass", "summary": "Synthetic resource contract.", "evidence": ["instruction.md"],
        "hardware_review": {"task_type": "cpu", "score_comparability": "same_hardware",
            "summary": "Synthetic CPU task and corresponding hardware reviewed.", "evidence": ["instruction.md"]},
        "enforcement_review": {"status": "pass", "summary": "Synthetic scheduler declaration reviewed.", "evidence": ["task.toml"]},
        "runs": [{"run_id": "synthetic-score", "scope": "score", "source_path": "instruction.md",
                  "score_seconds": 60, "gpu_count": 0, "gpu_type": None, "cpu_cores": 1,
                  "time_accounting": "Synthetic complete score.", "evidence": ["instruction.md"]}]}


class RuntimeIntegrityTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        (self.root / "environment").mkdir()
        (self.root / "tests").mkdir()
        (self.root / "task.toml").write_text('[verifier]\nenvironment_mode="separate"\n')
        (self.root / "instruction.md").write_text("Frozen instructions")
        (self.root / "environment/Dockerfile").write_text("FROM python:3.11\n")
        (self.root / "tests/test.sh").write_text("true\n")
        self.overview = [{"name": f"Agent {i}", "source_path": f"trajectory_{i}.json"} for i in range(2)]
        for row in self.overview:
            (self.root / row["source_path"]).write_text('{"rounds": []}')

    def tearDown(self):
        self.temp.cleanup()

    def files(self):
        return qa.inventory(self.root)

    def assess(self, review):
        facts = tr.collect(self.root, self.files(), fp.collect(self.root))
        return tr.apply_review(facts, review, self.overview, self.root, self.files(), qa.review_evidence)

    def test_each_frozen_component_changes_hash(self):
        original = fp.fingerprint(self.root)["task_content_sha256"]
        for name in ("instruction.md", "task.toml", "environment/Dockerfile", "tests/test.sh"):
            path = self.root / name
            old = path.read_bytes()
            path.write_bytes(old + b"\nchange\n")
            self.assertNotEqual(original, fp.fingerprint(self.root)["task_content_sha256"])
            path.write_bytes(old)
        (self.root / "environment/.dockerignore").write_text("cache\n")
        self.assertNotEqual(original, fp.fingerprint(self.root)["task_content_sha256"])

    def test_outputs_oracle_timestamps_and_packaging_do_not_change_hash(self):
        original = fp.fingerprint(self.root)["task_content_sha256"]
        (self.root / "solution").mkdir()
        (self.root / "solution/solve.sh").write_text("Oracle changed")
        (self.root / "trajectory_0.json").write_text("updated outputs")
        os.utime(self.root / "instruction.md", (1, 2))
        self.assertEqual(original, fp.fingerprint(self.root)["task_content_sha256"])

    def test_add_remove_rename_and_empty_directories_are_covered(self):
        original = fp.fingerprint(self.root)["task_content_sha256"]
        target = self.root / "tests/private.json"
        target.write_text("{}"); added = fp.fingerprint(self.root)["task_content_sha256"]
        self.assertNotEqual(original, added)
        target.rename(self.root / "tests/private2.json")
        self.assertNotEqual(added, fp.fingerprint(self.root)["task_content_sha256"])
        (self.root / "tests/private2.json").unlink()
        self.assertEqual(original, fp.fingerprint(self.root)["task_content_sha256"])
        (self.root / "tests/empty").mkdir()
        self.assertNotEqual(original, fp.fingerprint(self.root)["task_content_sha256"])

    def test_symlink_frozen_input_is_explicitly_uninspectable(self):
        (self.root / "environment/link").symlink_to(self.root / "instruction.md")
        with self.assertRaisesRegex(ValueError, "symlink"):
            fp.fingerprint(self.root)

    def test_binding_root_alias_does_not_make_evidence_unreadable(self):
        with tempfile.TemporaryDirectory() as alias_parent:
            alias = Path(alias_parent) / "bundle-alias"
            alias.symlink_to(self.root.resolve(), target_is_directory=True)
            self.assertEqual(fp.resolve_file(alias, "trajectory_0.json"),
                             self.root.resolve() / "trajectory_0.json")

    def test_binding_still_rejects_links_inside_bundle(self):
        (self.root / "linked-tests").symlink_to(self.root / "tests", target_is_directory=True)
        with self.assertRaisesRegex(ValueError, "symlink ancestor"):
            fp.resolve_file(self.root, "linked-tests/test.sh")
        with tempfile.TemporaryDirectory() as outside:
            (Path(outside) / "record.json").write_text("{}")
            (self.root / "outside-link").symlink_to(outside, target_is_directory=True)
            with self.assertRaisesRegex(ValueError, "regular bundle file"):
                fp.resolve_file(self.root, "outside-link/record.json")

    def test_matching_summary_hash_passes_without_start_record(self):
        current = fp.collect(self.root)
        binding = {"hash_profile": fp.PROFILE, "task_content_sha256": current["task_content_sha256"],
                   "trajectory_path": "trajectory_0.json", "trajectory_sha256": fp.sha256_file(self.root / "trajectory_0.json")}
        self.assertEqual(fp.check_binding(self.root, current, "trajectory_0.json", binding)["status"], "pass")
        binding["task_content_sha256"] = "0" * 64
        self.assertEqual(fp.check_binding(self.root, current, "trajectory_0.json", binding)["status"], "fail")

    def test_full_evidence_passes_but_summary_alone_does_not(self):
        review = complete_integrity_fixture(self.root, self.overview)
        self.assertEqual(self.assess(review)["status"], "pass")
        for row in review["trajectories"]:
            row["reviewed_sources"] = [row["source_path"]]
        self.assertEqual(self.assess(review)["status"], "manual")

    def test_missing_binding_summary_names_only_the_actual_gap(self):
        review = complete_integrity_fixture(self.root, self.overview)
        (self.root / "expert_evidence/run_summary.json").write_text('{"agent_execution": []}')
        actual = self.assess(review)
        self.assertEqual(actual["status"], "manual")
        self.assertIn("run_summary 题包哈希缺失", actual["summary"])
        self.assertNotIn("工具行为未确认", actual["summary"])
        self.assertNotIn("评分来源未确认", actual["summary"])
        self.assertEqual(actual["content_status"], "pass")

    def test_common_summary_hash_covers_both_agents(self):
        review = complete_integrity_fixture(self.root, self.overview)
        current = fp.fingerprint(self.root)
        (self.root / "expert_evidence/run_summary.json").write_text(json.dumps({"task_binding": {
            "hash_profile": fp.PROFILE, "task_content_sha256": current["task_content_sha256"]}}))
        self.assertEqual(self.assess(review)["status"], "pass")

    def test_per_agent_hash_overrides_common_hash(self):
        review = complete_integrity_fixture(self.root, self.overview)
        binding = {"hash_profile": fp.PROFILE, "task_content_sha256": fp.fingerprint(self.root)["task_content_sha256"]}
        (self.root / "expert_evidence/run_summary.json").write_text(json.dumps({"task_binding": binding,
            "agent_execution": [{"task_binding": {**binding, "task_content_sha256": "0" * 64}}, {}]}))
        actual = self.assess(review)
        self.assertEqual(actual["trajectories"][0]["task_binding"]["status"], "fail")
        self.assertEqual(actual["trajectories"][1]["task_binding"]["status"], "pass")

    def test_rounds_only_review_does_not_require_new_sessions(self):
        review = complete_integrity_fixture(self.root, self.overview)
        for index, row in enumerate(review["trajectories"]):
            (self.root / f"expert_evidence/session_{index}.jsonl").unlink()
            row["reviewed_sources"] = [row["source_path"]]
            row["behavior_review"]["evidence"] = [row["source_path"]]
        actual = self.assess(review)
        self.assertEqual(actual["content_status"], "pass")
        self.assertEqual(actual["trajectories"][0]["coverage"], "rounds_only")

    def test_real_codex_call_is_scanned_without_treating_user_text_as_action(self):
        expert = self.root / "expert_evidence"; expert.mkdir()
        path = expert / "codex_session.jsonl"
        path.write_text(json.dumps({"type": "message", "role": "user", "content": "Do not use github.com"}) + "\n" +
            json.dumps({"type": "response_item", "payload": {"type": "function_call", "name": "exec_command",
                        "arguments": '{"cmd":"curl https://github.com/example/repo"}'}}) + "\n")
        facts = tr.collect(self.root, self.files())
        self.assertEqual(facts["candidate_count"], 1)
        self.assertEqual(facts["sources"][0]["tool_calls"], 1)
        self.assertEqual(facts["status"], "manual")

    def test_optional_sessions_must_be_reviewed_when_supplied(self):
        review = complete_integrity_fixture(self.root, self.overview)
        (self.root / "expert_evidence/extra_session.jsonl").write_text('{"type":"function_call","name":"exec_command","arguments":"pwd"}\n')
        self.assertIn("expert_evidence/extra_session.jsonl", self.assess(review)["unreviewed_sources"])

    def test_zip_wrapper_preserves_package_relative_binding(self):
        review = complete_integrity_fixture(self.root, self.overview)
        children = list(self.root.iterdir())
        wrapper = self.root / "bundle"
        wrapper.mkdir()
        original = fp.fingerprint(self.root)["task_content_sha256"]
        for child in children:
            child.rename(wrapper / child.name)
        self.assertEqual(fp.fingerprint(wrapper)["task_content_sha256"], original)
        for trajectory, row in zip(self.overview, review["trajectories"]):
            trajectory["source_path"] = "bundle/" + trajectory["source_path"]
            row["source_path"] = "bundle/" + row["source_path"]
            for key in ("evidence", "reviewed_sources"):
                row[key] = ["bundle/" + ref for ref in row[key]]
            for key in ("binding_review", "behavior_review", "score_review"):
                row[key]["evidence"] = ["bundle/" + ref for ref in row[key]["evidence"]]
        facts = tr.collect(self.root, self.files(), fp.collect(wrapper))
        result = tr.apply_review(facts, review, self.overview, self.root, self.files(), qa.review_evidence)
        self.assertEqual(result["status"], "pass")

    def test_argument_hashes_without_arguments_cannot_establish_behavior(self):
        review = complete_integrity_fixture(self.root, self.overview)
        (self.root / "expert_evidence/session_0.jsonl").write_text(
            '{"type":"function_call","name":"exec_command","arguments_sha256":"abc","action":"tool_operation"}\n')
        actual = self.assess(review)
        self.assertEqual(actual["status"], "manual")
        self.assertEqual(actual["trajectories"][0]["coverage"], "partial_tool_calls")
        source = next(s for s in actual["sources"] if s["path"].endswith('session_0.jsonl'))
        self.assertEqual(source["tool_calls"], 1)
        self.assertEqual(source["inspectable_tool_calls"], 0)

    def test_legal_download_is_not_automatically_cheating(self):
        review = complete_integrity_fixture(self.root, self.overview)
        path = self.root / "expert_evidence/session_0.jsonl"
        path.write_text('{"type":"function_call","name":"exec_command","arguments":"curl https://pypi.org/simple/"}\n')
        candidate = tr.scan_source(self.root, "expert_evidence/session_0.jsonl")["candidates"][0]
        self.assertEqual(self.assess(review)["status"], "manual")
        review["trajectories"][0]["findings"] = [{"classification": "allowed", "certainty": "confirmed",
            "summary": "Allowed dependency fetch; no task source obtained.", "evidence": candidate["evidence"],
            "candidate_ids": [candidate["id"]], "score_effect": "none"}]
        self.assertEqual(self.assess(review)["status"], "pass")

    def test_confirmed_leakage_and_infra_are_separate(self):
        review = complete_integrity_fixture(self.root, self.overview)
        row = review["trajectories"][0]
        row["findings"] = [{"classification": "infra_bug", "certainty": "confirmed", "stage": "artifact_upload",
            "summary": "Candidate upload failed; no accepted score for that round.", "affected_rounds": [2], "score_effect": "none",
            "evidence": [row["source_path"]], "remediation": "Repair uploader.", "acceptance_evidence": "Upload log and later valid scoring."}]
        self.assertEqual(self.assess(review)["status"], "pass")
        row["findings"][0].update(classification="leakage", score_effect="invalid", summary="Private label was used by selected candidate.")
        self.assertEqual(self.assess(review)["trajectories"][0]["score_status"], "invalid")
        self.assertEqual(self.assess(review)["status"], "fail")

    def test_suspected_repaired_failure_without_score_does_not_block(self):
        review = complete_integrity_fixture(self.root, self.overview)
        review["trajectories"][0]["findings"] = [{"classification": "infra_bug", "certainty": "suspected",
            "stage": "artifact_upload", "summary": "Failed upload followed by valid retry; no accepted failed score.",
            "score_effect": "none", "affected_rounds": [2], "evidence": ["trajectory_0.json"]}]
        self.assertEqual(self.assess(review)["content_status"], "pass")

    def test_task_or_trajectory_change_cannot_be_overridden_by_pass(self):
        review = complete_integrity_fixture(self.root, self.overview)
        (self.root / "tests/test.sh").write_text("changed grader")
        self.assertEqual(self.assess(review)["status"], "fail")

    def resources(self, review, config=None):
        return resource_review.apply_review(resource_review.collect(self.root, self.files(), config=config), review, self.root, qa.review_evidence)

    def test_cpu_only_and_boundaries(self):
        review = complete_resources_fixture()
        self.assertEqual(self.resources(review)["status"], "pass")
        review["runs"][0].update(gpu_count=8, gpu_type="H20", cpu_cores=64, score_seconds=7200)
        review["hardware_review"]["task_type"] = "gpu"
        config = {"environment": {"gpus": 8, "gpu_types": ["H20"]}}
        self.assertEqual(self.resources(review, config)["status"], "pass")
        for field, value in (("gpu_count", 9), ("cpu_cores", 65), ("score_seconds", 7201)):
            changed = copy.deepcopy(review); changed["runs"][0][field] = value
            self.assertEqual(self.resources(changed, config)["status"], "fail")
        changed = copy.deepcopy(review)
        changed["runs"][0]["gpu_type"] = "A100"
        self.assertEqual(self.resources(changed, config)["status"], "pass")

    def test_unknown_resources_or_unenforced_limits_cannot_pass(self):
        review = complete_resources_fixture()
        review["runs"][0]["cpu_cores"] = None
        self.assertEqual(self.resources(review)["status"], "manual")

    def test_repeated_resource_gaps_do_not_hide_other_categories(self):
        review = complete_resources_fixture()
        review["runs"] = [{**review["runs"][0], "run_id": f"gpu-{i}", "gpu_count": 1, "gpu_type": None} for i in range(20)]
        review["hardware_review"]["task_type"] = "gpu"
        review["runs"].append({**review["runs"][0], "run_id": "cpu", "cpu_cores": None})
        review["enforcement_review"]["status"] = "manual"
        actual = self.resources(review)
        self.assertLess(len(actual["summary"]), 220)
        self.assertIn("CPU核数", actual["summary"])
        self.assertNotIn("限制生效", actual["summary"])
        self.assertNotIn("GPU 型号", actual["summary"])
        review = complete_resources_fixture(); del review["enforcement_review"]
        self.assertEqual(self.resources(review)["status"], "pass")

    def test_agent_wallclock_is_not_score_budget(self):
        review = complete_resources_fixture()
        review["runs"][0].update(scope="agent_run", score_seconds=36000)
        actual = self.resources(review)
        self.assertEqual(actual["status"], "manual")
        self.assertEqual(actual["problems"], [])

    def test_supported_estimate_passes_without_per_run_allocation_proofs(self):
        review = {"status": "pass", "summary": "Representative logs and code support the estimate.",
            "evidence": ["instruction.md"], "estimate": {"score_seconds": 600, "gpu_count": 1,
            "gpu_type": "H20/L20", "cpu_cores": 4, "basis": "Representative run plus model/data scale; includes margin.",
            "time_accounting": "Complete train/reload/score.", "evidence": ["instruction.md"]}}
        review["hardware_review"] = {**complete_resources_fixture()["hardware_review"], "task_type": "gpu"}
        config = {"environment": {"gpus": 1, "gpu_types": ["H20"]}}
        self.assertEqual(self.resources(review, config)["status"], "pass")
        review["estimate"]["basis"] = ""
        self.assertEqual(self.resources(review, config)["status"], "manual")
        review["estimate"]["basis"] = "Representative logs."
        review["estimate"]["score_seconds"] = 7201
        self.assertEqual(self.resources(review, config)["status"], "fail")

    def test_optimistic_estimate_cannot_hide_observed_score_overrun(self):
        review = complete_resources_fixture()
        review["estimate"] = {**review["runs"][0], "basis": "Estimate."}
        review["runs"][0]["score_seconds"] = 8000
        self.assertEqual(self.resources(review)["status"], "fail")

    def test_missing_formal_run_resources_cannot_be_hidden_by_one_run(self):
        path = self.root / "optimization_evidence/baseline_runs/seed_1/result.json"
        path.parent.mkdir(parents=True); path.write_text('{"role":"baseline","execution":null}')
        self.assertEqual(self.resources(complete_resources_fixture())["status"], "manual")

    def test_representative_score_need_not_cover_each_agent_round(self):
        path = self.root / "scores.json"
        path.write_text('{"rounds":[{"round":1,"status":"success","score":0.5}]}')
        facts = resource_review.collect(self.root, self.files(), trajectory_paths=["scores.json"])
        result = resource_review.apply_review(facts, complete_resources_fixture(), self.root, qa.review_evidence)
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["missing_agent_scores"], [{"source_path": "scores.json", "round": 1}])


if __name__ == "__main__":
    unittest.main()
