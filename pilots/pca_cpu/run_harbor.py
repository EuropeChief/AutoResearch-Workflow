"""Bounded synthetic Harbor 0.23 transfer probe. No model calls or GPU work."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import tomllib

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autoresearch_flow.pca_contract import task_digest


def inspect_trial(job, expected_candidate):
    """Harbor can exit zero on failed trials; verify the actual outcome."""
    results = list(Path(job).glob("*/result.json"))
    if len(results) != 1:
        raise ValueError("Expected exactly one completed trial result")
    result = json.loads(results[0].read_text())
    trial = results[0].parent
    if result.get("exception_info") is not None:
        raise ValueError("Harbor trial reported an exception")
    if result.get("verifier_environment_mode") != "separate":
        raise ValueError("Separate verifier was not used")
    if result.get("verifier_result", {}).get("rewards", {}).get("reward") != 1:
        raise ValueError("Unexpected verifier reward")
    agent_end = datetime.fromisoformat(result['agent_execution']['finished_at'].replace('Z', '+00:00'))
    verifier_start = datetime.fromisoformat(result['verifier']['started_at'].replace('Z', '+00:00'))
    if agent_end > verifier_start:
        raise ValueError("Verifier started before the Agent finished")
    transferred = trial / "artifacts/workspace/solution/method.py"
    expected = hashlib.sha256(Path(expected_candidate).read_bytes()).hexdigest()
    if transferred.is_symlink() or hashlib.sha256(transferred.read_bytes()).hexdigest() != expected:
        raise ValueError("Actual transferred candidate differs from probe")
    record = json.loads((trial / "agent/transfer_probe.json").read_text())
    if record.get("candidate_sha256") != expected or record.get("public_boundary") != "public-boundary-ok":
        raise ValueError("Agent boundary/candidate evidence mismatch")
    if float((trial / "verifier/reward.txt").read_text()) != 1:
        raise ValueError("Reward file disagrees with trial result")
    logs = (trial / "verifier/test-stdout.txt").read_text().splitlines()
    if not any(line.strip().startswith('{') and json.loads(line).get('candidate_uid') == 65534
               for line in logs):
        raise ValueError("Missing restricted candidate execution evidence")
    return {"trial": trial.name, "candidate_sha256": expected, "reward": 1,
            "mode": "separate", "candidate_uid": 65534}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--harbor-bin", type=Path, required=True)
    parser.add_argument("--docker-config", type=Path, required=True)
    parser.add_argument("--component-report", type=Path, required=True)
    parser.add_argument("--allow-docker", action="store_true", required=True)
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    run = root / "runs" / ("harbor-" + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ'))
    run.mkdir(parents=True, exist_ok=False)
    component = json.loads(args.component_report.read_text())
    if component.get("status") != "component_passed_not_harbor":
        raise ValueError("A passed component report is required")
    if component.get('contexts') != {name: task_digest(root/name) for name in ('environment', 'tests')}:
        raise ValueError("Component build evidence does not match current source contexts")
    harbor = str(args.harbor_bin.resolve(strict=True))
    version = subprocess.check_output([harbor, "--version"], text=True).strip()
    if version.split()[-1] != "0.23.0":
        raise ValueError("This compatibility pilot is pinned to Harbor 0.23.0")
    task = run / "task"
    task.mkdir()
    for name in ("environment", "tests"):
        shutil.copytree(root / name, task / name, ignore=shutil.ignore_patterns("__pycache__"))
    shutil.copy2(root / "instruction.md", task / "instruction.md")
    template = (root / "task.toml").read_text()
    parsed = tomllib.loads(template)
    for role, old in (("agent", parsed["environment"]["docker_image"]),
                      ("verifier", parsed["verifier"]["environment"]["docker_image"])):
        actual = subprocess.check_output(["docker", "image", "inspect", "--format", "{{.Id}}",
                                          component["images"][role]], text=True).strip()
        if actual != component["images"][role]:
            raise ValueError("Component image is not pinned to its actual ID")
        template = template.replace(old, actual)
    (task / "task.toml").write_text(template)
    probe = run / "probe"
    probe.mkdir()
    for name in ("probe_agent.py", "probe_candidate.py"):
        shutil.copy2(root / name, probe / name)
    env = dict(os.environ, DOCKER_CONFIG=str(args.docker_config.resolve(strict=True)), PYTHONPATH=str(probe))
    command = [harbor, "run", "-p", str(task), "-a", "probe_agent:TransferProbe", "-n", "1",
               "--jobs-dir", str(run / "jobs"), "--job-name", "transfer", "--max-retries", "0"]
    report = {"status": "failed", "command": command, "harbor_version": version,
              "images": component["images"], "model_calls": 0, "gpu_used": False,
              "stable_12h_tested": False, "scope": "synthetic compatibility test, not official Hidden"}
    try:
        with (run / "console.log").open("x") as stream:
            process = subprocess.Popen(command, env=env, stdout=stream, stderr=subprocess.STDOUT,
                                       start_new_session=True)
            try:
                report["exit_code"] = process.wait(timeout=240)
            except (subprocess.TimeoutExpired, KeyboardInterrupt):
                os.killpg(process.pid, signal.SIGINT)
                try:
                    process.wait(timeout=30)
                except subprocess.TimeoutExpired:
                    os.killpg(process.pid, signal.SIGKILL)
                    process.wait()
                raise RuntimeError("Pilot interrupted; inspect dedicated job/container cleanup before retry")
        if report["exit_code"] != 0:
            raise ValueError("Harbor command failed")
        report["trial"] = inspect_trial(run / "jobs/transfer", probe / "probe_candidate.py")
        report["status"] = "harbor_transfer_probe_passed"
    except Exception as exc:
        report["error"] = str(exc)
        raise
    finally:
        report["evidence"] = [{"path": str(p.relative_to(run)), "sha256": hashlib.sha256(p.read_bytes()).hexdigest()}
                              for p in sorted(run.rglob("*")) if p.is_file() and "__pycache__" not in p.parts]
        (run / "report.json").write_text(json.dumps(report, indent=2))
        print(json.dumps({"report": str(run / "report.json"), "status": report["status"]}))


if __name__ == "__main__":
    main()
