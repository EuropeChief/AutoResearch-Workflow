"""Synthetic W2 contracts. No task training or scientific claims."""
import copy
import json
import subprocess
import sys
import tempfile
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoresearch_flow.core import FlowError, Registry, TaskStore, _sha256
from autoresearch_flow.experiments import ExperimentBook, baseline_check, normalize, score_check, validate_protocol


class W2Tests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-w2-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        TaskStore(self.root).initialize(Registry(), "synthetic")
        self.book = ExperimentBook(self.root)
        self.method = self.ref("method.py", "# synthetic method")
        self.proof = self.ref("reason.md", "Synthetic expert evidence, not a real finding.")
        self.p = {"schema_version": 1, "id": "p1", "metric": {"name": "quality", "direction": "maximize"},
                  "seeds": [1, 2, 3], "training": False, "evaluation_mode": "random",
                  "fixed": {"data": "a"*64, "preprocessing": "b"*64, "evaluator": "c"*64},
                  "budget": {"updates": {"mode": "exact", "value": 100, "unit": "steps"}},
                  "rationale": "Synthetic common budget.", "reload_tolerance": 0.001}
        self.lock = self.book.lock(self.p)

    def ref(self, name, text):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
        return {"path": name, "sha256": _sha256(path)}

    def start(self, role, seed, run_id=None, **extra):
        return self.book.start({"run_id": run_id or f"{role}-{seed}", "protocol_id": "p1",
                                "role": role, "seed": seed, "method_files": [self.method], **extra})

    def finish(self, run, value, **changes):
        result = {"status": "succeeded", "seed": run["seed"], "role": run["role"],
                  "protocol_sha256": run["protocol_sha256"], "method_sha256": run["method_sha256"], "seed_plan_sha256": run["seed_plan_sha256"],
                  "fixed": self.p["fixed"], "raw_metric": value, "quality_passed": True,
                  "actual_budget": {"updates": 100},
                  "execution": {"command": None, "started_at": None, "finished_at": None, "exit_code": None, "missing_reason": "Synthetic test: no real training executed."}}
        if self.p["training"]:
            result.update(training_origin="initialization", reload_passed=True, reload_metric=value)
        result.update(changes)
        refs = {"log": self.ref(run["run_id"]+"/run.log", "synthetic stdout"),
                "result": self.ref(run["run_id"]+"/result.json", json.dumps(result))}
        if self.p["training"]:
            model = self.ref(run["run_id"]+"/model.bin", run["run_id"])
            artifact = {"seed": run["seed"], "role": run["role"], "method_sha256": run["method_sha256"],
                        "sha256": model["sha256"], "size_bytes": (self.root/model["path"]).stat().st_size,
                        "reload_metric": result["reload_metric"], "format": "synthetic-text"}
            refs.update(model=model, artifact=self.ref(run["run_id"]+"/artifact.json", json.dumps(artifact)),
                        reload_log=self.ref(run["run_id"]+"/reload.log", "synthetic reload"))
        result["evidence"] = refs
        return self.book.finish(run["run_id"], result)

    def pair(self, b=(9, 10, 11), r=(14, 15, 16)):
        for role, values in (("baseline", b), ("reference", r)):
            for seed, value in zip(self.p["seeds"], values):
                self.finish(self.start(role, seed), value)

    def review(self):
        report = self.book.report("p1")
        return {"protocol_sha256": self.lock["sha256"], "experiment_sha256": report["experiment_sha256"],
                "baseline_method_sha256": report["groups"]["baseline"]["method_sha256"],
                "reference_method_sha256": report["groups"]["reference"]["method_sha256"],
                "checks": {f"B{i:02d}": {"status": "pass", "reviewer": "synthetic expert",
                    "rationale": "Synthetic fixture only.", "evidence": [self.proof]} for i in range(1, 9)}}

    def test_maximize_sample_std_and_pairing(self):
        self.pair()
        r = self.book.report("p1")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(r["groups"]["baseline"]["sample_std"], 1)
        self.assertEqual(r["improvement"], 5)
        self.assertEqual(r["baseline_sigma_multiple"], 5)
        self.assertEqual(len(r["paired_results"]), 3)

    def test_minimize_and_deterministic_single_run(self):
        p = copy.deepcopy(self.p)
        p.update(id="min", evaluation_mode="deterministic", seeds=[7])
        p["metric"]["direction"] = "minimize"
        validate_protocol(p)
        self.assertEqual(normalize(5, 10, 0, "minimize"), 0.5)
        self.assertEqual(normalize(-1, 10, 0, "minimize"), 1.1)
        self.assertEqual(normalize(11, 10, 0, "minimize"), -0.1)
        self.assertEqual(normalize(None, 10, 0, "minimize", hard_gate_passed=False), -1)
        self.book.lock(p)
        self.p = p
        for role, value in (("baseline", 10), ("reference", 5)):
            run = self.book.start({"run_id": role, "protocol_id": "min", "role": role, "seed": 7, "method_files": [self.method]})
            self.finish(run, value)
        self.assertEqual(self.book.report("min")["status"], "ok")
        self.assertIsNone(self.book.report("min")["groups"]["baseline"]["sample_std"])

    def test_hard_gate_minus_one_does_not_clip_valid_scores(self):
        for direction, upper, raw_values in (
            ("maximize", 20, (0, -5, 10, 15, 20, 25)),
            ("minimize", 0, (20, 25, 10, 5, 0, -5)),
        ):
            with self.subTest(direction=direction):
                self.assertEqual(normalize(None, 10, upper, direction, hard_gate_passed=False), -1)
                self.assertEqual([normalize(raw, 10, upper, direction) for raw in raw_values],
                                 [-1, -1.5, 0, 0.5, 1, 1.5])

    def test_score_contract_and_wrong_upper_bounds(self):
        self.pair()
        contract = {"protocol_sha256": self.lock["sha256"], "upper_bound": 20, "metric_ceiling": 100, "rationale": "Synthetic ex ante reasoning", "evidence": [self.proof]}
        result = score_check(self.book, "p1", contract)
        self.assertEqual(result["reference_score"], 0.5)
        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["anchors"], {"baseline": 10, "reference": 15,
                                            "upper_bound": 20, "metric_ceiling": 100})
        self.assertIn("hard gate failure = -1", result["formula"])
        self.assertIn("excluded by status", result["formula"])
        for u in (10, 9, float("nan"), float("inf"), True):
            with self.assertRaises(FlowError):
                normalize(15, 10, u, "maximize")
        self.assertEqual(score_check(self.book, "p1", {**contract, "upper_bound": 15})["status"], "blocked")
        with self.assertRaises(FlowError):
            score_check(self.book, "p1", {**contract, "metric_ceiling": 19})

    def test_three_to_five_sigma_is_not_unconditional_pass(self):
        self.pair(r=(13, 14, 15))
        r = self.book.report("p1")
        self.assertEqual(r["evidence_strength"], "needs_more_runs")
        self.assertEqual(r["status"], "needs_review")

    def test_zero_variance_still_requires_positive_improvement(self):
        self.pair(b=(10, 10, 10), r=(10, 10, 10))
        self.assertEqual(self.book.report("p1")["status"], "blocked")

    def test_missing_seed_and_failed_run_retained(self):
        run = self.start("baseline", 1)
        self.book.finish(run["run_id"], {"status": "failed", "error": "numerical failure", "evidence": {"log": self.ref("failed.log", "NaN")}})
        result = self.book.report("p1")
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["attempts"][0]["status"], "failed")
        with self.assertRaises(FlowError):
            self.start("baseline", 1, "cannot-select-again", retry_of=run["run_id"])

    def test_cli_failure_types_are_retained_and_excluded_from_aggregation(self):
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        for status in ("hard_gate_failure", "format_error", "timeout", "resource_exceeded", "infra_error", "failed"):
            with self.subTest(status=status):
                protocol_id = "failure-" + status
                self.book.lock({**self.p, "id": protocol_id})
                run = self.book.start({"run_id": protocol_id, "protocol_id": protocol_id,
                                       "role": "best_method", "seed": 1, "method_files": [self.method]})
                failure = {"status": status, "error": f"Synthetic {status}: inspect log and correct the cause.",
                           "raw_metric": 999, "evidence": {"log": self.ref(protocol_id + ".log", status)}}
                if status == "hard_gate_failure":
                    failure["score"] = -1
                result_file = self.ref(protocol_id + ".json", json.dumps(failure))
                result = subprocess.run([sys.executable, str(cli), "--format", "json", "experiment", "finish",
                                         "--task-root", str(self.root), "--run-id", run["run_id"],
                                         "--file", str(self.root / result_file["path"])], capture_output=True, text=True)
                self.assertEqual(result.returncode, 2, result.stderr)
                recorded = json.loads(result.stdout)
                self.assertEqual(recorded["status"], status)
                self.assertEqual(recorded["result"], failure)
                for seed, value in ((2, 9), (3, 11)):
                    valid = self.book.start({"run_id": f"{protocol_id}-{seed}", "protocol_id": protocol_id,
                                             "role": "best_method", "seed": seed, "method_files": [self.method]})
                    self.finish(valid, value)
                report = self.book.report(protocol_id, ("best_method",))
                self.assertEqual(report["status"], "blocked")
                attempts = {item["run_id"]: item for item in report["attempts"]}
                self.assertEqual(attempts[run["run_id"]]["status"], status)
                self.assertEqual(report["groups"]["best_method"]["values"], {"2": 9, "3": 11})
                self.assertEqual(report["groups"]["best_method"]["mean"], 10)
                self.assertEqual(len(report["issues"]), 1)
                self.assertIn(status, report["issues"][0])

    def test_successful_negative_scores_remain_valid_in_aggregation(self):
        for seed, raw in zip(self.p["seeds"], (0, -5, 5)):
            score = normalize(raw, 10, 20, "maximize")
            result = self.finish(self.start("best_method", seed), raw, score=score)
            self.assertEqual(result["status"], "succeeded")
        report = self.book.report("p1", ("best_method",))
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["groups"]["best_method"]["count"], 3)
        self.assertEqual(report["groups"]["best_method"]["mean"], 0)
        scores = [normalize(raw, 10, 20, "maximize")
                  for raw in report["groups"]["best_method"]["values"].values()]
        self.assertEqual(sorted(scores, reverse=True), [-0.5, -1, -1.5])

    def test_infrastructure_retry_disclosed_and_evidence_not_dropped(self):
        run = self.start("baseline", 1, "broken")
        failure = self.ref("failure.log", "external failure")
        self.book.finish("broken", {"status": "infra_error", "error": "external failure", "evidence": {"log": failure}})
        self.finish(self.start("baseline", 1, "retried", retry_of="broken"), 9)
        for role, values in (("baseline", [(2, 10), (3, 11)]), ("reference", [(1, 14), (2, 15), (3, 16)])):
            for seed, value in values:
                self.finish(self.start(role, seed), value)
        r = self.book.report("p1")
        self.assertEqual(r["status"], "ok")
        self.assertEqual(len(r["attempts"]), 7)
        (self.root/"failure.log").write_text("rewritten")
        self.assertEqual(self.book.report("p1")["status"], "blocked")

    def test_wrong_seed_budget_and_protocol(self):
        with self.assertRaises(FlowError):
            self.start("baseline", 4)
        self.pair()
        data = json.loads(self.book.path.read_text())
        data["runs"]["baseline-1"]["result"]["actual_budget"]["updates"] = 99
        self.book.path.write_text(json.dumps(data))
        self.assertEqual(self.book.report("p1")["status"], "blocked")

    def test_raw_result_cannot_disagree_with_ledger(self):
        self.pair()
        data = json.loads(self.book.path.read_text())
        data["runs"]["baseline-1"]["result"]["raw_metric"] = -100
        self.book.path.write_text(json.dumps(data))
        self.assertIn("原始 result", " ".join(self.book.report("p1")["issues"]))

    def test_training_requires_checkpoint_and_reload(self):
        self.p = {**self.p, "id": "training", "training": True}
        self.book.lock(self.p)
        for seed in (1, 2, 3):
            run = self.book.start({"run_id": f"train-{seed}", "protocol_id": "training", "role": "baseline", "seed": seed, "method_files": [self.method]})
            self.finish(run, 10, reload_metric=9)
        self.assertEqual(self.book.report("training", ("baseline",))["status"], "blocked")

    def test_baseline_expert_reviews_and_deferral(self):
        self.pair()
        review = self.review()
        review["checks"]["B03"].update(status="deferred", due_stage=3, current_part_passed=True, pending_requirement="actual B/R budget comparison")
        self.assertEqual(baseline_check(self.book, "p1", review, 2)["deferred"], ["B03"])
        with self.assertRaises(FlowError):
            baseline_check(self.book, "p1", review, 3)
        review["checks"]["B03"]["status"] = "pass"
        self.assertEqual(baseline_check(self.book, "p1", review, 3)["status"], "ready_for_expert_confirmation")
        review["checks"]["B01"]["status"] = "manual"
        self.assertEqual(baseline_check(self.book, "p1", review, 2)["status"], "blocked")

    def test_no_protocol_overwrite_or_seed_cherry_pick(self):
        with self.assertRaises(FlowError):
            self.book.lock(self.p)
        self.start("baseline", 1)
        with self.assertRaises(FlowError):
            self.start("baseline", 1, "duplicate")
        bad = {**self.p, "seeds": [1, 2]}
        with self.assertRaises(FlowError):
            validate_protocol(bad)

    def test_parallel_registration_does_not_lose_runs(self):
        with ThreadPoolExecutor(max_workers=6) as pool:
            results = list(pool.map(lambda pair: self.start(*pair), [(r, s) for r in ("baseline", "reference") for s in (1, 2, 3)]))
        self.assertEqual(len(results), 6)
        self.assertEqual(len(json.loads(self.book.path.read_text())["runs"]), 6)

    def test_extend_seeds_preserves_original_runs_and_invalidates_old_review(self):
        self.pair()
        review = self.review()
        old = copy.deepcopy(json.loads(self.book.path.read_text())["runs"])
        self.book.extend("p1", {"seeds": [4, 5], "reason": "predeclare additional repeats"})
        self.assertEqual(json.loads(self.book.path.read_text())["runs"], old)
        self.assertEqual(self.book.report("p1")["status"], "blocked")
        for role, value in (("baseline", 10), ("reference", 15)):
            for seed in (4, 5):
                self.finish(self.start(role, seed), value)
        report = self.book.report("p1")
        self.assertEqual(report["status"], "ok")
        self.assertEqual(report["seeds"], [1, 2, 3, 4, 5])
        self.assertEqual(report["groups"]["baseline"]["count"], 5)
        with self.assertRaises(FlowError):
            baseline_check(self.book, "p1", review, 3)
        with self.assertRaises(FlowError):
            self.book.extend("p1", {"seeds": [1], "reason": "illegal repeat"})

    def test_maximum_budget_allows_legal_early_stopping(self):
        self.p = copy.deepcopy(self.p)
        self.p["id"] = "maximum"
        self.p["budget"]["updates"]["mode"] = "maximum"
        self.book.lock(self.p)
        for seed in (1, 2, 3):
            run = self.book.start({"run_id": f"max-{seed}", "protocol_id": "maximum", "role": "baseline", "seed": seed, "method_files": [self.method]})
            result = self.finish(run, 10, actual_budget={"updates": 50})
            self.assertEqual(result["status"], "succeeded")
        self.assertEqual(self.book.report("maximum", ("baseline",))["status"], "ok")

    def test_nonfinite_metric_saved_as_invalid_not_lost(self):
        run = self.start("baseline", 1)
        r = self.finish(run, float("nan"))
        self.assertEqual(r["status"], "recorded_invalid")
        self.assertTrue(r["validation_issues"])
        self.assertNotIn("NaN", self.book.path.read_text())
        self.assertEqual(len(json.loads(self.book.path.read_text())["runs"]), 1)

    def test_training_evidence_success_and_model_hash_drift(self):
        self.p = {**self.p, "id": "train-ok", "training": True}
        self.book.lock(self.p)
        for seed in (1, 2, 3):
            run = self.book.start({"run_id": f"ok-{seed}", "protocol_id": "train-ok", "role": "baseline", "seed": seed, "method_files": [self.method]})
            self.assertEqual(self.finish(run, 10)["status"], "succeeded")
        self.assertEqual(self.book.report("train-ok", ("baseline",))["status"], "ok")
        (self.root/"ok-1/model.bin").write_text("changed")
        self.assertEqual(self.book.report("train-ok", ("baseline",))["status"], "blocked")

    def test_protocol_revision_invalidates_passed_stages_and_keeps_runs(self):
        self.pair()
        old_runs = copy.deepcopy(json.loads(self.book.path.read_text())["runs"])
        state = json.loads(self.book.store.state_path.read_text())
        state["current_stage"] = None
        for stage in state["stages"].values():
            stage["status"] = "passed"
            for substep in stage["substeps"].values():
                substep["status"] = "passed"
        self.book.store.state_path.write_text(json.dumps(state))
        self.book.lock({**self.p, "id": "p2", "rationale": "new fixed protocol"})
        checked = self.book.store.check()
        self.assertEqual(checked["current_stage"], "2")
        self.assertEqual(checked["stage_statuses"]["1"], "passed")
        self.assertEqual(checked["stage_statuses"]["3"], "needs_recheck")
        self.assertEqual(json.loads(self.book.path.read_text())["runs"], old_runs)

    def test_high_variance_requires_five_declared_repeats(self):
        with self.assertRaises(FlowError):
            validate_protocol({**self.p, "high_variance": True})
        validate_protocol({**self.p, "high_variance": True, "seeds": [1, 2, 3, 4, 5]})

    def test_cli_report_blocks_incomplete_group(self):
        cli = Path(__file__).resolve().parents[1] / "cli.py"
        result = subprocess.run([sys.executable, str(cli), "--format", "json", "experiment", "report", "--task-root", str(self.root), "--protocol", "p1"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2, result.stderr)
        self.assertEqual(json.loads(result.stdout)["status"], "blocked")


if __name__ == "__main__":
    unittest.main()
