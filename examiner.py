"""Team: Fozza · Product: MicroLC — document examiner.

Pipeline:  PDF  --pypdf-->  text  --parser-->  typed fields  --rules-->  discrepancies, k

* Two parsers share one pydantic schema per document type: `GroqParser` (structured output
  via `with_structured_output`, never free-text) and `TemplateParser` (deterministic
  label/value scan). The LLM only reads documents; it never touches rules or money.
* `run_rules` is pure Python: 19 deterministic checks with UCP 600 style references.
  Each discrepancy is {rule_id, code, doc, field, found, expected, severity, article, message}.
  severity: "fatal" discrepancies refuse the presentation; "negotiable" ones feed the
  negotiation graph. `checkable` marks rules an external oracle can confirm or contradict.
"""
from __future__ import annotations

import json
import os
import re
from datetime import date, timedelta
from pathlib import Path
from typing import Literal, Optional

from dotenv import load_dotenv
from pydantic import BaseModel, Field
from pypdf import PdfReader

from ucp_articles import cite

load_dotenv()

DOC_FILES = {"invoice": "invoice.pdf", "bill_of_lading": "bill_of_lading.pdf", "packing_list": "packing_list.pdf"}


# --------------------------------------------------------------------------- schemas
class Invoice(BaseModel):
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD")
    lc_number: Optional[str] = None
    seller: Optional[str] = None
    buyer: Optional[str] = None
    currency: Optional[str] = None
    goods_description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    unit_price: Optional[float] = None
    total_amount: Optional[float] = None
    incoterm: Optional[str] = None
    vessel: Optional[str] = None
    voyage: Optional[str] = None
    container_number: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None


class BillOfLading(BaseModel):
    bl_number: Optional[str] = None
    carrier: Optional[str] = None
    shipper: Optional[str] = None
    consignee: Optional[str] = None
    notify_party: Optional[str] = None
    lc_number: Optional[str] = None
    vessel: Optional[str] = None
    voyage: Optional[str] = None
    container_number: Optional[str] = None
    seal_number: Optional[str] = None
    port_of_loading: Optional[str] = None
    port_of_discharge: Optional[str] = None
    shipped_on_board_date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD")
    goods_description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    packages: Optional[int] = None
    gross_weight_kg: Optional[float] = None
    clean_on_board: Optional[bool] = Field(None, description="true unless the B/L carries a clause about defective goods or packaging")


class PackingList(BaseModel):
    packing_list_number: Optional[str] = None
    date: Optional[str] = Field(None, description="ISO date YYYY-MM-DD")
    lc_number: Optional[str] = None
    seller: Optional[str] = None
    buyer: Optional[str] = None
    goods_description: Optional[str] = None
    quantity: Optional[float] = None
    unit: Optional[str] = None
    packages: Optional[int] = None
    gross_weight_kg: Optional[float] = None
    net_weight_kg: Optional[float] = None
    vessel: Optional[str] = None
    voyage: Optional[str] = None
    container_number: Optional[str] = None
    seal_number: Optional[str] = None


SCHEMAS: dict[str, type[BaseModel]] = {"invoice": Invoice, "bill_of_lading": BillOfLading, "packing_list": PackingList}

# labels printed on the fixture PDFs (and common on real ones) -> schema field
LABEL_TO_FIELD = {
    "INVOICE NO": "invoice_number", "INVOICE DATE": "invoice_date", "L/C NUMBER": "lc_number", "SELLER": "seller",
    "BUYER": "buyer", "CURRENCY": "currency", "DESCRIPTION OF GOODS": "goods_description", "QUANTITY": "quantity",
    "UNIT": "unit", "UNIT PRICE": "unit_price", "TOTAL AMOUNT": "total_amount", "INCOTERM": "incoterm",
    "VESSEL": "vessel", "VOYAGE": "voyage", "CONTAINER NO": "container_number", "PORT OF LOADING": "port_of_loading",
    "PORT OF DISCHARGE": "port_of_discharge", "B/L NUMBER": "bl_number", "CARRIER": "carrier", "SHIPPER": "shipper",
    "CONSIGNEE": "consignee", "NOTIFY PARTY": "notify_party", "SEAL NO": "seal_number",
    "SHIPPED ON BOARD DATE": "shipped_on_board_date", "PACKAGES": "packages", "GROSS WEIGHT (KG)": "gross_weight_kg",
    "NET WEIGHT (KG)": "net_weight_kg", "CLEAN ON BOARD": "clean_on_board", "PACKING LIST NO": "packing_list_number",
    "DATE": "date",
}


# --------------------------------------------------------------------------- text
def extract_text(pdf_path: str | Path) -> str:
    return "\n".join((p.extract_text() or "") for p in PdfReader(str(pdf_path)).pages)


