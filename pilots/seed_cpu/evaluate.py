"""Trusted CPU-only integration fixture, never a scientific task grader."""
import argparse
import datetime as dt
import hashlib
import json
import subprocess
from pathlib import Path

CASES = [[], [3, 1, 2], [0, -3, 0, 4], [9, 8, 7, 6], [1], [-8, -1, -3]]


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--smoke", action="store_true")
    parser.parse_args()
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    source = Path("/workspace/task/solution/method.py")
    method_hash = hashlib.sha256(source.read_bytes()).hexdigest()
    program = ("import importlib.util,json,sys; "
               "s=importlib.util.spec_from_file_location('candidate',sys.argv[1]); "
               "m=importlib.util.module_from_spec(s);s.loader.exec_module(m); "
               "print(json.dumps([m.order(x) for x in json.loads(sys.stdin.read())]))")
    run = subprocess.run(["/opt/conda/bin/python3", "-I", "-B", "-c", program, str(source)],
                         input=json.dumps(CASES), capture_output=True, text=True, timeout=10)
    if run.returncode:
        raise RuntimeError("candidate failed: " + run.stderr[-2000:])
    values = json.loads(run.stdout)
    assert isinstance(values, list) and len(values) == len(CASES)
    correct = sum(actual == sorted(case) for actual, case in zip(values, CASES))
    error = 1 - correct / len(CASES)
    result = {"status": "succeeded", "score": 1 - error,
              "raw_metric": {"name": "case_error_fraction", "direction": "minimize", "value": error},
              "method_sha256": method_hash, "cases": len(CASES), "correct": correct,
              "started_at": started, "ended_at": dt.datetime.now(dt.timezone.utc).isoformat(),
              "candidate_exit_code": run.returncode,
              "evaluator_sha256": hashlib.sha256(Path(__file__).read_bytes()).hexdigest()}
    output = Path("/workspace/output/evaluations")
    output.mkdir(exist_ok=True)
    target = output / (dt.datetime.now(dt.timezone.utc).strftime("%Y%m%dT%H%M%S%f") + ".json")
    target.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(result, ensure_ascii=False))


if __name__ == "__main__":
    main()
