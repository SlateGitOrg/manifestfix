"""ISO 6346 container number check digit, implemented from the standard.

A container number is a 3-letter owner code, a category letter (U, J or Z), a 6-digit serial
and a check digit. The check digit is computed as follows:

1. Each of the first ten characters gets a value. Digits keep their value. Letters start at
   A=10 and count upwards, skipping every multiple of 11 (so L=23 and V=34).
2. Each value is multiplied by 2**position, with the first character at position 0.
3. The products are summed, reduced mod 11, and the result mod 10 is the check digit
   (a remainder of 10 becomes 0).
"""

from __future__ import annotations

import re
import string
from dataclasses import dataclass

SHAPE = re.compile(r"^[A-Z]{3}[UJZ][0-9]{7}$")


def _letter_values() -> dict[str, int]:
    values: dict[str, int] = {}
    value = 10
    for letter in string.ascii_uppercase:
        if value % 11 == 0:
            value += 1
        values[letter] = value
        value += 1
    return values


LETTER_VALUES = _letter_values()


@dataclass(frozen=True)
class CheckResult:
    container_no: str
    given: int
    computed: int

    @property
    def valid(self) -> bool:
        return self.given == self.computed


def clean(container_no: str) -> str:
    """Upper-case a container number and drop whitespace."""
    return re.sub(r"\s+", "", container_no).upper()


def compute_check_digit(first_ten: str) -> int:
    """Check digit for the owner code, category letter and serial (10 characters)."""
    first_ten = clean(first_ten)
    if not re.fullmatch(r"[A-Z]{3}[UJZ][0-9]{6}", first_ten):
        raise ValueError(f"expected 3 letters, U/J/Z and 6 digits, got {first_ten!r}")
    total = 0
    for position, char in enumerate(first_ten):
        value = LETTER_VALUES[char] if char.isalpha() else int(char)
        total += value * 2**position
    return total % 11 % 10


def check(container_no: str) -> CheckResult:
    """Compare the given check digit of an 11-character container number with the computed one."""
    number = clean(container_no)
    if not SHAPE.match(number):
        raise ValueError(f"not an ISO 6346 shaped container number: {container_no!r}")
    return CheckResult(number, int(number[10]), compute_check_digit(number[:10]))


def is_valid(container_no: str) -> bool:
    try:
        return check(container_no).valid
    except ValueError:
        return False


def with_check_digit(first_ten: str) -> str:
    """Build a full container number from its first ten characters."""
    first_ten = clean(first_ten)
    return f"{first_ten}{compute_check_digit(first_ten)}"
