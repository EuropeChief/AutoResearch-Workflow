"""Harbor 0.23 extension. Imported only by the separately installed Harness."""
import asyncio
from importlib.metadata import version
from pathlib import Path
from typing import Literal

from harbor.agents.nop import NopAgent
from harbor.agents.options import AgentOptions
from pydantic import Field

from .core import _require, _atomic_json
from .harbor_runtime import HarborExecBackend, final_snapshot
from .runtime import Runtime
from . import FLOW_VERSION


class FlowOptions(AgentOptions):
    task_root: str
    track: Literal['codex', 'seed']
    action: Literal['preflight', 'run', 'finalize']
    budget: int = Field(gt=0)
    resume_original: bool = False


class FlowCodexAgent(NopAgent):
    options_model = FlowOptions

    @staticmethod
    def name():
        return 'autoresearch-codex'

    def version(self):
        return FLOW_VERSION

    async def setup(self, environment):
        _require(version('harbor') == '0.23.0', 'HARBOR_VERSION', '需 Harbor 0.23.0')
        # This is the sole pinned private Harbor interface used by the adapter.
        # It identifies a container Harbor has already created; no second agent
        # container and no Docker socket is mounted inside that container.
        result = await environment._run_docker_compose_command(['ps', '-q', 'main'])
        backend = HarborExecBackend(result.stdout.strip())
        self.runtime = Runtime(Path(self.options.task_root), backend=backend)
        self.runtime._load()
        await asyncio.to_thread(backend.check, self.runtime, self.options.track)
        await asyncio.to_thread(backend.boundary, self.runtime, self.options.track)

    async def run(self, instruction, environment, context):
        options = self.options
        if options.action == 'finalize':
            import json
            import subprocess
            from .trajectory import raw_public_metric
            snapshot = final_snapshot(self.runtime, options.track)
            command = self.runtime.backend.command(self.runtime, options.track, 'formal', 'ar-final-public',
                ['codex', 'sandbox', '-P', 'autoresearch', '--', '/workspace/evaluate'])
            try:
                check = await asyncio.to_thread(subprocess.run, command, capture_output=True, text=True,
                                                 timeout=options.budget)
            finally:
                await asyncio.to_thread(self.runtime.backend.stop, 'ar-final-public')
            _require(check.returncode == 0, 'FINAL_PUBLIC_FAILED', '最终公开复测失败，不运行 Hidden')
            value = json.loads(check.stdout.strip().splitlines()[-1])
            _require(raw_public_metric(value) is not None, 'FINAL_PUBLIC_FAILED', '公开复测没有成功原始指标')
            _require(snapshot == final_snapshot(self.runtime, options.track), 'FINAL_CANDIDATE_CHANGED', '公开复测改变了候选')
            result = {'status': 'candidate_ready', **snapshot, 'public_result': value}
        elif options.action == 'preflight':
            result = await asyncio.to_thread(self.runtime.preflight, options.track, allow_live=True)
            _require(result['status'] == 'ready', 'PREFLIGHT_FAILED', '真实预检失败；查看 runtime 分段日志')
        else:
            result = await asyncio.to_thread(self.runtime.run, options.track, options.budget,
                                             resume=options.resume_original, confirm_cost=True)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(self.logs_dir/'runtime_result.json', result)
        context.metadata = {'runtime_track': options.track, 'thread_id': result.get('thread_id')}
        # Every run/resume job has verifier.disable=true. Only explicit
        # finalize may reach Hidden; elapsed time alone never grants permission.
