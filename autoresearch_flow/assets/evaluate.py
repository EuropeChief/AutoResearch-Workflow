"""Public fixed-entry client. Uses files only; no Docker, sockets or credentials."""
import argparse
import json
import os
from pathlib import Path
import sys
import time
import uuid


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('operation', choices=['submit', 'status', 'logs', 'result'])
    parser.add_argument('--job-id')
    args = parser.parse_args()
    if (args.operation == 'submit') == (args.job_id is not None):
        parser.error('submit 不指定 job-id；查询须指定原 job-id')
    request_id = uuid.uuid4().hex
    request = {'request_id': request_id, 'operation': args.operation}
    if args.job_id:
        request['job_id'] = args.job_id
    root = Path('/run/autoresearch')
    path = root / 'requests' / (request_id + '.json')
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(request), encoding='utf-8')
    os.replace(temporary, path)
    response = root / 'responses' / path.name
    # This is only a short IPC timeout, never a training/track timeout.
    deadline = time.monotonic() + 30
    while not response.is_file():
        if time.monotonic() >= deadline:
            print(json.dumps({'status': 'unavailable', 'request_id': request_id,
                              'error': 'coordinator reply pending; existing job is not cancelled'}))
            return 1
        time.sleep(0.1)
    value = json.loads(response.read_text(encoding='utf-8'))
    print(json.dumps(value, ensure_ascii=False))
    return 1 if value.get('status') in {'failed','observation_pending'} else 0


if __name__ == '__main__':
    sys.exit(main())
