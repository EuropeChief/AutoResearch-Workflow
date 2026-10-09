"""Native Codex stdio proxy client; no new network server or screen parsing."""
from __future__ import annotations

import json
import queue
import subprocess
import socket
import threading
import time
from pathlib import Path

from .common import FlowError, _require
from .runtime_events import Redactor

METHODS = {'initialize', 'thread/start', 'thread/resume', 'thread/read',
           'thread/goal/get', 'thread/goal/set', 'turn/start', 'turn/interrupt'}


class CodexRpc:
    def __init__(self, command, *, env, log_path, secrets=(), request_timeout=30):
        self.log_path = Path(log_path)
        self.redactor = Redactor(secrets)
        self.request_timeout = request_timeout
        self.next_id = 0
        self.events = []
        self.incoming = queue.Queue()
        self.lock = threading.Lock()
        self.process = subprocess.Popen(command, stdin=subprocess.PIPE, stdout=subprocess.PIPE,
                                        stderr=subprocess.PIPE, env=env)
        # Codex's native `proxy` forwards raw control-socket bytes. That socket
        # speaks WebSocket, not newline stdio JSON. Use the installed client
        # library over a local socketpair; don't write our own framing/server.
        from websockets.sync.client import unix_connect
        self.endpoint, self.bridge = socket.socketpair()
        self.forward = threading.Thread(target=self._forward,daemon=True)
        self.backward = threading.Thread(target=self._backward,daemon=True)
        self.errors = threading.Thread(target=self._stderr,daemon=True)
        self.forward.start()
        self.backward.start()
        self.errors.start()
        try:
            self.websocket = unix_connect(sock=self.endpoint,
                open_timeout=request_timeout,close_timeout=2,max_size=8*1024*1024,proxy=None)
        except BaseException:
            self.process.terminate()
            self.process.wait(timeout=3)
            self.bridge.close()
            self.endpoint.close()
            raise
        self.reader = threading.Thread(target=self._read, daemon=True)
        self.reader.start()

    def _forward(self):
        try:
            while data := self.process.stdout.read1(65536):
                self.bridge.sendall(data)
        except OSError:
            pass
        finally:
            try:
                self.bridge.shutdown(socket.SHUT_WR)
            except OSError:
                pass

    def _backward(self):
        try:
            while data := self.bridge.recv(65536):
                self.process.stdin.write(data)
                self.process.stdin.flush()
        except (OSError,ValueError):
            pass

    def _record(self, direction, value):
        record = {'at': time.time(), 'monotonic': time.monotonic(), 'direction': direction,
                  'message': self.redactor.value(value)}
        with self.lock:
            with self.log_path.open('a', encoding='utf-8') as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + '\n')
        return record

    def _read(self):
        try:
            for line in self.websocket:
                value = json.loads(line)
                self.incoming.put(self._record('received', value))
        except Exception as exc:
            self.incoming.put(exc)
        finally:
            self.incoming.put(EOFError('原生代理已退出；不据此停止后端或健康作业'))

    def _stderr(self):
        for line in self.process.stderr:
            self._record('stderr', {'text': line.decode('utf-8',errors='replace').rstrip()})

    def request(self, method, params=None):
        _require(method in METHODS, 'RPC_METHOD_DENIED', '只使用既定会话/Goal 入口，不暴露外层任意执行')
        self.next_id += 1
        value = {'id': self.next_id, 'method': method, 'params': params or {}}
        self._record('sent', value)
        try:
            self.websocket.send(json.dumps(value))
        except (OSError, ValueError) as exc:
            raise FlowError('RPC_DISCONNECTED', '原生代理连接已中断') from exc
        end = time.monotonic() + self.request_timeout
        while True:
            try:
                record = self.incoming.get(timeout=max(0, end - time.monotonic()))
            except queue.Empty as exc:
                raise FlowError('RPC_TIMEOUT', '本次协议请求未返回；状态待核，不杀后端或作业') from exc
            if isinstance(record, BaseException):
                raise FlowError('RPC_DISCONNECTED', str(record)) from record
            message = record['message']
            if message.get('id') == value['id'] and 'method' not in message:
                if 'error' in message:
                    raise FlowError('RPC_ERROR', str(message['error']))
                return message['result']
            if 'method' in message and 'id' in message:
                # approval_policy=never should prevent approvals. Unexpected
                # server calls are denied, never auto-approved or elevated.
                denied = {'id': message['id'], 'error': {'code': -32601, 'message': 'unsupported server request'}}
                self.websocket.send(json.dumps(denied))
                self._record('sent', denied)
            else:
                self.events.append(record)

    def initialize(self):
        result = self.request('initialize', {'clientInfo': {'name': 'autoresearch-runtime', 'version': '1'},
                                             'capabilities': {'experimentalApi': False}})
        self.websocket.send('{"method":"initialized","params":{}}')
        return result

    def drain_events(self):
        while True:
            try:
                record = self.incoming.get_nowait()
            except queue.Empty:
                break
            if isinstance(record, BaseException):
                self.events.append({'at': time.time(), 'direction': 'received',
                                    'message': {'method': 'runtime/proxy_exit', 'params': {'error': str(record)}}})
            else:
                self.events.append(record)
        events, self.events = self.events, []
        return events

    def close(self):
        # This is only the stdio proxy, not the actual Codex app-server or jobs.
        self.websocket.close()
        self.bridge.close()
        if self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=3)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait(timeout=3)
        self.reader.join(timeout=2)
        self.errors.join(timeout=2)
        self.forward.join(timeout=2)
        self.backward.join(timeout=2)
        for stream in (self.process.stdin, self.process.stdout, self.process.stderr):
            stream.close()


