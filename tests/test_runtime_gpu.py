import json
import unittest

from autoresearch_flow.runtime_gpu import normalize_ids, normalize_uuid, validate_requests, validate_visible_uuids, gpu_overlay


class RuntimeGpuTests(unittest.TestCase):
    UUID = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

    def test_explicit_devices_and_cpu(self):
        self.assertEqual(normalize_ids(None), [])
        self.assertEqual(normalize_ids([]), [])
        self.assertEqual(normalize_ids('2,6'), ['2', '6'])
        self.assertEqual(normalize_ids(2), ['2'])
        for value in [True, '', 'all', '2,2', [True], [2, None], 'GPU-aaaa']:
            with self.assertRaises(ValueError):
                normalize_ids(value)

    def test_identity_normalizes_complete_uuid_not_prefix(self):
        self.assertEqual(normalize_uuid('GPU-' + self.UUID.upper()), self.UUID)
        validate_visible_uuids(['GPU-' + self.UUID], [self.UUID])
        with self.assertRaises(ValueError):
            validate_visible_uuids(['GPU-aaaaaaaa'], ['GPU-' + self.UUID])
        with self.assertRaises(ValueError):
            validate_visible_uuids(['GPU-' + self.UUID], [])

    def test_actual_device_request_must_match(self):
        request = {'Driver': 'nvidia', 'DeviceIDs': ['2'], 'Count': 0, 'Capabilities': [['gpu']]}
        validate_requests([request], ['2'])
        validate_requests(None, [])
        for bad, ids in [(None, ['2']), ([request], ['6']), ([request], []),
                         ([{**request, 'Count': -1}], ['2'])]:
            with self.assertRaises(ValueError):
                validate_requests(bad, ids)

    def test_overlay_adds_only_devices_and_cpu_clears_them(self):
        overlay = gpu_overlay(['2'])
        self.assertIn('device_ids: ["2"]', overlay)
        self.assertIn('devices: !override []', gpu_overlay([]))
        for unwanted in ['privileged', 'network_mode', 'docker.sock', 'entrypoint']:
            self.assertNotIn(unwanted, overlay)


if __name__ == '__main__':
    unittest.main()
