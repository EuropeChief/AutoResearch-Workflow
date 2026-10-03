"""OP-3 synthetic contracts, no real model calls or elapsed-time simulation claims."""
import copy
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import test_w2_contract as w2
import test_w3_contract as w3
import test_w4_contract as w4
from test_pca_contract import round_record

from autoresearch_flow.core import FlowError, TaskStore, _canonical_digest, _sha256
from autoresearch_flow.duration import select, snapshot, validate_roll
from autoresearch_flow.experiments import ExperimentBook
from autoresearch_flow.harbor_runtime import final_snapshot
from autoresearch_flow.runtime import Runtime
from autoresearch_flow.w4_package import check_package


def at_stage_four(root):
    store = TaskStore(root)
    state = json.loads(store.state_path.read_text())
    state["current_stage"] = "4"
    for n in range(1, 4):
        stage = state["stages"][str(n)]
        stage["status"] = "passed"
        for sub in stage["substeps"].values():
            sub["status"] = "passed"
    store.state_path.write_text(json.dumps(state))


def decision(ref):
    return {"mode": "non_training_7h", "protocol_id": "p1", "public_dev_protocol": "public-v1",
        "reviewer": "synthetic", "approved_by": "synthetic-user", "rationale": "synthetic qualified short iteration",
        "non_training": True, "no_finetuning": True, "short_iterations": True,
        "non_training_basis": "synthetic no fitting", "short_iteration_basis": "synthetic actual timing sample",
        "evidence": [ref], "iteration_samples": [{"seconds": 90, "evidence": ref}]}


def roll_review(ref):
    return {"reviewer": "synthetic", "continuous_evolution": "方向一到三连续发展", "next_direction": "验证第四方向",
        "typical_round_minutes": 1.5, "rounds": [{"round": n, "consistent": True, "method_iteration": True,
            "method_change": f"方法改动{n}", "score_conclusion": "同口径真实结果", "next_decision": "继续检验下一方向",
            "public_dev_protocol": "public-v1", "evidence": [{"ref": ref, "locator": f"line {n}"}]} for n in range(1, 4)]}


class DurationPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fx = w2.W2Tests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        at_stage_four(self.root)

    def test_default_and_explicit_evidenced_exception(self):
        self.assertEqual(snapshot(self.root)["policy"]["minimum_effective_seconds"], 36000)
        before = TaskStore(self.root).state_path.read_bytes()
        with self.assertRaises(FlowError):
            select(self.root, decision(self.fx.proof))
        self.assertEqual(TaskStore(self.root).state_path.read_bytes(), before)
        selected = select(self.root, decision(self.fx.proof), confirm=True)
        self.assertEqual(selected["policy"]["minimum_effective_seconds"], 25200)
        self.assertEqual(selected["assessment"]["protocol_sha256"], self.fx.lock["sha256"])
        self.assertEqual(TaskStore(self.root).check()["workflow_policy"]["duration_policy"], selected["policy"])
        with self.assertRaises(FlowError):
            select(self.root, decision(self.fx.proof), confirm=True)

    def test_training_short_or_missing_qualification_cannot_reduce_duration(self):
        for field, value in [("non_training", False), ("no_finetuning", False), ("short_iterations", False),
                             ("evidence", []), ("iteration_samples", []), ("protocol_id", "missing")]:
            proposal = decision(self.fx.proof)
            proposal[field] = value
            with self.subTest(field=field), self.assertRaises(FlowError):
                select(self.root, proposal, confirm=True)
        p = copy.deepcopy(self.fx.p)
        p.update(id="training", training=True)
        self.fx.book.lock(p)
        at_stage_four(self.root)
        proposal = decision(self.fx.proof) | {"protocol_id": "training"}
        with self.assertRaises(FlowError) as caught:
            select(self.root, proposal, confirm=True)
        self.assertEqual(caught.exception.code, "DURATION_INELIGIBLE")

    def test_no_retroactive_exception_after_preparation(self):
        (TaskStore(self.root).state_dir / "runtime").mkdir()
        with self.assertRaises(FlowError) as caught:
            select(self.root, decision(self.fx.proof), confirm=True)
        self.assertEqual(caught.exception.code, "DURATION_FROZEN")

    def test_changed_qualification_evidence_is_detected(self):
        select(self.root, decision(self.fx.proof), confirm=True)
        (self.root / self.fx.proof["path"]).write_text("changed")
        with self.assertRaises(FlowError):
            snapshot(self.root)

    def test_three_real_method_loops_and_continuity_required(self):
        rows = [round_record(n, f"改动{n}") for n in range(1, 4)]
        rows[1].update(status="method_failure", score=None, failure_reason="真实方法失败", retained_best=False)
        review = roll_review(self.fx.proof)
        self.assertEqual(validate_roll(self.root, rows, review, "public-v1"), 3)
        for kind in ("two_loops", "debugging", "duplicate", "no_future", "mixed_protocol"):
            r = copy.deepcopy(review)
            if kind == "two_loops": r["rounds"] = r["rounds"][:2]
            if kind == "debugging": r["rounds"][0]["method_iteration"] = False
            if kind == "duplicate": r["rounds"][1]["method_change"] = r["rounds"][0]["method_change"]
            if kind == "no_future": r["next_direction"] = ""
            if kind == "mixed_protocol": r["rounds"][0]["public_dev_protocol"] = "other"
            with self.subTest(kind=kind), self.assertRaises(FlowError):
                validate_roll(self.root, rows, r, "public-v1")


