"""Synthetic configuration regressions; never build or execute submitted tasks."""
from copy import deepcopy
from pathlib import Path
import tempfile
import unittest

import deployment_review as deployment


class DeploymentReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        (self.root / "task.toml").write_text("# Synthetic evidence only\n")
        for folder in ("environment", "tests"):
            (self.root / folder).mkdir()
            (self.root / folder / "Dockerfile").write_text("FROM scratch\n")
        self.config = {"environment": {"gpus": 0},
                       "verifier": {"environment_mode": "separate", "environment": {"gpus": 0}}}
        self.review = {"capability_review": {"status": "pass", "outcome": "not_required",
                       "summary": "Task does not depend on unsupported constraints.", "evidence": ["task.toml"]}}

    def tearDown(self):
        self.temp.cleanup()

    def resolve(self, root, relative):
        target = (root / relative).resolve()
        if not target.is_relative_to(root) or not target.is_file():
            raise ValueError("missing or escaped evidence")
        return target

    def assess(self, config=None, review=None):
        return deployment.assess(self.root, self.root, self.config if config is None else config,
                                 self.review if review is None else review, self.resolve)

    def test_default_internal_cpu_deployment(self):
        result = self.assess()
        self.assertEqual(result["profile"], "innerfield-maso-v1")
        self.assertEqual(result["status"], "pass")

    def test_submission_target_is_h20(self):
        for card in ("H20", "h20"):
            with self.subTest(card=card):
                self.config["environment"] = {"gpus": 1, "gpu_types": [card]}
                self.assertEqual(self.assess()["status"], "pass")

    def test_nonapproved_card_or_mixed_list_fails(self):
        for cards in (["L20"], ["A100"], ["H200"], ["H20", "L40"], ["H20/A100"]):
            with self.subTest(cards=cards):
                self.config["environment"] = {"gpus": 1, "gpu_types": cards}
                self.assertEqual(self.assess()["gpu_status"], "fail")

    def test_gpu_type_must_be_resolved_on_each_side(self):
        self.config["verifier"]["environment"] = {"gpus": 1}
        self.assertEqual(self.assess()["gpu_status"], "manual")

    def test_unused_gpu_type_with_zero_allocation_is_not_gpu_violation(self):
        self.config["environment"] = {"gpus": 0, "gpu_types": ["A100"]}
        self.assertEqual(self.assess()["gpu_status"], "pass")

    def test_storage_request_on_either_environment_fails(self):
        for role in ("agent", "verifier"):
            with self.subTest(role=role):
                cfg = deepcopy(self.config)
                env = cfg["environment"] if role == "agent" else cfg["verifier"]["environment"]
                env["storage_mb"] = 1024
                self.assertEqual(self.assess(cfg)["constraint_status"], "fail")

    def test_observed_storage_measurement_is_not_resource_request(self):
        self.config["metadata"] = {"peak_storage_mb": 1024}
        self.assertEqual(self.assess()["status"], "pass")

    def test_network_constraints_cannot_be_overridden_by_handwritten_pass(self):
        for mode in ("no-network", "allowlist"):
            with self.subTest(mode=mode):
                cfg = deepcopy(self.config)
                cfg["agent"] = {"network_mode": mode}
                self.assertEqual(self.assess(cfg)["constraint_status"], "fail")

    def test_legacy_network_request_is_also_checked(self):
        self.config["environment"]["allow_internet"] = False
        self.assertEqual(self.assess()["constraint_status"], "fail")

    def test_public_network_and_proxy_are_not_prohibited(self):
        self.config["agent"] = {"network_mode": "public"}
        self.config["environment"]["env"] = {"HTTPS_PROXY": "http://proxy.invalid"}
        self.assertEqual(self.assess()["status"], "pass")

    def test_public_phase_does_not_erase_unsupported_startup_request(self):
        self.config["environment"].update(network_mode="no-network", allowed_hosts=["old.example"])
        self.config["agent"] = {"network_mode": "public"}
        self.assertEqual(self.assess()["constraint_status"], "fail")

    def test_warning_or_fallback_is_not_effective_enforcement(self):
        for outcome in ("warning_only", "network_fallback"):
            with self.subTest(outcome=outcome):
                self.review["capability_review"]["outcome"] = outcome
                self.assertEqual(self.assess()["constraint_status"], "fail")

    def test_absent_or_unverified_capability_is_incomplete(self):
        self.assertEqual(self.assess(review={})["constraint_status"], "manual")
        self.review["capability_review"]["outcome"] = "unverified"
        self.assertEqual(self.assess()["constraint_status"], "manual")

    def test_old_warning_text_does_not_override_current_resolved_evidence(self):
        (self.root / "resolved.log").write_text("Earlier network warning; current task revised to public networking.\n")
        self.review["capability_review"].update(evidence=["resolved.log"], outcome="not_required")
        self.assertEqual(self.assess()["status"], "pass")

    def test_generic_profile_requires_real_basis_and_cannot_claim_internal_compliance(self):
        self.review["deployment_profile"] = "generic-harbor"
        with self.assertRaises(ValueError):
            self.assess()
        self.review["deployment_basis"] = {"summary": "Different provider; separate compatibility review.",
                                           "evidence": ["task.toml"]}
        self.config["environment"]["storage_mb"] = 1024
        result = self.assess()
        self.assertEqual(result["status"], "pass")
        self.assertFalse(result["innerfield_compliant"])

    def test_selected_compose_fails_for_each_sandbox(self):
        for folder in ("environment", "tests"):
            with self.subTest(folder=folder):
                dockerfile = self.root / folder / "Dockerfile"
                compose = self.root / folder / "docker-compose.yaml"
                dockerfile.unlink()
                compose.write_text("services:\n  main:\n    image: scratch\n")
                self.assertEqual(self.assess()["compose_status"], "fail")
                compose.unlink()
                dockerfile.write_text("FROM scratch\n")

    def test_unselected_historical_compose_is_not_failure(self):
        (self.root / "examples").mkdir()
        (self.root / "examples/docker-compose.yaml").write_text("services: {}\n")
        self.assertEqual(self.assess()["compose_status"], "pass")

    def test_dockerfile_does_not_prove_colocated_compose_is_unused(self):
        (self.root / "environment/docker-compose.yaml").write_text("services:\n  extra:\n    image: scratch\n")
        self.assertEqual(self.assess()["compose_status"], "fail")

    def test_compose_unused_never_exempts_either_role(self):
        for directory in ("environment", "tests"):
            (self.root / directory / "docker-compose.yaml").write_text("services: {}\n")
        self.review["compose_review"] = {"selection": "unused", "roles": ["agent"],
            "summary": "Target provider explicitly uses prebuilt single containers.", "evidence": ["task.toml"]}
        self.assertEqual(self.assess()["compose_status"], "fail")
        self.review["compose_review"]["roles"].append("verifier")
        self.assertEqual(self.assess()["compose_status"], "fail")
        self.review["compose_review"]["evidence"] = ["missing.log"]
        with self.assertRaises(ValueError):
            self.assess()

    def test_explicitly_selected_compose_cannot_be_hidden_by_image(self):
        self.config["environment"]["docker_image"] = "example:prebuilt"
        self.review["compose_review"] = {"selection": "selected", "roles": ["agent"],
            "summary": "Provider still uses Compose sidecars.", "evidence": ["task.toml"]}
        self.assertEqual(self.assess()["compose_status"], "fail")

    def test_explicit_prebuilt_images_do_not_exempt_runtime_compose(self):
        for directory in ("environment", "tests"):
            (self.root / directory / "docker-compose.yaml").write_text("services: {}\n")
        self.config["environment"]["docker_image"] = "example:prebuilt"
        self.config["verifier"]["environment"]["docker_image"] = "example:verifier"
        self.assertEqual(self.assess()["compose_status"], "fail")


    def test_four_names_both_roles_no_bypass(self):
        for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"):
            for role, directory in (("agent", "environment"), ("verifier", "tests")):
                for variant in ("compose_only", "dockerfile", "image", "unused", "generic"):
                    with self.subTest(name=name, role=role, variant=variant):
                        cfg, review = deepcopy(self.config), deepcopy(self.review)
                        compose = self.root / directory / name
                        dockerfile = self.root / directory / "Dockerfile"
                        compose.write_text("services: {}\n")
                        if variant == "compose_only":
                            dockerfile.unlink()
                        if variant in ("image", "unused", "generic"):
                            cfg["environment"]["docker_image"] = "example:agent"
                            cfg["verifier"]["environment"]["docker_image"] = "example:verifier"
                        if variant in ("unused", "generic"):
                            review["compose_review"] = {"selection": "unused", "roles": [role],
                                "summary": "Declared unused but still in formal runtime directory.",
                                "evidence": ["task.toml"]}
                        if variant == "generic":
                            review["deployment_profile"] = "generic-harbor"
                            review["deployment_basis"] = {"summary": "Another provider.", "evidence": ["task.toml"]}
                        result = self.assess(cfg, review)
                        self.assertEqual(result["compose_status"], "fail")
                        findings = [f for f in result["findings"] if f["code"] == "compose_unsupported"]
                        self.assertIn(f"{directory}/{name}", findings[0]["evidence"])
                        compose.unlink()
                        dockerfile.write_text("FROM scratch\n")

    def test_documentation_and_history_are_not_scanned_recursively(self):
        for folder in ("docs", "history", "examples", "environment/docs", "tests/history"):
            directory = self.root / folder
            directory.mkdir(parents=True, exist_ok=True)
            for name in ("docker-compose.yaml", "docker-compose.yml", "compose.yaml", "compose.yml"):
                (directory / name).write_text("services: {}\n")
        self.assertEqual(self.assess()["compose_status"], "pass")

if __name__ == "__main__":
    unittest.main()
