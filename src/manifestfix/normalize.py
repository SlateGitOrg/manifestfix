"""Deterministic clean-up applied to model output before validation.

Normalization only changes representation (units, separators, case). It never changes what a
value means: a container number is upper-cased and stripped of spaces, and its check digit is
left alone.
"""

from __future__ import annotations

import copy
import re
from typing import Any

LB_TO_KG = 0.45359237

# Languages whose usual number format is 1.234,5 (dot thousands, comma decimal).
DECIMAL_COMMA_LANGUAGES = frozenset(
    {"de", "fr", "es", "it", "nl", "pt", "pl", "tr", "ru", "sv", "da", "fi", "nb", "cs", "hu"}
)

_LOCALE_HINT = re.compile(r"\blocale\s*:\s*([A-Za-z]{2})(?:[_-][A-Za-z]{2})?\b", re.IGNORECASE)
_QUANTITY = re.compile(
    r"^\s*(?P<num>[-+]?[\d.,\s]*\d)\s*(?P<unit>kgs?|lbs?|cbm|m3|m³)?\s*$", re.IGNORECASE
)


def detect_decimal_comma(doc_text: str) -> bool:
    """True when the document's locale hint names a decimal-comma language."""
    match = _LOCALE_HINT.search(doc_text)
    return bool(match) and match.group(1).lower() in DECIMAL_COMMA_LANGUAGES


def parse_number(text: str, decimal_comma: bool = False) -> float:
    """Parse `18,230.50` (default) or `18.230,50` (decimal comma) into a float."""
    cleaned = re.sub(r"\s+", "", text)
    if decimal_comma:
        cleaned = cleaned.replace(".", "").replace(",", ".")
    else:
        cleaned = cleaned.replace(",", "")
    try:
        return float(cleaned)
    except ValueError as error:
        raise ValueError(f"not a number: {text!r}") from error


def parse_quantity(text: str, decimal_comma: bool = False) -> tuple[float, str | None]:
    """Split `52,910 LBS` into (52910.0, 'lb'). The unit is None when the text has none."""
    match = _QUANTITY.match(text)
    if not match:
        raise ValueError(f"not a quantity: {text!r}")
    unit = match.group("unit")
    if unit:
        unit = unit.lower()
        unit = "lb" if unit.startswith("lb") else "kg" if unit.startswith("kg") else "cbm"
    return parse_number(match.group("num"), decimal_comma), unit


def to_kg(value: float, unit: str | None) -> float:
    """Convert a weight to kilograms, rounded to 2 decimals."""
    if unit == "lb":
        value = value * LB_TO_KG
    return round(value, 2)


def parse_weight_kg(text: str, decimal_comma: bool = False) -> float:
    """`52,910 LBS` -> 23999.57, `1.234,5 KGS` (decimal comma) -> 1234.5."""
    value, unit = parse_quantity(text, decimal_comma)
    return to_kg(value, unit)


def normalize_container_no(value: str) -> str:
    return re.sub(r"\s+", "", value).upper()


def normalize_hs_code(value: str) -> str:
    return re.sub(r"[^0-9]", "", value)


def _weight(value: Any, decimal_comma: bool) -> Any:
    return parse_weight_kg(value, decimal_comma) if isinstance(value, str) else value


def _volume(value: Any, decimal_comma: bool) -> Any:
    return parse_quantity(value, decimal_comma)[0] if isinstance(value, str) else value


def _count(value: Any, decimal_comma: bool) -> Any:
    if isinstance(value, str):
        return int(parse_number(re.sub(r"[^\d.,\s]", "", value), decimal_comma))
    return value


def _safe(func: Any, value: Any, decimal_comma: bool) -> Any:
    """Apply a parser, leaving the value untouched when it cannot be parsed."""
    try:
        return func(value, decimal_comma)
    except ValueError:
        return value


def normalize_payload(data: Any, decimal_comma: bool = False) -> Any:
    """Return a normalized copy of a parsed manifest dict. Unknown keys pass through."""
    if not isinstance(data, dict):
        return data
    out = copy.deepcopy(data)
    lines = out.get("containers")
    if isinstance(lines, list):
        for line in lines:
            if not isinstance(line, dict):
                continue
            if isinstance(line.get("container_no"), str):
                line["container_no"] = normalize_container_no(line["container_no"])
            if isinstance(line.get("hs_code"), str):
                line["hs_code"] = normalize_hs_code(line["hs_code"])
            for key in ("gross_kg", "net_kg"):
                if key in line:
                    line[key] = _safe(_weight, line[key], decimal_comma)
            if "volume_cbm" in line:
                line["volume_cbm"] = _safe(_volume, line["volume_cbm"], decimal_comma)
            if "packages" in line:
                line["packages"] = _safe(_count, line["packages"], decimal_comma)
    totals = out.get("totals")
    if isinstance(totals, dict):
        if "gross_kg" in totals:
            totals["gross_kg"] = _safe(_weight, totals["gross_kg"], decimal_comma)
        if "volume_cbm" in totals:
            totals["volume_cbm"] = _safe(_volume, totals["volume_cbm"], decimal_comma)
        if "packages" in totals:
            totals["packages"] = _safe(_count, totals["packages"], decimal_comma)
    return out
