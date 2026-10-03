"""W3 synthetic contracts: no Docker, GPU, network or model charges."""
import copy
import datetime as dt
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
from autoresearch_flow.runtime import CLOSE_PROMPT, Runtime, DockerBackend, validate_config, model_config
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

    def command(self, runtime, track, phase, name, command, use_auth=False, tty=False):
        self.commands.append(command)
        self.context = (runtime, track, phase)
        return command

    def terminal(self):
        return FakeNativeTerminal(self)


class FakeNativeTerminal:
    """External TUI/rollout simulator; never starts a model, tmux or Docker."""
    def __init__(self, backend):
        self.backend = backend
        runtime, track, phase = backend.context
        self.base = runtime.directory/track/phase
        self.socket = self.base/'synthetic.sock'
        self.started = self.alive = False
        self.thread = THREAD if track == 'codex' else OTHER
        self.turns = 0
        self.sent = []
        self.closed = False
        backend.last_terminal = self

    def write(self, kind, **payload):
        record = {'timestamp': dt.datetime.now(dt.timezone.utc).isoformat(), 'type': kind, 'payload': payload}
        with self.path.open('a') as stream:
            stream.write(json.dumps(record)+'\n')

    def start(self, command, env):
        self.started = self.alive = True
        if 'resume' in command:
            self.thread = command[2]
        if self.backend.mode == 'mismatch':
            self.thread = OTHER
        self.path = self.base/'codex_home/sessions'/f'{self.thread}.jsonl'
        self.path.parent.mkdir(exist_ok=True)
        if not self.path.exists():
            self.write('session_meta', id=self.thread, cli_version='0.147.0')
        self.emit_turn()

    def emit_turn(self):
        self.turns += 1
        turn = str(self.turns)
        self.write('event_msg', type='task_started', turn_id=turn)
        if self.backend.mode == 'background' and self.turns > 1:
            self.write('response_item', type='function_call', name='write_stdin', call_id='poll',
                       arguments=json.dumps({'session_id': 999}))
            self.write('response_item', type='function_call_output', call_id='poll',
                       output='Process exited with code 0\nFinal output:\nworker done\n')
        self.write('response_item', type='function_call', name='exec_command', call_id=turn,
                   arguments=json.dumps({'cmd': '/workspace/evaluate'}))
        if self.backend.mode == 'pending':
            return
        if self.backend.mode == 'error':
            self.write('event_msg', type='error', message='provider error')
            return
        result = {'status': 'succeeded', 'score': 0.5,
                  'raw_metric': {'name': 'error', 'direction': 'minimize', 'value': 4.5}}
        from autoresearch_flow.pca_contract import task_digest
        digest = task_digest(self.base/'solution')
        result['evaluation_binding'] = {'candidate_before_sha256': digest, 'candidate_after_sha256': digest}
        self.write('response_item', type='function_call_output', call_id=turn,
                   output='Process exited with code 0\n'+json.dumps(result))
        self.write('event_msg', type='agent_message', message=SECRET)
        if self.backend.mode == 'unscored_change':
            (self.base/'solution/method.py').write_text('unscored changed candidate')
        if self.backend.mode != 'missing_output':
            best = self.base/'output/best_method'
            best.mkdir(exist_ok=True)
            (best/'method.py').write_bytes((self.base/'solution/method.py').read_bytes())
            trajectory = self.base/'output/trajectory.jsonl'
            count = len(trajectory.read_text().splitlines()) if trajectory.exists() else 0
            with trajectory.open('a') as stream:
                stream.write(json.dumps({'round': count+1, 'policy_name': 'synthetic',
                    'method_summary': '合成测试，非真实方法迭代。', 'status': 'ok', 'score': 4.5,
                    'failure_reason': None, 'retained_best': True, 'time': '2026-10-03 00:00:00'})+'\n')
        if self.backend.mode == 'background' and self.turns == 1:
            self.write('response_item', type='function_call', name='exec_command', call_id='worker',
                       arguments=json.dumps({'cmd': 'python train.py'}))
            self.write('response_item', type='function_call_output', call_id='worker',
                       output='Process running with session ID 999\nOutput:\nworking\n')
        if self.backend.mode != 'budget_pause':
            self.write('event_msg', type='task_complete', turn_id=turn)

    def send(self, prompt):
        self.sent.append(prompt)
        if prompt == '/quit':
            self.alive = False
        else:
            self.emit_turn()

    def status(self):
        return {'alive': self.alive, 'exit_code': None if self.alive else 0}

    def capture(self):
        return 'synthetic screen '+SECRET

    def close(self):
        self.alive = False
        self.closed = True


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
    def test_missing_docker_reports_host_setup_without_state_change(self):
        self.prepare()
        before = (self.runtime.directory / 'codex/state.json').read_bytes()
        with patch('subprocess.run', side_effect=FileNotFoundError('docker')), self.assertRaises(FlowError) as error:
            DockerBackend().check(self.runtime, 'codex')
        self.assertEqual(error.exception.code, 'HOST_DEPENDENCY_UNAVAILABLE')
        self.assertIn('docker --version', str(error.exception))
        self.assertEqual(before, (self.runtime.directory / 'codex/state.json').read_bytes())

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
        self.profiles = self.root / "profiles"
        self.runtime = Runtime(self.root, self.backend, profiles_dir=self.profiles,
                               terminal_factory=self.backend.terminal)

    def ref(self, name, value):
        path = self.root / name
        path.write_text(value)
        return {"path": name, "sha256": _sha256(path)}

    def write_profiles(self, tracks):
        self.profiles.mkdir(exist_ok=True)
        for name, track in tracks.items():
            lines = ["schema_version = 1"]
            lines.extend(f"{key} = {json.dumps(value)}" for key, value in track.items() if key != "auth_ref")
            lines.append("[auth_ref]")
            lines.extend(f"{key} = {json.dumps(value)}" for key, value in track["auth_ref"].items())
            (self.profiles / f"{name}.toml").write_text("\n".join(lines) + "\n")

    def prepare(self, config=None):
        requested = copy.deepcopy(self.config if config is None else config)
        self.write_profiles(requested.pop("tracks"))
        return self.runtime.prepare(requested)

    def test_prepare_separate_workspaces(self):
        self.prepare()
        a = self.runtime.directory / "codex/formal/solution/method.py"
        b = self.runtime.directory / "seed/formal/solution/method.py"
        a.write_text("changed")
        self.assertEqual(b.read_text(), "# starter")
        self.assertFalse((self.runtime.directory / "public/private-auth.json").exists())

    def test_inline_tracks_cannot_bypass_local_profiles(self):
        with self.assertRaises(FlowError) as caught:
            self.runtime.prepare(self.config)
        self.assertEqual(caught.exception.code, "INLINE_MODEL_CONFIG_UNSUPPORTED")
        self.assertFalse(self.runtime.directory.exists())

    def test_prepare_freezes_parsed_parameters_not_private_toml_comments(self):
        self.write_profiles(self.config["tracks"])
        profile = self.profiles / "seed.toml"
        profile.write_text(profile.read_text() + "\n# DO_NOT_COPY_PRIVATE_COMMENT\n")
        requested = copy.deepcopy(self.config)
        requested.pop("tracks")
        self.runtime.prepare(requested)
        for path in self.runtime.directory.rglob("*"):
            if path.is_file():
                self.assertNotIn(b"DO_NOT_COPY_PRIVATE_COMMENT", path.read_bytes(), str(path))
        manifest = json.loads((self.runtime.directory / "manifest.json").read_text())
        self.assertEqual(manifest["profile_sources"]["seed"]["sha256"], _sha256(profile))

    def test_missing_duration_snapshot_is_rejected_without_legacy_fallback(self):
        self.prepare()
        path = self.runtime.directory / "manifest.json"
        manifest = json.loads(path.read_text())
        del manifest["duration_snapshot"]
        path.write_text(json.dumps(manifest))
        before = path.read_bytes()
        with self.assertRaises(FlowError) as caught:
            self.runtime.status("seed")
        self.assertEqual(caught.exception.code, "DURATION_DRIFT")
        self.assertEqual(path.read_bytes(), before)

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

    def test_default_preflight_uses_native_tui_and_keeps_native_records(self):
        self.prepare()
        self.assertEqual(self.runtime.preflight('codex', True)['status'], 'ready')
        self.assertNotIn('exec', self.backend.commands[-1])
        self.assertTrue(list((self.runtime.directory/'codex/logs').rglob('native.jsonl')))

    def test_prepared_run_without_native_mode_cannot_silently_change_runner(self):
        self.prepare()
        path = self.runtime.directory/'manifest.json'
        manifest = json.loads(path.read_text())
        manifest.pop('runtime_mode', None)
        path.write_text(json.dumps(manifest))
        with self.assertRaises(FlowError) as error:
            self.runtime.status('codex')
        self.assertEqual(error.exception.code, 'RUNTIME_MODE')

    def test_formal_and_exact_resume(self):
        self.prepare()
        self.runtime.minimum_seconds = lambda: 0
        self.runtime.preflight("codex", True)
        state = self.runtime._state("codex")
        result, _ = self.runtime._segment("codex", "formal", state, "start", 2)
        self.assertEqual(result["status"], "completed")
        self.runtime._segment("codex", "formal", state, "continue", 2, state["thread_id"])
        self.assertEqual(self.backend.commands[-1][1:3], ["resume", THREAD])
        self.assertEqual(self.runtime.status("codex")["formal_segments"], 2)
        self.assertIsNone(self.runtime._state("seed")["thread_id"])

    def test_new_thread_on_resume_rejected(self):
        self.prepare()
        self.runtime.minimum_seconds = lambda: 0
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

    def test_native_run_continues_in_one_process_then_requests_explicit_closure(self):
        self.prepare()
        self.runtime.preflight('codex', True)
        self.backend.commands.clear()
        # Boundary clock fixture: exactly two iteration turns, then closure.
        self.runtime.minimum_seconds = lambda: (0 if hasattr(self.backend, 'last_terminal')
            and self.backend.last_terminal.base.name == 'formal'
            and self.backend.last_terminal.turns >= 2 else 36000)
        result = self.runtime.run('codex', 2, confirm_cost=True)
        terminal = self.backend.last_terminal
        self.assertEqual(len(self.backend.commands), 1)
        self.assertEqual(terminal.turns, 3)
        self.assertEqual(terminal.sent, [self.runtime.continuation_prompt(), CLOSE_PROMPT, '/quit'])
        self.assertTrue(terminal.closed)
        self.assertIsNone(result['active'])
        segment = self.runtime._state('codex')['segments'][-1]
        self.assertTrue(segment['closure_completed'])
        self.assertEqual(segment['status'], 'completed')

    def test_resume_after_error_uses_same_thread_and_does_not_replay_old_work(self):
        self.prepare()
        self.runtime.preflight('codex', True)
        self.backend.mode = 'error'
        self.runtime.run('codex', 2, confirm_cost=True)
        first = self.runtime._state('codex')['segments'][-1]
        self.assertEqual(first['status'], 'failed')
        self.backend.mode = 'ok'
        self.runtime.minimum_seconds = lambda: 0
        self.runtime.run('codex', 2, resume=True, confirm_cost=True)
        self.assertEqual(self.backend.commands[-1][1:3], ['resume', THREAD])
        self.assertEqual(self.runtime._state('codex')['segments'][-1]['completed_turns'], 1)
        self.assertEqual(self.backend.commands[-1][-1], CLOSE_PROMPT)

    def test_formal_closure_cannot_be_claimed_from_a_turn_without_agent_artifacts(self):
        self.prepare()
        self.runtime.preflight('codex', True)
        self.backend.mode = 'missing_output'
        self.runtime.minimum_seconds = lambda: 0
        state = self.runtime._state('codex')
        result, _ = self.runtime._segment('codex', 'formal', state, CLOSE_PROMPT, 2)
        self.assertEqual(result['status'], 'failed')
        self.assertFalse(result['closure_completed'])

    def test_changing_both_best_and_candidate_after_evaluation_is_not_valid_closure(self):
        self.prepare()
        self.runtime.minimum_seconds = lambda: 0
        self.backend.mode = 'unscored_change'
        result, _ = self.runtime._segment('codex', 'formal', self.runtime._state('codex'), CLOSE_PROMPT, 2)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('哈希', result['error'])
        self.assertFalse(result['closure_completed'])

    def test_budget_pause_does_not_count_unverified_pending_tail(self):
        self.prepare()
        self.runtime.preflight('codex', True)
        self.backend.mode = 'pending'
        state = self.runtime._state('codex')
        result, _ = self.runtime._segment('codex', 'formal', state, 'start', .2)
        self.assertEqual(result['status'], 'budget_exhausted')
        self.assertFalse(result['closure_completed'])
        self.assertEqual(result['thread_id'], THREAD)
        self.assertLess(result['observed_active_seconds'], .05)
        self.assertGreaterEqual(result['wall_seconds'], .2)
        self.assertIsNone(self.runtime.status('codex')['active'])

    def test_optional_screen_write_failure_cannot_skip_process_cleanup(self):
        self.prepare()
        original = Path.write_text
        def write(path, *args, **kwargs):
            if path.name == 'screen.txt':
                raise OSError('synthetic ENOSPC')
            return original(path, *args, **kwargs)
        with patch.object(Path, 'write_text', write), patch.object(self.backend, 'stop') as stop:
            self.assertEqual(self.runtime.preflight('codex', True)['status'], 'ready')
        stop.assert_called()
        self.assertTrue(self.backend.last_terminal.closed)
        self.assertIsNone(self.runtime.status('codex')['active'])

    def test_bad_agent_json_is_recorded_as_failure_before_recovery(self):
        self.prepare()
        self.runtime.minimum_seconds = lambda: 0
        original = Path.read_text
        def read(path, *args, **kwargs):
            if path.name == 'trajectory.jsonl':
                return '{not json}\n'
            return original(path, *args, **kwargs)
        with patch.object(Path, 'read_text', read):
            result, _ = self.runtime._segment('codex', 'formal', self.runtime._state('codex'), CLOSE_PROMPT, 2)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('轨迹', result['error'])
        self.assertIsNone(self.runtime.status('codex')['active'])

    def test_invalid_utf8_trajectory_is_recorded_as_failure(self):
        self.prepare()
        self.runtime.minimum_seconds = lambda: 0
        original = FakeNativeTerminal.emit_turn
        def corrupt(terminal):
            original(terminal)
            (terminal.base/'output/trajectory.jsonl').write_bytes(b'\xff\n')
        with patch.object(FakeNativeTerminal, 'emit_turn', corrupt):
            result, _ = self.runtime._segment('codex', 'formal', self.runtime._state('codex'), 'test', 5)
        self.assertEqual(result['status'], 'failed')
        self.assertIn('轨迹', result['error'])
        self.assertIsNone(self.runtime._state('codex')['active'])

    def test_completed_turn_waits_for_background_process_before_quit(self):
        self.prepare()
        self.runtime.minimum_seconds = lambda: 0
        self.backend.mode = 'background'
        result, _ = self.runtime._segment('codex', 'formal', self.runtime._state('codex'), 'test', 5)
        terminal = self.backend.last_terminal
        self.assertEqual(result['status'], 'completed')
        self.assertEqual(terminal.turns, 2)
        self.assertIn('后台', terminal.sent[0])
        self.assertEqual(terminal.sent[-1], '/quit')

    def test_attach_observes_only_recorded_active_terminal_and_does_not_change_state(self):
        self.prepare()
        with self.assertRaises(FlowError) as caught:
            self.runtime.attach('codex')
        self.assertEqual(caught.exception.code, 'TERMINAL_UNAVAILABLE')
        state = self.runtime._state('codex')
        state['active'] = {'terminal_socket': '/synthetic/ar-tui-test/tmux.sock'}
        self.runtime._save('codex', state)
        before = (self.runtime.directory/'codex/state.json').read_bytes()
        with patch('autoresearch_flow.runtime.TmuxTerminal.existing') as existing:
            existing.return_value.observe.return_value = {'status': 'observer_detached', 'readonly': True}
            self.assertTrue(self.runtime.attach('codex')['readonly'])
        existing.assert_called_once_with(state['active']['terminal_socket'])
        self.assertEqual((self.runtime.directory/'codex/state.json').read_bytes(), before)
        self.assertEqual(self.backend.commands, [])

    def test_cleanup_failure_requires_recovery_not_another_run(self):
        self.prepare()
        self.runtime.preflight('codex', True)
        self.backend.mode = 'error'
        with patch.object(self.backend, 'stop', side_effect=FlowError('CLEANUP_UNCONFIRMED', 'synthetic')):
            result = self.runtime.run('codex', 1, confirm_cost=True)
        self.assertIsNotNone(result['active'])
        self.assertEqual(self.runtime._state('codex')['segments'][-1]['status'], 'cleanup_unconfirmed')
        with self.assertRaises(FlowError) as error:
            self.runtime.run('codex', 1, resume=True, confirm_cost=True)
        self.assertEqual(error.exception.code, 'UNCLOSED_SEGMENT')
        self.assertIsNone(self.runtime.recover('codex')['active'])

    def test_preflight_retry_preserves_its_thread_and_is_not_formal_time(self):
        self.prepare()
        self.backend.mode = 'error'
        self.assertEqual(self.runtime.preflight('codex', True)['status'], 'blocked')
        self.backend.mode = 'ok'
        self.assertEqual(self.runtime.preflight('codex', True)['status'], 'ready')
        self.assertEqual(self.backend.commands[-1][1:3], ['resume', THREAD])
        self.assertIsNone(self.runtime.status('codex')['thread_id'])

    def test_log_tampering_detected(self):
        self.prepare()
        self.runtime.preflight("codex", True)
        p = next((self.runtime.directory / "codex/logs").rglob("native.jsonl"))
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
             patch('autoresearch_flow.runtime.TmuxTerminal.start', side_effect=AssertionError('API must not start')) as spawn, \
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
        self.prepare(config)
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
        (directory / "events.jsonl").write_text("".join(json.dumps({"at": at, "source": "native_rollout", "event": e})+"\n" for at,e in events))
        state["active"] = {"container": "owned", "segment_id": "interrupted", "phase": "formal"}
        self.runtime._save("codex", state)
        status = self.runtime.recover("codex")
        self.assertEqual(status["effective_seconds_before_content_review"], 10)
        self.assertEqual(status["thread_id"], THREAD)
        self.assertIsNone(status["active"])

    def test_default_profiles_prepare(self):
        config = copy.deepcopy(self.config)
        config.pop("tracks")
        templates = Path(__file__).resolve().parents[1] / "model_profiles"
        tracks = {}
        for name in ("codex", "seed"):
            tracks[name] = tomllib.loads((templates / f"{name}.example.toml").read_text())
            tracks[name].pop("schema_version")
            tracks[name]["auth_ref"]["path"] = str(self.auth)
        self.write_profiles(tracks)
        self.runtime.prepare(config)
        self.runtime.status("seed")
        self.assertEqual(self.runtime.config["tracks"]["seed"]["model"], "doubao-seed-2.1-turbo")
        self.assertEqual(self.runtime.config["tracks"]["seed"]["max_output_tokens"], 65536)
        self.assertEqual(self.runtime.config["tracks"]["codex"]["model"], "gpt-5.6-sol")
        self.assertEqual(set(json.loads((self.runtime.directory / "manifest.json").read_text())["profile_sources"]),
                         {"codex", "seed"})
        self.assertFalse((self.runtime.directory / "profiles").exists())

    def test_fixed_seed_profile_is_self_contained(self):
        # The root config.toml was an import source, not a deployment dependency.
        profile = tomllib.loads((Path(__file__).resolve().parents[1] / "model_profiles/seed.example.toml").read_text())
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
        snapshot = runtime.directory / "config.json"
        self.assertEqual(json.loads(snapshot.read_text())["tracks"]["seed"]["model"], "seed-first")
        (profiles / "seed.toml").write_text((profiles / "seed.toml").read_text().replace("seed-first", "seed-second"))
        runtime.status("seed")
        self.assertEqual(runtime.config["tracks"]["seed"]["model"], "seed-first")
        self.assertEqual(json.loads(snapshot.read_text())["tracks"]["seed"]["model"], "seed-first")
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
        self.assertEqual(runtime.store.check()["current_stage"], "1")
        self.assertEqual(runtime.store.check()["issues"], [])

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
