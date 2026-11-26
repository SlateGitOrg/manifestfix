"""Score the three configurations against ground truth.

The scoring separates valid output from correct output. A document is "accepted-correct" when the
accepted manifest equals the ground truth exactly, a "silent error" when it was accepted (it passed
every check that configuration runs) but differs from the truth, and "review" when it was held back.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from manifestfix import faults
from manifestfix.faults import Fault
from manifestfix.generator import Dataset
from manifestfix.model import FakeExtractor
from manifestfix.repair import CONFIGS, Pipeline

HEADER_FIELDS = (
    "bl_number",
    "shipper",
    "consignee",
    "vessel",
    "voyage",
    "port_of_loading",
    "port_of_discharge",
    "incoterm",
)
TOTAL_FIELDS = ("packages", "gross_kg", "volume_cbm")
LINE_FIELDS = (
    "container_no",
    "seal_no",
    "packages",
    "package_type",
    "gross_kg",
    "net_kg",
    "volume_cbm",
    "hs_code",
    "description",
)
FIELD_ORDER = (
    *HEADER_FIELDS,
    *(f"totals.{f}" for f in TOTAL_FIELDS),
    *(f"containers.{f}" for f in LINE_FIELDS),
)


@dataclass
class DocResult:
    doc_id: str
    status: str
    correct: bool
    calls: int
    rounds: int
    reasons: list[str]


@dataclass
class ConfigResult:
    name: str
    docs: list[DocResult] = field(default_factory=list)
    field_hits: dict[str, list[int]] = field(default_factory=dict)  # name -> [hits, total]

    @property
    def accepted_correct(self) -> int:
        return sum(d.status == "accepted" and d.correct for d in self.docs)

    @property
    def silent_errors(self) -> int:
        return sum(d.status == "accepted" and not d.correct for d in self.docs)

    @property
    def review(self) -> int:
        return sum(d.status == "review" for d in self.docs)

    @property
    def calls(self) -> int:
        return sum(d.calls for d in self.docs)

    @property
    def accepted(self) -> int:
        return self.accepted_correct + self.silent_errors

    @property
    def calls_per_accepted(self) -> float:
        return self.calls / self.accepted if self.accepted else float("nan")

    def field_accuracy(self, name: str) -> float:
        hits, total = self.field_hits.get(name, [0, 0])
        return hits / total if total else float("nan")


def score_fields(pred: dict[str, Any], truth: dict[str, Any]) -> dict[str, tuple[int, int]]:
    """Per-field (hits, total) for one accepted document. Container lines are matched to the
    truth by seal number, so a dropped line costs its own fields and nothing else."""
    scores: dict[str, tuple[int, int]] = {}
    for name in HEADER_FIELDS:
        scores[name] = (int(pred.get(name) == truth[name]), 1)
    for name in TOTAL_FIELDS:
        scores[f"totals.{name}"] = (int(pred["totals"].get(name) == truth["totals"][name]), 1)
    by_seal = {line["seal_no"]: line for line in pred["containers"]}
    for name in LINE_FIELDS:
        hits = 0
        for line in truth["containers"]:
            match = by_seal.get(line["seal_no"])
            hits += int(match is not None and match.get(name) == line[name])
        scores[f"containers.{name}"] = (hits, len(truth["containers"]))
    return scores


def run_config(name: str, dataset: Dataset) -> ConfigResult:
    pipeline = Pipeline(FakeExtractor(dataset.plan), CONFIGS[name])
    truth = dataset.truth()
    result = ConfigResult(name, field_hits={f: [0, 0] for f in FIELD_ORDER})
    for doc in dataset.docs:
        outcome = pipeline.run(doc.text)
        correct = outcome.manifest == truth[doc.doc_id]
        reasons = [v.code for v in outcome.reasons]
        status = outcome.status
        result.docs.append(
            DocResult(doc.doc_id, status, correct, outcome.calls, outcome.rounds, reasons)
        )
        if outcome.manifest is not None:
            for fname, (hits, total) in score_fields(outcome.manifest, truth[doc.doc_id]).items():
                result.field_hits[fname][0] += hits
                result.field_hits[fname][1] += total
    return result


def evaluate(names: list[str], dataset: Dataset) -> list[ConfigResult]:
    return [run_config(name, dataset) for name in names]


@dataclass(frozen=True)
class Expected:
    accepted_correct: int
    silent_errors: int
    review: int
    calls: int


def predict(plan: dict[str, Fault], n_docs: int, config: str) -> Expected:
    """Exact outcome counts for a configuration, derived from the fault plan alone.

    Lenient faults are repaired without a model call. A schema fault is caught by every
    configuration. A rule fault is invisible to `schema-only`, never fixed by a blind retry, and
    fixed by one targeted round unless it is stubborn. A document that is not fixed uses
    both repair rounds.
    """
    correct = silent = review = 0
    calls = n_docs
    for fault in plan.values():
        if fault.type in faults.LENIENT_FAULTS:
            correct += 1
        elif fault.type in faults.SCHEMA_FAULTS or fault.type in faults.RULE_FAULTS:
            is_schema = fault.type in faults.SCHEMA_FAULTS
            if config == "schema-only" and not is_schema:
                silent += 1
            elif config == "rules+blind" or fault.stubborn:
                review += 1
                calls += 2
            else:
                correct += 1
                calls += 1
    return Expected(n_docs - len(plan) + correct, silent, review, calls)
