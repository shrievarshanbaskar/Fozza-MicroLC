"""Team: Fozza · Product: MicroLC — shipment-telemetry oracle, paid per call over x402 (XRPL AI Starter Kit).

    GET /registry                      free   -> two providers with different price / coverage / latency
    GET /verify/harbor-ais?bl=...      0.05 RLUSD (x402 exact scheme, RLUSD IOU on xrpl:1)
    GET /verify/portlog-premium?bl=... 0.20 RLUSD

The paid routes are protected by `x402_xrpl.server.require_payment` from the starter kit: the first
request gets HTTP 402 with a v2 PaymentRequired body (amount, asset, payTo, network, a single-use
invoiceId nonce and maxTimeoutSeconds). The client pays on XRPL with the invoice bound in a Memo and
retries with PAYMENT-SIGNATURE; the middleware has a facilitator verify and settle the presigned
Payment on-ledger and only then calls our handler, which returns telemetry signed with the oracle's
XRPL key so the buyer can prove where the evidence came from.

Truth table is keyed by bill-of-lading number and covers the three fixture presets.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from typing import Optional

from dotenv import load_dotenv
from fastapi import FastAPI, HTTPException, Query, Request
from xrpl.core import keypairs
from xrpl.wallet import Wallet

from x402_xrpl.facilitator import AsyncFacilitatorClient, FacilitatorClientOptions
from x402_xrpl.server import require_payment

load_dotenv()

RLUSD_HEX = "524C555344000000000000000000000000000000"
NETWORK = os.getenv("XRPL_NETWORK", "xrpl:1")
# The hosted testnet facilitator rejects payments whose requirements carry no sourceTag
# (verify_failed:source_tag_mismatch); the SDK's documented analytics tag satisfies it.
SOURCE_TAG = int(os.getenv("X402_SOURCE_TAG", "804681468"))

REGISTRY = [
    {
        "id": "harbor-ais",
        "name": "HarborWatch AIS feed",
        "price_rlusd": "0.05",
        "coverage": ["vessel", "voyage", "container_number", "atd", "port_of_loading", "port_of_discharge"],
        "latency_ms": 450,
        "path": "/verify/harbor-ais",
        "description": "Vessel position history and departure times reconciled with carrier manifests.",
    },
    {
        "id": "portlog-premium",
        "name": "PortLog Premium terminal records",
        "price_rlusd": "0.20",
        "coverage": ["vessel", "voyage", "container_number", "seal_number", "atd", "gate_in",
                     "port_of_loading", "port_of_discharge"],
        "latency_ms": 120,
        "path": "/verify/portlog-premium",
        "description": "Terminal operating system events: gate-in, load, seal checks, actual departure.",
    },
]

# What actually happened, per bill of lading (the carrier's system of record).
TRUTH = {
    "TUTSIN-26-08841": {"vessel": "MV Sagar Kranti", "voyage": "SK-0917E", "container_number": "TCLU7702410",
                        "seal_number": "SL-448127", "atd": "2026-08-18", "gate_in": "2026-08-16",
                        "port_of_loading": "Tuticorin, India", "port_of_discharge": "Singapore"},
    "TUTSIN-26-08857": {"vessel": "MV Sagar Kranti", "voyage": "SK-0917E", "container_number": "TCLU7702410",
                        "seal_number": "SL-448127", "atd": "2026-08-23", "gate_in": "2026-08-21",
                        "port_of_loading": "Tuticorin, India", "port_of_discharge": "Singapore"},
    "TUTSIN-26-08902": {"vessel": "MV Ocean Pioneer", "voyage": "OP-2231W", "container_number": "TCLU7702410",
                        "seal_number": "SL-991004", "atd": "2026-08-18", "gate_in": "2026-08-17",
                        "port_of_loading": "Tuticorin, India", "port_of_discharge": "Singapore"},
}


def _load_wallets() -> dict:
    p = Path(os.getenv("MICROLC_WALLETS", "state/wallets.json"))
    return json.loads(p.read_text()) if p.exists() else {}


def make_app(pay_to: Optional[str] = None, issuer: Optional[str] = None, signer: Optional[Wallet] = None,
             facilitator_url: Optional[str] = None, facilitator: Optional[AsyncFacilitatorClient] = None,
             simulate_latency: bool = False) -> FastAPI:
    wallets = _load_wallets().get("wallets", {})
    pay_to = pay_to or os.getenv("ORACLE_PAY_TO") or wallets.get("oracle", {}).get("address")
    issuer = issuer or os.getenv("RLUSD_ISSUER") or wallets.get("issuer", {}).get("address")
    if signer is None and wallets.get("oracle", {}).get("seed"):
        signer = Wallet.from_seed(wallets["oracle"]["seed"])
    facilitator_url = facilitator_url or os.getenv("XRPL_FACILITATOR_URL", "https://xrpl-facilitator-testnet.t54.ai")
    if not (pay_to and issuer):
        raise RuntimeError("oracle needs pay_to + issuer (state/wallets.json or ORACLE_PAY_TO/RLUSD_ISSUER)")
    fac = facilitator or AsyncFacilitatorClient(FacilitatorClientOptions(base_url=facilitator_url))

    app = FastAPI(title="MicroLC shipment oracle (x402)")
    for prov in REGISTRY:
        app.middleware("http")(require_payment(
            path=prov["path"], price=prov["price_rlusd"], pay_to_address=pay_to, network=NETWORK,
            asset=RLUSD_HEX, issuer=issuer, facilitator=fac, resource=f"microlc:oracle:{prov['id']}",
            description=prov["description"], max_timeout_seconds=300, source_tag=SOURCE_TAG,
        ))

    @app.get("/registry")
    def registry(request: Request):
        base = str(request.base_url).rstrip("/")
        return {"network": NETWORK, "asset": "RLUSD", "asset_hex": RLUSD_HEX, "issuer": issuer, "pay_to": pay_to,
                "signer_public_key": signer.public_key if signer else None,
                "providers": [{**p, "endpoint": base + p["path"]} for p in REGISTRY]}

    def _lookup(provider: dict, bl: str, container: Optional[str]) -> dict:
        rec = TRUTH.get(bl.strip().upper())
        if rec is None:
            raise HTTPException(status_code=404, detail=f"no record for bill of lading {bl}")
        if simulate_latency:
            time.sleep(provider["latency_ms"] / 1000)
        fields = {k: rec[k] for k in provider["coverage"] if k in rec}
        body = {"provider": provider["id"], "bl_number": bl.strip().upper(), "queried_container": container,
                "container_match": (container or "").strip().upper() == rec["container_number"],
                "telemetry": fields, "observed_at_ms": int(time.time() * 1000), "network": NETWORK}
        canonical = json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
        if signer is not None:
            body["signature"] = keypairs.sign(canonical, signer.private_key)
            body["signer_public_key"] = signer.public_key
        return body

    @app.get("/verify/harbor-ais")
    def harbor(bl: str = Query(...), container: Optional[str] = None):
        return _lookup(REGISTRY[0], bl, container)

    @app.get("/verify/portlog-premium")
    def portlog(bl: str = Query(...), container: Optional[str] = None):
        return _lookup(REGISTRY[1], bl, container)

    @app.get("/health")
    def health():
        return {"ok": True, "facilitator": facilitator_url, "pay_to": pay_to}

    return app


def verify_signature(body: dict) -> bool:
    """Anyone can check the telemetry came from the oracle's XRPL key."""
    sig, pub = body.get("signature"), body.get("signer_public_key")
    if not (sig and pub):
        return False
    payload = {k: v for k, v in body.items() if k not in ("signature", "signer_public_key")}
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return keypairs.is_valid_message(canonical, bytes.fromhex(sig), pub)


if __name__ == "__main__":
    import uvicorn

    uvicorn.run(make_app(simulate_latency=True), host="127.0.0.1", port=int(os.getenv("ORACLE_PORT", "8001")))
