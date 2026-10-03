"""Explicit low-cost Docker-only probe; never certifies Harbor or model readiness."""
import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime, timezone

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from autoresearch_flow.pca_contract import task_digest


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--base-image', required=True, help='An existing local Python image; no implicit pull')
    parser.add_argument('--allow-docker', action='store_true', required=True)
    args=parser.parse_args()
    root=Path(__file__).resolve().parent
    run=root/'runs'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    run.mkdir(parents=True, exist_ok=False)
    commands=[]
    def call(command):
        result=subprocess.run(command, capture_output=True, text=True, timeout=180)
        commands.append({'command':command, 'exit_code':result.returncode,
                         'stdout':result.stdout, 'stderr':result.stderr})
        (run/'commands.json').write_text(json.dumps(commands, indent=2))
        if result.returncode:
            raise RuntimeError(result.stderr[-2000:])
        return result.stdout.strip()
    base_id=call(['docker','image','inspect','--format','{{.Id}}',args.base_image])
    images={}
    for role, context in [('agent','environment'), ('verifier','tests')]:
        tag='autoresearch-pca-component:'+role+'-'+run.name.lower()
        call(['docker','build','--pull=false','--network=none','--build-arg','BASE_IMAGE='+args.base_image,
              '-t',tag,'-f',str(root/context/'Dockerfile'),str(root/context)])
        images[role]=call(['docker','image','inspect','--format','{{.Id}}',tag])
    common=['docker','run','--rm','--network=none','--cpus=1','--memory=512m']
    public=json.loads(call(common+[images['agent']]))
    # Verify private final assets are not present in the public image.
    call(common+[images['agent'],'python','-c',
        "from pathlib import Path; assert not Path('/tests').exists(); assert not Path('/logs/verifier').exists()"])
    with tempfile.TemporaryDirectory(prefix='pca-component-') as tmp:
        candidate=Path(tmp)/'candidate'; candidate.mkdir()
        Path(tmp).chmod(0o755)
        shutil.copyfile(root/'environment/starter/method.py',candidate/'method.py')
        candidate.chmod(0o755); (candidate/'method.py').chmod(0o644)
        mount=['--mount',f'type=bind,src={candidate},dst=/workspace/solution,readonly']
        normal=json.loads(call(common+mount+['--workdir','/',images['verifier'],'bash','/tests/test.sh']))
        shutil.copyfile(root/'probe_candidate.py',candidate/'method.py')
        # Reproduce Harbor's post-build writable output-directory initialization.
        restricted=json.loads(call(common+mount+['--workdir','/tmp',images['verifier'],
            'sh','-c','chmod 777 /logs/verifier && exec bash /tests/test.sh']))
    assert public['raw_metric']['value']==0 and normal['reward']==restricted['reward']==1
    report={'status':'component_passed_not_harbor', 'at':datetime.now(timezone.utc).isoformat(),
            'base_image_id':base_id, 'images':images, 'public':public, 'normal':normal,
            'restricted_candidate':restricted, 'harbor_tested':False, 'model_calls':0,
            'gpu_used':False, 'stable_12h_tested':False,
            'contexts': {name: task_digest(root/name) for name in ('environment', 'tests')},
            'commands_sha256':hashlib.sha256((run/'commands.json').read_bytes()).hexdigest()}
    (run/'report.json').write_text(json.dumps(report, indent=2))
    print(json.dumps({'report':str(run/'report.json'), **report}))


if __name__=='__main__':
    main()
