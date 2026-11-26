import pytest

from manifestfix.normalize import (
    detect_decimal_comma,
    normalize_container_no,
    normalize_payload,
    parse_number,
    parse_weight_kg,
)


def test_pounds_convert_to_kilograms_two_decimals():
    assert parse_weight_kg("52,910 LBS") == 23999.57


def test_decimal_comma_with_hint():
    assert parse_weight_kg("1.234,5 KGS", decimal_comma=True) == 1234.5
    assert parse_number("1.234,5", decimal_comma=True) == 1234.5
    assert parse_number("1,234.5") == 1234.5


def test_locale_hint_detection():
    assert detect_decimal_comma("File ref: MF-1\nLocale: de_DE\n")
    assert detect_decimal_comma("locale: fr-FR")
    assert not detect_decimal_comma("Locale: en_US")
    assert not detect_decimal_comma("no hint at all")


def test_container_numbers_are_uppercased_and_stripped():
    assert normalize_container_no("csqu 3054383") == "CSQU3054383"


def test_payload_normalization_converts_string_weights_and_keeps_unknown_keys(clean):
    clean["containers"][0]["container_no"] = "csqu 3054383"
    clean["containers"][0]["gross_kg"] = "39,683 LBS"
    clean["containers"][0]["hs_code"] = "8501.10"
    clean["containers"][0]["extra"] = "kept"
    out = normalize_payload(clean)
    line = out["containers"][0]
    assert line["container_no"] == "CSQU3054383"
    assert line["gross_kg"] == round(39683 * 0.45359237, 2)
    assert line["hs_code"] == "850110"
    assert line["extra"] == "kept"
    assert clean["containers"][0]["hs_code"] == "8501.10"  # input is not mutated


def test_unparseable_value_is_left_for_the_schema_to_reject(clean):
    clean["totals"]["gross_kg"] = "heavy"
    assert normalize_payload(clean)["totals"]["gross_kg"] == "heavy"


def test_non_numeric_quantity_raises():
    with pytest.raises(ValueError):
        parse_weight_kg("n/a")
