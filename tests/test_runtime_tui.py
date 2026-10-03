"""Native rollout and terminal contracts; synthetic, no model or Docker calls."""
import datetime as dt
import json
from pathlib import Path
import tempfile
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autoresearch_flow.runtime_events import EventClock
from autoresearch_flow.core import FlowError
from autoresearch_flow.runtime import public_evaluation
from autoresearch_flow.runtime_tui import NativeEvents, RolloutTail, TmuxTerminal, codex_command

THREAD = '11111111-1111-1111-1111-111111111111'


def row(at, kind, **payload):
    return {'timestamp': dt.datetime.fromtimestamp(at, dt.timezone.utc).isoformat(),
            'type': kind, 'payload': payload}


def meta():
    return row(0, 'session_meta', id=THREAD, cli_version='0.147.0')


class NativeEventsTests(unittest.TestCase):
    def test_public_result_needs_exact_executed_command_and_successful_exit(self):
        adapter = NativeEvents('0.147.0')
        adapter.convert(meta())
        adapter.convert(row(0, 'event_msg', type='task_started', turn_id='t1'))
        result = {'status': 'succeeded', 'score': 0.5,
                  'raw_metric': {'name': 'error', 'direction': 'minimize', 'value': 4.5}}
        for command, code, expected in [('/workspace/evaluate', 0, result),
                                        ('echo /workspace/evaluate', 0, None),
                                        ('/workspace/evaluate', 1, None)]:
            adapter.convert(row(1, 'response_item', type='function_call', name='exec_command',
                                call_id='c', arguments=json.dumps({'cmd': command})))
            item = adapter.convert(row(2, 'response_item', type='function_call_output', call_id='c',
                                       output=f'Process exited with code {code}\nFinal output:\n'+json.dumps(result)))[0]['item']
            self.assertEqual(public_evaluation(item, ['/workspace/evaluate']), expected)

    def test_external_failure_stops_time_and_compaction_keeps_original_thread(self):
        adapter, clock = NativeEvents('0.147.0', THREAD), EventClock(THREAD)
        records = [meta(), row(0, 'event_msg', type='task_started', turn_id='t1'),
                   row(10, 'compacted', message='synthetic summary'),
                   row(20, 'event_msg', type='error', message='context exceeded'),
                   row(300, 'event_msg', type='token_count', info={}),
                   row(400, 'event_msg', type='task_started', turn_id='t2'),
                   row(420, 'event_msg', type='task_complete', turn_id='t2')]
        converted = []
        for record in records:
            for event in adapter.convert(record):
                converted.append(event)
                clock.event(event, dt.datetime.fromisoformat(record['timestamp']).timestamp())
        self.assertEqual(clock.summary()['observed_active_seconds'], 40)
        self.assertEqual(clock.summary()['completed_turns'], 1)
        self.assertEqual(clock.thread_id, THREAD)
        self.assertTrue(any(e.get('item', {}).get('type') == 'compaction' for e in converted))

    def test_session_and_turn_identity_are_not_guessed(self):
        adapter = NativeEvents('0.147.0', THREAD)
        different = meta()
        different['payload']['id'] = '22222222-2222-2222-2222-222222222222'
        with self.assertRaises(FlowError):
            adapter.convert(different)
        adapter.convert(meta())
        adapter.convert(row(0, 'event_msg', type='task_started', turn_id='t1'))
        with self.assertRaises(FlowError):
            adapter.convert(row(1, 'event_msg', type='task_started', turn_id='t2'))
        with self.assertRaises(FlowError):
            adapter.convert(row(2, 'event_msg', type='task_complete', turn_id='wrong'))
        with self.assertRaises(FlowError):
            adapter.convert(row(3, 'response_item', type='function_call_output', call_id='missing', output='ok'))

    def test_training_wait_and_idle_are_not_process_lifetime(self):
        adapter, clock = NativeEvents('0.147.0'), EventClock()
        records = [meta(), row(0, 'event_msg', type='task_started', turn_id='t1'),
                   row(1, 'response_item', type='function_call', name='exec_command',
                       call_id='c1', arguments='{"cmd":"python train.py"}'),
                   row(610, 'response_item', type='function_call_output', call_id='c1', output='score=0.5'),
                   row(620, 'event_msg', type='task_complete', turn_id='t1'),
                   row(1000, 'event_msg', type='token_count', info={})]
        adapted = []
        for record in records:
            for event in adapter.convert(record):
                adapted.append(event)
                clock.event(event, dt.datetime.fromisoformat(record['timestamp']).timestamp())
        self.assertEqual(clock.summary()['observed_active_seconds'], 620)
        self.assertTrue(adapter.idle)
        self.assertEqual(adapter.thread_id, THREAD)
        outputs = [e['item']['aggregated_output'] for e in adapted
                   if e['type'] == 'item.completed' and e['item'].get('type') == 'command_execution']
        self.assertEqual(outputs, ['score=0.5'])


