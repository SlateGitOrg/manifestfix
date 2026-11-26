"""Seeded generator for synthetic freight documents, ground truth and a fault plan.

Properties of the default dataset (300 documents):

* 1 to 6 containers per document, 1,041 container lines in total for the default seed (7).
* Every container number carries a valid ISO 6346 check digit.
* 30% of documents state weights in pounds, with a totals line giving both units.
* 15% use a decimal-comma locale (`1.234,5`).
* Three layouts in equal numbers: packing-list table, free-text email, key-value bill of lading.
* A fault plan that marks 115 documents for a specific model fault.

All company, vessel and cargo names are invented.
"""

from __future__ import annotations

import json
import random
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from manifestfix import iso6346
from manifestfix.faults import DEFAULT_COUNTS, Fault, load_plan, plan_faults, save_plan
from manifestfix.layouts import LAYOUTS, RENDERERS, lb_of
from manifestfix.normalize import LB_TO_KG
from manifestfix.schema import Incoterm
from manifestfix.unlocode import UNLOCODES

DEFAULT_SEED = 7
DEFAULT_COUNT = 300
LB_SHARE = 0.30
COMMA_SHARE = 0.15

EN_LOCALES = ("en_US", "en_GB", "en_CA", "en_AU")
COMMA_LOCALES = ("de_DE", "fr_FR", "es_ES", "it_IT", "nl_NL", "pt_PT")
SHIPPERS = (
    "Northgate Textiles Ltd.",
    "Brightwater Fabrication Co.",
    "Kestrel Components, Inc.",
    "Alder & Finch Trading",
    "Meridian Plastics GmbH",
    "Lowell Hardware Supply",
    "Sunhaven Foods Export",
    "Tidewell Ceramics, Ltd.",
    "Orchard Row Furniture",
    "Pinecrest Electronics",
)
CONSIGNEES = (
    "Halden Retail Group",
    "Corbin & Wray Distribution",
    "Ashford Home Supply, LLC",
    "Westmark Wholesale",
    "Ridgeline Imports Inc.",
    "Bellweather Stores Ltd.",
    "Harlow Industrial Buyers",
    "Stonebridge Logistics Customers Co.",
    "Fenwick Market Traders",
    "Larkspur Outfitters",
)
VESSELS = (
    "MV AURELIAN STAR",
    "MV NORTHERN CREST",
    "MV PACIFIC HERON",
    "MV CORAL MERIDIAN",
    "MV SILVER ARROW",
    "MV BALTIC DAWN",
    "MV ORIENT HARMONY",
    "MV ATLAS VOYAGER",
)
CARRIER_PREFIXES = ("NVLN", "HRBR", "TSLC", "PKMR", "ORNT", "BLFA")
PACKAGE_TYPES = ("CARTONS", "PALLETS", "CRATES", "DRUMS", "BAGS", "BALES")
CARGO = (
    ("850110", "Electric motors"),
    ("61091000", "Cotton knit t-shirts, assorted sizes"),
    ("73181500", "Bolts, nuts and washers"),
    ("69072100", "Ceramic floor tiles"),
    ("39239000", "Plastic storage boxes"),
    ("94036000", "Wooden bedroom furniture"),
    ("62033200", "Men's work jackets"),
    ("84713000", "Laptop computers"),
    ("20089900", "Canned fruit, packed in syrup"),
    ("40111000", "Passenger car tyres"),
    ("85423100", "Integrated circuits"),
    ("64039100", "Leather boots, women's"),
    ("95030000", "Toys and games, assorted"),
    ("73239300", "Stainless steel kitchenware"),
    ("33049900", "Skin care preparations"),
    ("85171300", "Smartphones"),
)


@dataclass
class SynthDoc:
    doc_id: str
    layout: str
    unit: str  # "kg" or "lb"
    decimal_comma: bool
    locale: str
    manifest: dict[str, Any]  # ground truth
    text: str


@dataclass
class Dataset:
    seed: int
    docs: list[SynthDoc]
    plan: dict[str, Fault]

    def texts(self) -> dict[str, str]:
        return {d.doc_id: d.text for d in self.docs}

    def truth(self) -> dict[str, dict[str, Any]]:
        return {d.doc_id: d.manifest for d in self.docs}


def _container_no(rng: random.Random) -> str:
    owner = "".join(rng.choice("ABCDEFGHIJKLMNOPQRSTUVWXYZ") for _ in range(3))
    serial = f"{rng.randrange(10**6):06d}"
    return iso6346.with_check_digit(f"{owner}U{serial}")


