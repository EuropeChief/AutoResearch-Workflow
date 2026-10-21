"""Preflight must execute the prepared implementation, without Docker/model calls."""
import json
from pathlib import Path
import shutil
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from autoresearch_flow.common import FlowError
from autoresearch_flow.runtime_cli import dispatch


class FrozenPreflightTests(unittest.TestCase):
    def prepare(self, fail=False):
        from test_independent_runtime import TrackPreparationTests
        fixture = TrackPreparationTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        original = shutil.copyfile
        script = (
            "import json,sys\nfrom pathlib import Path\n"
            "assert '--preflight-only' in sys.argv\n"
            "root=Path(sys.argv[sys.argv.index('--runtime-dir')+1])\n"
            "(root/'preflight.json').write_text(json.dumps({'status':'succeeded', 'controller_file':__file__}))\n"
        ) if not fail else "raise SystemExit('SYNTHETIC frozen preflight failure')\n"
        def copy(source, target, *args, **kwargs):
            result = original(source, target, *args, **kwargs)
            if Path(source).name == 'runtime_controller.py':
                Path(target).write_text(script)
            return result
        # Freeze the synthetic controller before hashes are collected; never
        # rewrite an already-frozen implementation or the production source.
        with patch('autoresearch_flow.track_runtime.shutil.copyfile', side_effect=copy):
            runtime = fixture.prepare()
        args = SimpleNamespace(runtime_action='preflight', runtime_dir=runtime.directory,
                               task_root=None, budget_seconds=None, track=None,
                               allow_live=True, allow_busy_gpu=False)
        return runtime, args

    def test_live_controller_update_cannot_replace_prepared_preflight(self):
        runtime, args = self.prepare()
        with patch('autoresearch_flow.runtime_controller.Controller',
                   side_effect=AssertionError('live controller must not execute')):
            result = dispatch(args)
        self.assertEqual(result['status'], 'succeeded')
        self.assertTrue(Path(result['controller_file']).is_relative_to(runtime.directory / 'implementation'))

    def test_failed_frozen_preflight_keeps_its_log_without_switching_versions(self):
        runtime, args = self.prepare(fail=True)
        with self.assertRaisesRegex(FlowError, '原冻结实现预检失败'):
            dispatch(args)
        self.assertIn('SYNTHETIC frozen preflight failure',
                      (runtime.directory / 'logs/preflight-controller.log').read_text())
        self.assertFalse((runtime.directory / 'preflight.json').exists())
