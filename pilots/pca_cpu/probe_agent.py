"""Deterministic Harbor transfer/permission probe, never a research trajectory."""
import hashlib
import json
from pathlib import Path

from harbor.agents.nop import NopAgent


class TransferProbe(NopAgent):
    @staticmethod
    def name():
        return "pca-transfer-probe"

    async def run(self, instruction, environment, context):
        # Use the actual public environment, not the verifier or host workspace.
        before = await environment.exec(
            "python -c \"from pathlib import Path; "
            "assert not Path('/tests').exists(); "
            "assert not Path('/var/run/docker.sock').exists(); "
            "print('public-boundary-ok')\"", timeout_sec=10)
        if before.return_code != 0:
            raise RuntimeError("Agent public boundary failed")
        candidate = Path(__file__).with_name("probe_candidate.py")
        await environment.upload_file(candidate, "/workspace/solution/method.py")
        result = await environment.exec(
            "python -c \"from pathlib import Path; import hashlib; "
            "print(hashlib.sha256(Path('/workspace/solution/method.py').read_bytes()).hexdigest())\"",
            timeout_sec=10)
        expected = hashlib.sha256(candidate.read_bytes()).hexdigest()
        if result.return_code != 0 or result.stdout.strip() != expected:
            raise RuntimeError("Updated candidate was not installed in Agent environment")
        record = {"kind": "synthetic_transfer_probe", "candidate_sha256": expected,
                  "public_boundary": before.stdout.strip(), "model_calls": 0}
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        (self.logs_dir / "transfer_probe.json").write_text(json.dumps(record, indent=2))
        context.metadata = record
