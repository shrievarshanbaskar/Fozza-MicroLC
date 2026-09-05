"""Team: Fozza · Product: MicroLC — trade-document fixture generator (reportlab).

Generates a complete LC presentation (commercial invoice, bill of lading, packing list)
as PDFs plus the credit terms as deal.json, in one of three presets:

    clean       everything consistent with the credit                      -> k = 0
    discrepant  short quantity on B/L + packing list, shipped 3 days late    -> k = 2
    fraudulent  container on the B/L differs from the packing list           -> k = 1, externally checkable

Every document carries vessel, voyage and container fields so the verifier agent
has something an external oracle can confirm or contradict.

    python doc_generator.py clean|discrepant|fraudulent|all [--out docs/generated]
"""
from __future__ import annotations

import argparse
import json
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.pdfgen import canvas

PRESETS = ("clean", "discrepant", "fraudulent")
DOC_FILES = {"invoice": "invoice.pdf", "bill_of_lading": "bill_of_lading.pdf", "packing_list": "packing_list.pdf"}

ISSUE = date(2026, 7, 15)
LATEST_SHIPMENT = date(2026, 8, 20)
ON_BOARD_CLEAN = date(2026, 8, 18)
PRESENTATION = date(2026, 9, 5)

CREDIT = {
    "lc_number": "MLC-SG-2026-0142",
    "applicant": "Meridian Apparel Trading Pte Ltd",
    "applicant_address": "71 Robinson Road, Singapore 068895",
    "beneficiary": "Coimbatore Spinning Mills Pvt Ltd",
    "beneficiary_address": "Plot 14, SIPCOT Industrial Park, Coimbatore 641402, India",
    "currency": "RLUSD",
    "amount": 10000.00,
    "goods_description": "100% Combed Cotton Yarn Ne 40/1 Compact Spun",
    "quantity": 4000,
    "unit": "KG",
    "unit_price": 2.50,
    "port_of_loading": "Tuticorin, India",
    "port_of_discharge": "Singapore",
    "incoterm": "CFR Singapore",
    "partial_shipments": "NOT ALLOWED",
    "transhipment": "NOT ALLOWED",
    "issue_date": ISSUE.isoformat(),
    "latest_shipment_date": LATEST_SHIPMENT.isoformat(),
    "expiry_date": date(2026, 9, 30).isoformat(),
    "presentation_period_days": 21,
    "presentation_date": PRESENTATION.isoformat(),
    "required_documents": ["Commercial Invoice", "Bill of Lading", "Packing List"],
}

SHIPMENT = {
    "vessel": "MV Sagar Kranti",
    "voyage": "SK-0917E",
    "container_number": "TCLU7702410",
    "seal_number": "SL-448127",
    "bl_number": "TUTSIN-26-08841",
    "invoice_number": "CSM-INV-2026-0733",
    "packing_list_number": "CSM-PL-2026-0733",
    "carrier": "Coromandel Container Lines",
    "packages": 160,
    "gross_weight_kg": 4180.0,
    "net_weight_kg": 4000.0,
}


def build_presentation(preset: str) -> dict:
    """Return {"deal": credit terms, "documents": {doc_type: field dict}} for a preset."""
    if preset not in PRESETS:
        raise ValueError(f"unknown preset {preset}")
    lc = deepcopy(CREDIT)
    lc["preset"] = preset
    s = SHIPMENT
    on_board = ON_BOARD_CLEAN
    qty_docs = lc["quantity"]
    bl_container = pl_container = s["container_number"]

    bl_number = s["bl_number"]
    if preset == "discrepant":
        on_board = LATEST_SHIPMENT + timedelta(days=3)
        qty_docs = 3900  # 2.5% short on B/L and packing list; invoice still claims 4000
        bl_number = "TUTSIN-26-08857"  # a later sailing has its own B/L number
    if preset == "fraudulent":
        pl_container = "MSKU8811207"  # packing list names a different box than the B/L
        bl_number = "TUTSIN-26-08902"  # the carrier's record for this B/L shows a different vessel

    invoice_date = on_board + timedelta(days=1)
    invoice = {
        "invoice_number": s["invoice_number"],
        "invoice_date": invoice_date.isoformat(),
        "lc_number": lc["lc_number"],
        "seller": lc["beneficiary"],
        "buyer": lc["applicant"],
        "currency": lc["currency"],
        "goods_description": lc["goods_description"],
        "quantity": lc["quantity"],
        "unit": lc["unit"],
        "unit_price": lc["unit_price"],
        "total_amount": round(lc["quantity"] * lc["unit_price"], 2),
        "incoterm": lc["incoterm"],
        "vessel": s["vessel"],
        "voyage": s["voyage"],
        "container_number": bl_container,
        "port_of_loading": lc["port_of_loading"],
        "port_of_discharge": lc["port_of_discharge"],
    }
    bill_of_lading = {
        "bl_number": bl_number,
        "carrier": s["carrier"],
        "shipper": lc["beneficiary"],
        "consignee": lc["applicant"],
        "notify_party": lc["applicant"],
        "lc_number": lc["lc_number"],
        "vessel": s["vessel"],
        "voyage": s["voyage"],
        "container_number": bl_container,
        "seal_number": s["seal_number"],
        "port_of_loading": lc["port_of_loading"],
        "port_of_discharge": lc["port_of_discharge"],
        "shipped_on_board_date": on_board.isoformat(),
        "goods_description": "Cotton Yarn, Combed, Ne 40/1",
        "quantity": qty_docs,
        "unit": lc["unit"],
        "packages": s["packages"],
        "gross_weight_kg": s["gross_weight_kg"],
        "clean_on_board": True,
        "freight": "FREIGHT PREPAID",
    }
    packing_list = {
        "packing_list_number": s["packing_list_number"],
        "date": invoice_date.isoformat(),
        "lc_number": lc["lc_number"],
        "seller": lc["beneficiary"],
        "buyer": lc["applicant"],
        "goods_description": lc["goods_description"],
        "quantity": qty_docs,
        "unit": lc["unit"],
        "packages": s["packages"],
        "gross_weight_kg": s["gross_weight_kg"],
        "net_weight_kg": float(qty_docs),
        "vessel": s["vessel"],
        "voyage": s["voyage"],
        "container_number": pl_container,
        "seal_number": s["seal_number"],
    }
    return {"deal": lc, "documents": {"invoice": invoice, "bill_of_lading": bill_of_lading, "packing_list": packing_list}}


