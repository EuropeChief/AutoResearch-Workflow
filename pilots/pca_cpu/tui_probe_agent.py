"""Thin Harbor plugin for the bounded native-TUI CPU acceptance probe."""
import asyncio

from autoresearch_flow.core import _require
from autoresearch_flow.harbor_agent import FlowCodexAgent
from pilots.pca_cpu.run_tui_probe import probe


class TuiProbeAgent(FlowCodexAgent):
    @staticmethod
    def name():
        return 'autoresearch-tui-probe'

    async def setup(self, environment):
        await super().setup(environment)
        result = await environment.exec(
            "python3 -c \"from pathlib import Path; assert not list(Path('/dev').glob('nvidia[0-9]*'))\"",
            timeout_sec=10)
        _require(result.return_code == 0, 'LIVE_SCOPE', '实际容器暴露了 GPU；本 CPU 探针在调用模型前停止')

    async def run(self, instruction, environment, context):
        _require(self.options.track == 'seed' and self.options.action == 'preflight',
                 'LIVE_SCOPE', '本联调仅授权 Seed 短测，不运行其他模型或正式评分')
        directory = self.runtime.root/'tui_probe/evidence'
        directory.mkdir()
        report = await asyncio.to_thread(probe, self.runtime, directory, self.options.budget)
        context.metadata = {'thread_id': report['thread_id'], 'tui_probe_status': report['status']}
