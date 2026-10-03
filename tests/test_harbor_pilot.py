"""Offline checks for the synthetic pilot's verdict reader, not a Harbor trial."""
import importlib.util
import hashlib
import json
from pathlib import Path
import tempfile
import unittest

PILOT = Path(__file__).resolve().parents[1] / 'pilots/pca_cpu/run_harbor.py'
spec = importlib.util.spec_from_file_location('pca_harbor_probe', PILOT)
pilot = importlib.util.module_from_spec(spec)
spec.loader.exec_module(pilot)


class VerdictTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.trial = self.root / 'job/trial'
        self.candidate = self.root / 'probe.py'
        self.candidate.write_text('# synthetic')
        sha = hashlib.sha256(self.candidate.read_bytes()).hexdigest()
        self.result = {'exception_info': None, 'verifier_environment_mode': 'separate',
                       'verifier_result': {'rewards': {'reward': 1}},
                       'agent_execution': {'finished_at': '2026-09-30T09:00:00Z'},
                       'verifier': {'started_at': '2026-09-30T09:00:01Z'}}
        files = {'result.json': json.dumps(self.result),
                 'artifacts/workspace/solution/method.py': '# synthetic',
                 'agent/transfer_probe.json': json.dumps({'candidate_sha256': sha, 'public_boundary': 'public-boundary-ok'}),
                 'verifier/reward.txt': '1\n',
                 'verifier/test-stdout.txt': '{"candidate_uid":65534}\n'}
        for name, text in files.items():
            path = self.trial / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text)

    def check(self):
        return pilot.inspect_trial(self.root / 'job', self.candidate)

    def test_actual_result_and_transfer_are_required(self):
        self.assertEqual(self.check()['reward'], 1)
        (self.trial/'artifacts/workspace/solution/method.py').write_text('# stale starter')
        with self.assertRaisesRegex(ValueError, 'candidate differs'):
            self.check()

    def test_exception_or_shared_mode_cannot_pass_with_reward(self):
        for field, value in [('exception_info', {'exception_type': 'Failure'}),
                             ('verifier_environment_mode', 'shared')]:
            with self.subTest(field=field):
                (self.trial/'result.json').write_text(json.dumps({**self.result, field: value}))
                with self.assertRaises(ValueError):
                    self.check()

    def test_output_and_execution_order_must_agree(self):
        (self.trial/'verifier/reward.txt').write_text('0')
        with self.assertRaisesRegex(ValueError, 'Reward file'):
            self.check()
        (self.trial/'verifier/reward.txt').write_text('1')
        self.result['verifier']['started_at'] = '2026-09-30T08:59:00Z'
        (self.trial/'result.json').write_text(json.dumps(self.result))
        with self.assertRaisesRegex(ValueError, 'before the Agent'):
            self.check()


if __name__ == '__main__':
    unittest.main()
