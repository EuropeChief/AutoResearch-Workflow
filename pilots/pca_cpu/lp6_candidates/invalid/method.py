"""Required config deliberately missing; stale reward must not make this pass."""
import json
from pathlib import Path


def predict(values):
    coefficient = json.loads(Path(__file__).with_name("model.json").read_text())["coefficient"]
    return [coefficient * value for value in values]