# --------------------------------------------------------------------------- PDF rendering
TITLES = {"invoice": "COMMERCIAL INVOICE", "bill_of_lading": "BILL OF LADING", "packing_list": "PACKING LIST"}
LABELS = {
    "invoice_number": "INVOICE NO", "invoice_date": "INVOICE DATE", "lc_number": "L/C NUMBER", "seller": "SELLER",
    "buyer": "BUYER", "currency": "CURRENCY", "goods_description": "DESCRIPTION OF GOODS", "quantity": "QUANTITY",
    "unit": "UNIT", "unit_price": "UNIT PRICE", "total_amount": "TOTAL AMOUNT", "incoterm": "INCOTERM",
    "vessel": "VESSEL", "voyage": "VOYAGE", "container_number": "CONTAINER NO", "port_of_loading": "PORT OF LOADING",
    "port_of_discharge": "PORT OF DISCHARGE", "bl_number": "B/L NUMBER", "carrier": "CARRIER", "shipper": "SHIPPER",
    "consignee": "CONSIGNEE", "notify_party": "NOTIFY PARTY", "seal_number": "SEAL NO",
    "shipped_on_board_date": "SHIPPED ON BOARD DATE", "packages": "PACKAGES", "gross_weight_kg": "GROSS WEIGHT (KG)",
    "net_weight_kg": "NET WEIGHT (KG)", "clean_on_board": "CLEAN ON BOARD", "freight": "FREIGHT",
    "packing_list_number": "PACKING LIST NO", "date": "DATE",
}


def _fmt(v) -> str:
    if isinstance(v, bool):
        return "YES" if v else "NO"
    if isinstance(v, float):
        return f"{v:,.2f}"
    return str(v)


def render_pdf(doc_type: str, fields: dict, path: Path, issuer: str) -> None:
    c = canvas.Canvas(str(path), pagesize=A4)
    w, h = A4
    c.setFont("Helvetica-Bold", 16)
    c.drawString(20 * mm, h - 25 * mm, TITLES[doc_type])
    c.setFont("Helvetica", 9)
    c.drawString(20 * mm, h - 31 * mm, issuer)
    c.line(20 * mm, h - 34 * mm, w - 20 * mm, h - 34 * mm)
    y = h - 44 * mm
    c.setFont("Helvetica", 10)
    for key, value in fields.items():
        label = LABELS.get(key, key.upper().replace("_", " "))
        c.setFont("Helvetica-Bold", 10)
        c.drawString(20 * mm, y, f"{label}:")
        c.setFont("Helvetica", 10)
        c.drawString(80 * mm, y, _fmt(value))
        y -= 7 * mm
    if doc_type == "bill_of_lading":
        y -= 4 * mm
        c.setFont("Helvetica-Oblique", 9)
        c.drawString(20 * mm, y, "SHIPPED ON BOARD IN APPARENT GOOD ORDER AND CONDITION. ORIGINAL 1 OF 3.")
    c.setFont("Helvetica", 8)
    c.drawString(20 * mm, 15 * mm, "Generated fixture for MicroLC (Team: Fozza). Not a real trade document.")
    c.showPage()
    c.save()


def generate_set(preset: str, out_root: str | Path = "docs/generated") -> Path:
    pres = build_presentation(preset)
    out = Path(out_root) / preset
    out.mkdir(parents=True, exist_ok=True)
    issuers = {
        "invoice": pres["deal"]["beneficiary"],
        "bill_of_lading": SHIPMENT["carrier"],
        "packing_list": pres["deal"]["beneficiary"],
    }
    for doc_type, fname in DOC_FILES.items():
        render_pdf(doc_type, pres["documents"][doc_type], out / fname, issuers[doc_type])
    (out / "deal.json").write_text(json.dumps(pres["deal"], indent=2))
    (out / "expected_fields.json").write_text(json.dumps(pres["documents"], indent=2))
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("preset", choices=PRESETS + ("all",))
    ap.add_argument("--out", default="docs/generated")
    a = ap.parse_args()
    for p in (PRESETS if a.preset == "all" else (a.preset,)):
        print("wrote", generate_set(p, a.out))
