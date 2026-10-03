"""Offline release regression in the explicitly approved CPU pilot environment.

No model/API/GPU calls; only synthetic auth is mounted. This is not a task preflight.
"""
import json
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLOW = HERE.parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import Registry, TaskStore, _atomic_json, _sha256, _utc_now
from autoresearch_flow.runtime import DockerBackend, Runtime


def main():
    image = subprocess.check_output([
        "docker", "image", "inspect", "--format", "{{.Id}}",
        "autoresearch-flow:seed-pilot-20260927"], text=True).strip()
    with tempfile.TemporaryDirectory(prefix="ar-release-probe-") as temporary:
        root = Path(temporary)
        for name in ("instruction.md", "method.py", "agent_prompt.md", "approval.md", "docker-codex-nested.json"):
            shutil.copyfile(HERE / name, root / name)
        ref = lambda name: {"path": name, "sha256": _sha256(root / name)}
        config = {
            "schema_version": 1, "image": image, "codex_version": "0.147.0",
            "docker_security": {"apparmor": "unconfined", "seccomp": ref("docker-codex-nested.json"),
                                "approval": ref("approval.md")},
            "public_files": [{"source": ref("instruction.md"), "destination": "instruction.md"}],
            "starter_files": [{"source": ref("method.py"), "destination": "method.py"}],
            "prompt": ref("agent_prompt.md"),
            "evaluation": {"command": ["/opt/conda/bin/python3", "-I", "/opt/pilot/evaluate.py"],
                           "smoke_args": ["--smoke"], "timeout_seconds": 60},
            "boundaries": {"readable": ["/workspace/task/instruction.md"],
                           "readonly": ["/workspace/task/instruction.md", "/opt/pilot"],
                           "unreadable": ["/opt/pilot/private-marker"]},
            "resources": {"cpus": 2, "memory": "2g", "gpus": {"codex": None, "seed": None}},
            "tracks": {track: {"model": "synthetic-offline", "reasoning_effort": "high",
                               "auth_ref": {"kind": "codex_login", "path": str(root / "never-used.json")}}
                       for track in ("codex", "seed")}}
        TaskStore(root).initialize(Registry(), "release-offline-probe")
        backend = DockerBackend()
        runtime = Runtime(root, backend)
        runtime.prepare(config)
        boundary = json.loads(backend.boundary(runtime, "seed"))
        auth = runtime.directory / "seed/preflight/codex_home/auth.json"
        auth.write_text('{"OPENAI_API_KEY":"synthetic-not-a-real-key"}\n')
        auth.chmod(0o600)
        probe = """from pathlib import Path
try:
    Path('/codex/auth.json').read_bytes()
except PermissionError:
    print('synthetic_login_auth_denied')
else:
    raise AssertionError('agent tools can read login credentials')
"""
        command = ["/bin/sh", "-c",
                   'test -r /codex/auth.json && exec codex sandbox -P autoresearch -- "$(command -v python3)" -c "$1"',
                   "release-auth-probe", probe]
        name = "ar-release-" + uuid.uuid4().hex[:12]
        try:
            result = subprocess.run(backend.command(runtime, "seed", "preflight", name, command),
                                    capture_output=True, text=True, timeout=60)
            assert result.returncode == 0, (result.returncode, result.stderr[-2000:])
            assert "synthetic_login_auth_denied" in result.stdout
        finally:
            backend.stop(name)
        report = {"status": "passed", "at": _utc_now(), "image": image,
                  "runtime_sha256": _sha256(FLOW / "autoresearch_flow/runtime.py"),
                  "probe_sha256": _sha256(Path(__file__)),
                  "boundary": boundary, "login_auth_parent_readable_tools_denied": True,
                  "model_calls": 0, "network": "none", "gpu": None,
                  "scope": "authorized CPU pilot only; not a reusable AppArmor exemption"}
    (FLOW / "release").mkdir(exist_ok=True)
    _atomic_json(FLOW / "release/offline_docker_probe.json", report)
    print(json.dumps({"status": report["status"], "model_calls": 0, "login_auth_denied": True}))


if __name__ == "__main__":
    main()
