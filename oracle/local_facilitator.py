"""Team: Fozza · Product: MicroLC — minimal x402 facilitator for XRPL (fallback / offline tests).

Speaks the same three endpoints the XRPL AI Starter Kit's `require_payment` middleware calls:

    GET  /supported                      -> kinds
    POST /verify  {paymentPayload, paymentRequirements} -> {isValid, invalidReason, payer}
    POST /settle  {paymentPayload, paymentRequirements} -> {success, transaction, network, payer}

The hosted facilitator at xrpl-facilitator-testnet.t54.ai is the default; this one exists so the
oracle keeps working when that host is unreachable and so the 402 flow can be tested offline with
a fake submitter. Verification mirrors the published xrpl-scheme checks: Payment type, destination,
exact amount (drops for XRP, currency/issuer/value for IOUs), LastLedgerSequence present, invoice
binding (Memo = hex(invoiceId) or InvoiceID = sha256(invoiceId)), no partial payments, and single
use of each invoice.
"""
from __future__ import annotations

import hashlib
import os
import time
from typing import Callable, Optional

from fastapi import FastAPI
from pydantic import BaseModel
from xrpl.clients import JsonRpcClient
from xrpl.core.binarycodec import decode
from xrpl.models.requests import SubmitOnly, Tx

NETWORK = os.getenv("XRPL_NETWORK", "xrpl:1")
TF_PARTIAL_PAYMENT = 0x00020000


class FacilitatorBody(BaseModel):
    paymentPayload: dict
    paymentRequirements: dict
    extensions: Optional[dict] = None


def tx_hash_from_blob(blob_hex: str) -> str:
    """Transaction hash = first 256 bits of SHA-512 over prefix 'TXN\\0' + serialized tx."""
    return hashlib.sha512(bytes.fromhex("54584E00") + bytes.fromhex(blob_hex)).hexdigest()[:64].upper()


def verify_payment(payload: dict, reqs: dict, used: set[str]) -> tuple[bool, str, Optional[str]]:
    """Pure verification of a presigned Payment blob against the requirements."""
    try:
        blob = payload["payload"]["signedTxBlob"]
        invoice_id = payload["payload"].get("invoiceId") or (reqs.get("extra") or {}).get("invoiceId")
        tx = decode(blob)
    except Exception as exc:
        return False, f"undecodable_blob:{type(exc).__name__}", None
    payer = tx.get("Account")
    if payload.get("x402Version") != 2 or reqs.get("scheme") != "exact" or reqs.get("network") != NETWORK:
        return False, "unsupported_envelope", payer
    if tx.get("TransactionType") != "Payment":
        return False, "not_a_payment", payer
    if tx.get("Destination") != reqs.get("payTo"):
        return False, "destination_mismatch", payer
    if not tx.get("LastLedgerSequence"):
        return False, "missing_last_ledger_sequence", payer
    if int(tx.get("Flags", 0)) & TF_PARTIAL_PAYMENT:
        return False, "partial_payment_not_allowed", payer
    amount = tx.get("Amount")
    asset = reqs.get("asset")
    if asset == "XRP":
        if not isinstance(amount, str) or amount != str(reqs.get("amount")):
            return False, "amount_mismatch", payer
    else:
        issuer = (reqs.get("extra") or {}).get("issuer")
        if not isinstance(amount, dict) or amount.get("currency") != asset or amount.get("issuer") != issuer:
            return False, "asset_mismatch", payer
        if _dec(amount.get("value")) != _dec(reqs.get("amount")):
            return False, "amount_mismatch", payer
        send_max = tx.get("SendMax")
        if send_max is not None and (not isinstance(send_max, dict) or send_max.get("currency") != asset):
            return False, "cross_currency_not_allowed", payer
    if not invoice_id:
        return False, "missing_invoice_id", payer
    if invoice_id in used:
        return False, "invoice_already_settled", payer
    memo_hex = invoice_id.encode("utf-8").hex().upper()
    memos = [m.get("Memo", {}).get("MemoData", "").upper() for m in tx.get("Memos", [])]
    inv_field = hashlib.sha256(invoice_id.encode("utf-8")).hexdigest().upper()
    if memo_hex not in memos and (tx.get("InvoiceID") or "").upper() != inv_field:
        return False, "invoice_binding_missing", payer
    return True, "", payer


def _dec(v):
    from decimal import Decimal

    try:
        return Decimal(str(v)).normalize()
    except Exception:
        return None


def make_app(rpc_url: Optional[str] = None, submitter: Optional[Callable[[str], dict]] = None) -> FastAPI:
    """`submitter(blob_hex) -> {"success", "transaction"}` can be injected for offline tests."""
    rpc_url = rpc_url or os.getenv("XRPL_RPC_URL", "https://s.altnet.rippletest.net:51234/")
    used: set[str] = set()
    app = FastAPI(title="MicroLC local x402 facilitator")

    def _submit_live(blob_hex: str) -> dict:
        client = JsonRpcClient(rpc_url)
        resp = client.request(SubmitOnly(tx_blob=blob_hex)).result
        h = resp.get("tx_json", {}).get("hash") or tx_hash_from_blob(blob_hex)
        eng = resp.get("engine_result", "")
        if not (eng == "tesSUCCESS" or eng.startswith("ter")):
            return {"success": False, "transaction": h, "errorReason": eng}
        deadline = time.time() + 60
        while time.time() < deadline:
            r = client.request(Tx(transaction=h)).result
            if r.get("validated"):
                code = (r.get("meta") or {}).get("TransactionResult")
                return {"success": code == "tesSUCCESS", "transaction": h, "errorReason": None if code == "tesSUCCESS" else code}
            time.sleep(1)
        return {"success": False, "transaction": h, "errorReason": "validation_timeout"}

    submit = submitter or _submit_live

    @app.get("/supported")
    def supported():
        return {"kinds": [{"x402Version": 2, "scheme": "exact", "network": NETWORK}], "extensions": [], "signers": {}}

    @app.post("/verify")
    def verify(body: FacilitatorBody):
        ok, reason, payer = verify_payment(body.paymentPayload, body.paymentRequirements, used)
        return {"isValid": ok, "invalidReason": reason or None, "payer": payer}

    @app.post("/settle")
    def settle(body: FacilitatorBody):
        ok, reason, payer = verify_payment(body.paymentPayload, body.paymentRequirements, used)
        if not ok:
            return {"success": False, "transaction": "", "network": NETWORK, "payer": payer, "errorReason": reason}
        invoice_id = body.paymentPayload["payload"].get("invoiceId")
        result = submit(body.paymentPayload["payload"]["signedTxBlob"])
        if result.get("success"):
            used.add(invoice_id)  # single use: a replayed invoice can never settle twice
        return {"success": bool(result.get("success")), "transaction": result.get("transaction", ""),
                "network": NETWORK, "payer": payer, "errorReason": result.get("errorReason")}

    app.state.used_invoices = used
    return app


app = make_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=int(os.getenv("FACILITATOR_PORT", "8011")))
