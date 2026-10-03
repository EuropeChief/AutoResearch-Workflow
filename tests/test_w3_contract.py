"""W3 synthetic contracts: no Docker, GPU, network or model charges."""
import copy
import json
import subprocess
import tomllib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from autoresearch_flow.core import FlowError, Registry, TaskStore, _sha256
from autoresearch_flow.runtime import Runtime, DockerBackend, validate_config, model_config
from autoresearch_flow.runtime_events import EventClock, Redactor, effective_seconds

THREAD = "11111111-1111-1111-1111-111111111111"
OTHER = "22222222-2222-2222-2222-222222222222"
SECRET = "synthetic-secret-not-a-real-key"


class FakeBackend:
    def __init__(self):
        self.commands = []
        self.mode = "ok"

    def check(self, runtime, track):
        return {"status": "ok"}

    def boundary(self, runtime, track):
        return '{"status":"ok"}'

    def stop(self, name):
        pass

    def command(self, runtime, track, phase, name, command, use_auth=False):
        self.commands.append(command)
        thread = command[3] if "resume" in command else THREAD if track == "codex" else OTHER
        if self.mode == "mismatch":
            thread = OTHER
        events = [{"type": "thread.started", "thread_id": thread}, {"type": "turn.started"},
                  {"type": "item.started", "item": {"id": "tool", "type": "command_execution"}}]
        if self.mode == "error":
            events += [{"type": "error", "message": "provider error"}, {"type": "turn.failed"}]
        else:
            events += [{"type": "item.completed", "item": {"id": "tool", "type": "command_execution",
                        "command": "/workspace/evaluate", "exit_code": 0,
                        "aggregated_output": json.dumps({"status": "succeeded", "score": 0.5,
                         "raw_metric": {"name": "error", "direction": "minimize", "value": 4.5}})}},
                       {"type": "item.completed", "item": {"type": "agent_message", "text": SECRET}},
                       {"type": "turn.completed"}]
        script = "import sys,json,time; sys.stdin.read(); events=json.loads(sys.argv[1]); " + \
                 "[(print(json.dumps(e),flush=True),time.sleep(.005)) for e in events]"
        return [sys.executable, "-c", script, json.dumps(events)]

    def spawn(self, command, env):
        return subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                stderr=subprocess.PIPE, env=env, start_new_session=True)


class ClockTests(unittest.TestCase):
    def clock(self):
        c = EventClock()
        c.event({"type": "thread.started", "thread_id": THREAD}, 0)
        c.event({"type": "turn.started"}, 0)
        return c

    def test_error_gap_excluded(self):
        c = self.clock()
        c.event({"type": "error"}, 10)
        c.event({"type": "item.completed", "item": {}}, 100)
        c.event({"type": "turn.completed"}, 110)
        self.assertEqual(c.summary()["observed_active_seconds"], 20)

    def test_long_silence_not_counted(self):
        c = self.clock()
        c.event({"type": "turn.completed"}, 600)
        self.assertEqual(c.summary()["observed_active_seconds"], 0)
        self.assertEqual(c.summary()["unverified_seconds"], 600)

    def test_pending_training_counted(self):
        c = self.clock()
        c.event({"type": "item.started", "item": {"type": "command_execution", "id": "a"}}, 0)
        c.event({"type": "item.completed", "item": {"type": "command_execution", "id": "a"}}, 600)
        c.stop(600)
        self.assertEqual(c.summary()["observed_active_seconds"], 600)

    def test_thread_mismatch(self):
        c = self.clock()
        with self.assertRaises(FlowError):
            c.event({"type": "thread.started", "thread_id": OTHER}, 1)

    def test_thread_flag_rejected(self):
        with self.assertRaises(FlowError):
            EventClock().event({"type": "thread.started", "thread_id": "--last"}, 0)

    def test_exclusions_union(self):
        self.assertEqual(effective_seconds([[0, 100], [50, 150]], [[10, 30], [20, 50]]), 110)

    def test_redactor(self):
        r = Redactor([SECRET])
        self.assertNotIn(SECRET, json.dumps(r.value({"text": SECRET, "access_token": "other"})))
        self.assertNotIn("abc", r.text("Authorization: Bearer abc"))


