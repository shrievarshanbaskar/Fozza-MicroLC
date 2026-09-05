"""Offline x402 tests: the starter kit's require_payment middleware in front of our oracle, talking to the
local facilitator over an in-process ASGI transport with a fake ledger submitter. No network.

Covers: 402 challenge shape, successful paid call, invoice (nonce) reuse rejected, wrong amount rejected.
"""
import base64
import json
import socket

import httpx
import pytest
from fastapi.testclient import TestClient
from xrpl.models.amounts import IssuedCurrencyAmount
from xrpl.models.transactions import Memo, Payment
from xrpl.transaction import sign
from xrpl.wallet import Wallet

from oracle.local_facilitator import make_app as make_facilitator, tx_hash_from_blob, verify_payment
from oracle.service import RLUSD_HEX, make_app as make_oracle, verify_signature
from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions

ISSUER = Wallet.create()
ORACLE = Wallet.create()
PAYER = Wallet.create()


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch):
    """Block every non-loopback connect (asyncio on Windows needs a loopback socketpair for its event loop)."""
    real = socket.socket.connect

    def guarded(self, addr, *a, **k):
        host = addr[0] if isinstance(addr, tuple) else str(addr)
        if host not in ("127.0.0.1", "::1", "localhost"):
            raise RuntimeError(f"network blocked: {addr}")
        return real(self, addr, *a, **k)

    monkeypatch.setattr(socket.socket, "connect", guarded)


@pytest.fixture
def stack():
    submitted = []

    def fake_submit(blob):
        submitted.append(blob)
        return {"success": True, "transaction": tx_hash_from_blob(blob)}

    fac_app = make_facilitator(rpc_url="http://fake", submitter=fake_submit)
    fac = AsyncFacilitatorClient(FacilitatorClientOptions(base_url="http://facilitator"))
    fac._client = httpx.AsyncClient(transport=httpx.ASGITransport(app=fac_app), base_url="http://facilitator")
    oracle = make_oracle(pay_to=ORACLE.classic_address, issuer=ISSUER.classic_address, signer=ORACLE, facilitator=fac)
    return TestClient(oracle), submitted


def presign(req: dict, value: str | None = None, seq: int = 1) -> str:
    """Build the PAYMENT-SIGNATURE header the kit client would: presigned Payment + invoice memo."""
    inv = req["extra"]["invoiceId"]
    tx = Payment(account=PAYER.classic_address, destination=req["payTo"], fee="12", sequence=seq,
                 last_ledger_sequence=99_999_999,
                 amount=IssuedCurrencyAmount(currency=req["asset"], issuer=req["extra"]["issuer"], value=value or req["amount"]),
                 memos=[Memo(memo_data=inv.encode().hex().upper())])
    blob = sign(tx, PAYER).blob()
    payload = {"x402Version": 2, "accepted": req, "payload": {"signedTxBlob": blob, "invoiceId": inv}}
    return base64.b64encode(json.dumps(payload).encode()).decode()


def test_registry_is_free_and_lists_two_providers(stack):
    client, _ = stack
    r = client.get("/registry")
    assert r.status_code == 200
    provs = r.json()["providers"]
    assert len(provs) == 2 and provs[0]["price_rlusd"] != provs[1]["price_rlusd"]
    assert set(provs[0]["coverage"]) != set(provs[1]["coverage"])


def test_402_challenge_shape(stack):
    client, _ = stack
    r = client.get("/verify/harbor-ais", params={"bl": "TUTSIN-26-08857"})
    assert r.status_code == 402 and "PAYMENT-REQUIRED" in r.headers
    body = r.json()
    assert body["x402Version"] == 2
    req = body["accepts"][0]
    assert req["scheme"] == "exact" and req["network"] == "xrpl:1"
    assert req["asset"] == RLUSD_HEX and req["amount"] == "0.05" and req["payTo"] == ORACLE.classic_address
    assert req["extra"]["issuer"] == ISSUER.classic_address and len(req["extra"]["invoiceId"]) >= 16
    assert req["maxTimeoutSeconds"] == 300
    # a second challenge issues a fresh nonce
    r2 = client.get("/verify/harbor-ais", params={"bl": "TUTSIN-26-08857"})
    assert r2.json()["accepts"][0]["extra"]["invoiceId"] != req["extra"]["invoiceId"]


def test_paid_call_returns_signed_telemetry_and_settles_once(stack):
    client, submitted = stack
    req = client.get("/verify/harbor-ais", params={"bl": "TUTSIN-26-08857"}).json()["accepts"][0]
    header = presign(req)
    r = client.get("/verify/harbor-ais", params={"bl": "TUTSIN-26-08857"}, headers={"PAYMENT-SIGNATURE": header})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["telemetry"]["atd"] == "2026-08-23" and body["telemetry"]["vessel"] == "MV Sagar Kranti"
    assert verify_signature(body)
    settlement = json.loads(base64.b64decode(r.headers["PAYMENT-RESPONSE"]))
    assert settlement["success"] and settlement["transaction"] == tx_hash_from_blob(json.loads(base64.b64decode(header))["payload"]["signedTxBlob"])
    assert len(submitted) == 1

    # replaying the same payment must not buy a second answer
    r2 = client.get("/verify/harbor-ais", params={"bl": "TUTSIN-26-08857"}, headers={"PAYMENT-SIGNATURE": header})
    assert r2.status_code in (400, 402) and len(submitted) == 1


def test_wrong_amount_is_rejected_without_settlement(stack):
    client, submitted = stack
    req = client.get("/verify/portlog-premium", params={"bl": "TUTSIN-26-08857"}).json()["accepts"][0]
    assert req["amount"] == "0.20"
    header = presign(req, value="0.05")  # underpay the premium provider
    r = client.get("/verify/portlog-premium", params={"bl": "TUTSIN-26-08857"}, headers={"PAYMENT-SIGNATURE": header})
    assert r.status_code == 402 and "verify_failed" in r.json().get("error", "")
    assert submitted == []


def test_verify_payment_pure_checks():
    req = {"scheme": "exact", "network": "xrpl:1", "asset": RLUSD_HEX, "amount": "0.05", "payTo": ORACLE.classic_address,
           "maxTimeoutSeconds": 300, "extra": {"issuer": ISSUER.classic_address, "invoiceId": "INV1"}}
    header = presign(req)
    payload = json.loads(base64.b64decode(header))
    ok, reason, payer = verify_payment(payload, req, set())
    assert ok and payer == PAYER.classic_address
    assert verify_payment(payload, req, {"INV1"}) == (False, "invoice_already_settled", PAYER.classic_address)
    assert verify_payment(payload, dict(req, payTo=PAYER.classic_address), set())[1] == "destination_mismatch"


def test_unknown_bl_is_404_after_payment(stack):
    client, submitted = stack
    req = client.get("/verify/harbor-ais", params={"bl": "NOPE-1"}).json()["accepts"][0]
    r = client.get("/verify/harbor-ais", params={"bl": "NOPE-1"}, headers={"PAYMENT-SIGNATURE": presign(req)})
    assert r.status_code == 404 and "no record" in r.json()["detail"]
