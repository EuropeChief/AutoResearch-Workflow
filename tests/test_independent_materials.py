"""Bounded synthetic package tests; no QA, Docker, model calls or real task changes."""
import copy
import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

FLOW = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(FLOW))
from autoresearch_flow.common import _atomic_json, _sha256, _canonical_digest, FlowError
from autoresearch_flow.materials_check import check, HEADINGS
from autoresearch_flow.materials_trajectory import prepare, check_rounds
from autoresearch_flow.materials_assemble import assemble
from autoresearch_flow.experiment_run import run
from autoresearch_flow.experiment_data import summarize, write_summary


def fixture(root, training=False):
    def text(name, value):
        p=root/name; p.parent.mkdir(parents=True, exist_ok=True); p.write_text(value)
        return p
    def obj(name, value):
        p=root/name; p.parent.mkdir(parents=True, exist_ok=True); _atomic_json(p, value)
        return p
    p = {"data":"synthetic-v1", "split":"dev", "training":training, "evaluation_mode":"random",
         "seeds":[1,2,3], "metric":{"name":"error","direction":"minimize","unit":"pp"},
         "budget":{"steps":{"mode":"exact","value":1,"unit":"step"}}}
    instruction="# 合成任务\n"+"\n".join("## "+h+"\n实际规则：seed 1/2/3，改善至少 3σ_B。仅修改方法；允许公开 Dev。\n" for h in HEADINGS)
    text("workspace/harbor_task/instruction.md",instruction)
    text("workspace/harbor_task/environment/Dockerfile", "FROM ubuntu:24.04\nWORKDIR /workspace\nCOPY starter/ /workspace/solution/\n")
    text("workspace/harbor_task/environment/starter/main.py","# SYNTHETIC starter\n")
    text("workspace/harbor_task/tests/Dockerfile","FROM ubuntu:24.04\nWORKDIR /tests\nCOPY test.sh /tests/test.sh\n")
    text("workspace/harbor_task/tests/test.sh","#!/bin/sh\n# SYNTHETIC only\nexit 0\n")
    task=text("workspace/harbor_task/task.toml",'artifacts=["/workspace/solution"]\n[environment]\ncpus=1\n[agent]\n[verifier]\nenvironment_mode="separate"\n[verifier.environment]\ncpus=1\n')
    text("workspace/reference/main.py","# SYNTHETIC reference\n")
    text("expert_evidence/专家作业说明文档.md","合成夹具，不是科研或实际时长证明。\n")
    text("optimization_evidence/训练证据说明.md","合成逐次证据；仅供工具测试。\n")
    text("expert_evidence/best_method/main.py","# SYNTHETIC best\n")
    obj("expert_evidence/expert_annotation.json",{
        "task_id":"synthetic","task_type":"S1","research_direction":"合成方向","optimization_surface":"合成方法",
        "score_contract":{"metric":"error","direction":"minimize","split":"dev","protocol":"v1",
            "baseline":{"raw_value":12,"normalized_score":0},
            "reference":{"raw_value":8,"normalized_score":2/3},
            "upper_bound":{"raw_value":6,"source":"estimated_attainable_upper_bound"}},
        "isolation":{"reference_visible_to_agent":False,"hidden_assets_visible_to_agent":False}})
    obj("expert_evidence/run_summary.json",{"task_id":"synthetic","status":"local_complete","image":"synthetic-agent",
        "agent_execution":[{"runtime":"Codex","model":model,"duration_hours":10,
            "effective_rounds":3,"typical_round_minutes":30} for model in ("GPT-5.6 Sol","Seed 2.1 Turbo")],
        "fast_iteration_exception":{"used":False,"non_training":None,"short_iterations":None,"rollable_proved":False,"evidence":""},
        "validation":dict.fromkeys(("baseline_passed","reference_passed","optimization_evidence_complete","best_method_rerun_passed"),True)})
    rows=[{"round":i,"policy_name":f"method-{i}","method_summary":"合成方法记录。","status":"ok","score":v,
           "failure_reason":None,"retained_best":True,"time":f"2026-10-09 0{i}:00:00"}
          for i,v in enumerate((10,8,7),1)]
    for track in ("codex","seed"):
        obj(f"expert_evidence/trajectory_{track}.json",{"rounds":rows})
        text(f"expert_evidence/{track}.log","SYNTHETIC operation log; not authentic hours\n")
    obj("expert_evidence/timing.json",{"tracks":{t:{"thread_id":t,"intervals":[[0,36000],[35000,37000]],
        "exclusions":[{"start":0,"end":1000,"reason":"synthetic outage"}],"effective_seconds":36000,
        "logs":[{"path":f"expert_evidence/{t}.log","sha256":_sha256(root/f"expert_evidence/{t}.log")}]} for t in ("codex","seed")}})
    results=[]
    for role, shift, source in (("baseline",0,"workspace/harbor_task/environment/starter"),
                                ("reference",-4,"workspace/reference"),
                                ("best_method",-5,"expert_evidence/best_method")):
        source_files={"main.py":_sha256(root/source/"main.py")}
        method={"path":source,"files":source_files,"sha256":_canonical_digest(source_files)}
        for seed in p["seeds"]:
            base=f"optimization_evidence/{role}_runs/seed_{seed}" if role!="best_method" else f"expert_evidence/best_retest/seed_{seed}"
            text(base+"/run.log",f"SYNTHETIC seed {seed} command output warning\n")
            raw=10+seed+shift
            record={"schema_version":1,"status":"COMPLETE","role":role,"seed":seed,
                "task_type":"training" if training else "non_training", "method":method,"protocol":p,
                "training":{"origin":"initialization"} if training else {"status":"NOT_APPLICABLE"},
                "execution":{"command":["synthetic"],"started_at":"2026-10-09T00:00:00Z","finished_at":"2026-10-09T00:00:01Z","exit_code":0,"duration_seconds":1},
                "metrics":{"name":"error","direction":"minimize","unit":"pp","raw":raw},
                "quality_gate":{"passed":True},"artifacts":{}}
            if training:
                model=text(base+"/model/weights.pt",f"SYNTHETIC bytes role={role} seed={seed}\n")
                text(base+"/model/reload.log","SYNTHETIC reload: tested by static tool only\n")
                obj(base+"/model/artifact.json",{"format":"synthetic","role":role,"seed":seed,"sha256":_sha256(model),
                    "size_bytes":model.stat().st_size,"method_sha256":method["sha256"],"reload_passed":True,"reload_metric":raw})
                record["artifacts"]={"model":{"path":base+"/model/weights.pt","sha256":_sha256(model)}}
            obj(base+"/result.json",record)
            if role!="best_method":
                results.append({"path":base+"/result.json","sha256":_sha256(root/base/"result.json"),"role":role,"seed":seed})
    obj("optimization_evidence/comparison_summary.json",{"status":"COMPLETE","metric":p["metric"],"split":"dev","protocol":p,"seeds":p["seeds"],
        "statistics":{"paired_run_count":3,"baseline_mean":12,"reference_mean":8,"baseline_sample_std":1,"reference_sample_std":1,"mean_paired_improvement":4,"relative_improvement":1/3,"baseline_sigma_multiple":4},
        "paired_results":{str(s):{"baseline":10+s,"reference":6+s,"paired_improvement":4} for s in p["seeds"]},
        "significance_rule":{"required_baseline_sigma_multiple":3,"passed":True},"source_results":results})
    trial="expert_evidence/nop_trial"
    obj(trial+"/config.json",{"task":{"name":"harbor_task","task_toml_sha256":_sha256(task)},"agent":{"name":"nop"}})
    obj(trial+"/result.json",{"task_name":"harbor_task","agent_info":{"name":"nop"},"verifier_environment_mode":"separate",
        "finished_at":"2026-10-09T00:01:00Z","exception_info":None,"verifier_result":{"rewards":{"reward":0}}})
    text(trial+"/verifier/reward.txt","0\n")
    text(trial+"/trial.log","SYNTHETIC NOP raw stdout\n")
    return p,rows


