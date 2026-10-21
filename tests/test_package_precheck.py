"""Read-only format checks on synthetic inputs, never submitted code execution."""
import json
from pathlib import Path
import tempfile
import unittest

from autoresearch_flow.common import FlowError
from autoresearch_flow.package_precheck import check
from autoresearch_flow.task_binding import fingerprint


class PackagePrecheckTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.package = self.root / 'package'
        self.task = self.package / 'workspace/harbor_task'
        for part in ('environment', 'tests'):
            (self.task / part).mkdir(parents=True)
        (self.task / 'instruction.md').write_text('# Synthetic task\n')
        (self.task / 'task.toml').write_text('version="1.0"\n[environment]\ndocker_image="synthetic/solver:1"\ngpus=0\n[verifier]\nenvironment_mode="separate"\n[verifier.environment]\ndocker_image="synthetic/verifier:1"\ngpus=0\n')
        (self.task / 'tests/test.sh').write_text('#!/bin/sh\nexit 0\n')

    def test_only_future_evidence_directories_are_deferred_at_launch(self):
        result = check(self.package, self.root / 'before', phase='before_research')
        self.assertEqual(result['status'], 'format_checked_not_qa')
        self.assertEqual(result['original_decision'], 'FAIL')
        self.assertEqual(len(result['deferred_until_final']), 2)
        raw = json.loads((self.root / 'before/report.json').read_text())
        self.assertEqual(raw['decision'], 'FAIL')
        result = check(self.package, self.root / 'final')
        self.assertEqual(result['status'], 'blocked')

    def test_missing_task_structure_is_never_deferred(self):
        (self.task / 'instruction.md').unlink()
        result = check(self.package, self.root / 'report', phase='before_research')
        self.assertEqual(result['status'], 'blocked')

    def test_reports_cannot_mutate_source_or_overwrite_old_evidence(self):
        with self.assertRaises(FlowError):
            check(self.package, self.package / 'report')
        (self.root / 'old').mkdir()
        with self.assertRaises(FlowError):
            check(self.package, self.root / 'old')

    def test_official_fingerprint_tracks_all_four_inputs_and_rejects_links(self):
        before = fingerprint(self.task)
        (self.task / 'environment/.hidden').write_text('included')
        self.assertNotEqual(before['task_content_sha256'], fingerprint(self.task)['task_content_sha256'])
        (self.task / 'environment/.hidden').unlink()
        (self.task / 'outside.txt').write_text('outside profile')
        self.assertEqual(before, fingerprint(self.task))
        (self.task / 'tests/alias').symlink_to(self.task / 'instruction.md')
        with self.assertRaises(FlowError):
            fingerprint(self.task)
