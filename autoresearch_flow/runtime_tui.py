"""Pinned native Codex records and detached terminal seam, not an ANSI parser."""
from __future__ import annotations

import json
import datetime as dt
import os
from pathlib import Path
import re
import shlex
import subprocess
import stat
import tempfile

from .core import FlowError, _require


class NativeEvents:
    """Translate observable rollout records to the existing event-clock seam.

    Keep the original records separately. Translations describe observable work,
    not Agent-authored trajectory rounds or unreturned model reasoning.
    """
    def __init__(self, version, expected_thread=None):
        _require(version == '0.147.0', 'CODEX_VERSION', 'TUI 适配目前只验证 Codex 0.147.0 协议')
        self.version = version
        self.thread_id = expected_thread
        self.saw_meta = False
        self.state = 'starting'
        self.turn_id = None
        self.calls = {}
        self.processes = {}

    @property
    def idle(self):
        return self.state == 'idle'

    def convert(self, record):
        _require(isinstance(record, dict), 'NATIVE_RECORD_INVALID', '原生记录须为对象，不接受 ANSI 输出')
        kind, payload = record.get('type'), record.get('payload')
        _require(isinstance(payload, dict), 'NATIVE_RECORD_INVALID', '原生记录缺 payload 对象')
        if kind == 'session_meta':
            thread = payload.get('id')
            _require(isinstance(thread, str) and bool(re.fullmatch(
                r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', thread)),
                'THREAD_MISSING', '原生会话缺合法标识')
            _require(self.thread_id in (None, thread), 'THREAD_MISMATCH', '不能把不同会话的原生记录拼接')
            _require(payload.get('cli_version') == self.version, 'CODEX_VERSION', '原生记录的 Codex 版本与锁定值不同')
            self.thread_id = thread
            self.saw_meta = True
            return [{'type': 'thread.started', 'thread_id': thread}]
        _require(self.saw_meta, 'THREAD_MISSING', '须先读取并核对原生 session_meta，不从请求猜测会话')
        event_type = payload.get('type')
        if kind == 'event_msg':
            if event_type == 'task_started':
                _require(self.thread_id and isinstance(payload.get('turn_id'), str) and payload['turn_id'],
                         'THREAD_MISSING', '回合开始前须有会话和回合标识')
                _require(self.state != 'running', 'NATIVE_TURN_INVALID', '前一回合未结束，不能重复开始')
                self.state, self.turn_id = 'running', payload['turn_id']
                return [{'type': 'turn.started'}]
            if event_type in {'error', 'turn_aborted', 'task_failed'}:
                self.state = 'failed'
                self.calls.clear()
                self.processes.clear()
                return [{'type': 'turn.failed', 'error': payload}]
            if event_type == 'task_complete':
                _require(self.state == 'running' and payload.get('turn_id') == self.turn_id
                         and not self.calls, 'NATIVE_TURN_INVALID', '回合收尾与当前回合或工具记录不一致')
                self.state = 'idle'
                return [{'type': 'turn.completed'}]
            if event_type in {'agent_message', 'agent_reasoning', 'token_count', 'user_message'}:
                return [{'type': 'item.completed', 'item': {'type': event_type, **payload}}]
        if kind == 'compacted' or (kind == 'event_msg' and event_type == 'context_compacted'):
            return [{'type': 'item.completed', 'item': {'type': 'compaction', 'native_payload': payload}}]
        if kind == 'response_item':
            if event_type in {'function_call', 'custom_tool_call'}:
                call_id = payload.get('call_id')
                _require(self.state == 'running' and isinstance(call_id, str) and call_id and call_id not in self.calls,
                         'NATIVE_TOOL_INVALID', '工具调用须位于当前回合并有唯一标识')
                name = payload.get('name', '')
                item = {'id': call_id, 'type': 'command_execution' if name in {
                    'exec_command', 'shell', 'shell_command'} else 'mcp_tool_call',
                    'name': name, 'arguments': payload.get('arguments', payload.get('input'))}
                try:
                    arguments = json.loads(item['arguments'])
                    if item['type'] == 'command_execution':
                        item['command'] = arguments.get('cmd', arguments.get('command', ''))
                    elif name == 'write_stdin':
                        item['process_session'] = str(arguments.get('session_id', ''))
                except (ValueError, TypeError, AttributeError):
                    if item['type'] == 'command_execution':
                        item['command'] = ''
                self.calls[call_id] = item
                return [{'type': 'item.started', 'item': item}]
            if event_type in {'function_call_output', 'custom_tool_call_output'}:
                call_id = payload.get('call_id')
                _require(call_id in self.calls, 'NATIVE_TOOL_INVALID', '工具结果缺对应调用；不补造开始时间')
                item = self.calls.pop(call_id)
                output = payload.get('output')
                return self._tool_output(item, output)
        return []

    def _tool_output(self, item, output):
        text = output if isinstance(output, str) else json.dumps(output, ensure_ascii=False)
        finished = re.search(r'(?m)^Process exited with code (-?[0-9]+)\s*$', text)
        running = re.search(r'(?m)^Process running with session ID (\S+)\s*$', text)
        if item['type'] == 'command_execution':
            item['exit_code'] = int(finished[1]) if finished else None
        events = [{'type': 'item.completed', 'item': {**item, 'aggregated_output': text}}]
        # Keep the original command alive across exec_command's asynchronous
        # return and write_stdin polls. Unknown sessions cannot certify a score.
        session = item.get('process_session')
        if running and item['type'] == 'command_execution':
            session = running[1]
            _require(session not in self.processes, 'NATIVE_TOOL_INVALID', '异步进程标识重复')
            self.processes[session] = {**item, 'id': 'process:'+session, 'output': ''}
            events.append({'type': 'item.started', 'item': self.processes[session].copy()})
        if session in self.processes:
            process = self.processes[session]
            body = re.split(r'(?m)^(?:Final output|Output):\s*\n', text, maxsplit=1)
            _require(len(body) == 2, 'NATIVE_TOOL_INVALID', '异步工具结果缺标准输出边界，不能猜测评分')
            process['output'] += body[1]
            _require(len(process['output'].encode('utf-8')) <= 4*1024*1024,
                     'LOG_LINE_LIMIT', '异步公开结果超出合并预算；原生分块仍须保留')
            if finished:
                self.processes.pop(session)
                events.append({'type': 'item.completed', 'item': {
                    **{k: v for k, v in process.items() if k != 'output'},
                    'exit_code': int(finished[1]), 'aggregated_output': process['output']}})
        return events


class RolloutTail:
    """Incremental reader constructed BEFORE launching or resuming a TUI.

    A resume reads the existing session header but skips prior work. Partial
    trailing lines wait for completion, never becoming synthetic events.
    """
    line_limit = 4 * 1024 * 1024

    def __init__(self, home, version, expected_thread=None):
        self.home = Path(home).resolve()
        self.adapter = NativeEvents(version, expected_thread)
        self.path = None
        self.offset = 0
        self.inode = None
        self.last_timestamp = None
        self.bootstrap = []
        files = self._files()
        if expected_thread:
            _require(len(files) == 1, 'THREAD_MISSING', '恢复须能唯一定位原会话记录；不得新建会话')
            self._select(files[0])
            with self.path.open('rb') as stream:
                header = stream.readline(self.line_limit + 1)
                self.bootstrap = [self._record(header)]
                self.offset = stream.seek(0, 2)
                stream.seek(-1, 2)
                _require(stream.read(1) == b'\n', 'NATIVE_RECORD_INVALID', '原会话记录末行不完整，须先核查')
        else:
            _require(not files, 'SESSION_EXISTS', '新运行目录已有会话；须显式恢复，不自动选 --last')

    def _files(self):
        return sorted((self.home/'sessions').rglob('*.jsonl'))

    def _select(self, path):
        _require(path.resolve().is_relative_to(self.home) and not path.is_symlink(),
                 'NATIVE_LOG_INVALID', '会话日志不得越界或使用符号链接')
        self.path = path
        self.inode = (path.stat().st_dev, path.stat().st_ino)

    def _record(self, line):
        _require(len(line) <= self.line_limit and line.endswith(b'\n'),
                 'NATIVE_RECORD_INVALID', '原生记录超长或缺换行')
        try:
            record = json.loads(line)
            stamp = dt.datetime.fromisoformat(record['timestamp'].replace('Z', '+00:00'))
            _require(stamp.tzinfo is not None, 'NATIVE_RECORD_INVALID', '原生时间戳须含时区')
            at = stamp.timestamp()
        except (ValueError, KeyError, TypeError, AttributeError) as exc:
            raise FlowError('NATIVE_RECORD_INVALID', '原生记录须为含时间戳的 JSONL，不接受终端画面') from exc
        _require(self.last_timestamp is None or at >= self.last_timestamp,
                 'CLOCK_ORDER', '原生事件时间倒退，须核查而非修造时间')
        self.last_timestamp = at
        return {'native': record, 'native_at': at, 'events': self.adapter.convert(record)}

    def poll(self):
        files = self._files()
        if self.path is None:
            if not files:
                return []
            _require(len(files) == 1, 'THREAD_MISMATCH', '出现多个会话，不能猜测主会话')
            self._select(files[0])
        _require(files == [self.path], 'THREAD_MISMATCH', '原会话消失或出现另一个会话')
        info = self.path.stat()
        _require((info.st_dev, info.st_ino) == self.inode and info.st_size >= self.offset
                 and not self.path.is_symlink(), 'NATIVE_LOG_CHANGED', '原生记录被替换或截断')
        records, self.bootstrap = self.bootstrap, []
        with self.path.open('rb') as stream:
            stream.seek(self.offset)
            start = self.offset
            while line := stream.readline(self.line_limit + 1):
                _require(len(line) <= self.line_limit, 'LOG_LINE_LIMIT', '原生记录超过单行预算')
                if not line.endswith(b'\n'):
                    break
                records.append(self._record(line))
                self.offset = stream.tell()
                if self.offset - start >= self.line_limit:
                    break
        return records


def codex_command(prompt, thread=None):
    """Explicit native session, never a picker, --last, or exec JSON mode."""
    _require(isinstance(prompt, str) and prompt and '\x00' not in prompt,
             'INVALID_PROMPT', 'TUI 须有非空文本指令')
    command = ['codex']
    if thread is not None:
        _require(isinstance(thread, str) and bool(re.fullmatch(
            r'[0-9a-fA-F]{8}(?:-[0-9a-fA-F]{4}){3}-[0-9a-fA-F]{12}', thread)),
            'THREAD_MISSING', '恢复须指定原会话 UUID')
        command += ['resume', thread]
    return command + ['--strict-config', '--no-alt-screen', prompt]


class TmuxTerminal:
    """One private detached server per supervised segment; observer is read-only.

    The socket lives in a short 0700 temp directory (Unix path limit), not the
    potentially long task directory. Keep its path in supervisor metadata when
    integrating this seam. This class does not count time or certify completion.
    """
    def __init__(self):
        self.directory = Path(tempfile.mkdtemp(prefix='ar-tui-'))
        self.socket = self.directory/'tmux.sock'
        self.started = False
        self.closed = False

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        self.close()

    @classmethod
    def existing(cls, socket):
        """Open only a tool-owned live socket; never create a replacement server."""
        path = Path(socket)
        _require(path.is_absolute() and path.name == 'tmux.sock' and path.parent.name.startswith('ar-tui-')
                 and path.parent.parent == Path(tempfile.gettempdir()) and not path.is_symlink()
                 and not path.parent.is_symlink(), 'TERMINAL_UNAVAILABLE', '专属终端路径无效；不猜测其他会话')
        try:
            info, parent = path.stat(), path.parent.stat()
        except OSError as exc:
            raise FlowError('TERMINAL_UNAVAILABLE', '专属终端已不存在；检查运行状态，不自动重建') from exc
        _require(stat.S_ISSOCK(info.st_mode) and info.st_uid == parent.st_uid == os.getuid()
                 and stat.S_IMODE(parent.st_mode) == 0o700,
                 'TERMINAL_UNAVAILABLE', '专属终端所有权或权限不符')
        terminal = cls.__new__(cls)
        terminal.directory, terminal.socket = path.parent, path
        terminal.started, terminal.closed = True, False
        return terminal

    def _command(self, *args, **kwargs):
        try:
            result = subprocess.run(['tmux', '-S', str(self.socket), '-f', '/dev/null', *args],
                                    capture_output=True, text=True, timeout=15, **kwargs)
        except (OSError, subprocess.SubprocessError) as exc:
            raise FlowError('HOST_DEPENDENCY_UNAVAILABLE',
                            '无法调用专属 tmux；请核对 tmux -V、临时目录及会话权限，不自动安装或改权限') from exc
        _require(result.returncode == 0, 'TERMINAL_FAILED', '专属终端命令失败；核对 tmux/socket 权限，不自动绕过')
        return result.stdout

    def start(self, command, env):
        _require(not self.started and not self.closed and not self.socket.exists(),
                 'TERMINAL_EXISTS', '不复用已有终端或覆盖运行')
        _require(isinstance(command, list) and command and all(
            isinstance(part, str) and part and '\x00' not in part for part in command),
            'INVALID_COMMAND', '终端命令须为明确参数数组')
        self._command('start-server', ';', 'set-option', '-g', 'remain-on-exit', 'on', ';',
                      'new-session', '-d', '-s', 'autoresearch', '-x', '120', '-y', '40',
                      shlex.join(command), env=env)
        self.started = True

    def status(self):
        raw = self._command('display-message', '-p', '-t', 'autoresearch:0.0',
                            '#{pane_dead}|#{pane_dead_status}').strip()
        _require(bool(re.fullmatch(r'[01]\|(?:[0-9]+)?', raw)),
                 'TERMINAL_FAILED', '无法确定专属终端状态；不推断已结束')
        dead, code = raw.split('|')
        return {'alive': dead == '0', 'exit_code': int(code) if code else None}

    def attach_command(self):
        return ['tmux', '-S', str(self.socket), 'attach-session', '-r', '-t', 'autoresearch']

    def observe(self):
        _require(self.status()['alive'], 'TERMINAL_UNAVAILABLE', '该分段已退出，无运行画面可连接')
        try:
            result = subprocess.run(self.attach_command())
        except (OSError, KeyboardInterrupt) as exc:
            raise FlowError('OBSERVER_DETACHED', '观察端已退出或无法连接；不会停止监督进程') from exc
        _require(result.returncode == 0, 'OBSERVER_DETACHED', '观察端连接结束；请查询 status，不能据此推断模型停止')
        return {'status': 'observer_detached', 'readonly': True}

    def send(self, prompt):
        _require(self.status()['alive'] and isinstance(prompt, str) and prompt
                 and not any(ord(c) < 32 and c not in '\n\t' for c in prompt),
                 'INVALID_PROMPT', '只能向仍存活的终端输入无控制字符的文本')
        self._command('load-buffer', '-b', 'flow', '-', input=prompt)
        self._command('paste-buffer', '-p', '-d', '-b', 'flow', '-t', 'autoresearch:0.0')
        self._command('send-keys', '-t', 'autoresearch:0.0', 'Enter')

    def capture(self):
        return self._command('capture-pane', '-p', '-e', '-S', '-200', '-t', 'autoresearch:0.0')

    def close(self):
        if self.closed:
            return
        if self.started or self.socket.exists():
            self._command('kill-server')
            self.socket.unlink(missing_ok=True)
        self.directory.rmdir()
        self.closed = True