class IndependentMaterialTests(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix="ar-materials-")
        self.addCleanup(self.temp.cleanup)
        self.root=Path(self.temp.name)/"package";self.root.mkdir()
        self.protocol,self.rows=fixture(self.root)

    def codes(self, report):
        return {x["code"] for x in report["issues"]}

    def edit(self, name, mutate):
        p=self.root/name
        d=json.loads(p.read_text());mutate(d);_atomic_json(p,d)

    def test_valid_package_is_readonly_and_not_qa(self):
        before={p:_sha256(p) for p in self.root.rglob("*") if p.is_file()}
        report=check(self.root)
        self.assertEqual(report["status"],"format_checked_not_qa",report["issues"])
        self.assertEqual(report["computed_statistics"]["baseline_mean"],12)
        self.assertTrue(report["pending"])
        self.assertEqual(before,{p:_sha256(p) for p in self.root.rglob("*") if p.is_file()})
        self.assertFalse((self.root/".autoresearch-flow").exists())

    def test_native_jsonl_conversion_preserves_source_and_history_best(self):
        source=self.root.parent/"agent.jsonl";source.write_text("\n".join(json.dumps(x) for x in self.rows)+"\n")
        before=source.read_bytes()
        out=self.root.parent/"final.json"
        r=prepare(source,out,metric={"direction":"minimize"})
        self.assertEqual(r["status"],"prepared")
        self.assertEqual(json.loads(out.read_text()),{"rounds":self.rows})
        self.assertEqual(source.read_bytes(),before)
        with self.assertRaises(FlowError):prepare(source,source)
        with self.assertRaises(FlowError):prepare(source,out)

    def test_trajectory_mutations_are_precisely_located(self):
        changes=[("round",True,"TRAJECTORY_ORDER"),("score",float("nan"),"TRAJECTORY_SCORE"),
                 ("retained_best","true","TRAJECTORY_FIELD"),("time","2026-02-30 12:00:00","TRAJECTORY_TIME"),
                 ("failure_reason","failed","TRAJECTORY_STATUS"),("method_summary","","TRAJECTORY_FIELD")]
        for key,value,code in changes:
            rows=copy.deepcopy(self.rows);rows[1][key]=value
            issues=check_rounds({"rounds":rows},"trajectory.json")
            self.assertIn(code,{x["code"] for x in issues},key)
            self.assertTrue(any("rounds[1]" in x["path"] for x in issues))
        self.assertIn("TRAJECTORY_ROUNDS",self.codes({"issues":check_rounds({"events":self.rows})}))
        rows=copy.deepcopy(self.rows);del rows[0]["policy_name"]
        self.assertIn("TRAJECTORY_FIELD",self.codes({"issues":check_rounds({"rounds":rows})}))

    def test_failed_unknown_and_normalized_score_are_not_invented(self):
        rows=copy.deepcopy(self.rows);rows[1].update(status="failed",score=None,failure_reason="OOM",retained_best=False)
        self.assertFalse(check_rounds({"rounds":rows}))
        rows[1]["retained_best"]=True
        self.assertIn("TRAJECTORY_BEST",self.codes({"issues":check_rounds({"rounds":rows})}))
        rows[1].update(status="custom_pause",failure_reason="external",retained_best=False)
        self.assertIn("TRAJECTORY_STATUS_REVIEW",self.codes({"issues":check_rounds({"rounds":rows})}))
        observations={str(r["round"]):{"raw_value":r["score"],"direction":"minimize","split":"dev"} for r in self.rows}
        wrong=copy.deepcopy(self.rows);wrong[1]["score"]=0.5
        self.assertIn("TRAJECTORY_RAW_SCORE",self.codes({"issues":check_rounds({"rounds":wrong},metric={"direction":"minimize","split":"dev"},observations=observations)}))

    def test_seed_role_field_protocol_and_statistic_errors(self):
        name="optimization_evidence/baseline_runs/seed_1/result.json"
        self.edit(name,lambda d:d.update(seed=2,role="reference"))
        codes=self.codes(check(self.root));self.assertIn("RESULT_SEED",codes);self.assertIn("RESULT_ROLE",codes)
        fixture(self.root)
        self.edit(name,lambda d:d["protocol"].update(split="hidden"))
        self.assertIn("RESULT_PROTOCOL",self.codes(check(self.root)))
        fixture(self.root)
        self.edit("optimization_evidence/comparison_summary.json",lambda d:d["statistics"].update(baseline_mean=99))
        self.assertIn("COMPARISON_STATISTICS",self.codes(check(self.root)))
        fixture(self.root)
        self.edit(name,lambda d:d.pop("execution"))
        self.assertIn("RESULT_FIELD",self.codes(check(self.root)))

    def test_missing_paths_hashes_and_symlink_boundary(self):
        outside=self.root.parent/"outside.log";outside.write_text("not package evidence")
        self.edit("optimization_evidence/baseline_runs/seed_1/result.json",
                  lambda d:d["artifacts"].update(log={"path":"../outside.log","sha256":_sha256(outside)}))
        self.assertIn("PACKAGE_ESCAPE",self.codes(check(self.root)))
        fixture(self.root)
        (self.root/"expert_evidence/link").symlink_to(outside)
        with patch("autoresearch_flow.materials_check.bundled",side_effect=AssertionError("must stop before outside parser")):
            self.assertIn("UNSAFE_FILE",self.codes(check(self.root)))

    def test_training_model_binding_missing_reload_and_nontraining(self):
        fixture(self.root,training=True)
        r=check(self.root);self.assertEqual(r["status"],"format_checked_not_qa",r["issues"])
        (self.root/"optimization_evidence/baseline_runs/seed_2/model/reload.log").unlink()
        self.assertIn("MISSING_EVIDENCE",self.codes(check(self.root)))
        (self.root/"optimization_evidence/reference_runs/seed_1/model/weights.pt").write_text("corrupt")
        self.assertIn("EVIDENCE_HASH",self.codes(check(self.root)))

    def test_duration_union_exclusions_and_session_independence(self):
        self.edit("expert_evidence/timing.json",lambda d:d["tracks"]["seed"].update(thread_id="codex"))
        self.assertIn("DURATION_SESSION",self.codes(check(self.root)))
        fixture(self.root)
        self.edit("expert_evidence/run_summary.json",lambda d:d["agent_execution"][0].update(duration_hours=10.5))
        self.assertIn("DURATION_TOTAL",self.codes(check(self.root)))
        fixture(self.root)
        (self.root/"expert_evidence/timing.json").unlink()
        r=check(self.root)
        self.assertTrue(any("未识别" in x for x in r["pending"]))
        self.assertNotEqual(r["status"],"qa_passed")

    def test_nop_originals_and_wrong_trial_reward(self):
        (self.root/"expert_evidence/nop_trial/verifier/reward.txt").write_text("1\n")
        self.assertIn("FIELD_ERROR",self.codes(check(self.root)))
        fixture(self.root)
        (self.root/"expert_evidence/nop_trial/config.json").unlink()
        self.assertIn("FIELD_ERROR",self.codes(check(self.root)))

    def test_best_retest_source_or_seed_drift(self):
        (self.root/"expert_evidence/best_method/main.py").write_text("# different method\n")
        self.assertIn("BEST_BINDING",self.codes(check(self.root)))
        fixture(self.root)
        (self.root/"expert_evidence/best_retest/seed_3/result.json").unlink()
        self.assertIn("BEST_SEED",self.codes(check(self.root)))

    def test_instruction_threshold_task_identity_and_private_context(self):
        path=self.root/"workspace/harbor_task/instruction.md";path.write_text(path.read_text().replace("3σ_B","足够好"))
        self.assertIn("INSTRUCTION_THRESHOLD",self.codes(check(self.root)))
        self.edit("expert_evidence/run_summary.json",lambda d:d.update(task_id="old-task"))
        self.assertIn("TASK_ID",self.codes(check(self.root)))
        path=self.root/"workspace/harbor_task/environment/reference/private.py";path.parent.mkdir();path.write_text("secret method")
        self.assertIn("PRIVATE_IN_AGENT_CONTEXT",self.codes(check(self.root)))

    def test_assemble_explicit_sources_preserves_nop_and_excludes_work(self):
        # Split actual materials instead of assuming any fixed author workspace.
        mapping={str(p.relative_to(self.root)):str(p) for p in [self.root/"workspace",self.root/"optimization_evidence"]}
        mapping.update({str(p.relative_to(self.root)):str(p) for p in (self.root/"expert_evidence").iterdir() if p.name!="best_method"})
        work=self.root/"workspace/.git";work.mkdir();(work/"config").write_text("local metadata")
        raw=(self.root/"expert_evidence/nop_trial/config.json").read_bytes()
        out=self.root.parent/"assembled"
        r=assemble(mapping,self.root/"expert_evidence/best_method",out)
        self.assertEqual(r["status"],"assembled")
        self.assertEqual(r["format_check"]["status"],"format_checked_not_qa",r["format_check"]["issues"])
        self.assertEqual((out/"expert_evidence/nop_trial/config.json").read_bytes(),raw)
        self.assertFalse((out/"workspace/.git").exists())
        self.assertTrue(work.is_dir())
        with self.assertRaises(FlowError):assemble(mapping,self.root/"expert_evidence/best_method",out)
        secret=self.root/"workspace/auth.json";secret.write_text('{"api_key":"synthetic-secret"}')
        with self.assertRaisesRegex(FlowError,"凭据"):assemble(mapping,self.root/"expert_evidence/best_method",self.root.parent/"secret-output")

    def test_cli_has_no_state_runtime_imports(self):
        code="import runpy,sys;sys.argv=['cli.py','--format','json','materials','check','--package-root',sys.argv[1]]\ntry: runpy.run_path('cli.py',run_name='__main__')\nexcept SystemExit as e:\n assert e.code==0\nassert 'autoresearch_flow.runtime' not in sys.modules\nassert 'autoresearch_flow.core' not in sys.modules\n"
        p=subprocess.run([sys.executable,"-c",code,str(self.root)],cwd=FLOW,text=True,capture_output=True)
        self.assertEqual(p.returncode,0,p.stdout+p.stderr)

    def test_lp2_runs_export_without_ledger_or_retry_tree(self):
        method=self.root.parent/"run-source";method.mkdir()
        shutil.copyfile(FLOW/"tests/fixtures/experiment_method.py",method/"main.py")
        groups={}
        for role,shift in (("baseline",0),("reference",-4),("best_method",-5)):
            group=self.root.parent/role
            run(method,self.protocol,group,[sys.executable,"{method}/main.py","--offset",str(shift)],role=role,jobs=2)
            groups[role]=group
        stat=self.root.parent/"comparison"
        write_summary(summarize([groups["baseline"],groups["reference"]]),stat)
        mapping={"workspace":str(self.root/"workspace"),
                 "optimization_evidence/训练证据说明.md":str(self.root/"optimization_evidence/训练证据说明.md"),
                 "optimization_evidence/baseline_runs":str(groups["baseline"]),
                 "optimization_evidence/reference_runs":str(groups["reference"]),
                 "optimization_evidence/comparison_summary.json":str(stat/"comparison_summary.json"),
                 "expert_evidence/best_retest":str(groups["best_method"])}
        mapping.update({str(p.relative_to(self.root)):str(p) for p in (self.root/"expert_evidence").iterdir() if p.name not in {"best_method","best_retest"}})
        out=self.root.parent/"exported"
        assembled=assemble(mapping,method,out)
        self.assertEqual(assembled["format_check"]["status"],"format_checked_not_qa",assembled["format_check"]["issues"])
        self.assertFalse(list(out.rglob("experiment.json")))
        self.assertFalse(list(out.rglob(".run.lock")))
        self.assertFalse(list(out.rglob("attempt_001")))
        path=out/"optimization_evidence/baseline_runs/seed_1/result.json"
        d=json.loads(path.read_text())
        self.assertEqual(d["artifacts"]["log"]["path"],"optimization_evidence/baseline_runs/seed_1/run.log")
        summary=json.loads((out/"optimization_evidence/comparison_summary.json").read_text())
        self.assertEqual(summary["source_results"][0]["sha256"],_sha256(path))

    def test_assemble_never_repairs_tampered_source_hash(self):
        self.edit("optimization_evidence/comparison_summary.json",lambda d:d["source_results"][0].update(sha256="0"*64))
        mapping={"workspace":str(self.root/"workspace"),"optimization_evidence":str(self.root/"optimization_evidence")}
        mapping.update({str(p.relative_to(self.root)):str(p) for p in (self.root/"expert_evidence").iterdir() if p.name!="best_method"})
        with self.assertRaisesRegex(FlowError,"来源证据哈希"):
            assemble(mapping,self.root/"expert_evidence/best_method",self.root.parent/"bad-hash")

    def test_scalar_and_nested_malformed_types_return_issues(self):
        self.edit("expert_evidence/expert_annotation.json",lambda d:d.update(task_type={"bad":"shape"},score_contract=[]))
        self.assertEqual(check(self.root)["status"],"issues_found")
        fixture(self.root)
        self.edit("expert_evidence/run_summary.json",lambda d:d.update(agent_execution=None))
        self.assertEqual(check(self.root)["status"],"issues_found")
        fixture(self.root)
        self.edit("optimization_evidence/baseline_runs/seed_1/result.json",lambda d:d["metrics"].update(unit="%"))
        self.assertIn("METRIC_CONFLICT",self.codes(check(self.root)))

    def test_standard_three_roots_assemble_with_explicit_best_override(self):
        mapping={x:str(self.root/x) for x in ("workspace","expert_evidence","optimization_evidence")}
        config=self.root/"workspace/harbor_task/environment/starter/artifact.json"
        config.write_text(json.dumps({"path":str(self.root/"workspace/reference/main.py")}))
        original_config=config.read_bytes()
        out=self.root.parent/"three-roots"
        original={str(p.relative_to(self.root)):_sha256(p) for p in (self.root/"expert_evidence/nop_trial").rglob("*") if p.is_file()}
        result=assemble(mapping,self.root/"expert_evidence/best_method",out)
        self.assertEqual(result["format_check"]["status"],"format_checked_not_qa",result["format_check"]["issues"])
        self.assertEqual(original,{str(p.relative_to(out)):_sha256(p) for p in (out/"expert_evidence/nop_trial").rglob("*") if p.is_file()})
        self.assertEqual((out/config.relative_to(self.root)).read_bytes(),original_config)

    def test_seven_hour_exception_preserves_training_and_duration_boundary(self):
        def set_summary(d):
            for x in d["agent_execution"]:
                x["duration_hours"]=7
            d["fast_iteration_exception"].update(used=True,non_training=True,short_iterations=True,
                                                rollable_proved=True,evidence="SYNTHETIC qualification; not actual approval")
        def set_timing(d):
            for x in d["tracks"].values():
                x.update(intervals=[[0,26200]],effective_seconds=25200)
        self.edit("expert_evidence/run_summary.json",set_summary)
        self.edit("expert_evidence/timing.json",set_timing)
        report=check(self.root)
        self.assertEqual(report["status"],"format_checked_not_qa",report["issues"])
        self.assertTrue(any("7h启动前资格" in x for x in report["pending"]))
        fixture(self.root,training=True)
        self.edit("expert_evidence/run_summary.json",set_summary)
        self.edit("expert_evidence/timing.json",set_timing)
        self.assertIn("DURATION_POLICY",self.codes(check(self.root)))


if __name__=="__main__":
    unittest.main()
