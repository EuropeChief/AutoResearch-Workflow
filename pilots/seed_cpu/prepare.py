"""Explicit, non-overwriting setup for the authorized Seed-only live pilot."""
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLOW = HERE.parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import Registry, TaskStore, _atomic_json, _sha256
from autoresearch_flow.runtime import Runtime


def main():
    name = sys.argv[1]
    assert name.isalnum(), "Use an alphanumeric run label"
    root = HERE / "runs" / name
    root.mkdir(parents=True, exist_ok=False)
    for name in ("instruction.md", "method.py", "agent_prompt.md", "approval.md", "docker-codex-nested.json"):
        shutil.copyfile(HERE / name, root / name)
    ref = lambda name: {"path": name, "sha256": _sha256(root / name)}
    image = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}",
                                    "autoresearch-flow:seed-pilot-20260927"], text=True).strip()
    config = {
        "schema_version": 1, "image": image, "codex_version": "0.147.0",
        "docker_security": {"apparmor": "unconfined", "seccomp": ref("docker-codex-nested.json"),
                            "approval": ref("approval.md")},
        "public_files": [{"source": ref("instruction.md"), "destination": "instruction.md"}],
        "starter_files": [{"source": ref("method.py"), "destination": "method.py"}],
        "prompt": ref("agent_prompt.md"),
        "evaluation": {"command": ["/opt/conda/bin/python3", "-I", "/opt/pilot/evaluate.py"],
                       "smoke_args": ["--smoke"], "timeout_seconds": 180},
        "boundaries": {"readable": ["/workspace/task/instruction.md"],
                       "readonly": ["/workspace/task/instruction.md", "/opt/pilot/evaluate.py"],
                       "unreadable": ["/opt/pilot/private-marker"]},
        "resources": {"cpus": 2, "memory": "2g", "gpus": {"codex": None, "seed": None}}}
    _atomic_json(root / "runtime.json", config)
    TaskStore(root).initialize(Registry(), "w5-seed-cpu-pilot")
    Runtime(root).prepare(config)
    print(json.dumps({"root": str(root), "image": image, "model_calls_authorized": ["seed"]}))


if __name__ == "__main__":
    main()