class GoalSession:
    def __init__(self, rpc, *, model, thread_id=None):
        self.rpc, self.model, self.thread_id = rpc, model, thread_id

    def start(self, objective, prompt):
        _require(self.thread_id is None and isinstance(objective, str) and 0 < len(objective) <= 4000,
                 'GOAL_INPUT', '首次启动须提供非空原目标，不能替换既有会话')
        result = self.rpc.request('thread/start', {'model': self.model, 'cwd': '/workspace/solution',
                                                  'approvalPolicy': 'never', 'ephemeral': False,
                                                  'developerInstructions': prompt})
        self.thread_id = result['thread']['id']
        goal = self.rpc.request('thread/goal/set', {'threadId': self.thread_id,
                                                   'objective': objective, 'status': 'active'})['goal']
        _require(goal and goal['threadId'] == self.thread_id and goal['objective'] == objective
                 and goal['status'] == 'active', 'GOAL_NOT_ACTIVE', '初始原生 Goal 未读回 active')
        self.rpc.request('turn/start', {'threadId': self.thread_id,
                                       'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]})
        return goal

    def get(self):
        _require(self.thread_id is not None, 'THREAD_MISSING', '不能猜测会话或使用 --last')
        return self.rpc.request('thread/goal/get', {'threadId': self.thread_id})['goal']

    def attach(self, expected_objective):
        _require(self.thread_id is not None, 'THREAD_MISSING', '恢复须使用记录的原 threadId')
        resumed = self.rpc.request('thread/resume', {'threadId': self.thread_id, 'model': self.model,
                                                    'cwd': '/workspace/solution', 'approvalPolicy': 'never'})
        _require(resumed['thread']['id'] == self.thread_id, 'THREAD_MISMATCH', '不能拼接新会话')
        goal = self.get()
        _require(goal and goal['threadId'] == self.thread_id and goal['objective'] == expected_objective,
                 'GOAL_MISMATCH', '原 Goal 丢失或目标改变；不静默新建')
        return goal

    def resume(self, expected_objective, prompt):
        goal = self.attach(expected_objective)
        if goal['status'] == 'paused':
            self.rpc.request('thread/goal/set', {'threadId': self.thread_id, 'status': 'active'})
            goal = self.get()
        _require(goal['status'] == 'active', 'GOAL_NOT_ACTIVE', '先解决原 Goal 的阻塞/限额，不重置计数绕过')
        thread=self.rpc.request('thread/read',{'threadId':self.thread_id,'includeTurns':False})['thread']
        status=thread.get('status',{}).get('type')
        if status=='active':
            return goal  # Observer recovery is not permission to inject a second turn.
        _require(status=='idle','THREAD_NOT_IDLE','原线程未就绪；保留状态，不猜测或重开会话')
        self.rpc.request('turn/start', {'threadId': self.thread_id,
                                       'input': [{'type': 'text', 'text': prompt, 'text_elements': []}]})
        return goal

    def pause(self):
        goal = self.get()
        _require(goal is not None, 'GOAL_MISSING', '缺少原 Goal')
        return self.rpc.request('thread/goal/set', {'threadId': self.thread_id, 'status': 'paused'})['goal']
