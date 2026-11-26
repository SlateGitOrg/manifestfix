"""Cross-field rules. Each violation carries a stable code and the JSON path to re-examine.

These catch output that is valid against the schema and still wrong: a mistyped container number,
a net weight above gross, a dropped container line, weights left in the wrong unit.
"""

from __future__ import annotations

import re
from collections.abc import Callable

from manifestfix import iso6346
from manifestfix.schema import Manifest, Violation
from manifestfix.unlocode import UNLOCODES

MAX_GROSS_KG = 30_480.0
SUM_TOLERANCE = 0.005  # relative, for weight and volume sums
HS_CODE = re.compile(r"^[0-9]{6,10}$")

RULE_CODES = (
    "ISO6346_CHECK_DIGIT",
    "NET_GT_GROSS",
    "SUM_PACKAGES",
    "SUM_GROSS",
    "SUM_VOLUME",
    "UNLOCODE_UNKNOWN",
    "HS_CODE_FORMAT",
    "DUPLICATE_CONTAINER",
    "GROSS_OVER_MAX",
)


def _iso6346(m: Manifest) -> list[Violation]:
    found = []
    for i, line in enumerate(m.containers):
        result = iso6346.check(line.container_no)
        if not result.valid:
            msg = f"container number {line.container_no} fails the ISO 6346 check digit test"
            found.append(Violation("ISO6346_CHECK_DIGIT", f"containers[{i}].container_no", msg))
    return found


def _net_gt_gross(m: Manifest) -> list[Violation]:
    return [
        Violation(
            "NET_GT_GROSS",
            f"containers[{i}]",
            f"net weight {line.net_kg} kg is above gross weight {line.gross_kg} kg",
        )
        for i, line in enumerate(m.containers)
        if line.net_kg > line.gross_kg
    ]


def _sum_packages(m: Manifest) -> list[Violation]:
    total = sum(line.packages for line in m.containers)
    if total == m.totals.packages:
        return []
    msg = (
        f"container lines add up to {total} packages but the document total is {m.totals.packages}"
    )
    return [Violation("SUM_PACKAGES", "containers", msg)]


def _sum_gross(m: Manifest) -> list[Violation]:
    total = sum(line.gross_kg for line in m.containers)
    if abs(total - m.totals.gross_kg) <= SUM_TOLERANCE * m.totals.gross_kg:
        return []
    msg = (
        f"container lines add up to {total:.2f} kg gross but the document total is "
        f"{m.totals.gross_kg:.2f} kg"
    )
    return [Violation("SUM_GROSS", "containers", msg)]


def _sum_volume(m: Manifest) -> list[Violation]:
    total = sum(line.volume_cbm for line in m.containers)
    if abs(total - m.totals.volume_cbm) <= max(SUM_TOLERANCE * m.totals.volume_cbm, 0.011):
        return []
    msg = (
        f"container lines add up to {total:.2f} cbm but the document total is "
        f"{m.totals.volume_cbm:.2f} cbm"
    )
    return [Violation("SUM_VOLUME", "containers", msg)]


def _unlocode(m: Manifest) -> list[Violation]:
    found = []
    for field in ("port_of_loading", "port_of_discharge"):
        code = getattr(m, field)
        if code not in UNLOCODES:
            found.append(Violation("UNLOCODE_UNKNOWN", field, f"{code} is not a known UN/LOCODE"))
    return found


def _hs_code(m: Manifest) -> list[Violation]:
    return [
        Violation(
            "HS_CODE_FORMAT",
            f"containers[{i}].hs_code",
            f"HS code {line.hs_code!r} is not 6 to 10 digits",
        )
        for i, line in enumerate(m.containers)
        if not HS_CODE.match(line.hs_code)
    ]


def _duplicates(m: Manifest) -> list[Violation]:
    seen: dict[str, int] = {}
    found = []
    for i, line in enumerate(m.containers):
        if line.container_no in seen:
            msg = f"container {line.container_no} already appears on line {seen[line.container_no]}"
            found.append(Violation("DUPLICATE_CONTAINER", f"containers[{i}].container_no", msg))
        else:
            seen[line.container_no] = i
    return found


def _gross_over_max(m: Manifest) -> list[Violation]:
    return [
        Violation(
            "GROSS_OVER_MAX",
            f"containers[{i}].gross_kg",
            f"gross weight {line.gross_kg} kg is above the {MAX_GROSS_KG:.0f} kg container limit",
        )
        for i, line in enumerate(m.containers)
        if line.gross_kg > MAX_GROSS_KG
    ]


_RULES: tuple[Callable[[Manifest], list[Violation]], ...] = (
    _iso6346,
    _net_gt_gross,
    _sum_packages,
    _sum_gross,
    _sum_volume,
    _unlocode,
    _hs_code,
    _duplicates,
    _gross_over_max,
)


def check_rules(manifest: Manifest) -> list[Violation]:
    """Run every cross-field rule and return all violations in a stable order."""
    found: list[Violation] = []
    for rule in _RULES:
        found.extend(rule(manifest))
    return found