def _build_manifest(rng: random.Random, unit: str) -> dict[str, Any]:
    ports = sorted(UNLOCODES)
    loading, discharge = rng.sample(ports, 2)
    lines: list[dict[str, Any]] = []
    numbers: set[str] = set()
    seals: set[str] = set()
    for _ in range(rng.randint(1, 6)):
        number = _container_no(rng)
        while number in numbers:
            number = _container_no(rng)
        numbers.add(number)
        seal = f"SL{rng.randrange(10**7):07d}"
        while seal in seals:
            seal = f"SL{rng.randrange(10**7):07d}"
        seals.add(seal)
        if unit == "lb":
            gross_lb = rng.randint(20_000, 62_000)
            net_lb = gross_lb - rng.randint(4_000, 9_000)
            gross, net = round(gross_lb * LB_TO_KG, 2), round(net_lb * LB_TO_KG, 2)
        else:
            gross = round(rng.uniform(9_000, 28_500), 2)
            net = round(gross - rng.uniform(1_800, 4_200), 2)
        hs_code, description = rng.choice(CARGO)
        lines.append(
            {
                "container_no": number,
                "seal_no": seal,
                "packages": rng.randint(10, 2_400),
                "package_type": rng.choice(PACKAGE_TYPES),
                "gross_kg": gross,
                "net_kg": net,
                "volume_cbm": round(rng.uniform(5, 67.5), 2),
                "hs_code": hs_code,
                "description": description,
            }
        )
    if unit == "lb":
        total_gross = round(sum(lb_of(c["gross_kg"]) for c in lines) * LB_TO_KG, 2)
    else:
        total_gross = round(sum(c["gross_kg"] for c in lines), 2)
    return {
        "bl_number": f"{rng.choice(CARRIER_PREFIXES)}{rng.randint(10**8, 10**9 - 1)}",
        "shipper": rng.choice(SHIPPERS),
        "consignee": rng.choice(CONSIGNEES),
        "vessel": rng.choice(VESSELS),
        "voyage": f"{rng.randint(100, 999)}{rng.choice('EWNS')}",
        "port_of_loading": loading,
        "port_of_discharge": discharge,
        "incoterm": rng.choice(list(Incoterm)).value,
        "containers": lines,
        "totals": {
            "packages": sum(c["packages"] for c in lines),
            "gross_kg": total_gross,
            "volume_cbm": round(sum(c["volume_cbm"] for c in lines), 2),
        },
    }


def generate_dataset(seed: int = DEFAULT_SEED, count: int = DEFAULT_COUNT) -> Dataset:
    """Build documents, ground truth and the fault plan. Same seed, same output."""
    rng = random.Random(seed)
    lb_ids = set(rng.sample(range(count), round(count * LB_SHARE)))
    comma_ids = set(rng.sample(range(count), round(count * COMMA_SHARE)))
    layouts = [LAYOUTS[i % len(LAYOUTS)] for i in range(count)]
    rng.shuffle(layouts)
    docs: list[SynthDoc] = []
    for i in range(count):
        doc_id = f"MF-{i + 1:04d}"
        unit = "lb" if i in lb_ids else "kg"
        comma = i in comma_ids
        locale = rng.choice(COMMA_LOCALES if comma else EN_LOCALES)
        manifest = _build_manifest(rng, unit)
        text = RENDERERS[layouts[i]](doc_id, manifest, unit, locale, comma)
        docs.append(SynthDoc(doc_id, layouts[i], unit, comma, locale, manifest, text))
    scale = count / DEFAULT_COUNT
    plan = plan_faults(rng, docs, _scaled_counts(scale))
    return Dataset(seed, docs, plan)


def _scaled_counts(scale: float) -> dict[str, int]:
    return {kind: round(n * scale) for kind, n in DEFAULT_COUNTS.items()}


def write_dataset(dataset: Dataset, out: Path) -> None:
    (out / "docs").mkdir(parents=True, exist_ok=True)
    for doc in dataset.docs:
        (out / "docs" / f"{doc.doc_id}.txt").write_text(doc.text)
    truth = {
        d.doc_id: {
            "layout": d.layout,
            "unit": d.unit,
            "decimal_comma": d.decimal_comma,
            "locale": d.locale,
            "manifest": d.manifest,
        }
        for d in dataset.docs
    }
    (out / "truth.json").write_text(json.dumps(truth, indent=1))
    save_plan(dataset.plan, out / "fault_plan.yaml")


def load_dataset(out: Path) -> Dataset:
    truth = json.loads((out / "truth.json").read_text())
    docs = []
    for doc_id, entry in truth.items():
        text = (out / "docs" / f"{doc_id}.txt").read_text()
        docs.append(
            SynthDoc(
                doc_id,
                entry["layout"],
                entry["unit"],
                entry["decimal_comma"],
                entry["locale"],
                entry["manifest"],
                text,
            )
        )
    return Dataset(0, docs, load_plan(out / "fault_plan.yaml"))
