"""Use the delivered fingerprint algorithm, without exposing private task entries."""
from .common import FlowError
from .materials_io import bundled


def fingerprint(task):
    module = bundled('task_fingerprint')
    try:
        result = module.fingerprint(task)
    except (OSError, ValueError) as exc:
        raise FlowError('TASK_FINGERPRINT', str(exc)) from exc
    result.pop('entries')
    return result
