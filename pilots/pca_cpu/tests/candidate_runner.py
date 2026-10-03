"""Runs only after dropping uid/gid; never receives synthetic private labels."""
import json
import runpy
import sys

method = runpy.run_path('/workspace/solution/method.py')
print(json.dumps(method['predict'](json.load(sys.stdin))))
