"""Value-preserving pre-repairs for almost-JSON model output.

The scanner walks the text once, tracking whether it is inside a string. Repairs are applied only
outside strings, so a value such as "bolts, nuts, 'washers'" or "http://x" is never touched. The
one exception is a single-quoted string, which is re-quoted with the same characters. Every repair
is logged.

Handled: markdown fences, prose before and after the object, trailing commas, single-quoted
strings, Python literals (True/False/None) and `//` or `/* */` comments.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

_FENCE = re.compile(r"```[A-Za-z0-9_-]*[ \t]*\n(.*?)```", re.DOTALL)
_PY_LITERALS = {"True": "true", "False": "false", "None": "null"}


class LenientJSONError(ValueError):
    """The text could not be turned into JSON even after the pre-repairs."""


@dataclass(frozen=True)
class Repair:
    kind: str
    position: int

    def __str__(self) -> str:
        return f"{self.kind}@{self.position}"


@dataclass
class LenientResult:
    data: Any
    repairs: list[Repair] = field(default_factory=list)

    @property
    def kinds(self) -> list[str]:
        return [r.kind for r in self.repairs]


def _end_of_double_quoted(text: str, start: int) -> int:
    i = start + 1
    while i < len(text):
        if text[i] == "\\":
            i += 2
            continue
        if text[i] == '"':
            return i + 1
        i += 1
    return len(text)


def _convert_single_quoted(text: str, start: int) -> tuple[str, int]:
    out = ['"']
    i = start + 1
    while i < len(text):
        char = text[i]
        if char == "\\" and i + 1 < len(text):
            nxt = text[i + 1]
            out.append("'" if nxt == "'" else char + nxt)
            i += 2
            continue
        if char == "'":
            out.append('"')
            return "".join(out), i + 1
        out.append('\\"' if char == '"' else char)
        i += 1
    return "".join(out), len(text)


def _skip_comment(text: str, i: int) -> int | None:
    """If a comment starts at i return the index after it, else None."""
    if text.startswith("//", i):
        end = text.find("\n", i)
        return len(text) if end == -1 else end
    if text.startswith("/*", i):
        end = text.find("*/", i + 2)
        return len(text) if end == -1 else end + 2
    return None


def _next_significant(text: str, i: int) -> int:
    """Index of the next character that is not whitespace or part of a comment."""
    while i < len(text):
        if text[i].isspace():
            i += 1
            continue
        skipped = _skip_comment(text, i)
        if skipped is None:
            break
        i = skipped
    return i


def _find_start(body: str) -> int | None:
    stripped = body.lstrip()
    if stripped.startswith("["):
        return len(body) - len(stripped)
    index = body.find("{")
    return index if index != -1 else None


def _convert(body: str, start: int, repairs: list[Repair]) -> tuple[str, int]:
    out: list[str] = []
    depth = 0
    i = start
    while i < len(body):
        char = body[i]
        if char == '"':
            end = _end_of_double_quoted(body, i)
            out.append(body[i:end])
            i = end
        elif char == "'":
            repairs.append(Repair("single_quote", i))
            converted, i = _convert_single_quoted(body, i)
            out.append(converted)
        elif char == "/" and (skipped := _skip_comment(body, i)) is not None:
            repairs.append(Repair("comment", i))
            i = skipped
        elif char in "{[":
            depth += 1
            out.append(char)
            i += 1
        elif char in "}]":
            depth -= 1
            out.append(char)
            i += 1
            if depth == 0:
                break
        elif char == ",":
            nxt = _next_significant(body, i + 1)
            if nxt < len(body) and body[nxt] in "}]":
                repairs.append(Repair("trailing_comma", i))
            else:
                out.append(char)
            i += 1
        elif char.isalpha() or char == "_":
            j = i
            while j < len(body) and (body[j].isalnum() or body[j] == "_"):
                j += 1
            word = body[i:j]
            if word in _PY_LITERALS:
                repairs.append(Repair("python_literal", i))
                word = _PY_LITERALS[word]
            out.append(word)
            i = j
        else:
            out.append(char)
            i += 1
    return "".join(out), i


def parse_lenient(text: str) -> LenientResult:
    """Parse model output into JSON, logging each repair. Raises LenientJSONError."""
    repairs: list[Repair] = []
    body = text
    fenced = _FENCE.search(text)
    if fenced:
        repairs.append(Repair("markdown_fence", fenced.start()))
        if (text[: fenced.start()] + text[fenced.end() :]).strip():
            repairs.append(Repair("prose", 0))
        body = fenced.group(1)
    start = _find_start(body)
    if start is None:
        raise LenientJSONError("no JSON object found in model output")
    if not fenced and body[:start].strip():
        repairs.append(Repair("prose", 0))
    converted, end = _convert(body, start, repairs)
    if not fenced and body[end:].strip():
        repairs.append(Repair("prose", end))
    try:
        return LenientResult(json.loads(converted), repairs)
    except json.JSONDecodeError as error:
        raise LenientJSONError(f"still not valid JSON after pre-repairs: {error}") from error
