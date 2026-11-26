from __future__ import annotations

import copy
from typing import Any

import pytest

from manifestfix.generator import Dataset, generate_dataset
from manifestfix.schema import Manifest

CLEAN: dict[str, Any] = {
    "bl_number": "NVLN123456789",
    "shipper": "Northgate Textiles Ltd.",
    "consignee": "Halden Retail Group",
    "vessel": "MV AURELIAN STAR",
    "voyage": "412E",
    "port_of_loading": "CNSHA",
    "port_of_discharge": "USLAX",
    "incoterm": "FOB",
    "containers": [
        {
            "container_no": "CSQU3054383",
            "seal_no": "SL0000001",
            "packages": 100,
            "package_type": "CARTONS",
            "gross_kg": 18000.0,
            "net_kg": 15000.0,
            "volume_cbm": 30.0,
            "hs_code": "850110",
            "description": "Electric motors",
        },
        {
            "container_no": "MSCU1234566",
            "seal_no": "SL0000002",
            "packages": 200,
            "package_type": "PALLETS",
            "gross_kg": 12000.0,
            "net_kg": 10000.0,
            "volume_cbm": 20.0,
            "hs_code": "73181500",
            "description": "Bolts, nuts and washers",
        },
    ],
    "totals": {"packages": 300, "gross_kg": 30000.0, "volume_cbm": 50.0},
}


@pytest.fixture
def clean() -> dict[str, Any]:
    return copy.deepcopy(CLEAN)


@pytest.fixture
def clean_manifest(clean: dict[str, Any]) -> Manifest:
    return Manifest.model_validate(clean)


@pytest.fixture(scope="session")
def dataset() -> Dataset:
    return generate_dataset(seed=7, count=300)
