"""The extraction pipeline: model output -> lenient JSON -> normalize -> schema -> rules -> repair.

A failing document gets a repair prompt, a patch from the model and a frozen-field merge, for at
most `MAX_ROUNDS` rounds. A document that still fails goes to the review queue with its reasons.
The pipeline never computes a check digit to "fix" a container number; it only asks the model to
re-read the document.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any

from manifestfix.lenient_json import LenientJSONError, parse_lenient
from manifestfix.model import ExtractionModel
from manifestfix.normalize import detect_decimal_comma, normalize_payload
from manifestfix.patch import merge_frozen
from manifestfix.rules import check_rules
from manifestfix.schema import Violation, validate_manifest

MAX_ROUNDS = 2
BLIND_PROMPT = "The output was invalid. Try again and return the corrected JSON."

_CONTAINER_NO = re.compile(r"\b([A-Za-z]{3}[UuJjZz])\s?(\d{7})\b")
_CONTAINER_HEADER = re.compile(r"^\s*Container\s*#?\s*\d+\s*$")
_TOTALS_LINE = re.compile(r"\btotals?\b", re.IGNORECASE)
_FIELD_WORDS = {
    "incoterm": ("incoterm", "terms"),
    "bl_number": ("b/l", "bl number", "bill of lading"),
    "port_of_loading": ("loading",),
    "port_of_discharge": ("discharge",),
    "voyage": ("voyage", "vessel"),
}


@dataclass(frozen=True)
class Config:
    """Which checks and which repair prompt a run uses."""

    name: str
    rules: bool
    targeted: bool


CONFIGS = {
    "schema-only": Config("schema-only", rules=False, targeted=True),
    "rules+blind": Config("rules+blind", rules=True, targeted=False),
    "rules+targeted": Config("rules+targeted", rules=True, targeted=True),
}


@dataclass
class Outcome:
    status: str  # "accepted" or "review"
    manifest: dict[str, Any] | None
    calls: int
    rounds: int
    reasons: list[Violation] = field(default_factory=list)
    prompts: list[str] = field(default_factory=list)
    patches: list[str] = field(default_factory=list)
    trace: list[str] = field(default_factory=list)
    lenient_repairs: list[str] = field(default_factory=list)


def _container_lines(doc_lines: list[str]) -> list[tuple[int, str]]:
    found = []
    for i, line in enumerate(doc_lines):
        match = _CONTAINER_NO.search(line)
        if match:
            found.append((i, (match.group(1) + match.group(2)).upper()))
    return found


def _block(doc_lines: list[str], i: int) -> list[int]:
    """The line at i plus the indented detail lines that belong to it (bill of lading layout)."""
    start = i - 1 if i > 0 and _CONTAINER_HEADER.match(doc_lines[i - 1]) else i
    end = i
    while end + 1 < len(doc_lines) and doc_lines[end + 1].startswith("  "):
        end += 1
    return list(range(start, end + 1))


def _lines_for_container(doc_lines: list[str], index: int, number: str | None) -> list[int]:
    found = _container_lines(doc_lines)
    exact = [i for i, no in found if no == number]
    if not exact and number:
        # A transposed number still shares its prefix and digits with the printed one.
        exact = [
            i for i, no in found if no[:4] == number[:4] and sorted(no[4:]) == sorted(number[4:])
        ]
    if not exact and index < len(found):
        exact = [found[index][0]]
    return [n for i in exact for n in _block(doc_lines, i)]


def relevant_lines(doc_text: str, violations: list[Violation], data: Any) -> list[str]:
    """Document lines that mention the affected containers or totals, in document order."""
    doc_lines = doc_text.splitlines()
    chosen: set[int] = set()
    containers = data.get("containers") if isinstance(data, dict) else None
    for v in violations:
        container = re.match(r"containers\[(\d+)\]", v.path)
        if container:
            index = int(container.group(1))
            number = None
            if isinstance(containers, list) and index < len(containers):
                line = containers[index]
                number = line.get("container_no") if isinstance(line, dict) else None
            chosen.update(_lines_for_container(doc_lines, index, number))
        elif v.path == "containers" or v.path.startswith("totals"):
            chosen.update(i for i, text in enumerate(doc_lines) if _TOTALS_LINE.search(text))
            for i, _ in _container_lines(doc_lines):
                chosen.update(_block(doc_lines, i))
        elif v.kind == "rule" or v.code in ("SCHEMA_ENUM", "SCHEMA_MISSING"):
            words = _FIELD_WORDS.get(v.path, (v.path.replace("_", " "),))
            chosen.update(
                i for i, text in enumerate(doc_lines) if any(w in text.lower() for w in words)
            )
    return [doc_lines[i] for i in sorted(chosen) if doc_lines[i].strip()]


def build_targeted_prompt(violations: list[Violation], doc_text: str, data: Any) -> str:
    """List only the failed checks, with their paths, plus the document lines that matter."""
    lines = [
        "The previous extraction failed validation. Correct only the failures listed below. "
        "Every other field is frozen and any change to it is discarded.",
        'Reply with a JSON object {"patch": [{"op": "replace" or "remove", "path": "<path>", '
        '"value": <value>}]} that edits only the listed paths. Re-read the document; do not '
        "guess.",
        "",
        "Failures:",
    ]
    lines += [f"- {v.code} at {v.path}: {v.message}" for v in violations]
    excerpt = relevant_lines(doc_text, violations, data)
    if excerpt:
        lines += ["", "Document lines:"] + [f"> {text}" for text in excerpt]
    return "\n".join(lines)


class Pipeline:
    """Run one document through extraction, checks and bounded repair."""

    def __init__(self, model: ExtractionModel, config: Config, max_rounds: int = MAX_ROUNDS):
        self.model = model
        self.config = config
        self.max_rounds = max_rounds

    def _check(self, data: Any, hint: bool) -> tuple[Any, list[Violation]]:
        data = normalize_payload(data, hint)
        manifest, violations = validate_manifest(data)
        if manifest is not None and self.config.rules:
            violations = check_rules(manifest)
        return data, violations

    def _parse(self, raw: str, out: Outcome) -> Any:
        result = parse_lenient(raw)
        for repair in result.repairs:
            out.lenient_repairs.append(str(repair))
        if result.repairs:
            out.trace.append("lenient JSON repairs: " + ", ".join(sorted(set(result.kinds))))
        return result.data

    def run(self, doc_text: str) -> Outcome:
        hint = detect_decimal_comma(doc_text)
        out = Outcome("review", None, calls=1, rounds=0)
        raw = self.model.extract(doc_text)
        out.trace.append("model call 1: extract")
        data: Any = None
        try:
            data, violations = self._check(self._parse(raw, out), hint)
        except LenientJSONError as error:
            violations = [Violation("JSON_PARSE", "$", str(error), "parse")]
        while violations and out.rounds < self.max_rounds:
            out.trace.append("failed: " + ", ".join(f"{v.code} at {v.path}" for v in violations))
            prompt = (
                build_targeted_prompt(violations, doc_text, data)
                if self.config.targeted
                else BLIND_PROMPT
            )
            out.prompts.append(prompt)
            current = json.dumps(data) if data is not None else ""
            response = self.model.repair(doc_text, current, prompt)
            out.calls += 1
            out.rounds += 1
            out.patches.append(response)
            out.trace.append(f"model call {out.calls}: repair round {out.rounds}")
            allowed = {v.path for v in violations} if self.config.targeted else {"$"}
            try:
                merged = merge_frozen(data, self._parse(response, out), allowed)
            except LenientJSONError:
                out.trace.append("repair response was not parseable; no change")
                continue
            if merged.rejected:
                out.trace.append(
                    "discarded edits outside the failed paths: " + str(merged.rejected)
                )
            data, violations = self._check(merged.data, hint)
        out.reasons = violations
        if not violations:
            manifest, _ = validate_manifest(data)
            out.status = "accepted"
            out.manifest = manifest.model_dump(mode="json") if manifest else None
            out.trace.append("accepted")
        else:
            out.trace.append("sent to review: " + ", ".join(v.code for v in violations))
        return out
