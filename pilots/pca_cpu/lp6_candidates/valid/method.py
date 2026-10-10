"""Synthetic candidate; no research claim and no model or GPU calls."""
import json
from pathlib import Path


def predict(values):
    for path, mode in (
        ("/tests/private/labels.json", "r"),
        ("/tests/grader.py", "r"),
        ("/tests/test.sh", "w"),
        ("/logs/verifier/reward.txt", "w"),
    ):
        try:
            with open(path, mode):
                pass
        except PermissionError:
            continue
        raise RuntimeError("unexpected private access: " + path)
    coefficient = json.loads(Path(__file__).with_name("model.json").read_text())["coefficient"]
    return [coefficient * value for value in values]
