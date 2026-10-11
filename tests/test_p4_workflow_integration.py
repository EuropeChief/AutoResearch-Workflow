"""P4 integration: synthetic stages/consent/QA, real tiny CPU subprocesses.

No model, Docker, GPU, genuine long trajectory or scientific QA is run here.
Fixture decisions never authorize work outside each temporary directory.
"""
from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path

from autoresearch_flow.common import _sha256
from autoresearch_flow.experiment_data import summarize, write_summary
from autoresearch_flow.experiment_run import run
from autoresearch_flow.materials_assemble import assemble
from autoresearch_flow.materials_trajectory import prepare
from autoresearch_flow.package_delivery import package
from autoresearch_flow.preflight import Preflight
from autoresearch_flow.task_workspace import TaskWorkspace
from test_independent_materials import fixture as material_fixture
from test_independent_packaging import NOTES
from test_qa_contract import synthetic_report

FLOW = Path(__file__).resolve().parents[1]


class WorkflowIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="ar-p4-integration-")
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.root = self.base / "合成题目"
        self.root.mkdir()
        self.checker = Preflight(self.root)
        self.evidence = {}

    def put(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value if isinstance(value, str) else json.dumps(value, ensure_ascii=False), encoding="utf-8")
        return path

    def inputs(self, stage, *, before=None, phase="enter"):
        """Only test routing/binding; fixture reviews do not certify the sources."""
        result = self.checker.check(stage, before=before, phase=phase)
        roles = {role for row in result["obligations"] for role in row["required_evidence"]}
        for item in self.checker.rules.stages():
            if item["id"] <= stage:
                roles.update(item.get("confirmation_evidence", []))
        for role in roles:
            if role not in self.evidence:
                self.evidence[role] = f"evidence/{role}.md"
                self.put(self.evidence[role], f"SYNTHETIC {role}; not genuine scientific/runtime evidence.\n")
        bindings = {role: _sha256(self.root / (ref if isinstance(ref, str) else ref["path"]))
                    for role, ref in self.evidence.items()}
        self.put("assessment/check.json", {"status": "passed", "issues": [], "scope": "synthetic routing only"})
        self.put("assessment/review.md", "Fixture reviewer: synthetic routing only, no real consent or scientific finding.\n")
        keys = [row["id"] for row in result["obligations"]]
        return {"evidence": dict(self.evidence),
                "checks": [{"obligations": keys, "report": "assessment/check.json", "bindings": bindings}],
                "reviews": [{"obligations": keys, "report": "assessment/review.md", "bindings": bindings,
                             "reviewer": "synthetic fixture reviewer", "summary": "synthetic routing, not actual validation", "conclusion": "PASS"}]}

    def decide(self, gate, inputs):
        stage = next(s["id"] for s in self.checker.rules.stages() if s["gate"] == gate)
        result = self.checker.check(stage, inputs, before=gate)
        proposal = next(row["proposal"] for row in result["confirmations"] if row["gate"] == gate)
        self.append_decision({**proposal, "status": "approved", "approver": "SYNTHETIC fixture expert",
                              "limits": "temporary fixture only; no real resources or launch authorization"})

    def append_decision(self, fields):
        fields = dict(fields)
        gate = fields.pop("gate")
        path = self.root / ".autoresearch/decision-log.md"
        previous = path.read_text(encoding="utf-8") if path.exists() else ""
        body = f"## 2026-10-11T00:00:00Z — {gate}\n"
        body += "\n".join(f"- {k}: {json.dumps(v, ensure_ascii=False) if isinstance(v, dict) else v}"
                          for k, v in fields.items()) + "\n"
        self.put(path.relative_to(self.root).as_posix(), previous + body)

    def test_six_stages_real_cpu_statistics_and_three_archives(self):
        workspace = TaskWorkspace(self.root)
        self.assertEqual(workspace.status()["mode"], "new")
        workspace.init_git(confirm=True)
        # Local fixture identity only. Never changes the user's/global identity.
        for key, value in (("user.name", "P4 synthetic fixture"), ("user.email", "fixture@example.invalid")):
            subprocess.run(["git", "-C", str(self.root), "config", "--local", key, value], check=True)
        self.put("research/notes.md", "SYNTHETIC research direction, not a real task.\n")
        plan = workspace.preview([".gitignore", "research/notes.md"])
        checkpoint = workspace.checkpoint(plan, "synthetic initial checkpoint", confirm=True)
        self.assertTrue(checkpoint["commit"])

        first = self.inputs(1, before="research_contract")
        self.assertFalse(self.checker.check(1, first, before="research_contract")["ready"])
        self.decide("research_contract", first)
        self.assertTrue(self.checker.check(1, first, phase="exit")["ready"])
        second = self.inputs(2, before="task_ready")
        self.assertTrue(self.checker.check(2, second, before="task_ready")["ready"])

        sources = self.root / "material-sources"
        sources.mkdir()
        protocol, rounds = material_fixture(sources)
        protocol["seeds"] = [1, 2, 3, 4, 5]
        method = self.root / "cpu-method"
        method.mkdir()
        shutil.copyfile(FLOW / "tests/fixtures/experiment_method.py", method / "main.py")
        groups = {}
        for role, offset in (("baseline", 0), ("reference", -6)):
            groups[role] = self.root / "experiments" / role
            output = run(method, protocol, groups[role],
                         [sys.executable, "{method}/main.py", "--offset", str(offset)], role=role, jobs=2)
            self.assertEqual(output["status"], "COMPLETE")
        statistics = summarize([groups["baseline"], groups["reference"]],
                               score_contract={"upper_bound": 4, "rationale": "synthetic known bound"})
        self.assertEqual(statistics["statistics"]["paired_run_count"], 5)
        self.assertEqual(statistics["statistics"]["baseline_mean"], 13)
        self.assertEqual(statistics["statistics"]["reference_mean"], 7)
        self.assertTrue(statistics["significance_rule"]["passed"])
        self.assertAlmostEqual(statistics["normalization"]["reference"], 2 / 3)
        self.assertEqual(statistics["scientific_review"], "NOT_PERFORMED")
        stat_dir = self.root / "experiments/comparison"
        write_summary(statistics, stat_dir)
        self.put("protocol.json", protocol)
        self.evidence.update({
            "formal_protocol": {"path": "protocol.json", "validator": "protocol"},
            "baseline_formal_results": "experiments/baseline/seed_1/result.json",
            "reference_formal_results": "experiments/reference/seed_1/result.json",
            "comparison_summary": "experiments/comparison/comparison_summary.json",
        })
        third = self.inputs(3, before="anchor_freeze")
        self.assertFalse(self.checker.check(3, third, before="anchor_freeze")["ready"])
        self.decide("anchor_freeze", third)
        self.assertTrue(self.checker.check(3, third, before="anchor_freeze")["ready"])

        fourth = self.inputs(4, before="dual_track_launch")
        # No future trajectories/timing are required to authorize a first launch.
        self.assertNotIn("trajectory_codex", fourth["evidence"])
        self.assertNotIn("timing_ledger", fourth["evidence"])
        self.assertFalse(self.checker.check(4, fourth, before="dual_track_launch")["ready"])
        self.decide("dual_track_launch", fourth)
        self.assertTrue(self.checker.check(4, fourth, before="dual_track_launch")["ready"])
        for track in ("codex", "seed"):
            raw = self.put(f"simulated-tracks/{track}.jsonl", "\n".join(json.dumps(row) for row in rounds) + "\n")
            target = self.root / f"simulated-tracks/{track}.json"
            original = raw.read_bytes()
            self.assertEqual(prepare(raw, target)["status"], "prepared")
            self.assertEqual(raw.read_bytes(), original)
            self.evidence[f"trajectory_{track}"] = {"path": str(target.relative_to(self.root)), "validator": "trajectory"}
        after_tracks = self.inputs(4, phase="exit")
        self.assertTrue(self.checker.check(4, after_tracks, phase="exit")["ready"])

        fifth = self.inputs(5, before="best_method_retest")
        self.assertTrue(self.checker.check(5, fifth, before="best_method_retest")["ready"])
        groups["best_method"] = self.root / "experiments/best_method"
        self.assertEqual(run(method, protocol, groups["best_method"],
                             [sys.executable, "{method}/main.py", "--offset", "-7"],
                             role="best_method", jobs=2)["status"], "COMPLETE")
        self.assertTrue(self.checker.check(5, self.inputs(5, phase="exit"), phase="exit")["ready"])

        # The material fixture's hours/NOP/QA remain explicitly simulated.
        annotation_path = sources / "expert_evidence/expert_annotation.json"
        annotation = json.loads(annotation_path.read_text())
        annotation["score_contract"].update(
            baseline={"raw_value": 13, "normalized_score": 0},
            reference={"raw_value": 7, "normalized_score": 2 / 3},
            upper_bound={"raw_value": 4, "source": "estimated_attainable_upper_bound"})
        annotation_path.write_text(json.dumps(annotation), encoding="utf-8")
        (sources / "expert_evidence/专家作业说明文档.md").write_text(NOTES, encoding="utf-8")
        mapping = {"workspace": str(sources / "workspace"),
                   "optimization_evidence/训练证据说明.md": str(sources / "optimization_evidence/训练证据说明.md"),
                   "optimization_evidence/baseline_runs": str(groups["baseline"]),
                   "optimization_evidence/reference_runs": str(groups["reference"]),
                   "optimization_evidence/comparison_summary.json": str(stat_dir / "comparison_summary.json"),
                   "expert_evidence/best_retest": str(groups["best_method"])}
        mapping.update({str(p.relative_to(sources)): str(p) for p in (sources / "expert_evidence").iterdir()
                        if p.name not in {"best_method", "best_retest"}})
        final = self.base / "最终提交夹具"
        assembled = assemble(mapping, method, final)
        self.assertEqual(assembled["format_check"]["status"], "format_checked_not_qa", assembled["format_check"]["issues"])
        sixth = self.inputs(6, before="independent_qa")
        self.assertTrue(self.checker.check(6, sixth, before="independent_qa")["ready"])
        self.assertEqual(len(workspace.read_decisions()["entries"]), 3)
        self.assertFalse((final / ".autoresearch").exists())

        qa_dir = self.base / "synthetic-independent-qa"
        qa_dir.mkdir()
        report = synthetic_report(final)
        report.update(workspace_root=str(final), generated_at=dt.datetime.now(dt.timezone.utc).isoformat())
        qa = qa_dir / "report.json"
        qa.write_text(json.dumps(report), encoding="utf-8")
        (qa_dir / "inventory.json").write_text(json.dumps({"root": str(final), "files": sorted(
            str(p.relative_to(final)) for p in final.rglob("*") if p.is_file())}), encoding="utf-8")
        before = {str(p.relative_to(final)): _sha256(p) for p in final.rglob("*") if p.is_file()}
        result = package(final, qa, self.base / "attachments", name="synthetic-mechanism")
        self.assertEqual(result["status"], "packaged")
        self.assertEqual(set(result["archives"]), {"submission", "harbor_task", "optimization_evidence"})
        self.assertEqual(result["form"]["status"], "complete")
        self.assertEqual(before, {str(p.relative_to(final)): _sha256(p) for p in final.rglob("*") if p.is_file()})
        for item in result["archives"].values():
            with zipfile.ZipFile(Path(result["output_directory"]) / item["path"]) as archive:
                self.assertIsNone(archive.testzip())
                self.assertFalse(any(".autoresearch/" in name for name in archive.namelist()))
        self.assertFalse((self.root / ".autoresearch-flow").exists())

    def test_block_waive_changed_dependency_and_fresh_authoring_process(self):
        inputs = self.inputs(1, before="research_contract")
        self.decide("research_contract", inputs)
        obligation = "M01-S1"
        missing = inputs["evidence"].pop("research_notes")
        blocked = self.checker.check(1, inputs, before="research_contract")
        self.assertFalse(blocked["ready"])
        self.assertEqual(next(r["status"] for r in blocked["obligations"] if r["id"] == obligation), "BLOCKED")
        self.put("exception.md", "SYNTHETIC exception authority; not real consent\n")
        fields = {"gate": "exception", "status": "waived", "scope": "M01-S1, M02-S1",
                  "evidence": "exception.md", "approver": "SYNTHETIC expert", "reason": "fixture branch",
                  "limits": "synthetic obligation only", "before": "research_contract"}
        self.append_decision(fields)
        self.assertFalse(self.checker.check(1, inputs, before="research_contract")["ready"])
        self.append_decision({**fields, "rule_version": self.checker.version})
        waived = self.checker.check(1, inputs, before="research_contract")
        self.assertTrue(waived["ready"])
        self.assertEqual(next(r["status"] for r in waived["obligations"] if r["id"] == obligation), "WAIVED")
        self.evidence["research_notes"] = missing
        restored = self.inputs(1, before="research_contract")
        path = self.put("preflight.json", restored)
        decisions_before = (self.root / ".autoresearch/decision-log.md").read_bytes()
        # New authoring process reads the same files; this is NOT a new iteration thread.
        command = [sys.executable, str(FLOW / "cli.py"), "--format", "json", "preflight", "--task-root", str(self.root),
                   "--stage", "1", "--inputs", str(path), "--before", "research_contract"]
        resumed = subprocess.run(command, cwd=self.base, text=True, capture_output=True, check=False)
        self.assertEqual(resumed.returncode, 0, resumed.stderr)
        self.assertTrue(json.loads(resumed.stdout)["ready"])
        self.put(restored["evidence"]["research_contract"], "changed SYNTHETIC scope\n")
        changed = self.checker.check(1, self.inputs(1, before="research_contract"), before="research_contract", changed=["M01"])
        self.assertTrue(changed["checks_ready"])
        self.assertFalse(changed["confirmations_ready"])
        self.assertFalse(changed["ready"])
        self.assertIn("M01-S1", changed["recheck"]["obligations"])
        self.assertEqual(changed["recheck"]["mode"], "targeted_review_hint_only_no_cascade")
        self.assertEqual((self.root / ".autoresearch/decision-log.md").read_bytes(), decisions_before)
        self.assertFalse((self.root / ".autoresearch-flow").exists())


if __name__ == "__main__":
    unittest.main()
