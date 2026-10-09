"""Expert-side fixed runner wrapper, never imports a model-selected command."""
import json
import os
from pathlib import Path
import subprocess
import sys
import signal
import threading


def main():
    request = json.loads(Path(sys.argv[1]).read_text())
    command, output = request['command'], Path(request['output'])
    output.mkdir(exist_ok=True)
    env = {'PATH': '/opt/conda/bin:/usr/local/bin:/usr/bin:/bin', 'LANG': 'C.UTF-8',
           'PYTHONUNBUFFERED': '1', 'NVIDIA_DRIVER_CAPABILITIES': 'compute,utility',
           'HOME': str(output), 'CUDA_VISIBLE_DEVICES': request['cuda_visible_devices']}
    with (output / 'runner.log').open('w') as log:
        child = subprocess.Popen(command, cwd=request['candidate'], env=env,
                                 stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                                 errors='replace', bufsize=1, start_new_session=True)
        expired=threading.Event()
        def expire():
            expired.set()
            # Only this wrapper's own job group; never a shared track/backend.
            try:
                os.killpg(child.pid,signal.SIGTERM)
            except ProcessLookupError:
                return
            # The leader may exit before a descendant that still holds stdout/GPU.
            # Always finish this same job group's grace period, not just leader.wait.
            threading.Event().wait(2)
            try:
                os.killpg(child.pid,signal.SIGKILL)
            except ProcessLookupError:
                pass
        timeout=request.get('timeout_seconds')
        timer=threading.Timer(timeout,expire) if timeout else None
        if timer:
            timer.start()
        try:
            for line in child.stdout:
                log.write(line)
                log.flush()
                sys.stdout.write(line)
                sys.stdout.flush()
            status = child.wait()
        finally:
            if timer:
                timer.cancel()
                timer.join()
            child.stdout.close()
        if expired.is_set():
            print('fixed public job exceeded its configured timeout',file=sys.stderr)
            return 124
    return status


if __name__ == '__main__':
    sys.exit(main())
