"""No-model native Agent: install an explicitly selected frozen candidate only.

Harbor creates the Agent image, transfers artifacts, creates the separate
Verifier and retrieves rewards. This adapter cannot choose or train a method.
"""
import json
from pathlib import Path
import shlex

from harbor.agents.nop import NopAgent
from harbor.agents.options import AgentOptions

from . import FLOW_VERSION
from .common import _atomic_json, _require
from .harbor_native import inventory


class CandidateOptions(AgentOptions):
    candidate_path: str


class CandidateAgent(NopAgent):
    options_model = CandidateOptions

    @staticmethod
    def name():
        return "autoresearch-candidate"

    def version(self):
        return FLOW_VERSION

    async def run(self, instruction, environment, context):
        candidate = Path(self.options.candidate_path)
        expected = inventory(candidate)
        # This fixed deletion is confined to Harbor's disposable Agent container;
        # it never acts on the host candidate or the expert's research Git.
        reset = "import shutil,os; p='/workspace/solution'; shutil.rmtree(p); os.makedirs(p)"
        result = await environment.exec("python -c " + shlex.quote(reset), user="root", timeout_sec=30)
        _require(result.return_code == 0, "HARBOR_CANDIDATE", "不能重置 Agent 容器的 solution")
        await environment.upload_dir(candidate, "/workspace/solution")
        verify = (
            "import hashlib,json,os,stat; from pathlib import Path; root=Path('/workspace/solution'); result={}; "
            "\nfor base,dirs,names in os.walk(root,followlinks=False):\n"
            " for name in dirs+names:\n"
            "  p=Path(base)/name; m=p.lstat().st_mode; assert stat.S_ISREG(m) or stat.S_ISDIR(m)\n"
            "  if stat.S_ISREG(m):\n"
            "   h=hashlib.sha256()\n"
            "   with p.open('rb') as f:\n"
            "    for block in iter(lambda:f.read(1048576),b''): h.update(block)\n"
            "   result[p.relative_to(root).as_posix()]={'sha256':h.hexdigest(),'size':p.stat().st_size,'mode':stat.S_IMODE(m)}\n"
            "print(json.dumps(result))")
        result = await environment.exec("python -c " + shlex.quote(verify), user="root", timeout_sec=30)
        _require(result.return_code == 0 and json.loads(result.stdout) == expected,
                 "HARBOR_CANDIDATE", "Agent 内模型、配置或源码与冻结候选不符")
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        record = {"files": expected, "model_calls": 0, "kind": "frozen_candidate_transfer"}
        _atomic_json(self.logs_dir / "candidate_transfer.json", record)
        context.metadata = {"candidate_transfer": "candidate_transfer.json", "model_calls": 0}
