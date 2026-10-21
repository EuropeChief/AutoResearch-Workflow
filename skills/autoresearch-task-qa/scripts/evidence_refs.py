"""Validate explicit evidence locations without judging semantic support.

Only trusted review syntax is interpreted, never submission code. See the
implementation report contract for supported line, field and Pointer forms.
"""
import json
from pathlib import Path
import re
from urllib.parse import unquote

LIMIT = 4 * 1024 * 1024
_LINE = re.compile(r"L?(-?\d+)(?:-L?(-?\d+))?\Z")
_FIELD = re.compile(r"[A-Za-z_][A-Za-z_0-9]*(?:(?:\.[A-Za-z_][A-Za-z_0-9]*)|(?:\[\d+\]))*\Z")


def _field_tokens(field):
    if not _FIELD.fullmatch(field):
        raise ValueError(f"invalid explicit JSON field locator: {field}")
    return [int(index) if index else key for key, index in
            re.findall(r"([A-Za-z_][A-Za-z_0-9]*)|\[(\d+)\]", field)]


def resolve_ref(root, ref):
    """Return the safe file; validate only explicitly supplied locations."""
    if not isinstance(ref, str) or not ref:
        raise ValueError("evidence must be a nonempty relative file reference")
    name, separator, fragment = ref.partition("#")
    lines = None
    suffix = re.search(r":(-?\d+(?:--?\d+)?)$", name)
    if suffix:
        lines = _LINE.fullmatch(suffix[1])
        name = name[:suffix.start()]
    if Path(name).is_absolute():
        raise ValueError(f"evidence must be relative to the inspected bundle: {ref}")
    root = Path(root).resolve()
    path = (root / name).resolve()
    if not path.is_relative_to(root) or not path.is_file():
        raise ValueError(f"evidence path is not a file within the inspected bundle: {ref}")
    fragment_lines = _LINE.fullmatch(fragment) if fragment.startswith("L") else None
    if fragment_lines:
        if lines:
            raise ValueError(f"multiple line locators are ambiguous: {ref}")
        lines = fragment_lines
    pointer = separator and fragment.startswith("/")
    field = None
    if fragment.startswith("field="):
        field = fragment[6:]
    elif fragment.startswith("$."):
        field = fragment[2:]
    elif not fragment_lines and path.suffix.lower() == ".json" and _FIELD.fullmatch(fragment):
        field = fragment  # Existing #score / #agent_execution[0] / #metrics.score syntax.
    if not lines and not pointer and field is None:
        return path  # No locator, or a descriptive fragment: do not infer one.
    if path.stat().st_size > LIMIT:
        raise ValueError(f"explicit evidence location exceeds the 4 MiB inspection limit: {ref}")
    try:
        text = path.read_text(encoding="utf-8")
        if lines:
            start = int(lines[1])
            end = int(lines[2]) if lines[2] is not None else start
            if not 1 <= start <= end <= len(text.splitlines()):
                raise ValueError(f"evidence line location out of bounds: {ref}")
        if pointer or field is not None:
            node = json.loads(text)
            if pointer:
                decoded = unquote(fragment)
                if re.search(r"~(?![01])", decoded):
                    raise ValueError(f"invalid JSON Pointer escape: {ref}")
                tokens = [part.replace("~1", "/").replace("~0", "~") for part in decoded[1:].split("/")]
            else:
                tokens = _field_tokens(field)
            for token in tokens:
                if isinstance(node, dict) and isinstance(token, str) and token in node:
                    node = node[token]
                elif isinstance(node, list) and (isinstance(token, int) or re.fullmatch(r"0|[1-9]\d*", token)):
                    index = int(token)
                    if index >= len(node):
                        raise ValueError(f"JSON array location does not exist: {ref}")
                    node = node[index]
                else:
                    raise ValueError(f"JSON field location does not exist: {ref}")
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read explicit evidence location: {ref}: {exc}") from exc
    return path
