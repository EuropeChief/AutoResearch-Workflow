"""CPU-only trusted evaluation receipts; no Docker or model calls."""
import contextlib
import io
import json
import os
from pathlib import Path
import sys
import signal
import subprocess
import tempfile
import unittest
import time

from autoresearch_flow.pca_contract import task_digest
from autoresearch_flow.runtime_evaluate import evaluate


class EvaluationBindingTests(unittest.TestCase):
    def test_timeout_interrupts_silent_stubborn_work_instead_of_postchecking(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            pidfile = root / 'worker.pid'
            candidate = root / 'candidate'
            candidate.mkdir()
            code = ('import os,signal,time,pathlib;signal.signal(signal.SIGTERM,signal.SIG_IGN);'
                    f'pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid()));time.sleep(60)')
            start = time.monotonic()
            self.assertEqual(evaluate([sys.executable, '-c', code], candidate, timeout=.15), 124)
            self.assertLess(time.monotonic() - start, 4)
            with self.assertRaises(ProcessLookupError):
                os.kill(int(pidfile.read_text()), 0)

    def test_wrapper_term_cleans_stubborn_evaluator_before_outer_five_second_kill(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root/'candidate'
            candidate.mkdir()
            pidfile = root/'evaluator.pid'
            evaluator = ('import os,signal,pathlib,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); '
                         f'pathlib.Path({str(pidfile)!r}).write_text(str(os.getpid())); time.sleep(60)')
            wrapper = subprocess.Popen([sys.executable, '-c',
                'from autoresearch_flow.runtime_evaluate import evaluate; '
                f'evaluate({[sys.executable, "-c", evaluator]!r}, {str(candidate)!r})'],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            evaluator_pid = None
            try:
                deadline = time.monotonic()+3
                while not pidfile.exists() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertTrue(pidfile.exists())
                evaluator_pid = int(pidfile.read_text())
                wrapper.terminate()
                wrapper.wait(timeout=3)  # Must finish safely before the outer 5 s deadline.
                with self.assertRaises(ProcessLookupError):
                    os.kill(evaluator_pid, 0)
            finally:
                if wrapper.poll() is None:
                    wrapper.kill()
                    wrapper.wait(timeout=3)
                if evaluator_pid is not None:
                    try:
                        os.kill(evaluator_pid, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_output_failure_stops_the_evaluator_worker_too(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            candidate = root/'candidate'
            candidate.mkdir()
            pidfile = root/'worker.pid'
            command = [sys.executable, '-c',
                'import subprocess,sys,pathlib; '
                'p=subprocess.Popen([sys.executable,"-c","import time; time.sleep(60)"], stdout=subprocess.DEVNULL); '
                'pathlib.Path(sys.argv[1]).write_text(str(p.pid)); '
                'print("x"*(4*1024*1024+1), flush=True)', str(pidfile)]
            worker = None
            try:
                with contextlib.redirect_stdout(io.StringIO()), self.assertRaises(ValueError):
                    evaluate(command, candidate)
                worker = int(pidfile.read_text())
                def running():
                    status = Path(f'/proc/{worker}/stat')
                    return status.exists() and status.read_text().split(') ')[1].split()[0] != 'Z'
                deadline = time.monotonic()+2
                while running() and time.monotonic() < deadline:
                    time.sleep(.02)
                self.assertFalse(running(), 'evaluation worker survived wrapper failure')
            finally:
                if worker is not None:
                    try:
                        os.kill(worker, signal.SIGKILL)
                    except ProcessLookupError:
                        pass

    def test_original_result_is_bound_to_actual_candidate_without_a_second_evaluation(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root/'method.py').write_text('original')
            before = task_digest(root)
            stream = io.StringIO()
            command = [sys.executable, '-c', 'print("progress"); print(\'{"status":"succeeded","score":0.5}\')']
            with contextlib.redirect_stdout(stream):
                self.assertEqual(evaluate(command, root), 0)
            lines = stream.getvalue().splitlines()
            self.assertEqual(lines[0], 'progress')
            result = json.loads(lines[-1])
            self.assertEqual(result['score'], .5)
            self.assertEqual(result['evaluation_binding'],
                {'candidate_before_sha256': before, 'candidate_after_sha256': before})
            (root/'method.py').write_text('unscored replacement')
            self.assertNotEqual(task_digest(root), result['evaluation_binding']['candidate_after_sha256'])

    def test_candidate_mutation_during_evaluation_is_visible_and_failure_is_not_a_score(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root/'method.py'
            path.write_text('original')
            command = [sys.executable, '-c',
                'import pathlib,sys; pathlib.Path(sys.argv[1]).write_text("changed"); print(\'{"status":"succeeded"}\')', str(path)]
            stream = io.StringIO()
            with contextlib.redirect_stdout(stream):
                self.assertEqual(evaluate(command, root), 0)
            binding = json.loads(stream.getvalue().splitlines()[-1])['evaluation_binding']
            self.assertNotEqual(binding['candidate_before_sha256'], binding['candidate_after_sha256'])
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(evaluate([sys.executable, '-c', 'raise SystemExit(7)'], root), 7)


if __name__ == '__main__':
    unittest.main()