class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="autoresearch-w3-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        TaskStore(self.root).initialize(Registry(), "synthetic")
        self.auth = self.root / "private-auth.json"
        self.auth.write_text(json.dumps({"OPENAI_API_KEY": SECRET}))
        track = {"model": "synthetic", "reasoning_effort": "high", "base_url": "https://example.invalid/v1",
                 "auth_ref": {"kind": "api_key_json", "path": str(self.auth), "key": "OPENAI_API_KEY"}}
        self.config = {"schema_version": 2, "image": "sha256:" + "a"*64, "codex_version": "0.147.0",
                       "public_files": [{"source": self.ref("instruction.md", "public task"), "destination": "instruction.md"}],
                       "starter_files": [{"source": self.ref("method.py", "# starter"), "destination": "method.py"}],
                       "prompt": self.ref("prompt.md", "synthetic prompt"),
                       "evaluation": {"command": ["/opt/task/evaluate"], "timeout_seconds": 5},
                       "boundaries": {"readable": ["/workspace/instruction.md"], "readonly": [], "unreadable": []},
                       "resources": {"cpus": 1, "memory": "1g", "gpus": {"codex": None, "seed": None}},
                       "tracks": {"codex": copy.deepcopy(track), "seed": copy.deepcopy(track)}}
        self.backend = FakeBackend()
        self.runtime = Runtime(self.root, self.backend)

    def ref(self, name, value):
        path = self.root / name
        path.write_text(value)
        return {"path": name, "sha256": _sha256(path)}

    def prepare(self):
        self.runtime.prepare(self.config)

    def test_prepare_separate_workspaces(self):
        self.prepare()
        a = self.runtime.directory / "codex/formal/solution/method.py"
        b = self.runtime.directory / "seed/formal/solution/method.py"
        a.write_text("changed")
        self.assertEqual(b.read_text(), "# starter")
        self.assertFalse((self.runtime.directory / "public/private-auth.json").exists())

    def test_requires_explicit_live_consent(self):
        self.prepare()
        with self.assertRaises(FlowError):
            self.runtime.preflight("codex")
        self.assertFalse(self.backend.commands)

    def test_preflight_not_formal_time_and_redacted(self):
        self.prepare()
        self.assertEqual(self.runtime.preflight("codex", True)["status"], "ready")
        state = self.runtime.status("codex")
        self.assertIsNone(state["thread_id"])
        self.assertEqual(state["effective_seconds_before_content_review"], 0)
        logs = list((self.runtime.directory / "codex/logs").rglob("*.jsonl"))
        self.assertTrue(logs)
        self.assertTrue(all(SECRET not in p.read_text() for p in logs))

    def test_formal_and_exact_resume(self):
        self.prepare()
        self.runtime.preflight("codex", True)
        state = self.runtime._state("codex")
        result, _ = self.runtime._segment("codex", "formal", state, "start", 2)
        self.assertEqual(result["status"], "completed")
        self.runtime._segment("codex", "formal", state, "continue", 2, state["thread_id"])
        self.assertEqual(self.backend.commands[-1][2:4], ["resume", THREAD])
        self.assertEqual(self.runtime.status("codex")["formal_segments"], 2)
        self.assertIsNone(self.runtime._state("seed")["thread_id"])

    def test_new_thread_on_resume_rejected(self):
        self.prepare()
        state = self.runtime._state("codex")
        self.runtime._segment("codex", "formal", state, "start", 2)
        self.backend.mode = "mismatch"
        result, _ = self.runtime._segment("codex", "formal", state, "continue", 2, THREAD)
        self.assertEqual(result["status"], "failed")
        self.assertEqual(result["observed_active_seconds"], 0)

    def test_errors_retained(self):
        self.prepare()
        self.backend.mode = "error"
        state = self.runtime._state("seed")
        result, _ = self.runtime._segment("seed", "formal", state, "start", 2)
        self.assertEqual(result["status"], "failed")
        self.assertTrue(result["errors"])

    def test_log_tampering_detected(self):
        self.prepare()
        self.runtime.preflight("codex", True)
        p = next((self.runtime.directory / "codex/logs").rglob("codex.jsonl"))
        p.write_text("tampered")
        with self.assertRaises(FlowError):
            self.runtime.status("codex")

    def test_public_drift_detected(self):
        self.prepare()
        (self.runtime.directory / "public/instruction.md").chmod(0o644)
        (self.runtime.directory / "public/instruction.md").write_text("changed")
        with self.assertRaises(FlowError):
            self.runtime.status("codex")

    def test_starter_drift_rejected(self):
        self.prepare()
        self.runtime.preflight("codex", True)
        (self.runtime.directory / "codex/formal/solution/method.py").write_text("changed")
        with self.assertRaises(FlowError):
            self.runtime.run("codex", 1, confirm_cost=True)

    def test_docker_mounts_no_parent_no_secret(self):
        self.prepare()
        with patch("os.getuid", return_value=1000), patch("os.getgid", return_value=1000):
            cmd = DockerBackend().command(self.runtime, "codex", "formal", "test", ["codex"], True)
        mounts = [cmd[i+1] for i, s in enumerate(cmd) if s == "--mount"]
        self.assertFalse(any('dst=/workspace,' in m for m in mounts))
        self.assertTrue(any('dst=/workspace/starter,readonly' in m for m in mounts))
        self.assertTrue(any('dst=/expert_evidence' in m for m in mounts))
        self.assertFalse(any("docker.sock" in m or "/seed/" in m for m in mounts))
        self.assertNotIn(SECRET, " ".join(cmd))
        self.assertIn("--read-only", cmd)
        self.assertIn("-i", cmd)

    def test_pca_public_grader_can_receive_candidate_argument(self):
        self.config['evaluation']['command'] = ['/workspace/public_eval/evaluate', '--candidate', '/workspace/solution']
        validate_config(self.config, self.root)
        self.config['evaluation']['command'] = ['/usr/bin/python3', '/workspace/solution/fake_grader.py']
        with self.assertRaises(FlowError): validate_config(self.config, self.root)

    def test_docker_cannot_claim_formal_harbor_execution(self):
        self.prepare()
        self.runtime.backend = DockerBackend()
        with self.assertRaises(FlowError) as error:
            self.runtime.run('codex', 60, confirm_cost=True)
        self.assertEqual(error.exception.code, 'HARBOR_DRIVER_REQUIRED')

    def test_sandbox_failure_blocks_before_model_call(self):
        self.prepare()
        self.runtime.backend = DockerBackend()
        success = subprocess.CompletedProcess([], 0, '{"status":"ok"}', '')
        failure = subprocess.CompletedProcess([], 1, '', 'bwrap: namespace denied')
        with patch.object(self.runtime.backend, "check"), \
             patch.object(self.runtime.backend, "stop"), \
             patch.object(self.runtime.backend, "spawn", side_effect=AssertionError("API must not start")) as spawn, \
             patch("autoresearch_flow.runtime.subprocess.run", side_effect=[success, failure]) as run:
            with self.assertRaises(FlowError) as raised:
                self.runtime.preflight("seed", True)
            self.assertEqual(raised.exception.code, "SANDBOX_FAILED")
            self.assertIn("codex sandbox -P autoresearch", " ".join(run.call_args_list[1].args[0]))
            spawn.assert_not_called()

    def test_docker_boundary_checks_both_layers(self):
        self.prepare()
        backend = DockerBackend()
        success = subprocess.CompletedProcess([], 0, '{"status":"ok"}', '')
        with patch.object(backend, "stop"), \
             patch("autoresearch_flow.runtime.subprocess.run", return_value=success) as run:
            result = json.loads(backend.boundary(self.runtime, "seed"))
        self.assertEqual(run.call_count, 2)
        self.assertEqual([p["layer"] for p in result["probes"]], ["container", "codex_sandbox"])

    def test_named_permissions_match_formal_and_probe(self):
        parsed = tomllib.loads(model_config(self.config["tracks"]["seed"]))
        self.assertEqual(parsed["default_permissions"], "autoresearch")
        self.assertNotIn("sandbox_mode", parsed)
        profile = parsed["permissions"]["autoresearch"]
        self.assertEqual(profile["filesystem"]["/workspace/solution"], "write")
        self.assertEqual(profile["filesystem"]["/expert_evidence"], "write")
        self.assertFalse(profile["network"]["enabled"])
        self.assertEqual(parsed["shell_environment_policy"]["inherit"], "all")
        self.assertNotIn("AUTORESEARCH_MODEL_KEY", parsed["shell_environment_policy"]["include_only"])

    def test_security_override_requires_evidence_and_snapshots(self):
        config = copy.deepcopy(self.config)
        config["docker_security"] = {"apparmor": "unconfined"}
        with self.assertRaises(FlowError):
            validate_config(config, self.root)
        config["docker_security"].update(
            approval=self.ref("approval.md", "User explicitly authorized this isolated pilot."),
            seccomp=self.ref("seccomp.json", json.dumps({"defaultAction": "SCMP_ACT_ERRNO", "syscalls": []})))
        self.runtime.prepare(config)
        command = DockerBackend().command(self.runtime, "seed", "formal", "probe", ["true"])
        self.assertIn("apparmor=unconfined", command)
        self.assertIn("seccomp=" + str(self.runtime.directory / "security/seccomp.json"), command)
        self.assertNotIn("--privileged", command)
        self.assertNotIn("seccomp=unconfined", command)
        snapshot = self.runtime.directory / "security/seccomp.json"
        snapshot.chmod(0o644)
        snapshot.write_text("{}")
        with self.assertRaises(FlowError):
            self.runtime.status("seed")

    def test_invalid_image_and_context(self):
        self.config["image"] = "mutable:latest"
        with self.assertRaises(FlowError):
            validate_config(self.config, self.root)
        self.config["image"] = "sha256:" + "a"*64
        self.config["tracks"]["seed"].update(context_window=256000, auto_compact_token_limit=230000, max_output_tokens=64000)
        with self.assertRaises(FlowError):
            validate_config(self.config, self.root)

    def test_recover_does_not_infer_tail(self):
        self.prepare()
        state = self.runtime._state("codex")
        directory = self.runtime.directory / "codex/logs/interrupted"
        directory.mkdir(parents=True)
        events = [(0, {"type": "thread.started", "thread_id": THREAD}),
                  (0, {"type": "turn.started"}), (10, {"type": "item.completed", "item": {}})]
        (directory / "events.jsonl").write_text("".join(json.dumps({"at": at, "source": "codex", "event": e})+"\n" for at,e in events))
        state["active"] = {"container": "owned", "segment_id": "interrupted", "phase": "formal"}
        self.runtime._save("codex", state)
        status = self.runtime.recover("codex")
        self.assertEqual(status["effective_seconds_before_content_review"], 10)
        self.assertEqual(status["thread_id"], THREAD)
        self.assertIsNone(status["active"])

    def test_default_profiles_prepare(self):
        config = copy.deepcopy(self.config)
        config.pop("tracks")
        self.runtime.prepare(config)
        self.runtime.status("seed")
        self.assertEqual(self.runtime.config["tracks"]["seed"]["model"], "doubao-seed-2.1-turbo")
        self.assertEqual(self.runtime.config["tracks"]["seed"]["max_output_tokens"], 65536)
        self.assertEqual(self.runtime.config["tracks"]["codex"]["model"], "gpt-5.6-sol")
        self.assertEqual(set((self.runtime.directory / "profiles").iterdir()),
                         {self.runtime.directory / "profiles/codex.toml", self.runtime.directory / "profiles/seed.toml"})

    def test_fixed_seed_profile_is_self_contained(self):
        # The root config.toml was an import source, not a deployment dependency.
        profile = tomllib.loads((Path(__file__).resolve().parents[1] / "model_profiles/seed.toml").read_text())
        rendered = tomllib.loads(model_config(profile))
        self.assertEqual(rendered["model"], "doubao-seed-2.1-turbo")
        self.assertEqual(rendered["model_providers"]["autoresearch"]["base_url"],
                         "https://ark.cn-beijing.volces.com/api/coding/v3")
        self.assertEqual(rendered["model_context_window"], 262144)
        self.assertEqual(rendered["model_auto_compact_token_limit"], 160000)
        self.assertEqual(profile["max_output_tokens"], 65536)
        self.assertLess(profile["auto_compact_token_limit"] + profile["max_output_tokens"],
                        profile["context_window"])

    def test_profile_prepare_snapshots_and_does_not_hot_reload(self):
        profiles = self.root / "profiles"
        profiles.mkdir()
        config = copy.deepcopy(self.config)
        config.pop("tracks")
        for name in ("codex", "seed"):
            (profiles / f"{name}.toml").write_text(
                f'schema_version = 1\nmodel = "{name}-first"\nreasoning_effort = "high"\n'
                'base_url = "https://example.invalid/v1"\n[auth_ref]\n'
                f'kind = "api_key_json"\npath = "{self.auth}"\nkey = "OPENAI_API_KEY"\n')
        runtime = Runtime(self.root, self.backend, profiles_dir=profiles)
        result = runtime.prepare(config)
        self.assertEqual(set(result["profile_sources"]), {"codex", "seed"})
        snapshot = runtime.directory / "profiles/seed.toml"
        self.assertIn('model = "seed-first"', snapshot.read_text())
        (profiles / "seed.toml").write_text((profiles / "seed.toml").read_text().replace("seed-first", "seed-second"))
        runtime.status("seed")
        self.assertEqual(runtime.config["tracks"]["seed"]["model"], "seed-first")
        self.assertIn('model = "seed-first"', snapshot.read_text())
        self.assertEqual(runtime._state("seed")["segments"], [])
        snapshot.chmod(0o644)
        snapshot.write_text("tampered")
        with self.assertRaises(FlowError):
            runtime.status("seed")

    def test_missing_profile_rejected_before_prepare(self):
        config = copy.deepcopy(self.config)
        config.pop("tracks")
        profiles = self.root / "profiles"
        profiles.mkdir()
        runtime = Runtime(self.root, self.backend, profiles_dir=profiles)
        with self.assertRaises(FlowError):
            runtime.prepare(config)
        self.assertFalse(runtime.directory.exists())

    def test_config_no_inherited_home(self):
        text = model_config(self.config["tracks"]["codex"])
        self.assertIn('inherit = "all"', text)
        self.assertFalse(tomllib.loads(text)["permissions"]["autoresearch"]["network"]["enabled"])
        self.assertNotIn(SECRET, text)
        track = copy.deepcopy(self.config["tracks"]["seed"])
        track.update(context_window=256000, auto_compact_token_limit=160000, max_output_tokens=64000)
        text = model_config(track)
        self.assertIn("model_auto_compact_token_limit = 160000", text)
        self.assertNotIn("model_max_output_tokens", text)


if __name__ == "__main__":
    unittest.main()
