"""Fault types injected by the offline model, and the fault plan that assigns them to documents.

Each fault type declares the rule code and JSON path that identify it. The offline model repairs
a fault only when a repair prompt names both, which is what makes targeted prompts measurably
better than a blind "try again".
"""

from __future__ import annotations

import copy
import json
import random
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml

from manifestfix import iso6346
from manifestfix.layouts import lb_of

LENIENT_FAULTS = ("markdown_fence", "trailing_comma")
SCHEMA_FAULTS = ("extra_field", "bad_incoterm")
RULE_FAULTS = ("lb_not_converted", "digit_transposition", "dropped_line", "net_gross_swap")
FAULT_TYPES = LENIENT_FAULTS + SCHEMA_FAULTS + RULE_FAULTS

# Documents per fault type for the default 300-document dataset.
DEFAULT_COUNTS = {
    "markdown_fence": 13,
    "trailing_comma": 12,
    "lb_not_converted": 20,
    "digit_transposition": 20,
    "dropped_line": 15,
    "net_gross_swap": 15,
    "extra_field": 10,
    "bad_incoterm": 10,
}
INVALID_INCOTERMS = ("FREE ON BOARD", "FOB SHANGHAI", "DDT", "C&F", "CNF", "DEP")


@dataclass
class Fault:
    doc_id: str
    type: str
    params: dict[str, Any] = field(default_factory=dict)
    stubborn: bool = False

    @property
    def code(self) -> str:
        return identify(self)[0]

    @property
    def path(self) -> str:
        return identify(self)[1]


def identify(fault: Fault) -> tuple[str, str]:
    """The (rule code, JSON path) pair that points at this fault."""
    kind, p = fault.type, fault.params
    if kind in LENIENT_FAULTS:
        return "LENIENT_JSON", "$"
    if kind == "lb_not_converted":
        return "SUM_GROSS", "containers"
    if kind == "digit_transposition":
        return "ISO6346_CHECK_DIGIT", f"containers[{p['index']}].container_no"
    if kind == "dropped_line":
        return "SUM_PACKAGES", "containers"
    if kind == "net_gross_swap":
        return "NET_GT_GROSS", f"containers[{p['index']}]"
    if kind == "extra_field":
        return "SCHEMA_EXTRA_FORBIDDEN", p["path"]
    if kind == "bad_incoterm":
        return "SCHEMA_ENUM", "incoterm"
    raise ValueError(f"unknown fault type {kind!r}")


def transpose(container_no: str, position: int) -> str:
    chars = list(container_no)
    chars[position], chars[position + 1] = chars[position + 1], chars[position]
    return "".join(chars)


def transposition_changes_check_digit(container_no: str, position: int) -> bool:
    """True when swapping two adjacent digits leaves a number that fails the ISO 6346 test."""
    swapped = transpose(container_no, position)
    return swapped != container_no and not iso6346.is_valid(swapped)


def faulty_payload(fault: Fault, clean: dict[str, Any]) -> dict[str, Any]:
    """The clean extraction with this fault applied."""
    out = copy.deepcopy(clean)
    kind, p = fault.type, fault.params
    if kind == "lb_not_converted":
        for line in out["containers"]:
            line["gross_kg"] = lb_of(line["gross_kg"])
            line["net_kg"] = lb_of(line["net_kg"])
    elif kind == "digit_transposition":
        line = out["containers"][p["index"]]
        number = iso6346.clean(line["container_no"])
        line["container_no"] = transpose(number, p["position"])
    elif kind == "dropped_line":
        del out["containers"][p["index"]]
    elif kind == "net_gross_swap":
        line = out["containers"][p["index"]]
        line["gross_kg"], line["net_kg"] = line["net_kg"], line["gross_kg"]
    elif kind == "extra_field":
        target = out
        if p["path"].startswith("containers["):
            target = out["containers"][p["index"]]
        target[p["path"].rsplit(".", 1)[-1]] = p["value"]
    elif kind == "bad_incoterm":
        out["incoterm"] = p["value"]
    return out


def render_output(fault: Fault | None, payload: dict[str, Any]) -> str:
    """Serialize a payload as model text, adding the formatting faults when the plan asks."""
    text = json.dumps(payload, indent=2)
    if fault is None:
        return text
    if fault.type == "markdown_fence":
        return f"Here is the extracted manifest:\n\n```json\n{text}\n```\n\nAnything else?"
    if fault.type == "trailing_comma":
        lines = text.split("\n")
        for i in range(len(lines) - 1):
            closes_next = lines[i + 1].lstrip().startswith(("}", "]"))
            if closes_next and not lines[i].rstrip().endswith(("{", "[", ",")):
                lines[i] += ","
        return "\n".join(lines)
    return text