# --------------------------------------------------------------------------- parsers
class TemplateParser:
    """Deterministic fallback: scans `LABEL:` lines and coerces values through the schema."""

    name = "template"

    def parse(self, doc_type: str, text: str) -> dict:
        schema = SCHEMAS[doc_type]
        lines = [ln.strip() for ln in text.splitlines() if ln.strip()]
        raw: dict = {}
        for i, ln in enumerate(lines):
            if ln.endswith(":") and ln[:-1] in LABEL_TO_FIELD and i + 1 < len(lines):
                field = LABEL_TO_FIELD[ln[:-1]]
                if field in schema.model_fields:
                    raw[field] = _coerce(schema, field, lines[i + 1])
        return schema(**raw).model_dump()


def _coerce(schema: type[BaseModel], field: str, value: str):
    ann = str(schema.model_fields[field].annotation)
    v = value.strip()
    if "bool" in ann:
        return v.upper() in ("YES", "TRUE", "Y")
    if "float" in ann or "int" in ann:
        m = re.search(r"-?[\d,]+(?:\.\d+)?", v)
        if not m:
            return None
        num = float(m.group(0).replace(",", ""))
        return int(num) if "int" in ann else num
    return v


class GroqParser:
    """LLM extraction with structured output. Model IDs come from .env only."""

    name = "groq"

    def __init__(self, model: Optional[str] = None, temperature: float = 0.0):
        from langchain_groq import ChatGroq

        self.model = model or os.environ["GROQ_SMALL_MODEL"]
        self.llm = ChatGroq(model=self.model, temperature=temperature, max_tokens=900)
        self.fallback = TemplateParser()

    def parse(self, doc_type: str, text: str) -> dict:
        schema = SCHEMAS[doc_type]
        prompt = (
            f"You are a trade-finance document examiner. Extract the fields of this {doc_type.replace('_', ' ')} "
            "exactly as printed. Use ISO dates (YYYY-MM-DD). Numbers as plain numbers without thousands separators. "
            "Leave a field null if it is absent. Do not infer or correct anything.\n\n--- DOCUMENT TEXT ---\n" + text
        )
        try:
            out = self.llm.with_structured_output(schema, method="json_schema").invoke(prompt)
            return out.model_dump()
        except Exception as exc:  # network/model failure -> deterministic parser keeps the pipeline alive
            data = self.fallback.parse(doc_type, text)
            data["_parser_fallback"] = f"groq failed: {type(exc).__name__}"
            return data


def get_parser(kind: str = "auto"):
    if kind == "template":
        return TemplateParser()
    if kind == "groq" or (kind == "auto" and os.getenv("GROQ_API_KEY")):
        return GroqParser()
    return TemplateParser()


# --------------------------------------------------------------------------- rules
Severity = Literal["fatal", "negotiable"]

RULES: dict[str, dict] = {
    # rule_id: code, article, severity, checkable (an external oracle can confirm/contradict it)
    "R01": ("MISSING_DOCUMENT", "UCP600-14a", "fatal", False),
    "R02": ("LC_NUMBER_MISMATCH", "UCP600-14d", "fatal", False),
    "R03": ("CURRENCY_MISMATCH", "UCP600-18a-iii", "fatal", False),
    "R04": ("INVOICE_AMOUNT_EXCEEDS_LC", "UCP600-18b", "fatal", False),
    "R05": ("GOODS_DESCRIPTION_MISMATCH", "UCP600-18c", "negotiable", False),
    "R06": ("BENEFICIARY_MISMATCH", "UCP600-18a-i", "fatal", False),
    "R07": ("APPLICANT_MISMATCH", "UCP600-18a-ii", "negotiable", False),
    "R08": ("INVOICE_QTY_VS_LC", "UCP600-30b", "negotiable", False),
    "R09": ("QTY_INCONSISTENT", "UCP600-14d", "negotiable", False),
    "R10": ("GOODS_DESCRIPTION_CONFLICT", "UCP600-14e", "negotiable", False),
    "R11": ("CONSIGNEE_MISMATCH", "UCP600-14d", "negotiable", False),
    "R12": ("PORT_OF_LOADING_MISMATCH", "UCP600-20a-iii", "negotiable", True),
    "R13": ("PORT_OF_DISCHARGE_MISMATCH", "UCP600-20a-iii", "negotiable", True),
    "R14": ("BL_NOT_CLEAN", "UCP600-27", "fatal", False),
    "R15": ("LATE_SHIPMENT", "UCP600-20a-ii", "negotiable", True),
    "R16": ("LATE_PRESENTATION", "UCP600-14c", "fatal", False),
    "R17": ("LC_EXPIRED", "UCP600-6d-i", "fatal", False),
    "R18": ("VESSEL_MISMATCH", "UCP600-14d", "negotiable", True),
    "R19": ("CONTAINER_MISMATCH", "UCP600-14d", "negotiable", True),
}
FATAL_RULES = frozenset(r for r, (_, _, sev, _) in RULES.items() if sev == "fatal")
CHECKABLE_RULES = frozenset(r for r, (_, _, _, chk) in RULES.items() if chk)


