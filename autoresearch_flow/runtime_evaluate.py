"""Standalone read-only Public/Dev wrapper; no model calls or second evaluation.

Prepared into the container with its fixed command. The same tree digest is
used by the host, so a tool result can identify the exact evaluated candidate.
"""
import hashlib
import json
import os
from pathlib import Path
import stat
import signal
import subprocess
import sys


class TreeError(ValueError):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code


def tree_digest(root):
    root = Path(root)
    if not root.is_dir() or root.is_symlink():
        raise TreeError('TASK_DIRECTORY', '任务目录不存在或为链接')
    entries = []
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise TreeError('TASK_SYMLINK', '构建/移交材料不得通过符号链接越界')
        mode = path.stat().st_mode
        if not (stat.S_ISREG(mode) or stat.S_ISDIR(mode)):
            raise TreeError('TASK_SPECIAL_FILE', '任务材料不能含设备、管道等特殊文件')
        item = {'path': path.relative_to(root).as_posix(), 'mode': stat.S_IMODE(mode),
                'kind': 'file' if stat.S_ISREG(mode) else 'directory'}
        if stat.S_ISREG(mode):
            digest = hashlib.sha256()
            with path.open('rb') as stream:
                for block in iter(lambda: stream.read(1024*1024), b''):
                    digest.update(block)
            item['sha256'] = digest.hexdigest()
        entries.append(item)
    return hashlib.sha256(json.dumps(entries, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':')).encode('utf-8')).hexdigest()


def evaluate(command, candidate):
    before = tree_digest(candidate)
    process = subprocess.Popen(command, stdout=subprocess.PIPE, text=True, errors='replace', start_new_session=True)
    # A private process group owns evaluator workers. Forward wrapper shutdown
    # through finally, so it does not strand them outside the caller's group.
    def interrupted(signum, frame):
        raise InterruptedError(f'Public/Dev interrupted by signal {signum}')
    handlers = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    def stop_group(sig):
        try:
            os.killpg(process.pid, sig)
        except ProcessLookupError:
            pass
    last = ''
    try:
        for sig in handlers:
            signal.signal(sig, interrupted)
        while line := process.stdout.readline(4*1024*1024+1):
            if len(line) > 4*1024*1024:
                raise ValueError('Public/Dev 输出单行超出 4 MiB 记录预算')
            if line.strip():
                if last:
                    print(last, end='', flush=True)
                last = line
        code = process.wait()
        if code == 0:
            value = json.loads(last)
            if not isinstance(value, dict):
                raise ValueError('Public/Dev 最后一行须为 JSON 对象')
            value['evaluation_binding'] = {'candidate_before_sha256': before,
                                            'candidate_after_sha256': tree_digest(candidate)}
            print(json.dumps(value, ensure_ascii=False), flush=True)
        elif last:
            print(last, end='', flush=True)
        return code
    finally:
        try:
            for sig in handlers:
                signal.signal(sig, signal.SIG_IGN)
            stop_group(signal.SIGTERM)
            try:
                process.wait(timeout=1)  # Finish before the outer segment's 5 s TERM grace.
            except subprocess.TimeoutExpired:
                pass
            finally:
                stop_group(signal.SIGKILL)
                process.wait(timeout=1)
                process.stdout.close()
        finally:
            for sig, handler in handlers.items():
                signal.signal(sig, handler)


if __name__ == '__main__':
    try:
        command = json.loads(Path('/workspace/_public_command.json').read_text())
        code = evaluate([*command, *sys.argv[1:]], Path('/workspace/solution'))
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        print(json.dumps({'status': 'infrastructure_error', 'error': str(error)}, ensure_ascii=False), flush=True)
        code = 1
    raise SystemExit(code)