def fix_ops(fault: Fault, clean: dict[str, Any]) -> list[dict[str, Any]]:
    """Patch operations that undo this fault, taken from the clean extraction."""
    kind, p = fault.type, fault.params
    if kind in ("lb_not_converted", "dropped_line"):
        return [{"op": "replace", "path": "containers", "value": clean["containers"]}]
    if kind == "digit_transposition":
        number = iso6346.clean(clean["containers"][p["index"]]["container_no"])
        return [{"op": "replace", "path": identify(fault)[1], "value": number}]
    if kind == "net_gross_swap":
        line = clean["containers"][p["index"]]
        return [{"op": "replace", "path": f"containers[{p['index']}]", "value": line}]
    if kind == "extra_field":
        return [{"op": "remove", "path": p["path"]}]
    if kind == "bad_incoterm":
        return [{"op": "replace", "path": "incoterm", "value": clean["incoterm"]}]
    return []


def plan_faults(
    rng: random.Random, docs: list[Any], counts: dict[str, int] | None = None
) -> dict[str, Fault]:
    """Assign at most one fault per document. `docs` are SynthDoc-like (id, unit, manifest)."""
    counts = counts or DEFAULT_COUNTS
    free = {d.doc_id: d for d in docs}
    plan: dict[str, Fault] = {}

    def take(n: int, eligible: Any) -> list[Any]:
        pool = [d for d in docs if d.doc_id in free and eligible(d)]
        chosen = rng.sample(pool, n)
        for d in chosen:
            del free[d.doc_id]
        return chosen

    for d in take(counts["lb_not_converted"], lambda d: d.unit == "lb"):
        plan[d.doc_id] = Fault(d.doc_id, "lb_not_converted")

    def has_two_lines(d: Any) -> bool:
        return len(d.manifest["containers"]) >= 2

    for d in take(counts["dropped_line"], has_two_lines):
        index = rng.randrange(len(d.manifest["containers"]))
        plan[d.doc_id] = Fault(d.doc_id, "dropped_line", {"index": index})
    transposed = take(counts["digit_transposition"], lambda d: True)
    stubborn_ids = {d.doc_id for d in rng.sample(transposed, len(transposed) // 4)}
    for d in transposed:
        lines = d.manifest["containers"]
        existing = {c["container_no"] for c in lines}
        options = [
            (i, pos)
            for i, c in enumerate(lines)
            for pos in range(4, 10)
            if transposition_changes_check_digit(c["container_no"], pos)
            and transpose(c["container_no"], pos) not in existing
        ]
        index, position = rng.choice(options)
        params = {"index": index, "position": position}
        plan[d.doc_id] = Fault(d.doc_id, "digit_transposition", params, d.doc_id in stubborn_ids)
    for d in take(counts["net_gross_swap"], lambda d: True):
        index = rng.randrange(len(d.manifest["containers"]))
        plan[d.doc_id] = Fault(d.doc_id, "net_gross_swap", {"index": index})
    for n, d in enumerate(take(counts["extra_field"], lambda d: True)):
        if n % 2 == 0:
            params = {"path": "notes", "value": "Handle with care"}
        else:
            index = rng.randrange(len(d.manifest["containers"]))
            path = f"containers[{index}].temperature_c"
            params = {"path": path, "index": index, "value": 18}
        plan[d.doc_id] = Fault(d.doc_id, "extra_field", params)
    for d in take(counts["bad_incoterm"], lambda d: True):
        value = rng.choice(INVALID_INCOTERMS)
        plan[d.doc_id] = Fault(d.doc_id, "bad_incoterm", {"value": value})
    for kind in LENIENT_FAULTS:
        for d in take(counts[kind], lambda d: True):
            plan[d.doc_id] = Fault(d.doc_id, kind)
    return plan


def save_plan(plan: dict[str, Fault], path: Path) -> None:
    entries = {}
    for doc_id in sorted(plan):
        fault = plan[doc_id]
        code, json_path = identify(fault)
        entries[doc_id] = {
            "type": fault.type,
            "code": code,
            "path": json_path,
            "stubborn": fault.stubborn,
            "params": fault.params,
        }
    path.write_text(yaml.safe_dump({"version": 1, "faults": entries}, sort_keys=False))


def load_plan(path: Path) -> dict[str, Fault]:
    raw = yaml.safe_load(path.read_text())
    return {
        doc_id: Fault(doc_id, e["type"], e.get("params") or {}, bool(e.get("stubborn")))
        for doc_id, e in (raw.get("faults") or {}).items()
    }