class RuntimeDurationTests(unittest.TestCase):
    def setUp(self):
        self.fx = w3.RuntimeTests()
        self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        source = w2.W2Tests()
        source.setUp()
        self.addCleanup(source.doCleanups)
        ExperimentBook(self.root).lock(source.p)
        at_stage_four(self.root)
        proof = self.root / "eligibility.log"
        proof.write_text("SYNTHETIC short non-training round")
        self.ref = {"path": "eligibility.log", "sha256": _sha256(proof)}
        select(self.root, decision(self.ref), confirm=True)
        prompt = self.root / self.fx.config["prompt"]["path"]
        prompt.write_text("{{DURATION_REQUIREMENT}}")
        self.fx.config["prompt"]["sha256"] = _sha256(prompt)

    def test_prepare_binds_both_tracks_prompts_and_resume(self):
        self.fx.prepare()
        runtime = self.fx.runtime
        self.assertIn("至少 7 小时", (runtime.directory / "prompt.md").read_text())
        self.assertIn("至少 7 小时", runtime.continuation_prompt())
        for t in ("codex", "seed"):
            self.assertEqual(runtime.status(t)["minimum_seconds"], 25200)
        state = runtime._state("seed")
        state["duration_sha256"] = "wrong"
        runtime._save("seed", state)
        with self.assertRaises(FlowError) as caught:
            runtime.status("codex")
        self.assertEqual(caught.exception.code, "DURATION_DRIFT")

    def test_net_time_not_wall_time_or_other_track_sum(self):
        self.fx.prepare()
        runtime = self.fx.runtime
        for track in ("codex", "seed"):
            state = runtime._state(track)
            state["thread_id"] = "thread-" + track
            state["segments"] = [{"phase": "formal", "status": "completed", "intervals": [[0, 26000]],
                                  "logs": [], "unverified_seconds": 0}]
            state["exclusions"] = [{"start": 0, "end": 900, "evidence": [self.ref]}]
            runtime._save(track, state)
            self.assertEqual(runtime.status(track)["status"], "not_ready_or_paused")
            state["exclusions"][0]["end"] = 800
            runtime._save(track, state)
            self.assertEqual(runtime.status(track)["status"], "duration_reached")
        base = runtime.directory / "codex/formal"
        best = base / "output/best_method"
        best.mkdir()
        (best / "method.py").write_bytes((base / "solution/method.py").read_bytes())
        (base / "output/trajectory.jsonl").write_text("\n".join(json.dumps(round_record(n, f"改动{n}")) for n in range(1, 4)))
        self.assertEqual(final_snapshot(runtime, "codex")["thread_id"], "thread-codex")
        state = runtime._state("codex")
        state["preflight"] = {"ready": True, "config_sha256": _canonical_digest(runtime.config)}
        runtime._save("codex", state)
        self.assertEqual(runtime.run("codex", 1, resume=True, confirm_cost=True)["status"], "duration_reached")
        self.assertEqual(self.fx.backend.commands, [])  # No unnecessary 10h continuation.
        state["exclusions"][0]["end"] = 801
        runtime._save("codex", state)
        with self.assertRaises(FlowError) as caught:
            final_snapshot(runtime, "codex")
        self.assertEqual(caught.exception.code, "FINAL_NOT_READY")

    def test_rejects_conflicting_prompt(self):
        prompt = self.root / self.fx.config["prompt"]["path"]
        prompt.write_text("{{DURATION_REQUIREMENT}} 至少10小时")
        self.fx.config["prompt"]["sha256"] = _sha256(prompt)
        with self.assertRaises(FlowError) as caught:
            self.fx.prepare()
        self.assertEqual(caught.exception.code, "DURATION_PROMPT")


