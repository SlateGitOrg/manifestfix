"""Three text layouts for synthetic manifests: a renderer and a parser for each.

The renderers turn a ground-truth manifest into a document. The parsers read such a document back
into a raw manifest dict (container numbers as printed, weights converted to kilograms). The
offline model uses the parsers, so a clean extraction is exactly right by construction.
"""

from __future__ import annotations

import re
from typing import Any

from manifestfix.normalize import (
    LB_TO_KG,
    detect_decimal_comma,
    parse_number,
    parse_quantity,
    parse_weight_kg,
    to_kg,
)
from manifestfix.unlocode import UNLOCODES

LAYOUTS = ("table", "email", "bol")
_ID = re.compile(r"^File ref:\s*(\S+)\s*$", re.MULTILINE)
_PORT = re.compile(r"\(([A-Z]{2}[A-Z0-9]{3})\)\s*$")


def lb_of(kg: float) -> int:
    """Whole pounds that a kilogram figure was derived from."""
    return round(kg / LB_TO_KG)


def fmt_number(value: float, decimals: int, decimal_comma: bool) -> str:
    text = f"{value:,.{decimals}f}"
    if decimal_comma:
        text = text.replace(",", "\0").replace(".", ",").replace("\0", ".")
    return text


def doc_id_of(text: str) -> str | None:
    match = _ID.search(text)
    return match.group(1) if match else None


def detect_layout(text: str) -> str:
    head = text.lstrip()[:40].upper()
    if head.startswith("PACKING LIST"):
        return "table"
    if head.startswith("FROM:"):
        return "email"
    if head.startswith("BILL OF LADING"):
        return "bol"
    raise ValueError("unrecognised document layout")


def _hs_display(hs_code: str) -> str:
    parts = [hs_code[:4], hs_code[4:6]] + ([hs_code[6:8]] if len(hs_code) > 6 else [])
    return ".".join(parts)


def _port_display(code: str) -> str:
    return f"{UNLOCODES[code]} ({code})"


class _Fmt:
    """Number formatting for one document: unit and locale are fixed."""

    def __init__(self, unit: str, decimal_comma: bool) -> None:
        self.lb = unit == "lb"
        self.comma = decimal_comma
        self.unit_upper = "LBS" if self.lb else "KGS"

    def weight(self, kg: float) -> str:
        if self.lb:
            return fmt_number(lb_of(kg), 0, self.comma)
        return fmt_number(kg, 2, self.comma)

    def count(self, n: int) -> str:
        return fmt_number(n, 0, self.comma)

    def volume(self, cbm: float) -> str:
        return fmt_number(cbm, 2, self.comma)

    def total_weight(self, manifest: dict[str, Any]) -> str:
        kg = manifest["totals"]["gross_kg"]
        if not self.lb:
            return f"{fmt_number(kg, 2, self.comma)} KGS"
        pounds = sum(lb_of(line["gross_kg"]) for line in manifest["containers"])
        return f"{fmt_number(pounds, 0, self.comma)} LBS ({fmt_number(kg, 2, self.comma)} KGS)"


