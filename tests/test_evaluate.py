from __future__ import annotations

import json

import pytest
from typer.testing import CliRunner

from manifestfix.cli import app
from manifestfix.evaluate import evaluate, predict, score_fields
from manifestfix.repair import CONFIGS

EXPECTED = {
    "schema-only": (230, 70, 0, 320, 300),
    "rules+blind": (210, 0, 90, 480, 210),
    "rules+targeted": (295, 0, 5, 395, 295),
}


@pytest.fixture(scope="module")
def results(dataset):
    return {r.name: r for r in evaluate(list(CONFIGS), dataset)}


@pytest.mark.parametrize("name", list(EXPECTED))
def test_exact_outcomes(results, name):
    correct, silent, review, calls, accepted = EXPECTED[name]
    r = results[name]
    assert (r.accepted_correct, r.silent_errors, r.review, r.calls, r.accepted) == (
        correct,
        silent,
        review,
        calls,
        accepted,
    )


def test_calls_per_accepted_document(results):
    assert round(results["schema-only"].calls_per_accepted, 3) == 1.067
    assert round(results["rules+blind"].calls_per_accepted, 3) == 2.286
    assert round(results["rules+targeted"].calls_per_accepted, 3) == 1.339


def test_rules_bring_silent_errors_to_zero(results):
    assert results["schema-only"].silent_errors == 70
    assert results["rules+blind"].silent_errors == 0
    assert results["rules+targeted"].silent_errors == 0


def test_measured_counts_equal_the_fault_plan_prediction(dataset, results):
    for name, r in results.items():
        e = predict(dataset.plan, len(dataset.docs), name)
        assert (r.accepted_correct, r.silent_errors, r.review, r.calls) == (
            e.accepted_correct,
            e.silent_errors,
            e.review,
            e.calls,
        )


def test_stubborn_transpositions_are_the_only_targeted_review_docs(dataset, results):
    review = [d for d in results["rules+targeted"].docs if d.status == "review"]
    stubborn = {k for k, f in dataset.plan.items() if f.stubborn}
    assert {d.doc_id for d in review} == stubborn
    assert all(d.reasons == ["ISO6346_CHECK_DIGIT"] for d in review)


def test_no_document_exceeds_two_repair_rounds(results):
    assert max(d.rounds for r in results.values() for d in r.docs) == 2
    assert all(d.calls <= 3 for r in results.values() for d in r.docs)


def test_field_accuracy_drops_only_where_silent_errors_live(results):
    schema_only, targeted = results["schema-only"], results["rules+targeted"]
    assert targeted.field_accuracy("containers.container_no") == 1.0
    assert targeted.field_accuracy("containers.gross_kg") == 1.0
    assert schema_only.field_accuracy("containers.container_no") < 1.0
    assert schema_only.field_accuracy("containers.gross_kg") < 1.0
    assert schema_only.field_accuracy("vessel") == 1.0


def test_score_fields_aligns_lines_by_seal(clean):
    import copy

    pred = copy.deepcopy(clean)
    del pred["containers"][0]
    scores = score_fields(pred, clean)
    assert scores["containers.container_no"] == (1, 2)
    assert scores["vessel"] == (1, 1)


def test_eval_cli_end_to_end(tmp_path):
    runner = CliRunner()
    data = tmp_path / "data"
    assert runner.invoke(app, ["seed", "--out", str(data)]).exit_code == 0
    out = tmp_path / "results.json"
    result = runner.invoke(
        app, ["eval", "--configs", "all", "--data", str(data), "--json-out", str(out)]
    )
    assert result.exit_code == 0, result.output
    payload = json.loads(out.read_text())
    assert payload["rules+targeted"]["review"] == 5
    assert payload["schema-only"]["silent_errors"] == 70
    assert "Silent errors" in result.output
