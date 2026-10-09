"""Thin Harbor 0.23 NVIDIA provider; native lifecycle and verifier remain intact.

Load with -e autoresearch_flow.harbor_gpu:GpuDockerEnvironment --ek gpu_ids=2.
Requires existing NVIDIA Docker runtime, Compose >=2.24.4 and CUDA PyTorch image.
"""
import asyncio
import importlib.metadata
import json
from pathlib import Path
import shlex
import tempfile
import hashlib

from harbor.environments.docker.docker import DockerEnvironment, _sanitize_docker_compose_project_name

from .runtime_gpu import gpu_overlay, normalize_ids, normalize_uuid, validate_requests, validate_visible_uuids


async def host_output(*args):
    proc = await asyncio.create_subprocess_exec(*args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    try:
        out, err = await asyncio.wait_for(proc.communicate(), timeout=20)
    except BaseException:
        if proc.returncode is None:
            proc.kill()
            await proc.wait()
        raise
    if proc.returncode:
        raise RuntimeError(err.decode(errors='replace'))
    return out.decode().strip()


class GpuDockerEnvironment(DockerEnvironment):
    def __init__(self, *args, gpu_ids=None, allow_busy=False, **kwargs):
        if importlib.metadata.version('harbor') != '0.23.0':
            raise ValueError('thin provider currently verified only against Harbor 0.23.0')
        if kwargs.get('keep_containers'):
            raise ValueError('thin provider uses native cleanup, not keep_containers')
        self._gpu_ids = normalize_ids(gpu_ids)
        if allow_busy not in (True, False, 'true', 'false'):
            raise ValueError('allow_busy must be an explicit boolean permission')
        self._allow_busy = allow_busy in (True, 'true')
        self._gpu_temp = self._gpu_overlay = None
        super().__init__(*args, **kwargs)
        if self._is_windows_container:
            raise ValueError('thin GPU provider requires Linux NVIDIA Docker')
        if self._effective_gpus != len(self._gpu_ids):
            raise ValueError('task GPU count differs from explicit gpu_ids')
        self._gpu_temp = tempfile.TemporaryDirectory(prefix='ar-harbor-gpu-')
        self._gpu_overlay = Path(self._gpu_temp.name) / 'gpu.yaml'
        self._gpu_overlay.write_text(gpu_overlay(self._gpu_ids))

    @property
    def capabilities(self):
        return super().capabilities.model_copy(update={'gpus': True})

    @property
    def _docker_compose_paths(self):
        return super()._docker_compose_paths + ([self._gpu_overlay] if self._gpu_overlay else [])

    async def start(self, force_build):
        try:
            expected = [await host_output('nvidia-smi', '-i', x, '--query-gpu=uuid', '--format=csv,noheader')
                        for x in self._gpu_ids]
            if len(set(normalize_uuid(x) for x in expected)) != len(expected):
                raise ValueError('GPU aliases select the same physical device')
            if expected and not self._allow_busy:
                raw = await host_output('nvidia-smi', '--query-compute-apps=gpu_uuid,pid', '--format=csv,noheader')
                selected = {normalize_uuid(x) for x in expected}
                for line in raw.splitlines():
                    parts = line.split(',')
                    if len(parts) == 2 and normalize_uuid(parts[0]) in selected:
                        raise ValueError('selected GPU has an existing compute process; do not take over')
            await super().start(force_build)
            cid_result = await self._run_docker_compose_command(['ps', '-q', 'main'], timeout_sec=20)
            cid = (cid_result.stdout or '').strip()
            if not cid or '\n' in cid:
                raise RuntimeError('cannot identify one native main container')
            info = json.loads(await host_output('docker', 'inspect', cid))[0]
            host = info['HostConfig']
            validate_requests(host.get('DeviceRequests'), self._gpu_ids)
            if host.get('Privileged') or any(m.get('Destination', '').endswith('docker.sock') for m in info['Mounts']):
                raise ValueError('privileged container or Docker socket exposure')
            if not expected:
                return
            identity = await self.exec('nvidia-smi --query-gpu=uuid --format=csv,noheader', user='root', timeout_sec=20)
            if identity.return_code:
                raise RuntimeError('GPU UUID query failed: ' + (identity.stderr or ''))
            validate_visible_uuids((identity.stdout or '').strip().splitlines(), expected)
            code = ('import torch,json; assert torch.cuda.is_available(); assert torch.cuda.device_count()=='
                    + str(len(expected)) + ';\nfor i in range(torch.cuda.device_count()):\n'
                    + " x=torch.ones((32,32),device=f'cuda:{i}'); assert float((x@x).sum())==32768.0\n"
                    + "print(json.dumps({'cuda_matmul':True}))")
            compute = await self.exec('python -c ' + shlex.quote(code), user='root', timeout_sec=40)
            if compute.return_code:
                raise RuntimeError('CUDA admission failed: ' + (compute.stderr or compute.stdout or ''))
            audit = {'session_id': self.session_id, 'container_id': cid, 'image': info['Image'],
                     'gpu_ids': self._gpu_ids, 'gpu_uuids': expected, 'device_requests': host['DeviceRequests'],
                     'cuda_matmul': True, 'privileged': False, 'docker_socket_absent': True,
                     'provider_sha256': hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                     'gpu_helpers_sha256': hashlib.sha256(Path(__file__).with_name('runtime_gpu.py').read_bytes()).hexdigest(),
                     'allow_busy': self._allow_busy}
            self.trial_paths.trial_dir.mkdir(parents=True, exist_ok=True)
            (self.trial_paths.trial_dir / ('gpu-admission-' + cid[:12] + '.json')).write_text(json.dumps(audit, indent=2) + '\n')
        except BaseException:
            await self.stop(delete=True)
            raise

    async def stop(self, delete):
        await super().stop(delete)
        remaining = await host_output('docker', 'ps', '-aq', '--filter',
                                     'label=com.docker.compose.project=' + _sanitize_docker_compose_project_name(self.session_id))
        if remaining:
            raise RuntimeError('native cleanup left scoped containers; retain overlay: ' + remaining)
        if self._gpu_temp:
            self._gpu_temp.cleanup()
            self._gpu_temp = self._gpu_overlay = None
