import pytest
from typer.testing import CliRunner

from manifestfix import iso6346
from manifestfix.cli import app


def test_published_example_is_valid():
    result = iso6346.check("CSQU3054383")
    assert result.valid
    assert result.computed == 3


def test_transposed_example_is_invalid_with_computed_digit_one():
    result = iso6346.check("CSQU3045383")
    assert not result.valid
    assert result.given == 3
    assert result.computed == 1


def test_letter_values_skip_multiples_of_eleven():
    values = iso6346.LETTER_VALUES
    assert values["A"] == 10
    assert values["K"] == 21
    assert values["L"] == 23
    assert values["U"] == 32
    assert values["V"] == 34
    assert values["Z"] == 38
    assert all(v % 11 != 0 for v in values.values())


def test_remainder_of_ten_becomes_zero():
    # Search for a serial whose weighted sum is 10 mod 11 and confirm the digit is 0.
    for serial in range(1000):
        first_ten = f"ABCU{serial:06d}"
        total = sum(
            (iso6346.LETTER_VALUES[c] if c.isalpha() else int(c)) * 2**i
            for i, c in enumerate(first_ten)
        )
        if total % 11 == 10:
            assert iso6346.compute_check_digit(first_ten) == 0
            return
    pytest.fail("no serial with remainder 10 found")


def test_spaces_and_case_are_ignored():
    assert iso6346.is_valid("csqu 3054383")


def test_bad_shape_raises():
    with pytest.raises(ValueError):
        iso6346.check("CSQX3054383")
    assert not iso6346.is_valid("12345")


def test_cli_check_digit_exit_codes():
    runner = CliRunner()
    ok = runner.invoke(app, ["check-digit", "CSQU3054383"])
    assert ok.exit_code == 0 and "valid" in ok.output
    bad = runner.invoke(app, ["check-digit", "CSQU3045383"])
    assert bad.exit_code == 1
    assert "computed 1" in bad.output
