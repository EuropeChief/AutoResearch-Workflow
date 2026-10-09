import unittest
from unittest.mock import AsyncMock, Mock, patch
from types import SimpleNamespace

from autoresearch_flow.runtime_container import NativeContainer
from test_independent_runtime import TrackPreparationTests


class ContainerTests(TrackPreparationTests, unittest.IsolatedAsyncioTestCase):
    async def test_native_start_persists_actual_container_id(self):
        runtime=self.prepare()
        container=NativeContainer(runtime)
        fake=SimpleNamespace(start=AsyncMock(),_run_docker_compose_command=AsyncMock(
            return_value=SimpleNamespace(stdout='actual-container')))
        def create():
            container.environment=fake
        with patch.object(container,'create',side_effect=create),patch.object(container,'exec_agent',
            AsyncMock(return_value=SimpleNamespace(return_code=0,stdout='codex-cli 0.160.0'))):
            await container.start()
        self.assertEqual(container.cid,'actual-container')
        self.assertTrue((runtime.directory/'container.json').exists())

    async def test_readiness_checked_inside_container_not_host_symlink(self):
        runtime=self.prepare()
        container=NativeContainer(runtime)
        container.cid='actual-container'
        (runtime.directory/'codex_home/control.sock').symlink_to('/tmp/container-only-socket')
        fake=SimpleNamespace(returncode=0,communicate=AsyncMock(return_value=(b'',b'')))
        with patch('asyncio.create_subprocess_exec',AsyncMock(return_value=fake)),patch.object(container,'exec_agent',
            AsyncMock(return_value=SimpleNamespace(return_code=0))) as observed:
            await container.backend()
        observed.assert_awaited_once_with('test -S /codex/control.sock',timeout=5)
