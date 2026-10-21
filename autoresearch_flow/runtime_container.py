"""Independent local adapter over Harbor's native Docker environment lifecycle.

This is not a replacement Harness/Verifier. Final Trial transfer and scoring
remain Harbor's responsibility. A per-track controller owns this one environment.
"""
from __future__ import annotations

import asyncio
import json
import math
import os
from pathlib import Path
import shlex

from .common import FlowError, _atomic_json, _read_json, _require
from .runtime_security import PROFILE, classify_sandbox_result


class NativeContainer:
    def __init__(self, runtime, *, allow_busy=False):
        self.runtime = runtime
        self.directory = runtime.directory
        self.config, _, _ = runtime._load()
        self.environment = None
        self.cid = None
        self.allow_busy = allow_busy
        self.uid = os.getuid()
        _require(self.uid != 0, 'ROOT_AGENT_FORBIDDEN', '本地控制器须由非 root 专家用户运行')
        self.codex = '/opt/autoresearch-codex/bin/codex' if self.config.get('codex_vendor') else 'codex'

    def docker_command(self, *args):
        _require(self.cid, 'CONTAINER_MISSING', '尚未启动本轨容器')
        return ['docker', 'exec', '-u', f'{self.uid}:{os.getgid()}', '-e', 'CODEX_HOME=/codex', *args, self.cid]

    def proxy_command(self):
        return self.docker_command('-i') + [self.codex, 'app-server', 'proxy', '--sock', '/codex/control.sock']

    def tui_command(self, thread):
        return self.docker_command('-it') + [self.codex, '--remote', 'unix:///codex/control.sock',
                                           'resume', thread, '--no-alt-screen']

    def overlay(self):
        d = self.directory
        volumes = [f'{d / "public"}:/workspace:ro', f'{d / "solution"}:/workspace/solution:rw',
                   f'{d / "output"}:/expert_evidence:rw', f'{d / "codex_home"}:/codex:rw',
                   f'{d / "jobs/requests"}:/run/autoresearch/requests:rw',
                   f'{d / "jobs/responses"}:/run/autoresearch/responses:ro']
        if self.config.get('codex_vendor'):
            volumes.append(f'{d / "codex_runtime"}:/opt/autoresearch-codex:ro')
        # JSON is valid YAML scalar/list syntax; no new YAML dependency.
        lines = ['services:', '  main:', '    read_only: true', '    cap_drop: [ALL]',
                 '    security_opt:', '      - no-new-privileges:true']
        if self.config['security']['mode'] == 'codex_nested':
            lines += ['      - apparmor:unconfined', '      - ' + json.dumps('seccomp:' + str(PROFILE))]
        lines += ['    tmpfs:', '      - /tmp:rw,nosuid,size=256m,mode=1777', '    volumes:']
        lines += ['      - ' + json.dumps(value, ensure_ascii=False) for value in volumes]
        lines += ['    cpus: ' + str(self.config['resources']['cpus'])]
        return '\n'.join(lines) + '\n'

    def create(self):
        from harbor.environments.factory import EnvironmentFactory
        from harbor.models.task.config import EnvironmentConfig, NetworkMode
        from harbor.models.trial.config import EnvironmentConfig as TrialEnvironment
        from harbor.models.trial.paths import TrialPaths
        d = self.directory
        for name in ['requests', 'responses', 'worker', 'records']:
            (d / 'jobs' / name).mkdir(exist_ok=True)
        (d / 'jobs/responses').chmod(0o755)
        (d / 'jobs/worker').chmod(0o755)
        (d / 'environment').mkdir(exist_ok=True)
        (d / 'trial').mkdir(exist_ok=True)
        overlay = d / 'container.yaml'
        overlay.write_text(self.overlay(), encoding='utf-8')
        resource = self.config['resources']
        memory = int(resource['memory'][:-1]) * (1024 if resource['memory'][-1].lower() == 'g' else 1)
        task = EnvironmentConfig(docker_image=self.config['image'], gpus=len(resource['gpu_ids']),
                                 cpus=math.ceil(resource['cpus']), memory_mb=memory, network_mode=NetworkMode.PUBLIC)
        self.environment = EnvironmentFactory.create_environment_from_config(
            config=TrialEnvironment(import_path='autoresearch_flow.harbor_gpu:GpuDockerEnvironment',
                extra_docker_compose=[overlay], kwargs={'gpu_ids':resource['gpu_ids'], 'allow_busy':self.allow_busy}),
            environment_dir=d / 'environment', environment_name='autoresearch-independent-track',
            session_id='ar-track-' + self.config['instance_id'][:20], trial_paths=TrialPaths(trial_dir=d / 'trial'),
            task_env_config=task)
    async def start(self):
        d = self.directory
        self.create()
        await self.environment.start(force_build=False)
        result = await self.environment._run_docker_compose_command(['ps','-q','main'], timeout_sec=20)
        self.cid = result.stdout.strip()
        _require(self.cid and '\n' not in self.cid, 'CONTAINER_MISSING', '不能确定唯一容器')
        _atomic_json(d / 'container.json', {'container_id':self.cid, 'uid':self.uid, 'codex':self.codex})
        version = await self.exec_agent(shlex.join([self.codex, '--version']))
        _require(version.return_code == 0 and ('codex-cli ' + self.config['codex_version']) in version.stdout,
                 'CODEX_VERSION', '实际 Codex 版本与本轨显式支持版本不符')

    async def adopt(self):
        """Attach only to the exact original container; no rebuild/admission/rerun."""
        self.create()
        saved = _read_json(self.directory / 'container.json')
        result = await self.environment._run_docker_compose_command(['ps','-q','main'], timeout_sec=20)
        self.cid = result.stdout.strip()
        _require(self.cid and self.cid == saved['container_id'], 'CONTAINER_MISMATCH',
                 '原容器未运行或身份改变；先定位外部故障，不能接管其他容器')

    async def exec_agent(self, command, timeout=30):
        return await self.environment.exec('env CODEX_HOME=/codex ' + command,
                                            user=f'{self.uid}:{os.getgid()}', timeout_sec=timeout)

    async def preflight(self):
        code = ("from pathlib import Path;import os,json; p=Path('/workspace/solution/.runtime-probe');"
                "p.write_text('probe');p.unlink();r={'uid':os.getuid(),'docker_socket_absent':not Path('/var/run/docker.sock').exists()};\n"
                "for name,path in [('auth','/codex/auth.json'),('runtime','/runtime/assets/run_worker.py')]:\n"
                " try: Path(path).read_text();r[name+'_denied']=False\n except OSError:r[name+'_denied']=True\n"
                "print(json.dumps(r));assert r['uid']!=0 and all(v for k,v in r.items() if k!='uid')")
        command = shlex.join([self.codex,'sandbox','-C','/workspace/solution','-P','autoresearch','--','python','-c',code])
        result = await self.exec_agent(command)
        report = classify_sandbox_result(result.return_code, result.stdout or '', result.stderr or '')
        report.update(stdout=result.stdout, stderr=result.stderr, image=self.config['image'],
                      codex_version=self.config['codex_version'], security=self.config['security']['mode'])
        _atomic_json(self.directory / 'preflight.json', report)
        _require(report['status'] == 'succeeded', 'SANDBOX_BLOCKED', '实际沙箱探针被阻止，详见本轨 preflight.json；不自动降级')
        if self.config['resources']['gpu_ids']:
            gpu_command = shlex.join([self.codex, 'sandbox', '-C', '/workspace/solution', '-P',
                                     'autoresearch', '--', 'python', '/workspace/_gpu_probe.py',
                                     str(len(self.config['resources']['gpu_ids']))])
            result = await self.exec_agent(gpu_command, timeout=60)
            gpu = {'status': 'succeeded' if result.return_code == 0 else 'blocked',
                   'exit_code': result.return_code, 'stdout': result.stdout, 'stderr': result.stderr,
                   'scope': 'actual CUDA kernel inside current Agent sandbox'}
            report['gpu'] = gpu
            if gpu['status'] != 'succeeded':
                report['status'] = 'blocked'
            _atomic_json(self.directory / 'preflight.json', report)
            _require(gpu['status'] == 'succeeded', 'GPU_SANDBOX_BLOCKED',
                     '当前 Agent sandbox 内 CUDA 核计算未通过；详见preflight.json，不回退额外worker')
        return report

    def credential_material(self):
        auth = self.config['model']['auth_ref']
        source = Path(auth['path'])
        _require(source.is_file() and not source.is_symlink(), 'AUTH_MISSING', '缺少本轨显式鉴权文件')
        value = _read_json(source)
        if auth['kind'] == 'api_key_json':
            key = value.get(auth['key'])
            _require(isinstance(key, str) and key.strip(), 'AUTH_MISSING', '本轨指定 JSON key 不存在')
            material = {'auth_mode':'apikey', 'OPENAI_API_KEY':key}
            secrets = [key]
        else:
            material = value
            secrets = [x for x in value.values() if isinstance(x,str)]
            secrets += [x for x in value.get('tokens',{}).values() if isinstance(x,str)]
        path = self.directory / 'codex_home/auth.json'
        _atomic_json(path, material)
        path.chmod(0o600)
        return secrets

    async def backend(self):
        # No key in Docker argv/environment/proc. The provider reads protected auth.json.
        command = 'umask 077; echo $$ > /codex/backend.pid; exec ' + shlex.join([
            self.codex,'app-server','--listen','unix:///codex/control.sock']) + ' >> /codex/backend.log 2>&1'
        proc = await asyncio.create_subprocess_exec(*self.docker_command('-d'), 'sh','-c',command,
                                                   stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        out, err = await proc.communicate()
        _require(proc.returncode == 0, 'BACKEND_START', err.decode(errors='replace'))
        for _ in range(100):
            # Codex may symlink to /tmp inside the container's private namespace.
            # Host Path.exists() on that absolute symlink is not readiness proof.
            ready = await self.exec_agent('test -S /codex/control.sock',timeout=5)
            if ready.return_code == 0:
                return
            await asyncio.sleep(0.1)
        raise FlowError('BACKEND_START','原生后端 socket 未就绪；保留本轨日志')

    async def backend_alive(self):
        code=("from pathlib import Path;import os,json; p=Path('/codex/backend.pid'); alive=False;\n"
              "try:\n pid=int(p.read_text());q=Path('/proc')/str(pid);"
              "parts=(q/'cmdline').read_bytes().split(bytes([0]));"
              "alive=q.stat().st_uid==os.getuid() and b'app-server' in parts and b'proxy' not in parts\n"
              "except (OSError,ValueError):pass\nprint(json.dumps({'alive':alive}))")
        result=await self.exec_agent(shlex.join(['python','-c',code]),timeout=5)
        _require(result.return_code==0,'BACKEND_UNKNOWN','原后端存活状态无法确认；不能猜测或杀进程')
        return json.loads(result.stdout.strip())['alive']

    async def run_job(self, job, work):
        candidate, output = '/worker_jobs/' + job + '/solution', '/worker_jobs/' + job + '/output'
        command = [arg.replace('{candidate}',candidate).replace('{output}',output) for arg in self.config['evaluation']['command']]
        request = work / 'run.json'
        timeout=self.config['evaluation'].get('timeout_seconds')
        _atomic_json(request, {'command':command,'candidate':candidate,'output':output,
                              'timeout_seconds':timeout,
                              'cuda_visible_devices':','.join(str(i) for i in range(len(self.config['resources']['gpu_ids'])))})
        request.chmod(0o444)
        # Fixed wrapper starts the fixed public command; model cannot select either.
        result = await self.environment.exec(shlex.join(['env','-i','PATH=/opt/conda/bin:/usr/local/bin:/usr/bin:/bin',
            'python','/runtime/assets/run_worker.py','/worker_jobs/' + job + '/run.json']),
            user='65533:65533', timeout_sec=timeout+10 if timeout else None)
        return {'exit_code':result.return_code,'stdout':result.stdout or '', 'stderr':result.stderr or ''}

    async def stop(self):
        if self.environment:
            await self.environment.stop(delete=True)
