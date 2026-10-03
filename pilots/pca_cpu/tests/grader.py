"""Toy permission/entrypoint probe. Not a generic sandbox or scientific grader."""
import json
import math
import os
from pathlib import Path
import resource
import subprocess
import sys


def restrict():
    os.setgroups([])
    os.setgid(65534)
    os.setuid(65534)
    resource.setrlimit(resource.RLIMIT_CPU, (3, 3))
    resource.setrlimit(resource.RLIMIT_AS, (256*1024*1024, 256*1024*1024))
    resource.setrlimit(resource.RLIMIT_FSIZE, (1024*1024, 1024*1024))


output = Path('/logs/verifier')
# Harbor recreates/chmods this output mount after image construction. Restore
# ownership and access before executing any untrusted candidate code.
os.chown('/logs', 0, 0)
Path('/logs').chmod(0o755)
# Keep the trusted host logger's ownership on Harbor's bind mount. The
# candidate UID is distinct; it may read the final reward but cannot create,
# replace or truncate it. Root-only ownership would break Harbor log writes.
assert output.stat().st_uid != 65534
output.chmod(0o755)
for name in ('reward.txt', 'reward.json'):
    (output / name).unlink(missing_ok=True)
result = subprocess.run([sys.executable, '/tests/candidate_runner.py'], input='[1,2,3]',
                        text=True, capture_output=True, timeout=10, preexec_fn=restrict,
                        env={'PATH': os.environ['PATH']}, cwd='/workspace/solution')
if result.returncode:
    raise RuntimeError('candidate failed: '+result.stderr)
values = json.loads(result.stdout)
assert isinstance(values, list) and len(values) == 3
assert all(type(x) in (int, float) and math.isfinite(x) for x in values)
labels = json.loads(Path('/tests/private/labels.json').read_text())
reward = 1-sum(abs(a-b) for a, b in zip(values, labels))
temporary = output/'reward.tmp'
temporary.write_text(str(reward)+'\n')
os.replace(temporary, output/'reward.txt')
print(json.dumps({'status':'succeeded', 'reward':reward, 'candidate_uid':65534}))
