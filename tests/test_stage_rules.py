"""P0 阶段矩阵、规则来源和派生视图合同。"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from autoresearch_flow.stage_rules import StageRules


FLOW = Path(__file__).resolve().parents[1]


class StageRulesTests(unittest.TestCase):
    def test_matrix_covers_all_current_rules_and_views(self):
        rules = StageRules(FLOW)
        self.assertEqual(rules.validate(), [])
        for stage in rules.stages():
            path = FLOW / stage["view_path"]
            self.assertEqual(path.read_text(encoding="utf-8"), rules.render_stage(stage["id"]))

    def test_missing_obligation_is_reported_by_view_check(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FLOW / "rules", root / "rules")
            view = root / "rules/stages/stage-1-research-design.md"
            text = view.read_text(encoding="utf-8")
            view.write_text(text.replace("### M01-S1 — 界定真实方法空间", "### M01-S1 — 已移除", 1)
                            .replace("### M01-S1 — 已移除", "", 1), encoding="utf-8")
            issues = StageRules(root).validate()
            self.assertTrue(any(issue["code"] == "VIEW_MISSING_OBLIGATION" for issue in issues))

    def test_unknown_dependency_is_reported_without_state_engine(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FLOW / "rules", root / "rules")
            matrix_path = root / "rules/stage_matrix.json"
            matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
            matrix["obligations"][0]["depends_on"] = ["MISSING-S1"]
            matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            issues = StageRules(root).validate(check_views=False)
            self.assertTrue(any(issue["code"] == "DEPENDENCY_UNKNOWN" for issue in issues))

    def test_forward_dependency_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FLOW / "rules", root / "rules")
            matrix_path = root / "rules/stage_matrix.json"
            matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
            matrix["obligations"][0]["depends_on"] = ["M02-S2"]
            matrix_path.write_text(json.dumps(matrix, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
            issues = StageRules(root).validate(check_views=False)
            self.assertTrue(any(issue["code"] == "DEPENDENCY_FORWARD" for issue in issues))

    def test_rules_check_exposes_stage_matrix_status(self):
        result = subprocess.run(
            [sys.executable, str(FLOW / "cli.py"), "--format", "json", "rules", "check"],
            cwd=FLOW, capture_output=True, text=True, check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        payload = json.loads(result.stdout)
        self.assertEqual(payload["stage_matrix"]["status"], "ok")
        self.assertEqual(payload["stage_matrix"]["stage_count"], 6)
        self.assertEqual(payload["stage_matrix"]["obligation_count"], 44)

    def test_preparation_and_deferred_metadata_reject_unknown_actions(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FLOW / "rules", root / "rules")
            matrix_path = root / "rules/stage_matrix.json"
            matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
            matrix["obligations"][0]["pre_action"] = {"unknown": ["evidence"]}
            matrix["obligations"][0]["deferred_before"] = ["unknown"]
            matrix_path.write_text(json.dumps(matrix, ensure_ascii=False), encoding="utf-8")
            issues = StageRules(root).validate(check_views=False)
            self.assertTrue({"OBLIGATION_PRE_ACTION", "OBLIGATION_DEFERRED"} <= {row["code"] for row in issues})

    def test_expert_gates_are_limited_and_bound_to_existing_stage_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            shutil.copytree(FLOW / "rules", root / "rules")
            matrix_path = root / "rules/stage_matrix.json"
            matrix = json.loads(matrix_path.read_text())
            matrix["stages"][0]["confirmation_evidence"] = ["invented-evidence"]
            matrix["stages"][1]["expert_confirmation"] = True
            matrix["stages"][3]["required_confirmations"] = []
            matrix["stages"][5]["required_confirmations"] = ["dual_track_launch"]
            matrix_path.write_text(json.dumps(matrix), encoding="utf-8")
            codes = {row["code"] for row in StageRules(root).validate(check_views=False)}
            self.assertTrue({"EXPERT_GATE", "CONFIRMATION_EVIDENCE", "CONFIRMATION_DEPENDENCY"} <= codes)


if __name__ == "__main__":
    unittest.main()