def _norm(s) -> str:
    return re.sub(r"[^a-z0-9]", "", str(s or "").lower())


def _date(s) -> Optional[date]:
    try:
        return date.fromisoformat(str(s)[:10]) if s else None
    except ValueError:
        return None


def run_rules(lc: dict, docs: dict[str, Optional[dict]], presentation_date: date) -> list[dict]:
    out: list[dict] = []

    def flag(rule_id: str, doc: str, field: str, found, expected, message: str):
        code, article, severity, checkable = RULES[rule_id]
        out.append({
            "rule_id": rule_id, "code": code, "doc": doc, "field": field, "found": found, "expected": expected,
            "severity": severity, "checkable": checkable, "article": article, "article_text": cite(article),
            "message": message,
        })

    inv, bl, pl = docs.get("invoice"), docs.get("bill_of_lading"), docs.get("packing_list")
    for name, d in (("invoice", inv), ("bill_of_lading", bl), ("packing_list", pl)):
        if d is None:
            flag("R01", name, "document", None, "presented", f"Required document {name} not presented")
    if not (inv and bl and pl):
        return out

    lc_amount, lc_qty = float(lc["amount"]), float(lc["quantity"])
    tolerance = 0.0 if str(lc.get("partial_shipments", "")).upper().startswith("NOT") else 0.05

    # ---- invoice vs credit (Art. 18)
    if inv.get("lc_number") and _norm(inv["lc_number"]) != _norm(lc["lc_number"]):
        flag("R02", "invoice", "lc_number", inv["lc_number"], lc["lc_number"], "Invoice references a different credit")
    if inv.get("currency") and _norm(inv["currency"]) != _norm(lc["currency"]):
        flag("R03", "invoice", "currency", inv["currency"], lc["currency"], "Invoice currency differs from the credit")
    if inv.get("total_amount") is not None and inv["total_amount"] > lc_amount + 1e-6:
        flag("R04", "invoice", "total_amount", inv["total_amount"], lc_amount, "Invoice amount exceeds the credit amount")
    if _norm(inv.get("goods_description")) != _norm(lc["goods_description"]):
        flag("R05", "invoice", "goods_description", inv.get("goods_description"), lc["goods_description"],
             "Invoice goods description does not correspond with the credit")
    if _norm(inv.get("seller")) != _norm(lc["beneficiary"]):
        flag("R06", "invoice", "seller", inv.get("seller"), lc["beneficiary"], "Invoice not issued by the beneficiary")
    if _norm(inv.get("buyer")) != _norm(lc["applicant"]):
        flag("R07", "invoice", "buyer", inv.get("buyer"), lc["applicant"], "Invoice not made out to the applicant")
    if inv.get("quantity") is not None and abs(inv["quantity"] - lc_qty) > lc_qty * tolerance + 1e-6:
        flag("R08", "invoice", "quantity", inv["quantity"], lc_qty, "Invoice quantity differs from the credit quantity")

    # ---- consistency across documents (Art. 14(d)/(e))
    qtys = {n: d.get("quantity") for n, d in (("invoice", inv), ("bill_of_lading", bl), ("packing_list", pl))}
    if len({q for q in qtys.values() if q is not None}) > 1:
        ref = qtys["invoice"]
        others = {n: q for n, q in qtys.items() if n != "invoice" and q is not None and q != ref}
        pct = max(abs(q - ref) / ref * 100 for q in others.values()) if ref and others else 0
        flag("R09", ",".join(others) or "bill_of_lading", "quantity", others, ref,
             f"Quantity inconsistent across documents ({pct:.1f}% deviation from invoice)")
    for name, d in (("bill_of_lading", bl), ("packing_list", pl)):
        gd = _norm(d.get("goods_description"))
        lcd = _norm(lc["goods_description"])
        if gd and lcd not in gd and gd not in lcd and not _general_terms_ok(d.get("goods_description"), lc["goods_description"]):
            flag("R10", name, "goods_description", d.get("goods_description"), lc["goods_description"],
                 "Goods description conflicts with the credit")
    if _norm(bl.get("consignee")) != _norm(lc["applicant"]):
        flag("R11", "bill_of_lading", "consignee", bl.get("consignee"), lc["applicant"], "Consignee is not the applicant")

    # ---- transport document (Art. 20 / 27)
    if _norm(bl.get("port_of_loading")) != _norm(lc["port_of_loading"]):
        flag("R12", "bill_of_lading", "port_of_loading", bl.get("port_of_loading"), lc["port_of_loading"],
             "Port of loading differs from the credit")
    if _norm(bl.get("port_of_discharge")) != _norm(lc["port_of_discharge"]):
        flag("R13", "bill_of_lading", "port_of_discharge", bl.get("port_of_discharge"), lc["port_of_discharge"],
             "Port of discharge differs from the credit")
    if bl.get("clean_on_board") is False:
        flag("R14", "bill_of_lading", "clean_on_board", False, True, "Bill of lading is claused (not clean on board)")

    # ---- dates (Art. 6, 14(c), 20(a)(ii))
    on_board = _date(bl.get("shipped_on_board_date"))
    latest = _date(lc.get("latest_shipment_date"))
    if on_board and latest and on_board > latest:
        flag("R15", "bill_of_lading", "shipped_on_board_date", on_board.isoformat(), latest.isoformat(),
             f"Shipped {(on_board - latest).days} day(s) after the latest shipment date")
    if on_board:
        deadline = on_board + timedelta(days=int(lc.get("presentation_period_days", 21)))
        if presentation_date > deadline:
            flag("R16", "presentation", "presentation_date", presentation_date.isoformat(), deadline.isoformat(),
                 "Documents presented after the presentation period")
    expiry = _date(lc.get("expiry_date"))
    if expiry and presentation_date > expiry:
        flag("R17", "presentation", "presentation_date", presentation_date.isoformat(), expiry.isoformat(),
             "Presented after the credit expiry date")

    # ---- shipment identity across documents (Art. 14(d)); externally checkable
    if _norm(bl.get("vessel")) and _norm(pl.get("vessel")) and _norm(bl["vessel"]) != _norm(pl["vessel"]):
        flag("R18", "packing_list", "vessel", pl["vessel"], bl["vessel"], "Vessel on packing list differs from the bill of lading")
    if _norm(bl.get("container_number")) and _norm(pl.get("container_number")) \
            and _norm(bl["container_number"]) != _norm(pl["container_number"]):
        flag("R19", "packing_list", "container_number", pl["container_number"], bl["container_number"],
             "Container on packing list differs from the bill of lading")
    return out