def render_table(doc_id: str, m: dict[str, Any], unit: str, locale: str, comma: bool) -> str:
    f = _Fmt(unit, comma)
    lines = [
        "PACKING LIST",
        f"File ref: {doc_id}",
        f"Locale: {locale}",
        f"B/L No.: {m['bl_number']}",
        f"Shipper: {m['shipper']}",
        f"Consignee: {m['consignee']}",
        f"Vessel / Voyage: {m['vessel']} / {m['voyage']}",
        f"Port of loading: {_port_display(m['port_of_loading'])}",
        f"Port of discharge: {_port_display(m['port_of_discharge'])}",
        f"Incoterm: {m['incoterm']}",
        f"Weights: {f.unit_upper}",
        "",
        "| Container | Seal | Pkgs | Type | Gross | Net | CBM | HS | Description |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for c in m["containers"]:
        no = f"{c['container_no'][:4]} {c['container_no'][4:]}"
        cells = [
            no,
            c["seal_no"],
            f.count(c["packages"]),
            c["package_type"],
            f.weight(c["gross_kg"]),
            f.weight(c["net_kg"]),
            f.volume(c["volume_cbm"]),
            _hs_display(c["hs_code"]),
            c["description"],
        ]
        lines.append("| " + " | ".join(cells) + " |")
    t = m["totals"]
    totals = (
        f"{f.count(t['packages'])} pkgs | {f.total_weight(m)} | {f.volume(t['volume_cbm'])} CBM"
    )
    lines.append(f"TOTALS: {totals}")
    return "\n".join(lines) + "\n"


def render_email(doc_id: str, m: dict[str, Any], unit: str, locale: str, comma: bool) -> str:
    f = _Fmt(unit, comma)
    wu = "lbs" if f.lb else "kg"
    lines = [
        "From: dispatch@harbourline-forwarding.example",
        "To: customs-desk@harbourline-forwarding.example",
        f"Subject: Packing details for {doc_id}",
        f"File ref: {doc_id}",
        f"Locale: {locale}",
        "",
        "Hello,",
        "",
        "Please find the shipment details below.",
        "",
        f"B/L number: {m['bl_number']}",
        f"Shipper: {m['shipper']}",
        f"Consignee: {m['consignee']}",
        f"Vessel: {m['vessel']}, voyage {m['voyage']}",
        f"Loading port: {_port_display(m['port_of_loading'])}",
        f"Discharge port: {_port_display(m['port_of_discharge'])}",
        f"Terms: {m['incoterm']}",
        "",
    ]
    for i, c in enumerate(m["containers"], start=1):
        no = f"{c['container_no'][:4]} {c['container_no'][4:]}".lower()
        lines.append(
            f"Container {i}: {no}, seal {c['seal_no']}, {f.count(c['packages'])} "
            f"{c['package_type']}, gross {f.weight(c['gross_kg'])} {wu}, "
            f"net {f.weight(c['net_kg'])} {wu}, {f.volume(c['volume_cbm'])} cbm, "
            f"HS {_hs_display(c['hs_code'])}, {c['description']}."
        )
    t = m["totals"]
    total_w = f.total_weight(m).replace("KGS", "kg").replace("LBS", "lbs")
    lines += [
        "",
        f"Totals: {f.count(t['packages'])} packages, {total_w} gross, "
        f"{f.volume(t['volume_cbm'])} cbm.",
        "",
        "Regards,",
        "Dispatch desk",
    ]
    return "\n".join(lines) + "\n"


def render_bol(doc_id: str, m: dict[str, Any], unit: str, locale: str, comma: bool) -> str:
    f = _Fmt(unit, comma)
    lines = [
        "BILL OF LADING",
        f"File ref: {doc_id}",
        f"Locale: {locale}",
        f"BL Number: {m['bl_number']}",
        f"Shipper: {m['shipper']}",
        f"Consignee: {m['consignee']}",
        f"Vessel: {m['vessel']}",
        f"Voyage: {m['voyage']}",
        f"Port of Loading: {_port_display(m['port_of_loading'])}",
        f"Port of Discharge: {_port_display(m['port_of_discharge'])}",
        f"Incoterm: {m['incoterm']}",
        "",
    ]
    for i, c in enumerate(m["containers"], start=1):
        lines += [
            f"Container {i}",
            f"  Container No: {c['container_no']}",
            f"  Seal No: {c['seal_no']}",
            f"  Packages: {f.count(c['packages'])} {c['package_type']}",
            f"  Gross Weight: {f.weight(c['gross_kg'])} {f.unit_upper}",
            f"  Net Weight: {f.weight(c['net_kg'])} {f.unit_upper}",
            f"  Volume: {f.volume(c['volume_cbm'])} CBM",
            f"  HS Code: {_hs_display(c['hs_code'])}",
            f"  Description: {c['description']}",
        ]
    t = m["totals"]
    lines += [
        f"Total Packages: {f.count(t['packages'])}",
        f"Total Gross Weight: {f.total_weight(m)}",
        f"Total Volume: {f.volume(t['volume_cbm'])} CBM",
    ]
    return "\n".join(lines) + "\n"


RENDERERS = {"table": render_table, "email": render_email, "bol": render_bol}


def _field(text: str, label: str) -> str:
    match = re.search(rf"^{re.escape(label)}:\s*(.+?)\s*$", text, re.MULTILINE)
    if not match:
        raise ValueError(f"missing field {label!r}")
    return match.group(1)


def _port(text: str, label: str) -> str:
    match = _PORT.search(_field(text, label))
    if not match:
        raise ValueError(f"no UN/LOCODE in {label!r}")
    return match.group(1)


def _total_weight(text: str, comma: bool) -> float:
    inner = re.search(r"\(([^)]+)\)", text)
    return parse_weight_kg(inner.group(1) if inner else text, comma)


def _weight(value: str, unit: str, comma: bool) -> float:
    return to_kg(parse_number(value, comma), "lb" if unit.lower().startswith("lb") else "kg")


def _split_packages(text: str, comma: bool) -> tuple[int, str]:
    count, _, kind = text.strip().partition(" ")
    return int(parse_number(count, comma)), kind.strip()


def parse_table(text: str, comma: bool) -> dict[str, Any]:
    vessel, _, voyage = _field(text, "Vessel / Voyage").partition(" / ")
    unit = _field(text, "Weights")
    containers = []
    for row in text.splitlines():
        if not row.startswith("|") or row.startswith("|---") or "| Seal |" in row:
            continue
        cells = [cell.strip() for cell in row.strip().strip("|").split("|")]
        no, seal, pkgs, kind, gross, net, cbm, hs, desc = cells
        containers.append(
            {
                "container_no": no,
                "seal_no": seal,
                "packages": int(parse_number(pkgs, comma)),
                "package_type": kind,
                "gross_kg": _weight(gross, unit, comma),
                "net_kg": _weight(net, unit, comma),
                "volume_cbm": parse_number(cbm, comma),
                "hs_code": hs,
                "description": desc,
            }
        )
    totals = re.search(r"^TOTALS:\s*(.+?) pkgs \| (.+?) \| (.+?) CBM\s*$", text, re.MULTILINE)
    if not totals:
        raise ValueError("missing TOTALS line")
    return {
        "bl_number": _field(text, "B/L No."),
        "shipper": _field(text, "Shipper"),
        "consignee": _field(text, "Consignee"),
        "vessel": vessel,
        "voyage": voyage,
        "port_of_loading": _port(text, "Port of loading"),
        "port_of_discharge": _port(text, "Port of discharge"),
        "incoterm": _field(text, "Incoterm"),
        "containers": containers,
        "totals": {
            "packages": int(parse_number(totals.group(1), comma)),
            "gross_kg": _total_weight(totals.group(2), comma),
            "volume_cbm": parse_number(totals.group(3), comma),
        },
    }


_EMAIL_LINE = re.compile(
    r"^Container \d+: (?P<no>[^,]+), seal (?P<seal>[^,]+), (?P<pk>[\d.,]+) (?P<kind>\S+), "
    r"gross (?P<g>[\d.,]+) (?P<gu>kg|lbs), net (?P<n>[\d.,]+) (?P<nu>kg|lbs), "
    r"(?P<v>[\d.,]+) cbm, HS (?P<hs>[\d.]+), (?P<desc>.+)\.$",
    re.MULTILINE,
)


def parse_email(text: str, comma: bool) -> dict[str, Any]:
    vessel, _, voyage = _field(text, "Vessel").partition(", voyage ")
    containers = []
    for m in _EMAIL_LINE.finditer(text):
        containers.append(
            {
                "container_no": m["no"],
                "seal_no": m["seal"],
                "packages": int(parse_number(m["pk"], comma)),
                "package_type": m["kind"],
                "gross_kg": _weight(m["g"], m["gu"], comma),
                "net_kg": _weight(m["n"], m["nu"], comma),
                "volume_cbm": parse_number(m["v"], comma),
                "hs_code": m["hs"],
                "description": m["desc"],
            }
        )
    totals = re.search(r"^Totals: (.+?) packages, (.+?) gross, (.+?) cbm\.\s*$", text, re.MULTILINE)
    if not totals:
        raise ValueError("missing Totals line")
    return {
        "bl_number": _field(text, "B/L number"),
        "shipper": _field(text, "Shipper"),
        "consignee": _field(text, "Consignee"),
        "vessel": vessel,
        "voyage": voyage,
        "port_of_loading": _port(text, "Loading port"),
        "port_of_discharge": _port(text, "Discharge port"),
        "incoterm": _field(text, "Terms"),
        "containers": containers,
        "totals": {
            "packages": int(parse_number(totals.group(1), comma)),
            "gross_kg": _total_weight(totals.group(2), comma),
            "volume_cbm": parse_number(totals.group(3), comma),
        },
    }


def parse_bol(text: str, comma: bool) -> dict[str, Any]:
    containers: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for line in text.splitlines():
        if re.match(r"^Container \d+\s*$", line):
            current = {}
            containers.append(current)
            continue
        if current is None or not line.startswith("  "):
            continue
        key, _, value = line.strip().partition(": ")
        if key == "Container No":
            current["container_no"] = value
        elif key == "Seal No":
            current["seal_no"] = value
        elif key == "Packages":
            current["packages"], current["package_type"] = _split_packages(value, comma)
        elif key in ("Gross Weight", "Net Weight"):
            number, unit = value.rsplit(" ", 1)
            name = "gross_kg" if key == "Gross Weight" else "net_kg"
            current[name] = _weight(number, unit, comma)
        elif key == "Volume":
            current["volume_cbm"] = parse_quantity(value, comma)[0]
        elif key == "HS Code":
            current["hs_code"] = value
        elif key == "Description":
            current["description"] = value
    return {
        "bl_number": _field(text, "BL Number"),
        "shipper": _field(text, "Shipper"),
        "consignee": _field(text, "Consignee"),
        "vessel": _field(text, "Vessel"),
        "voyage": _field(text, "Voyage"),
        "port_of_loading": _port(text, "Port of Loading"),
        "port_of_discharge": _port(text, "Port of Discharge"),
        "incoterm": _field(text, "Incoterm"),
        "containers": containers,
        "totals": {
            "packages": int(parse_number(_field(text, "Total Packages"), comma)),
            "gross_kg": _total_weight(_field(text, "Total Gross Weight"), comma),
            "volume_cbm": parse_quantity(_field(text, "Total Volume"), comma)[0],
        },
    }


PARSERS = {"table": parse_table, "email": parse_email, "bol": parse_bol}


def parse_document(text: str) -> dict[str, Any]:
    """Read a synthetic document into a raw manifest dict using its layout's parser."""
    return PARSERS[detect_layout(text)](text, detect_decimal_comma(text))
