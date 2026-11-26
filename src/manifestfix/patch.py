"""Frozen-field merging of a model's repair response.

A repair response is only allowed to touch the JSON paths that failed. Whatever else the model
returns (an edit to `vessel`, a re-written copy of the whole document) is discarded, so a repair
round cannot damage a field that was already right.
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass, field
from typing import Any

Token = str | int
_TOKEN = re.compile(r"\[(\d+)\]|([^.\[\]]+)")


def parse_path(path: str) -> list[Token]:
    """`containers[1].container_no` -> ['containers', 1, 'container_no']. `$` is the root."""
    if path in ("", "$"):
        return []
    return [
        int(m.group(1)) if m.group(1) is not None else m.group(2) for m in _TOKEN.finditer(path)
    ]


def covers(allowed: str, target: str) -> bool:
    """True when `target` is `allowed` itself or lies inside it."""
    a, t = parse_path(allowed), parse_path(target)
    return t[: len(a)] == a


def get_path(data: Any, tokens: list[Token]) -> Any:
    for token in tokens:
        data = data[token]
    return data


def _set(data: Any, tokens: list[Token], value: Any) -> None:
    parent = get_path(data, tokens[:-1])
    key = tokens[-1]
    if isinstance(parent, list):
        if not isinstance(key, int) or key >= len(parent):
            raise IndexError(f"no list item at {key!r}")
        parent[key] = value
    elif isinstance(parent, dict) and isinstance(key, str):
        parent[key] = value
    else:
        raise TypeError("cannot set that path")


def _remove(data: Any, tokens: list[Token]) -> None:
    parent = get_path(data, tokens[:-1])
    del parent[tokens[-1]]


@dataclass
class MergeResult:
    data: Any
    applied: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)


def _ops_from_response(response: Any, allowed: set[str]) -> list[dict[str, Any]]:
    if isinstance(response, dict) and isinstance(response.get("patch"), list):
        return [op for op in response["patch"] if isinstance(op, dict)]
    if isinstance(response, list):
        return [op for op in response if isinstance(op, dict)]
    ops = []
    if isinstance(response, dict):
        for path in sorted(allowed):
            try:
                value = get_path(response, parse_path(path))
            except (KeyError, IndexError, TypeError):
                continue
            ops.append({"op": "replace", "path": path, "value": value})
    return ops


def merge_frozen(current: Any, response: Any, allowed: set[str]) -> MergeResult:
    """Apply a repair response to `current`, touching only paths inside `allowed`.

    The response may be a patch (`{"patch": [{"op", "path", "value"}]}` or a bare list) or a full
    object, from which only the allowed paths are read. If `$` is allowed, a full object replaces
    the document. `current` is never mutated.
    """
    if "$" in allowed and isinstance(response, dict) and "patch" not in response:
        return MergeResult(copy.deepcopy(response), ["$"])
    result = MergeResult(copy.deepcopy(current))
    for op in _ops_from_response(response, allowed):
        path = op.get("path")
        kind = op.get("op", "replace")
        if not isinstance(path, str) or kind not in ("replace", "remove"):
            result.rejected.append(str(path))
            continue
        if not any(covers(a, path) for a in allowed):
            result.rejected.append(path)
            continue
        tokens = parse_path(path)
        try:
            if not tokens:
                result.data = copy.deepcopy(op["value"])
            elif kind == "remove":
                _remove(result.data, tokens)
            else:
                _set(result.data, tokens, copy.deepcopy(op["value"]))
        except (KeyError, IndexError, TypeError):
            result.rejected.append(path)
            continue
        result.applied.append(path)
    return result
