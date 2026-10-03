"""Bounded real pilot through the public CLI; never substitutes a fake backend."""
import argparse
import json
import signal
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLOW = HERE.parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import _atomic_json, _utc_now
from autoresearch_flow.runtime import Runtime


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("run_label")
    parser.add_argument("action", choices=("probe", "preflight", "run", "resume"))
    args = parser.parse_args()
    assert args.run_label.isalnum()
    root = HERE / "runs" / args.run_label
    runtime = Runtime(root)
    runtime._load()
    report = {"action": args.action, "started_at": _utc_now()}
    evidence_dir = root / "pilot_evidence"
    evidence_dir.mkdir(exist_ok=True)
    target = evidence_dir / (args.action + ".json")
    assert not target.exists(), "Use a new run label, never overwrite pilot evidence"
    if args.action == "probe":
        report["boundary"] = json.loads(runtime.backend.boundary(runtime, "seed"))
        script = '''import errno, socket, pathlib, json
checks={}
try:
 pathlib.Path('/codex/pilot-forbidden').write_text('probe')
except OSError as exc: checks['outside_workspace_write_denied']=exc.errno in (errno.EACCES,errno.EPERM,errno.EROFS)
else: checks['outside_workspace_write_denied']=False
try: s=socket.socket(socket.AF_INET,socket.SOCK_STREAM)
except PermissionError: checks['inet_socket_denied']=True
else: s.close();checks['inet_socket_denied']=False
print(json.dumps(checks));assert all(checks.values())
'''
        inner = ["/bin/sh", "-c", 'exec codex sandbox -P autoresearch -- "$(command -v python3)" "$@"',
                 "probe", "-c", script]
        command = runtime.backend.command(runtime, "seed", "preflight", "ar-pilot-negative", inner)
        process = subprocess.run(command, capture_output=True, text=True, timeout=30)
        report.update(exit_code=process.returncode, stdout=process.stdout, stderr=process.stderr)
    else:
        command = [sys.executable, str(FLOW / "cli.py"), "--format", "json", "runtime", args.action,
                   "--task-root", str(root), "--track", "seed"]
        if args.action == "preflight":
            command += ["--allow-live"]
        else:
            command += ["--budget-seconds", "180", "--confirm-cost"]
        initial = runtime._state("seed")
        before = len(initial["segments"])
        report["thread_before"] = initial["thread_id"]
        log = evidence_dir / (args.action + ".log")
        with log.open("x") as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=stream, start_new_session=True)
            deadline = time.monotonic() + 240
            sent = False
            while process.poll() is None:
                # First finish a genuine turn, then inject interruption in the next
                # turn. No synthetic waiting is counted as annotation evidence.
                state = runtime._state("seed")
                completed = any(s["phase"] == "formal" and s["status"] == "completed"
                                for s in state["segments"][before:])
                active = state["active"]
                if args.action != "preflight" and completed and active and not sent:
                    events = runtime.directory / "seed/logs" / active["segment_id"] / "codex.jsonl"
                    if events.exists() and '"type": "turn.started"' in events.read_text():
                        process.send_signal(signal.SIGINT)
                        report["interrupt_sent_at"] = _utc_now()
                        report["interrupted_segment"] = active["segment_id"]
                        sent = True
                if time.monotonic() >= deadline:
                    process.send_signal(signal.SIGINT)
                    raise TimeoutError("Pilot exceeded bounded budget; inspect/recover its dedicated state")
                time.sleep(0.1)
        report["exit_code"] = process.returncode
        report["state_after"] = runtime.status("seed")
        report["command"] = command
    report["ended_at"] = _utc_now()
    _atomic_json(target, report)
    print(json.dumps(report, ensure_ascii=False, indent=2))
    if report["exit_code"]:
        raise SystemExit(report["exit_code"])


if __name__ == "__main__":
    main()