def _general_terms_ok(doc_desc, lc_desc) -> bool:
    """Art. 14(e): general terms are fine if every significant word in the document also appears in the credit."""
    words = [w for w in re.findall(r"[a-z0-9/]+", str(doc_desc or "").lower()) if len(w) > 2]
    lc_words = set(re.findall(r"[a-z0-9/]+", str(lc_desc or "").lower()))
    return bool(words) and all(w in lc_words for w in words)


# --------------------------------------------------------------------------- orchestration
def examine(deal_dir: str | Path, parser=None, presentation_date: Optional[date] = None) -> dict:
    deal_dir = Path(deal_dir)
    parser = parser or get_parser("auto")
    lc = json.loads((deal_dir / "deal.json").read_text())
    presentation_date = presentation_date or _date(lc.get("presentation_date")) or date.today()
    docs: dict[str, Optional[dict]] = {}
    for doc_type, fname in DOC_FILES.items():
        path = deal_dir / fname
        docs[doc_type] = parser.parse(doc_type, extract_text(path)) if path.exists() else None
    return summarize(lc, docs, presentation_date, parser.name)


def summarize(lc: dict, docs: dict, presentation_date: date, parser_name: str) -> dict:
    discrepancies = run_rules(lc, docs, presentation_date)
    fatal = sorted({d["rule_id"] for d in discrepancies if d["severity"] == "fatal"})
    k = len(discrepancies)
    return {
        "lc_number": lc["lc_number"],
        "parser": parser_name,
        "presentation_date": presentation_date.isoformat(),
        "documents": docs,
        "discrepancies": discrepancies,
        "k": k,
        "fatal": fatal,
        "verdict": "REFUSE" if fatal else ("COMPLIANT" if k == 0 else "DISCREPANT"),
    }


if __name__ == "__main__":
    import argparse

    ap = argparse.ArgumentParser()
    ap.add_argument("deal_dir")
    ap.add_argument("--parser", default="auto", choices=("auto", "groq", "template"))
    a = ap.parse_args()
    res = examine(a.deal_dir, get_parser(a.parser))
    print(json.dumps({k: v for k, v in res.items() if k != "documents"}, indent=2, default=str))
    raise SystemExit(0 if res["k"] == 0 else 2)
