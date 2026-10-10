"""Small GPU input/admission checks, not a scheduler or device supervisor."""
from __future__ import annotations

import re
import uuid


def normalize_ids(value):
    if value is None or value == []:
        return []
    if isinstance(value, bool) or not isinstance(value, (str, int, list)):
        raise ValueError('gpu_ids must be explicit indexes or complete GPU UUIDs')
    values = value if isinstance(value, list) else str(value).split(',')
    if any(isinstance(x, bool) or not isinstance(x, (str, int)) for x in values):
        raise ValueError('invalid GPU ID type')
    ids = [str(x).strip() for x in values]
    if not ids or len(set(ids)) != len(ids) or any(not re.fullmatch(r'(?:\d+|GPU-[0-9a-fA-F-]{36})', x) for x in ids):
        raise ValueError('empty, duplicate or unsupported GPU IDs')
    for x in ids:
        if x.startswith('GPU-'):
            normalize_uuid(x)
    return ids


def normalize_uuid(value):
    if isinstance(value, bytes):
        return str(uuid.UUID(bytes=value))
    if not isinstance(value, str):
        raise ValueError('GPU identity must be a complete UUID')
    return str(uuid.UUID(value.strip().removeprefix('GPU-')))


def validate_requests(requests, ids):
    if not ids:
        if requests:
            raise ValueError('zero-GPU environment has device requests')
        return
    if len(requests or []) != 1:
        raise ValueError('exactly one NVIDIA DeviceRequest required')
    item = requests[0]
    if (item.get('Driver') != 'nvidia' or item.get('DeviceIDs') != ids
            or item.get('Count', 0) != 0 or ['gpu'] not in item.get('Capabilities', [])):
        raise ValueError('actual Docker GPU allocation differs from explicit IDs')


def validate_visible_uuids(actual, expected):
    actual = [normalize_uuid(x) for x in actual]
    expected = [normalize_uuid(x) for x in expected]
    if len(actual) != len(set(actual)) or len(expected) != len(set(expected)) or sorted(actual) != sorted(expected):
        raise ValueError('visible physical GPU identity differs from allocation')


def gpu_overlay(ids):
    import json
    prefix = 'services:\n  main:\n    deploy:\n      resources:\n        reservations:\n'
    if not ids:
        return prefix + '          devices: !override []\n'
    return (prefix + '          devices: !override\n            - driver: nvidia\n              device_ids: '
            + json.dumps(ids) + '\n              capabilities: [gpu]\n')
