"""Synthetic public-only component check, not a research task."""
import json
import runpy

method = runpy.run_path('/workspace/solution/method.py')
predictions = method['predict']([1, 2, 3])
error = sum(abs(a-b) for a, b in zip(predictions, [2, 4, 6]))
print(json.dumps({'status': 'succeeded', 'score': 1-error,
                  'raw_metric': {'name': 'toy_error', 'direction': 'minimize', 'value': error}}))
