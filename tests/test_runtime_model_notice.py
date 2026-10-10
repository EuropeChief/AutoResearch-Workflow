"""Native UI notices must not migrate the model selected by the expert."""
from pathlib import Path
import tempfile
import tomllib
import unittest

from autoresearch_flow.common import FlowError
from autoresearch_flow.runtime_profiles import acknowledge_kept_model


class NoticeTests(unittest.TestCase):
    def setUp(self):
        tmp = tempfile.TemporaryDirectory()
        self.addCleanup(tmp.cleanup)
        self.path = Path(tmp.name) / 'config.toml'
        self.path.write_text('model = "configured-old"\nmodel_reasoning_effort = "max"\n'
                             '[permissions.track.network]\nenabled = false\n')
        self.catalog = {'data': [{'model': 'configured-old', 'upgrade': 'advertised-new'}]}

    def test_acknowledges_target_but_preserves_model_and_permissions(self):
        self.path.chmod(0o444)
        before = tomllib.loads(self.path.read_text())
        report = acknowledge_kept_model(self.path, 'configured-old', self.catalog)
        after = tomllib.loads(self.path.read_text())
        self.assertEqual(after.pop('notice'), {'model_migrations': {'configured-old': 'advertised-new'}})
        self.assertEqual(after, before)
        self.assertEqual(self.path.stat().st_mode & 0o777, 0o444)
        self.assertFalse(report['effective_model_changed'])

    def test_custom_model_or_no_upgrade_leaves_config_unchanged(self):
        before = self.path.read_bytes()
        for catalog in [None, {}, {'data': []}, {'data': [{'model': 'another', 'upgrade': 'new'}]},
                        {'data': [{'model': 'configured-old', 'upgrade': None}]}]:
            self.assertIsNone(acknowledge_kept_model(self.path, 'configured-old', catalog))
            self.assertEqual(self.path.read_bytes(), before)

    def test_repeat_keeps_native_notice_preferences(self):
        acknowledge_kept_model(self.path, 'configured-old', self.catalog)
        before = self.path.read_bytes()
        acknowledge_kept_model(self.path, 'configured-old', self.catalog)
        self.assertEqual(self.path.read_bytes(), before)

    def test_wrong_effective_model_is_not_acknowledged(self):
        with self.assertRaises(FlowError):
            acknowledge_kept_model(self.path, 'another', {'data': [{'model': 'another', 'upgrade': 'new'}]})