class ExceptionPackageTests(unittest.TestCase):
    def setUp(self):
        proto = w2.W2Tests()
        proto.setUp()
        self.addCleanup(proto.doCleanups)
        original_init = TaskStore.initialize

        def initialize(store, *args, **kwargs):
            result = original_init(store, *args, **kwargs)
            ExperimentBook(store.task_root).lock(proto.p)
            at_stage_four(store.task_root)
            proof = store.task_root / "eligibility.log"
            proof.write_text("SYNTHETIC qualification, not an actual task")
            select(store.task_root, decision({"path": "eligibility.log", "sha256": _sha256(proof)}), confirm=True)
            return result

        self.fx = w4.DeliveryTests()
        with patch.object(TaskStore, "initialize", initialize):
            self.fx.setUp()
        self.addCleanup(self.fx.doCleanups)
        self.root = self.fx.root
        self.fx.status_patch.stop()
        self.fx.state_patch.stop()
        self.states = {}
        for track in ("codex", "seed"):
            output = self.fx.runtime.directory / track / "formal/output"
            (output / "trajectory.jsonl").write_text("\n".join(json.dumps(round_record(n, f"方法改动{n}"), ensure_ascii=False) for n in range(1, 4)))
            log = self.fx.runtime.directory / track / "logs/segment-1/events.jsonl"
            log.write_text("SYNTHETIC tool event 1\nSYNTHETIC tool event 2\nSYNTHETIC tool event 3\n")
            self.states[track] = {"segments": [{"segment_id": "segment-1", "phase": "formal", "status": "completed",
                "intervals": [[0, 25200]], "logs": [{"path": str(log.relative_to(self.fx.runtime.directory)), "sha256": _sha256(log)}]}],
                "exclusions": []}
        self.status_patch = patch.object(Runtime, "status", side_effect=lambda t: {
            "active": None, "thread_id": "thread-" + t, "effective_seconds_before_content_review": 25200})
        self.state_patch = patch.object(Runtime, "_state", side_effect=lambda t: self.states[t])
        self.status_patch.start()
        self.state_patch.start()
        self.addCleanup(self.status_patch.stop)
        self.addCleanup(self.state_patch.stop)
        for track in ("codex", "seed"):
            self.fx.ev.finalize_trajectory(track)
            log = self.fx.runtime.directory / track / "logs/segment-1/events.jsonl"
            self.fx.ev.review_trajectory(track, roll_review(self.fx.ref(log)))
        # Stage 4 evidence is valid before any stage-5 rerun exists.
        self.assertFalse((self.fx.ev.directory / "best_verification_current.json").exists())
        results = {}
        for track, score in (("codex", .4), ("seed", .5)):
            p = self.root / f"{track}-result.json"
            p.write_text(json.dumps({"status": "succeeded", "score": score}))
            results[track] = {"result": self.fx.ref(p)}
        chosen = self.fx.ev.snapshot_best({"selected_track": "seed", "rationale": "synthetic higher", "candidate_results": results})
        method = _canonical_digest(sorted(chosen["method_files"], key=lambda x: x["path"]))
        self.protocol_hash = snapshot(self.root)["assessment"]["protocol_sha256"]
        self.best = {"status": "ok", "protocol_sha256": self.protocol_hash, "experiment_sha256": "e-best",
                     "groups": {"best_method": {"method_sha256": method, "mean": .5}}}
        clean, log = self.root / "clean.json", self.root / "clean.log"
        clean.write_text(json.dumps({"status": "succeeded", "score": .5, "method_sha256": method,
            "execution": {"exit_code": 0, "command": ["evaluate"], "started_at": "t1", "finished_at": "t2"}}))
        log.write_text("SYNTHETIC clean snapshot success")
        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", return_value=self.best):
            self.fx.ev.verify_best({"protocol_id": "p1", "clean_result": self.fx.ref(clean), "clean_log": self.fx.ref(log),
                "reviewer": "synthetic", "rationale": "synthetic clean rerun"})
        self.spec = self.fx.prepare_package_sources()
        summary = self.root / "summary.json"
        value = json.loads(summary.read_text())
        for item in value["agent_execution"]:
            item.update(duration_hours=7, effective_rounds=3, typical_round_minutes=1.5)
        value["fast_iteration_exception"].update(used=True, non_training=True, short_iterations=True, rollable_proved=True,
            evidence="不训练，典型1.5分钟，三轮闭环和干净重跑，见duration_evidence.json")
        summary.write_text(json.dumps(value))
        self.spec["run_summary"] = self.fx.ref(summary)

    def build(self):
        original_report = self.fx.reports(self.best)

        def report(*args):
            value = original_report(*args)
            if "evaluation_protocol" in value:
                value["evaluation_protocol"]["training"] = False
            return value

        with patch("autoresearch_flow.w4_evidence.ExperimentBook.report", return_value=self.best), \
             patch("autoresearch_flow.w4_package.ExperimentBook.report", side_effect=report):
            return Path(self.fx.package.build(self.spec)["package_path"])

    def test_seven_hour_package_is_self_contained_and_eight_fields_unchanged(self):
        package = self.build()
        checked = check_package(package)
        self.assertEqual(checked["trajectory_rounds"], {"codex": 3, "seed": 3})
        for track in ("codex", "seed"):
            rows = json.loads((package / f"expert_evidence/trajectory_{track}.json").read_text())["rounds"]
            self.assertEqual(set(rows[0]), set(round_record()))
        self.assertIn("7h 例外证据", (package / "expert_evidence/专家作业说明文档.md").read_text())

    def test_package_cannot_self_declare_training_or_short_duration_exception(self):
        package = self.build()
        summary_path = package / "expert_evidence/run_summary.json"
        original = summary_path.read_bytes()
        for key, value in (("duration_hours", 6.99), ("effective_rounds", 2), ("typical_round_minutes", 99)):
            summary = json.loads(original)
            summary["agent_execution"][0][key] = value
            summary_path.write_text(json.dumps(summary))
            with self.subTest(key=key), self.assertRaises(FlowError):
                check_package(package)
        summary_path.write_bytes(original)
        comparison = package / "optimization_evidence/comparison_summary.json"
        value = json.loads(comparison.read_text())
        value["evaluation_protocol"]["training"] = True
        comparison.write_text(json.dumps(value))
        with self.assertRaises(FlowError) as caught:
            check_package(package)
        self.assertEqual(caught.exception.code, "DURATION_INELIGIBLE")

    def test_missing_clean_evidence_and_changed_final_method_block(self):
        package = self.build()
        path = package / "expert_evidence/duration_evidence.json"
        bundle = json.loads(path.read_text())
        log = package / bundle["clean_verification"]["log"]["path"]
        original = log.read_bytes()
        log.write_text("changed")
        with self.assertRaises(FlowError):
            check_package(package)
        log.write_bytes(original)
        (package / "expert_evidence/best_method/method.py").write_text("different best")
        with self.assertRaises(FlowError) as caught:
            check_package(package)
        self.assertEqual(caught.exception.code, "CLEAN_RERUN_INVALID")

    def test_two_sessions_cannot_share_thread_or_combine_time(self):
        package = self.build()
        path = package / "expert_evidence/duration_evidence.json"
        bundle = json.loads(path.read_text())
        bundle["tracks"]["seed"]["thread_id"] = bundle["tracks"]["codex"]["thread_id"]
        path.write_text(json.dumps(bundle))
        with self.assertRaises(FlowError) as caught:
            check_package(package)
        self.assertEqual(caught.exception.code, "ROLL_EVIDENCE")

    def test_duration_under_threshold_blocks_trajectory_finalization(self):
        self.status_patch.stop()
        with patch.object(Runtime, "status", return_value={"active": None, "thread_id": "t",
            "effective_seconds_before_content_review": 6.99 * 3600}), self.assertRaises(FlowError) as caught:
            self.fx.ev.finalize_trajectory("codex")
        self.assertEqual(caught.exception.code, "DURATION_SHORT")

    def test_no_stage_four_requirement_for_future_clean_rerun_but_build_requires_it(self):
        pointer = self.fx.ev.directory / "best_verification_current.json"
        pointer.unlink()
        self.assertEqual(self.fx.ev.current_review("seed")["track"], "seed")
        with self.assertRaises(FlowError):
            self.build()

    def test_interrupted_final_segment_needs_original_session_resume(self):
        self.states["seed"]["segments"][-1]["status"] = "failed"
        with self.assertRaises(FlowError) as caught:
            self.fx.ev.finalize_trajectory("seed")
        self.assertEqual(caught.exception.code, "TRAJECTORY_RUNNING")
