from __future__ import annotations

from collections import Counter

from manifestfix import iso6346
from manifestfix.faults import transposition_changes_check_digit
from manifestfix.generator import generate_dataset, load_dataset, write_dataset
from manifestfix.layouts import parse_document
from manifestfix.normalize import detect_decimal_comma, normalize_payload
from manifestfix.rules import check_rules
from manifestfix.schema import validate_manifest


def test_dataset_shape(dataset):
    assert len(dataset.docs) == 300
    lines = sum(len(d.manifest["containers"]) for d in dataset.docs)
    assert 900 <= lines <= 1200
    assert all(1 <= len(d.manifest["containers"]) <= 6 for d in dataset.docs)
    assert Counter(d.layout for d in dataset.docs) == {"table": 100, "email": 100, "bol": 100}
    assert sum(d.unit == "lb" for d in dataset.docs) == 90
    assert sum(d.decimal_comma for d in dataset.docs) == 45


def test_every_generated_container_number_is_valid(dataset):
    for doc in dataset.docs:
        for line in doc.manifest["containers"]:
            assert iso6346.check(line["container_no"]).valid


def test_fault_plan_counts(dataset):
    counts = Counter(f.type for f in dataset.plan.values())
    assert counts == {
        "markdown_fence": 13,
        "trailing_comma": 12,
        "lb_not_converted": 20,
        "digit_transposition": 20,
        "dropped_line": 15,
        "net_gross_swap": 15,
        "extra_field": 10,
        "bad_incoterm": 10,
    }
    assert len(dataset.plan) == 115
    stubborn = [f for f in dataset.plan.values() if f.stubborn]
    assert len(stubborn) == 5 and {f.type for f in stubborn} == {"digit_transposition"}


def test_planned_transpositions_really_change_the_check_digit(dataset):
    for doc in dataset.docs:
        fault = dataset.plan.get(doc.doc_id)
        if fault and fault.type == "digit_transposition":
            number = doc.manifest["containers"][fault.params["index"]]["container_no"]
            assert transposition_changes_check_digit(number, fault.params["position"])


def test_lb_faults_only_on_lb_documents_and_drops_need_two_lines(dataset):
    by_id = {d.doc_id: d for d in dataset.docs}
    for fault in dataset.plan.values():
        if fault.type == "lb_not_converted":
            assert by_id[fault.doc_id].unit == "lb"
        if fault.type == "dropped_line":
            assert len(by_id[fault.doc_id].manifest["containers"]) >= 2


def test_lb_documents_state_both_units_in_the_totals_line(dataset):
    doc = next(d for d in dataset.docs if d.unit == "lb" and not d.decimal_comma)
    assert " LBS (" in doc.text or " lbs (" in doc.text


def test_parsers_recover_ground_truth_and_clean_docs_pass_every_check(dataset):
    for doc in dataset.docs:
        raw = parse_document(doc.text)
        data = normalize_payload(raw, detect_decimal_comma(doc.text))
        assert data == doc.manifest, doc.doc_id
        manifest, schema_violations = validate_manifest(data)
        assert schema_violations == []
        assert check_rules(manifest) == [], doc.doc_id


def test_same_seed_same_documents_and_ground_truth(dataset, tmp_path):
    again = generate_dataset(seed=7, count=300)
    assert again.texts() == dataset.texts()
    assert again.truth() == dataset.truth()
    assert {k: (f.type, f.params, f.stubborn) for k, f in again.plan.items()} == {
        k: (f.type, f.params, f.stubborn) for k, f in dataset.plan.items()
    }
    other = generate_dataset(seed=8, count=300)
    assert other.texts() != dataset.texts()


def test_write_and_load_round_trip(tmp_path):
    small = generate_dataset(seed=3, count=30)
    write_dataset(small, tmp_path)
    loaded = load_dataset(tmp_path)
    assert loaded.texts() == small.texts()
    assert loaded.truth() == small.truth()
    assert {k: f.type for k, f in loaded.plan.items()} == {k: f.type for k, f in small.plan.items()}
    assert (tmp_path / "fault_plan.yaml").read_text().count("code:") == len(small.plan)
