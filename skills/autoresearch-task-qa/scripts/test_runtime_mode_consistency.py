import json
import unittest

import implementation_review as qa
import test_implementation_review as fixtures


class RuntimeModeConsistencyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.ImplementationReviewTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.tearDown)
        self.root = self.fixture.root

    def apply(self, review):
        return qa.apply_review(self.fixture.report(), review, self.root)

    def test_effective_overview_conflict_cannot_pass(self):
        review = self.fixture.review()
        review["overview"]["trajectories"][0]["duration_hours"] = 12
        report = self.apply(review)
        self.assertEqual(report["checks"][15]["status"], "manual")
        table = qa.compact_markdown(report).split("# 两条轨迹迭代概况", 1)[1].split("#", 1)[0]
        self.assertIn("10", table)
        self.assertNotIn("12h", table)

    def test_raw_one_hour_cannot_support_ten_effective_hours(self):
        review = self.fixture.review()
        path = self.root / "trajectory_a.json"
        data = json.loads(path.read_text())
        data["duration_seconds"] = 3600
        path.write_text(json.dumps(data))
        report = self.apply(review)
        self.assertEqual(report["checks"][15]["status"], "manual")
        self.assertNotEqual(report["summary"]["decision"], "PASS")

    def test_explicit_wall_bound_cannot_be_exceeded(self):
        review = self.fixture.review()
        path = self.root / "trajectory_a.json"
        data = json.loads(path.read_text())
        del data["duration_seconds"]
        data["wall_time_seconds"] = 3600
        path.write_text(json.dumps(data))
        self.assertEqual(self.apply(review)["checks"][15]["status"], "fail")

    def test_nested_round_timing_does_not_cap_whole_run(self):
        review = self.fixture.review()
        path = self.root / "trajectory_a.json"
        data = json.loads(path.read_text())
        data["rounds"][0]["duration_seconds"] = 10
        path.write_text(json.dumps(data))
        self.assertEqual(self.apply(review)["checks"][15]["status"], "pass")

    def test_stochastic_checks_cannot_be_marked_not_applicable(self):
        review = self.fixture.review()
        for row in review["checks"]:
            if row["id"] in ("QA04", "QA19"):
                row["status"] = "not_applicable"
        report = self.apply(review)
        states = {row["id"]: row["status"] for row in report["checks"]}
        self.assertEqual(states["QA04"], "manual")
        self.assertEqual(states["QA19"], "manual")
        self.assertNotEqual(report["summary"]["decision"], "PASS")

    def test_deterministic_checks_may_be_not_applicable(self):
        review = self.fixture.review()
        review["content_gates"]["checks"][2]["assessment"]["evaluation_mode"] = "deterministic"
        for row in review["checks"]:
            if row["id"] in ("QA04", "QA19"):
                row["status"] = "not_applicable"
        states = {row["id"]: row["status"] for row in self.apply(review)["checks"]}
        self.assertEqual(states["QA04"], "not_applicable")
        self.assertEqual(states["QA19"], "not_applicable")


if __name__ == "__main__":
    unittest.main()
