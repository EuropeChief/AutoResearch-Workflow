import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


class WorkerTimeoutTests(unittest.TestCase):
    def test_fixed_job_timeout_ends_actual_child_and_returns_nonzero(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            output=root/'output'
            output.mkdir()
            request=root/'run.json'
            request.write_text(json.dumps({'command':[sys.executable,'-c',
                'import os,time;print(os.getpid(),flush=True);time.sleep(60)'],
                'candidate':str(root),'output':str(output),'cuda_visible_devices':'','timeout_seconds':.1}))
            wrapper=Path(__file__).resolve().parents[1]/'autoresearch_flow/assets/run_worker.py'
            result=subprocess.run([sys.executable,str(wrapper),str(request)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,124)
            pid=int((output/'runner.log').read_text().strip())
            self.assertFalse(Path('/proc').joinpath(str(pid)).exists())

    def test_timeout_cleans_descendant_even_if_group_leader_exited(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp)
            (root/'output').mkdir()
            request=root/'run.json'
            descendant='import os,signal,time;signal.signal(signal.SIGTERM,signal.SIG_IGN);print(os.getpid(),flush=True);time.sleep(60)'
            parent='import subprocess,sys,time;subprocess.Popen([sys.executable,"-c",'+repr(descendant)+']);time.sleep(60)'
            request.write_text(json.dumps({'command':[sys.executable,'-c',parent],
                'candidate':str(root),'output':str(root/'output'),'cuda_visible_devices':'','timeout_seconds':.2}))
            wrapper=Path(__file__).resolve().parents[1]/'autoresearch_flow/assets/run_worker.py'
            result=subprocess.run([sys.executable,str(wrapper),str(request)],capture_output=True,text=True,timeout=5)
            self.assertEqual(result.returncode,124)
            pid=int((root/'output/runner.log').read_text().strip())
            stat=Path('/proc')/str(pid)/'stat'
            self.assertTrue(not stat.exists() or stat.read_text().split()[2]=='Z')
