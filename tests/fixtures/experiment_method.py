"""Bounded CPU fixture, not research evidence or a GPU workload."""
import argparse
import json
import os
import subprocess
import sys
import time
from pathlib import Path

p = argparse.ArgumentParser()
p.add_argument("--offset", type=float, default=0)
p.add_argument("--delay", type=float, default=0)
p.add_argument("--fail-once", type=Path)
p.add_argument("--training", action="store_true")
p.add_argument("--nan", action="store_true")
p.add_argument("--wrong-seed", action="store_true")
args = p.parse_args()
seed = int(os.environ["AUTORESEARCH_SEED"])
out = Path(os.environ["AUTORESEARCH_OUTPUT_DIR"])
print(f"synthetic CPU seed={seed} pid={os.getpid()}", flush=True)
time.sleep(args.delay)
if args.fail_once and seed == 2 and not args.fail_once.exists():
    args.fail_once.write_text("failed once")
    print("synthetic expected failure", file=sys.stderr)
    sys.exit(7)
value = float("nan") if args.nan else 10 + seed + args.offset
measurement = {"status": "SUCCESS", "seed": seed + 1 if args.wrong_seed else seed,
               "metrics": {"raw": value}, "quality_gate": {"passed": True},
               "actual_budget": {"steps": 1}, "artifacts": {}}
if args.training:
    model = out / "model"
    model.mkdir()
    (model / "weights.json").write_text(json.dumps({"value": value, "seed": seed}))
    # A genuinely separate process reloads the synthetic JSON artifact; no pickle/import of submitted code.
    result = subprocess.run([sys.executable, "-c",
        "import json,sys,os; print(json.load(open(sys.argv[1]))['value']); print('pid='+str(os.getpid()))",
        str(model / "weights.json")], capture_output=True, text=True, check=True)
    (model / "reload.log").write_text(result.stdout + result.stderr)
    measurement["artifacts"] = {"model": "model/weights.json", "reload_log": "model/reload.log"}
    measurement["training"] = {"origin": "initialization", "model_format": "synthetic-json",
        "reload": {"passed": True, "raw_metric": float(result.stdout.splitlines()[0])}}
Path(os.environ["AUTORESEARCH_RESULT"]).write_text(json.dumps(measurement))
