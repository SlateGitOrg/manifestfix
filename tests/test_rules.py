from __future__ import annotations

import copy

import pytest

from manifestfix.rules import RULE_CODES, check_rules
from manifestfix.schema import Manifest, validate_manifest


def codes(data) -> set[str]:
    manifest = Manifest.model_validate(data)
    return {v.code for v in check_rules(manifest)}


def test_clean_fixture_fires_no_rule(clean_manifest):
    assert check_rules(clean_manifest) == []


def _iso(d):
    d["containers"][1]["container_no"] = "MSCU1234565"


def _net(d):
    d["containers"][0]["net_kg"] = 18100.0


def _packages(d):
    d["totals"]["packages"] = 301


def _gross(d):
    d["totals"]["gross_kg"] = 30300.0  # 1% off


def _volume(d):
    d["totals"]["volume_cbm"] = 51.0


def _locode(d):
    d["port_of_discharge"] = "ZZXXX"


def _hs(d):
    d["containers"][0]["hs_code"] = "85011"


def _dup(d):
    d["containers"][1]["container_no"] = d["containers"][0]["container_no"]


def _over(d):
    d["containers"][0]["gross_kg"] = 30500.0
    d["totals"]["gross_kg"] = 42500.0


CASES = [
    ("ISO6346_CHECK_DIGIT", _iso),
    ("NET_GT_GROSS", _net),
    ("SUM_PACKAGES", _packages),
    ("SUM_GROSS", _gross),
    ("SUM_VOLUME", _volume),
    ("UNLOCODE_UNKNOWN", _locode),
    ("HS_CODE_FORMAT", _hs),
    ("DUPLICATE_CONTAINER", _dup),
    ("GROSS_OVER_MAX", _over),
]


@pytest.mark.parametrize(("code", "mutate"), CASES)
def test_each_rule_fires_alone(clean, code, mutate):
    mutate(clean)
    assert codes(clean) == {code}


def test_every_rule_code_is_covered():
    assert {code for code, _ in CASES} == set(RULE_CODES)


def test_violation_paths_point_at_the_field(clean):
    _iso(clean)
    (violation,) = check_rules(Manifest.model_validate(clean))
    assert violation.path == "containers[1].container_no"
    clean2 = copy.deepcopy(clean)
    _locode(clean2)
    paths = {v.path for v in check_rules(Manifest.model_validate(clean2))}
    assert "port_of_discharge" in paths


def test_gross_sum_tolerance_is_half_a_percent(clean):
    clean["totals"]["gross_kg"] = 30000.0 * 1.004
    assert codes(clean) == set()
    clean["totals"]["gross_kg"] = 30000.0 * 1.006
    assert codes(clean) == {"SUM_GROSS"}


def test_extra_field_and_bad_incoterm_are_schema_violations(clean):
    clean["notes"] = "x"
    clean["containers"][0]["temperature_c"] = 18
    clean["incoterm"] = "DDT"
    _, violations = validate_manifest(clean)
    found = {(v.code, v.path) for v in violations}
    assert ("SCHEMA_EXTRA_FORBIDDEN", "notes") in found
    assert ("SCHEMA_EXTRA_FORBIDDEN", "containers[0].temperature_c") in found
    assert ("SCHEMA_ENUM", "incoterm") in found
