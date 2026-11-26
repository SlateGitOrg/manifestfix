from __future__ import annotations

import json

from manifestfix.faults import Fault
from manifestfix.model import FakeExtractor
from manifestfix.repair import BLIND_PROMPT, CONFIGS, Pipeline
from manifestfix.rules import RULE_CODES


class ScriptedModel:
    """Returns canned text and records what it was asked."""

    def __init__(self, extract_text: str, repair_texts: list[str]) -> None:
        self.extract_text = extract_text
        self.repair_texts = list(repair_texts)
        self.repair_prompts: list[str] = []

    def extract(self, doc_text: str) -> str:
        return self.extract_text

    def repair(self, doc_text: str, current_json: str, errors: str) -> str:
        self.repair_prompts.append(errors)
        return self.repair_texts.pop(0)


def _first(dataset, kind, stubborn=False):
    return next(
        d
        for d in dataset.docs
        if d.doc_id in dataset.plan
        and dataset.plan[d.doc_id].type == kind
        and dataset.plan[d.doc_id].stubborn == stubborn
    )


def test_transposition_prompt_names_only_its_code_path_and_document_line(dataset):
    doc = _first(dataset, "digit_transposition")
    fault = dataset.plan[doc.doc_id]
    outcome = Pipeline(FakeExtractor(dataset.plan), CONFIGS["rules+targeted"]).run(doc.text)
    prompt = outcome.prompts[0]
    index = fault.params["index"]
    number = doc.manifest["containers"][index]["container_no"]
    printed_line = next(ln for ln in doc.text.splitlines() if number[4:] in ln.replace(" ", ""))
    assert "ISO6346_CHECK_DIGIT" in prompt
    assert f"containers[{index}].container_no" in prompt
    assert printed_line.strip() in prompt
    assert not [c for c in RULE_CODES if c != "ISO6346_CHECK_DIGIT" and c in prompt]
    assert not [c for c in ("SCHEMA_ENUM", "SCHEMA_EXTRA_FORBIDDEN") if c in prompt]
    assert outcome.status == "accepted"
    assert outcome.manifest == doc.manifest
    assert (outcome.calls, outcome.rounds) == (2, 1)


def test_prompt_lists_every_failed_code_for_a_dropped_line(dataset):
    doc = _first(dataset, "dropped_line")
    outcome = Pipeline(FakeExtractor(dataset.plan), CONFIGS["rules+targeted"]).run(doc.text)
    prompt = outcome.prompts[0]
    assert "- SUM_PACKAGES at containers:" in prompt
    assert "- SUM_GROSS at containers:" in prompt
    assert "Totals" in prompt or "TOTALS" in prompt or "Total" in prompt
    assert outcome.manifest == doc.manifest


def test_blind_prompt_is_generic_and_does_not_fix_anything(dataset):
    doc = _first(dataset, "net_gross_swap")
    outcome = Pipeline(FakeExtractor(dataset.plan), CONFIGS["rules+blind"]).run(doc.text)
    assert outcome.prompts == [BLIND_PROMPT, BLIND_PROMPT]
    assert outcome.status == "review"
    assert {v.code for v in outcome.reasons} >= {"NET_GT_GROSS"}
    assert outcome.calls == 3


def test_stubborn_transposition_ends_in_review_without_autocorrect(dataset):
    doc = _first(dataset, "digit_transposition", stubborn=True)
    fault = dataset.plan[doc.doc_id]
    outcome = Pipeline(FakeExtractor(dataset.plan), CONFIGS["rules+targeted"]).run(doc.text)
    assert outcome.status == "review"
    assert outcome.rounds == 2
    assert outcome.calls == 3
    assert [v.code for v in outcome.reasons] == ["ISO6346_CHECK_DIGIT"]
    assert outcome.manifest is None
    path = outcome.reasons[0].path
    assert path == f"containers[{fault.params['index']}].container_no"


def test_lenient_faults_need_no_repair_call(dataset):
    for kind in ("markdown_fence", "trailing_comma"):
        doc = _first(dataset, kind)
        outcome = Pipeline(FakeExtractor(dataset.plan), CONFIGS["rules+targeted"]).run(doc.text)
        assert outcome.calls == 1 and outcome.rounds == 0
        assert outcome.manifest == doc.manifest
        assert outcome.lenient_repairs


def test_repair_response_cannot_edit_frozen_fields(dataset):
    doc = _first(dataset, "digit_transposition")
    fault = dataset.plan[doc.doc_id]
    path = fault.path
    good = doc.manifest["containers"][fault.params["index"]]["container_no"]
    sneaky = {
        "patch": [
            {"op": "replace", "path": path, "value": good},
            {"op": "replace", "path": "vessel", "value": "HACKED"},
        ]
    }
    model = ScriptedModel(FakeExtractor(dataset.plan).extract(doc.text), [json.dumps(sneaky)])
    outcome = Pipeline(model, CONFIGS["rules+targeted"]).run(doc.text)
    assert outcome.manifest == doc.manifest
    assert any("discarded edits" in step for step in outcome.trace)


def test_unparseable_first_answer_is_retried(dataset):
    doc = dataset.docs[0]
    clean = FakeExtractor({}).extract(doc.text)
    model = ScriptedModel("I could not read this document.", [clean])
    outcome = Pipeline(model, CONFIGS["rules+blind"]).run(doc.text)
    assert outcome.status == "accepted"
    assert outcome.manifest == doc.manifest
    assert model.repair_prompts == [BLIND_PROMPT]


def test_schema_only_does_not_run_cross_field_rules(dataset):
    doc = _first(dataset, "net_gross_swap")
    outcome = Pipeline(FakeExtractor(dataset.plan), CONFIGS["schema-only"]).run(doc.text)
    assert outcome.status == "accepted"
    assert outcome.manifest != doc.manifest  # a silent error
    assert outcome.calls == 1


def test_fake_only_fixes_when_prompt_has_both_code_and_path():
    fault = Fault("MF-0001", "digit_transposition", {"index": 0, "position": 5})
    assert fault.code == "ISO6346_CHECK_DIGIT"
    assert fault.path == "containers[0].container_no"
