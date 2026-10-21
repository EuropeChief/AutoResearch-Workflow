"""Offline synthetic cases for policy boundaries and existing H03 aggregation.

Expected semantic decisions are supplied by the fixture author. This is NOT an
LLM evaluation or an automatic deployment-code classifier. Fixture commands are
plain text and are never executed. NOP is intentionally absent: H03/static
status is tested independently of the existing H06/QA17 missing-NOP failure.
"""
from pathlib import Path
import unittest

import test_harbor_review as fixtures
import harbor_review as harbor


# case id, reviewed H03 status, inert evidence text
CASES = [
    ("framework_separate", "pass", "Framework creates Agent A, transfers artifacts, then creates separate Verifier B."),
    ("pre_run_build", "pass", "Before the task, the platform prepares the current image using docker build."),
    ("local_process", "pass", "Task starts a Python child process inside the assigned sandbox."),
    ("local_multi_gpu", "pass", "torchrun uses only two GPUs already assigned inside this sandbox."),
    ("local_inference", "pass", "A local HTTP inference process runs inside the current sandbox."),
    ("normal_model_service", "pass", "HTTP request calls an approved model API; no extra work environment is used."),
    ("normal_data_download", "pass", "HTTP retrieves approved public data, not a remote GPU work environment."),
    ("incidental_words", "pass", "Historical note: Docker SSH HTTP broker GPU worker; no current deployment dependency."),
    ("task_broker_allocation", "fail", "Task requires its broker to request and use an extra GPU sandbox during execution."),
    ("task_sdk_allocation", "fail", "Task runtime calls an SDK create API to launch a new working sandbox."),
    ("task_nested_docker", "fail", "Task starts Docker-in-Docker and runs its experiment in a nested container."),
    ("task_sibling_docker", "fail", "Task uses the host Docker socket to run an additional working container."),
    ("task_existing_remote", "fail", "Task sends its training command by SSH to an existing remote GPU sandbox."),
    ("task_http_worker", "fail", "Task submits its experiment over HTTP to a GPU worker in another container."),
    ("verifier_extra_worker", "fail", "Verifier starts an additional GPU worker container to perform scoring."),
    ("task_allocation_denied", "fail", "Task instruction requires allocation via SDK; the allocation request was denied."),
    ("agent_disobedience_only", "pass", "Task prohibits extra environments. Agent independently requests one and is denied; attribute to QA18, not an H03 author defect."),
    ("unknown_wrapper", "manual", "Wrapper implementation is unavailable; execution location and allocation purpose are unknown."),
    ("unknown_http_purpose", "manual", "A current HTTP request is shown, but its target and purpose are not established."),
]


class ContainerGpuPolicyTests(unittest.TestCase):
    def setUp(self):
        fixtures.HarborReviewTests.setUp(self)

    def tearDown(self):
        fixtures.HarborReviewTests.tearDown(self)

    def apply_case(self, status, text):
        (self.root / "policy-evidence.txt").write_text(text)
        review = fixtures.valid_review()
        row = review["checks"][2]
        row.update(status=status, summary="Reviewed synthetic deployment boundary: " + status)
        row["evidence"].append("policy-evidence.txt")
        files = [p.relative_to(self.root).as_posix() for p in self.root.rglob("*") if p.is_file()]
        return harbor.apply_review(harbor.collect(self.root, files), review, self.root)

    def test_reviewed_boundary_matrix(self):
        for case, status, text in CASES:
            with self.subTest(case=case):
                result = self.apply_case(status, text)
                self.assertEqual(result["checks"][2]["status"], status)
                self.assertEqual(result["static_status"], status)
                # No synthetic NOP score or execution claim is produced.
                self.assertEqual(result["runtime_status"], "not_run")
                self.assertEqual(result["checks"][5]["status"], "warn")

    def test_keywords_alone_do_not_create_deployment_failure(self):
        # Even prohibited-looking strings do not replace semantic review.
        # A real review MUST inspect their stage, caller and destination first.
        for token in ("docker run", "docker.from_env", "docker.sock", "SSH", "HTTP", "broker.create", "GPU worker"):
            with self.subTest(token=token):
                result = self.apply_case("pass", "Historical unused example: " + token)
                self.assertEqual(result["checks"][2]["status"], "pass")

    def test_canonical_rule_and_attribution_are_present(self):
        root = Path(__file__).resolve().parents[1]
        policy = (root / "references/innerfield-deployment.md").read_text()
        for phrase in ("## 容器组织与GPU使用要求", "Docker-in-Docker", "sibling Docker",
                       "普通子进程", "模型服务请求", "已有的远端 GPU 沙盒", "被拒绝的请求",
                       "不能仅凭这类 Agent 行为推定作者", "本版没有新增自动识别任意部署代码的能力"):
            with self.subTest(phrase=phrase):
                self.assertIn(phrase, policy)
        for path in root.rglob("*.md"):
            self.assertNotIn("优先单容器", path.read_text(), str(path))


if __name__ == "__main__":
    unittest.main()
