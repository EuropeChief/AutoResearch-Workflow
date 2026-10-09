import unittest
from autoresearch_flow.runtime_clock import activity_summary, union_seconds


class ClockTests(unittest.TestCase):
    def record(self, action, activity, t, **fields):
        return dict(action=action, activity=activity, monotonic=t, at=t+1000, segment='a', **fields)

    def test_overlapping_job_and_model_time_are_counted_once(self):
        rows = [self.record('start', 'turn', 10), self.record('start', 'job', 15),
                self.record('end', 'turn', 20), self.record('end', 'job', 25)]
        self.assertEqual(activity_summary(rows)['net_active_seconds'], 15)

    def test_known_outage_subtracted_and_unknown_open_not_guessed(self):
        rows = [self.record('start', 'turn', 10), self.record('end', 'turn', 30),
                self.record('exclude', None, 35, start_at=1015, stop_at=1020, reason='API error', evidence='log:4'),
                self.record('start', 'unknown', 40)]
        result = activity_summary(rows)
        self.assertEqual(result['net_active_seconds'], 15)
        self.assertEqual(len(result['unresolved']), 1)

    def test_pause_does_not_remove_healthy_training_interval(self):
        rows = [self.record('start', 'turn', 10), self.record('start', 'job', 11),
                self.record('end', 'turn', 12), self.record('end', 'job', 20)]
        self.assertEqual(activity_summary(rows)['net_active_seconds'], 10)

    def test_live_progress_and_same_thread_new_segment(self):
        rows = [self.record('start', 'turn', 10)]
        self.assertEqual(activity_summary(rows, now={'segment':'a','monotonic':20})['net_active_seconds'],10)
        self.assertEqual(activity_summary(rows, now={'segment':'b','monotonic':20})['net_active_seconds'],0)
