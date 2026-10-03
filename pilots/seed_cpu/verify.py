"""Read real pilot artifacts and bind metrics, source hashes and same-thread evidence."""
import argparse
import json
import shlex
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
FLOW = HERE.parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.core import FlowError, _atomic_json, _sha256, _utc_now
from autoresearch_flow.runtime import Runtime
from autoresearch_flow.w4_evidence import DeliveryEvidence


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("label")
    parser.add_argument("--write-report", action="store_true", help="首次创建验证快照；默认只读")
    args = parser.parse_args()
    label = args.label
    assert label.isalnum()
    root = HERE / "runs" / label
    runtime = Runtime(root)
    status = runtime.status("seed")  # rechecks every bound log hash
    state = runtime._state("seed")
    formal = [s for s in state["segments"] if s["phase"] == "formal"]
    assert [s["status"] for s in formal] == ["completed", "interrupted", "completed", "interrupted"]
    assert {s["thread_id"] for s in formal} == {state["thread_id"]}
    assert status["active"] is None and state["preflight"]["ready"]
    assert not runtime._state("codex")["segments"], "GPT must not have been invoked"
    assert state["segments"][0]["thread_id"] != state["thread_id"], "Preflight must be independent"
    output = runtime.directory / "seed/formal/output"
    rows = [json.loads(line) for line in (output / "trajectory.jsonl").read_text().splitlines()]
    assert [row["round"] for row in rows] == [1, 2]
    assert all(row["context_marker"] == "seed-pilot-context-20260927" for row in rows)
    assert all(isinstance(row["method_summary"], str) and row["method_summary"] for row in rows)
    evaluations = []
    usage = []
    operations = []
    refs = []
    for segment in state["segments"]:
        log = runtime.directory / "seed/logs" / segment["segment_id"] / "codex.jsonl"
        refs.extend(segment["logs"])
        for line_no, line in enumerate(log.read_text().splitlines(), 1):
            event = json.loads(line)
            if event["type"] == "turn.completed":
                usage.append({"segment_id": segment["segment_id"], "reported_usage": event.get("usage")})
            item = event.get("item", {})
            if event["type"] != "item.completed" or item.get("type") != "command_execution":
                continue
            operations.append({"phase": segment["phase"], "segment_id": segment["segment_id"],
                               "line": line_no, "command": item.get("command"), "exit_code": item.get("exit_code")})
            command = shlex.split(item.get("command", ""))
            if len(command) == 3 and Path(command[0]).name in ("bash", "sh") and command[1] in ("-lc", "-c"):
                command = shlex.split(command[2])
            if command in (["/workspace/task/evaluate"], ["/workspace/task/evaluate", "--smoke"]):
                assert item["exit_code"] == 0
                value = json.loads(item["aggregated_output"].strip().splitlines()[-1])
                assert value["status"] == "succeeded" and value["candidate_exit_code"] == 0
                assert value["evaluator_sha256"] == _sha256(HERE / "evaluate.py")
                evaluations.append({"phase": segment["phase"], "segment_id": segment["segment_id"],
                                    "line": line_no, "result": value})
    assert [v["result"]["correct"] for v in evaluations] == [2, 6, 6]
    results = [json.loads(path.read_text()) for path in sorted((output / "evaluations").glob("*.json"))]
    assert results == [v["result"] for v in evaluations if v["phase"] == "formal"]
    best = output / "best_method/method.py"
    assert _sha256(best) == evaluations[1]["result"]["method_sha256"]
    assert _sha256(runtime.directory / "seed/formal/solution/method.py") == evaluations[2]["result"]["method_sha256"]
    assert evaluations[1]["result"]["method_sha256"] != evaluations[2]["result"]["method_sha256"]
    # This is deliberately not a ten-hour annotation trajectory. The real W4
    # gate must reject it; no monkeypatching clocks or fabricated final rounds.
    try:
        DeliveryEvidence(root).finalize_trajectory("seed")
    except FlowError as error:
        assert error.code == "DURATION_SHORT"
        short_guard = error.code
    else:
        raise AssertionError("A short pilot must not pass the formal trajectory gate")
    evidence = root / "pilot_evidence"
    report = {"status": "pilot_passed_not_annotation_acceptance", "verified_at": _utc_now(),
              "thread_id": state["thread_id"], "runtime_status": status,
              "trajectory_sha256": _sha256(output / "trajectory.jsonl"),
              "best_method_sha256": _sha256(best), "rounds": rows,
              "evaluations": evaluations, "operations": operations, "reported_usage": usage,
              "logs": refs, "formal_duration_gate": short_guard,
              "verifier_runtime_source_sha256": _sha256(FLOW / "autoresearch_flow/runtime.py"),
              "note": "Usage is preserved as returned; resumed-session totals may overlap and are not summed into billed usage."}
    if args.write_report:
        destination = evidence / "verification.json"
        assert not destination.exists(), "Refusing to overwrite existing pilot evidence"
        evidence.mkdir(exist_ok=True)
        _atomic_json(destination, report)
    print(json.dumps({key: report[key] for key in ("status", "thread_id", "best_method_sha256", "formal_duration_gate")}, indent=2))


if __name__ == "__main__":
    main()
