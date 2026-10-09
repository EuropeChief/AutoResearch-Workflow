"""LP-5: one-track preparation must not load workflow or another track."""
import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch
import subprocess

FLOW_ROOT = Path(__file__).resolve().parents[1]

from autoresearch_flow.common import FlowError
from autoresearch_flow.track_runtime import TrackRuntime


class TrackPreparationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / 'starter').mkdir()
        (self.root / 'starter/method.py').write_text('value = 1\n')
        (self.root / 'public_eval').mkdir()
        (self.root / 'public_eval/run.py').write_text('print("public")\n')
        (self.root / 'instruction.md').write_text('合法公开任务\n')
        (self.root / 'prompt.md').write_text('请独立迭代并由你记录轨迹。\n')
        self.profile = self.root / 'seed.toml'
        self.profile.write_text('''# do not copy this raw comment
schema_version = 1
model = "doubao-seed-2.1-turbo"
reasoning_effort = "high"
base_url = "https://example.invalid/v1"
context_window = 262144
auto_compact_token_limit = 160000
max_output_tokens = 65536
[auth_ref]
kind = "api_key_json"
path = "/private/auth.json"
key = "OPENAI_API_KEY"
''')
        self.config = {
            'schema_version': 3, 'track': 'seed', 'image': 'sha256:' + 'a' * 64,
            'codex_version': '0.160.0', 'model_profile': 'seed.toml',
            'candidate': 'starter', 'prompt': 'prompt.md',
            'public_files': [{'source': 'instruction.md', 'destination': 'instruction.md'},
                             {'source': 'public_eval', 'destination': 'public_eval'}],
            'evaluation': {'command': ['/usr/bin/python3', '/workspace/public_eval/run.py',
                                       '--candidate', '{candidate}', '--output', '{output}'],
                           'mode': 'direct'},
            'resources': {'cpus': 1, 'memory': '2g', 'gpu_ids': []},
        }

    def prepare(self, name='seed-run', config=None):
        return TrackRuntime.prepare(config or self.config, self.root / name, base_dir=self.root)

    def test_prepare_requires_neither_taskstore_nor_other_profile(self):
        (self.root / 'codex.toml').write_text('invalid toml = [')
        with patch('autoresearch_flow.core.TaskStore', side_effect=AssertionError('workflow access')):
            runtime = self.prepare()
            report = runtime.status()
        self.assertEqual(report['status'], 'prepared')
        self.assertEqual(report['track'], 'seed')
        self.assertFalse((self.root / '.autoresearch').exists())
        self.assertEqual((runtime.directory / 'solution/method.py').read_text(), 'value = 1\n')

    def test_snapshot_is_independent_of_live_source_and_other_track(self):
        runtime = self.prepare()
        source_hash = runtime.status()['implementation_sha256']
        self.profile.write_text('broken = [')
        (self.root / 'starter/method.py').write_text('value = 999\n')
        (self.root / 'codex-run').mkdir()
        (self.root / 'codex-run/config.json').write_text('broken')
        self.assertEqual(runtime.status()['implementation_sha256'], source_hash)
        self.assertEqual((runtime.directory / 'solution/method.py').read_text(), 'value = 1\n')

    def test_no_credentials_or_raw_toml_comments_in_snapshot(self):
        with patch('autoresearch_flow.track_runtime._read_json', side_effect=AssertionError('auth read')):
            runtime = self.prepare()
        text = (runtime.directory / 'config.json').read_text()
        generated = (runtime.directory / 'codex_home/config.toml').read_text()
        self.assertNotIn('do not copy this raw comment', text + generated)
        self.assertIn('model_context_window = 262144', generated)
        self.assertIn('model_auto_compact_token_limit = 160000', generated)
        self.assertNotIn('max_output_tokens =', generated)
        self.assertEqual(runtime.status()['model_parameters']['max_output_tokens'],
                         {'value': 65536, 'application': 'compaction_headroom_validation'})

    def test_snapshot_modification_is_detected_without_global_locks(self):
        runtime = self.prepare()
        p = runtime.directory / 'public/instruction.md'
        p.chmod(0o644)
        p.write_text('modified')
        with self.assertRaisesRegex(FlowError, '冻结'):
            runtime.status()

    def test_no_overwrite_and_no_parent_or_symlink_inputs(self):
        self.prepare()
        with self.assertRaises(FlowError):
            self.prepare()
        cfg = copy.deepcopy(self.config)
        (self.root / 'link').symlink_to(self.root / 'starter', target_is_directory=True)
        cfg['candidate'] = 'link'
        with self.assertRaises(FlowError):
            self.prepare('linked', cfg)
        self.assertFalse((self.root / 'linked').exists())

    def test_public_mapping_cannot_expose_auth_or_private_material(self):
        (self.root / 'auth.json').write_text('{"OPENAI_API_KEY":"DO_NOT_COPY"}')
        cfg = copy.deepcopy(self.config)
        cfg['model_profile'] = 'seed.toml'
        self.profile.write_text(self.profile.read_text().replace('/private/auth.json', str(self.root / 'auth.json')))
        cfg['public_files'].append({'source': 'auth.json', 'destination': 'data.json'})
        with self.assertRaises(FlowError):
            self.prepare('auth-exposure', cfg)
        self.assertFalse((self.root / 'auth-exposure').exists())
        cfg = copy.deepcopy(self.config)
        (self.root / 'reference').mkdir()
        (self.root / 'reference/method.py').write_text('private')
        cfg['public_files'].append({'source': 'reference', 'destination': 'ordinary'})
        with self.assertRaises(FlowError):
            self.prepare('reference-exposure', cfg)

    def test_unknown_wall_clock_and_inline_secrets_rejected(self):
        for field, value in [('wall_clock_seconds', 36000), ('tracks', {}), ('api_key', 'secret')]:
            cfg = copy.deepcopy(self.config)
            cfg[field] = value
            with self.assertRaises(FlowError):
                self.prepare('invalid-' + field, cfg)

    def test_two_tracks_prepare_separately_and_do_not_share_writable_paths(self):
        a = self.prepare()
        cfg = copy.deepcopy(self.config)
        cfg['track'] = 'codex'
        b = self.prepare('codex-run', cfg)
        self.assertNotEqual(a.directory, b.directory)
        for relative in ['solution', 'output', 'codex_home', 'jobs', 'logs']:
            self.assertNotEqual((a.directory / relative).stat().st_ino,
                                (b.directory / relative).stat().st_ino)
        self.assertNotEqual(a.status()['instance_id'], b.status()['instance_id'])

    def test_direct_cli_prepares_and_reads_without_task_root(self):
        config_path = self.root / 'runtime.json'
        config_path.write_text(json.dumps(self.config))
        for argv in [['prepare', '--config', str(config_path), '--output-dir', str(self.root / 'cli-run')],
                     ['status', '--runtime-dir', str(self.root / 'cli-run')]]:
            p = subprocess.run(['python3', str(FLOW_ROOT / 'cli.py'), '--format', 'json', 'runtime', *argv],
                               capture_output=True, text=True)
            self.assertEqual(p.returncode, 0, p.stderr + p.stdout)
            value = json.loads(p.stdout)
            self.assertEqual(value['status'], 'prepared')
            self.assertEqual(value['track'], 'seed')
        self.assertFalse((self.root / '.autoresearch').exists())

    def test_candidate_executable_permission_is_preserved(self):
        p = self.root / 'starter/run.sh'
        p.write_text('#!/bin/sh\nexit 0\n')
        p.chmod(0o755)
        runtime = self.prepare()
        self.assertEqual((runtime.directory / 'solution/run.sh').stat().st_mode & 0o777, 0o755)

    def test_native_tui_preferences_do_not_interrupt_frozen_track(self):
        runtime=self.prepare()
        path=runtime.directory/'codex_home/config.toml'
        path.chmod(0o644)
        with path.open('a') as stream:
            stream.write('\n[tui]\nscreen_reader_detection_done=true\n')
        self.assertEqual(runtime.status()['status'],'prepared')
        path.write_text(path.read_text().replace('approval_policy = "never"','approval_policy = "on-request"'))
        with self.assertRaises(FlowError):
            runtime.status()

    def test_explicit_codex_bundle_is_frozen_per_track(self):
        vendor=self.root/'vendor'
        (vendor/'bin').mkdir(parents=True)
        (vendor/'bin/codex').write_text('original')
        (vendor/'bin/codex').chmod(0o755)
        cfg=copy.deepcopy(self.config)
        cfg['codex_vendor']='vendor'
        runtime=self.prepare(config=cfg)
        (vendor/'bin/codex').write_text('upgraded')
        self.assertEqual((runtime.directory/'codex_runtime/bin/codex').read_text(),'original')
        self.assertEqual(runtime.status()['status'],'prepared')


if __name__ == '__main__':
    unittest.main()