class RolloutTailTests(unittest.TestCase):
    def test_missing_identity_changed_log_and_foreign_session_are_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            path = home/'sessions/rollout.jsonl'
            path.parent.mkdir()
            path.write_text(json.dumps(row(0, 'event_msg', type='task_started', turn_id='t1'))+'\n')
            with self.assertRaises(FlowError):
                RolloutTail(home, '0.147.0', THREAD)
            path.write_text(json.dumps(meta())+'\n')
            tail = RolloutTail(home, '0.147.0', THREAD)
            tail.poll()
            path.write_text('')
            with self.assertRaises(FlowError):
                tail.poll()
            path.write_text(json.dumps(meta())+'\n')
            tail = RolloutTail(home, '0.147.0', THREAD)
            (path.parent/'foreign.jsonl').write_text(json.dumps(meta())+'\n')
            with self.assertRaises(FlowError):
                tail.poll()

    def test_partial_line_and_resume_do_not_replay_old_work(self):
        with tempfile.TemporaryDirectory() as directory:
            home = Path(directory)
            tail = RolloutTail(home, '0.147.0')
            self.assertEqual(tail.poll(), [])
            path = home/'sessions/day/rollout.jsonl'
            path.parent.mkdir(parents=True)
            path.write_text(json.dumps(meta())+'\n')
            self.assertEqual(tail.poll()[0]['events'][0]['thread_id'], THREAD)
            started = json.dumps(row(10, 'event_msg', type='task_started', turn_id='old'))
            with path.open('a') as stream:
                stream.write(started[:12])
            self.assertEqual(tail.poll(), [])
            with path.open('a') as stream:
                stream.write(started[12:]+'\n')
                stream.write(json.dumps(row(20, 'event_msg', type='task_complete', turn_id='old'))+'\n')
            self.assertEqual(len(tail.poll()), 2)
            resumed = RolloutTail(home, '0.147.0', THREAD)
            boot = resumed.poll()
            self.assertEqual([e['type'] for item in boot for e in item['events']], ['thread.started'])
            with path.open('a') as stream:
                stream.write(json.dumps(row(100, 'event_msg', type='task_started', turn_id='new'))+'\n')
            new = resumed.poll()
            self.assertEqual(len(new), 1)
            self.assertEqual(new[0]['native']['payload']['turn_id'], 'new')
            self.assertEqual(new[0]['native_at'], 100)
            self.assertFalse(resumed.adapter.idle)


class TerminalTests(unittest.TestCase):
    def test_native_resume_detached_terminal_and_readonly_observer(self):
        calls = []
        def run(args, **kwargs):
            calls.append((args, kwargs))
            output = '0|\n' if 'display-message' in args else ''
            return SimpleNamespace(returncode=0, stdout=output, stderr='')
        with patch('subprocess.run', side_effect=run):
            terminal = TmuxTerminal()
            try:
                terminal.start(codex_command('synthetic prompt', THREAD), {'PATH': '/synthetic'})
                self.assertEqual(terminal.status(), {'alive': True, 'exit_code': None})
                attach = terminal.attach_command()
                self.assertIn('-r', attach)
                self.assertIn('attach-session', attach)
                terminal.send('固定的继续指令\n不改变方法范围')
            finally:
                terminal.close()
        start = next(args for args, _ in calls if 'new-session' in args)
        self.assertIn('-d', start)
        self.assertIn('-f', start)
        self.assertIn('/dev/null', start)
        native = codex_command('hello', THREAD)
        self.assertEqual(native[:3], ['codex', 'resume', THREAD])
        self.assertNotIn('--json', native)
        self.assertNotIn('exec', native)
        self.assertFalse(any('attach-session' in args for args, _ in calls))
        paste = next(kwargs for args, kwargs in calls if 'load-buffer' in args)
        self.assertEqual(paste['input'], '固定的继续指令\n不改变方法范围')
        self.assertTrue(any('kill-server' in args for args, _ in calls))

    def test_missing_tmux_is_actionable_without_installing(self):
        with patch('subprocess.run', side_effect=FileNotFoundError), self.assertRaises(FlowError) as error:
            with TmuxTerminal() as terminal:
                terminal.start(['synthetic'], {})
        self.assertEqual(error.exception.code, 'HOST_DEPENDENCY_UNAVAILABLE')


class PilotEvidenceTests(unittest.TestCase):
    def test_error_and_later_success_in_one_poll_cannot_reuse_failed_turn_result(self):
        import test_w3_contract as w3
        from autoresearch_flow.harbor_runtime import HarborExecBackend
        from pilots.pca_cpu.run_tui_probe import probe
        fx = w3.RuntimeTests()
        fx.setUp()
        self.addCleanup(fx.doCleanups)
        fx.prepare()
        fx.runtime.backend = HarborExecBackend('a'*64)
        directory = fx.root/'probe'
        directory.mkdir()
        result = {'status': 'succeeded', 'score': 0.5,
                  'raw_metric': {'name': 'error', 'direction': 'minimize', 'value': 4.5}}
        def run(args, **kwargs):
            if 'new-session' in args:
                at = time.time()
                records = [row(at, 'session_meta', id=THREAD, cli_version='0.147.0'),
                           row(at, 'event_msg', type='task_started', turn_id='A'),
                           row(at, 'response_item', type='function_call', name='exec_command', call_id='c',
                               arguments='{"cmd":"/workspace/evaluate"}'),
                           row(at, 'response_item', type='function_call_output', call_id='c',
                               output='Process exited with code 0\n'+json.dumps(result)),
                           row(at, 'event_msg', type='error', message='external failure'),
                           row(at, 'event_msg', type='task_started', turn_id='B'),
                           row(at, 'event_msg', type='task_complete', turn_id='B')]
                path = fx.runtime.directory/'seed/preflight/codex_home/sessions/rollout.jsonl'
                path.parent.mkdir()
                path.write_text(''.join(json.dumps(value)+'\n' for value in records))
            return SimpleNamespace(returncode=0, stdout='0|\n' if 'display-message' in args else '', stderr='')
        with patch('subprocess.run', side_effect=run), \
             patch('subprocess.Popen', side_effect=AssertionError('must stop before opening observer')), \
             self.assertRaises(FlowError) as error:
            probe(fx.runtime, directory, 10)
        self.assertEqual(error.exception.code, 'TUI_FAILED')
        self.assertEqual(json.loads((directory/'report.json').read_text())['status'], 'blocked')


if __name__ == '__main__':
    unittest.main()
