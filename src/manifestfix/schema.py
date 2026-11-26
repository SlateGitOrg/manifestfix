"""Pydantic models for a freight manifest, and the violation record shared with the rules."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, ValidationError

CONTAINER_NO_PATTERN = r"^[A-Z]{3}[UJZ][0-9]{7}$"
LOCODE_PATTERN = r"^[A-Z]{2}[A-Z0-9]{3}$"


class Incoterm(StrEnum):
    """The 11 Incoterms 2020 rules."""

    EXW = "EXW"
    FCA = "FCA"
    CPT = "CPT"
    CIP = "CIP"
    DAP = "DAP"
    DPU = "DPU"
    DDP = "DDP"
    FAS = "FAS"
    FOB = "FOB"
    CFR = "CFR"
    CIF = "CIF"


class ContainerLine(BaseModel):
    model_config = ConfigDict(extra="forbid")

    container_no: str = Field(pattern=CONTAINER_NO_PATTERN)
    seal_no: str = Field(min_length=1)
    packages: int = Field(ge=1)
    package_type: str = Field(min_length=1)
    gross_kg: float = Field(gt=0)
    net_kg: float = Field(ge=0)
    volume_cbm: float = Field(ge=0)
    hs_code: str = Field(min_length=1)
    description: str = Field(min_length=1)


class Totals(BaseModel):
    model_config = ConfigDict(extra="forbid")

    packages: int = Field(ge=1)
    gross_kg: float = Field(gt=0)
    volume_cbm: float = Field(ge=0)


class Manifest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bl_number: str = Field(min_length=1)
    shipper: str = Field(min_length=1)
    consignee: str = Field(min_length=1)
    vessel: str = Field(min_length=1)
    voyage: str = Field(min_length=1)
    port_of_loading: str = Field(pattern=LOCODE_PATTERN)
    port_of_discharge: str = Field(pattern=LOCODE_PATTERN)
    incoterm: Incoterm
    containers: list[ContainerLine] = Field(min_length=1)
    totals: Totals


@dataclass(frozen=True)
class Violation:
    """One failed check: a stable code, the JSON path it applies to and a human message."""

    code: str
    path: str
    message: str
    kind: str = "rule"  # "schema", "rule" or "parse"


def format_path(loc: tuple[Any, ...]) -> str:
    """Render a pydantic location tuple as `containers[1].container_no`."""
    path = ""
    for part in loc:
        if isinstance(part, int):
            path += f"[{part}]"
        else:
            path += f".{part}" if path else str(part)
    return path or "$"


def violations_from_error(error: ValidationError) -> list[Violation]:
    found = []
    for item in error.errors():
        code = "SCHEMA_" + str(item["type"]).upper().replace(".", "_")
        found.append(Violation(code, format_path(item["loc"]), item["msg"], "schema"))
    return found


def validate_manifest(data: Any) -> tuple[Manifest | None, list[Violation]]:
    """Validate a parsed JSON value against the schema."""
    if not isinstance(data, dict):
        found = [Violation("SCHEMA_NOT_OBJECT", "$", "expected a JSON object", "schema")]
        return None, found
    try:
        return Manifest.model_validate(data), []
    except ValidationError as error:
        return None, violations_from_error(error)
