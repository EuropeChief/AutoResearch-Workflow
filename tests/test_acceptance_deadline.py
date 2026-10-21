"""The synthetic live harness must bound execution and clean its own environment."""
import asyncio
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from pilots.direct_sandbox import acceptance


class AcceptanceDeadlineTests(unittest.IsolatedAsyncioTestCase):
    async def test_hung_startup_times_out_and_records_failure_before_cleanup(self):
        with tempfile.TemporaryDirectory() as temp:
            out = Path(temp) / 'acceptance'
            runtime = SimpleNamespace(directory=out / 'runtime')
            async def stalled():
                await asyncio.sleep(60)
            container = SimpleNamespace(start=AsyncMock(side_effect=stalled), stop=AsyncMock())
            args = SimpleNamespace(output=out, allow_live=True, image='synthetic',
                                   profile=Path('/synthetic/profile.toml'),
                                   codex_vendor=Path('/synthetic/vendor'),
                                   gpu_id=None, security_authorization=None)
            with patch.object(acceptance.TrackRuntime, 'prepare', return_value=runtime), \
                 patch.object(acceptance, 'NativeContainer', return_value=container), \
                 patch.object(acceptance, 'DEADLINE_SECONDS', .03):
                with self.assertRaises(TimeoutError):
                    await acceptance.run(args)
            container.stop.assert_awaited_once()
            result = json.loads((out / 'report.json').read_text())
            self.assertEqual(result['status'], 'failed')
            self.assertIn('TimeoutError', result['error'])
            self.assertEqual(result['model_calls'], 0)
