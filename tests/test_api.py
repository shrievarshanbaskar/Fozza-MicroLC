"""API tests (offline): create -> examine (template parser) -> mock negotiation SSE -> plan-only settlement."""
import json
import os
import shutil
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

os.environ.pop("GROQ_API_KEY", None)  # force template parser + mock agents in this process
import main  # noqa: E402


@pytest.fixture(scope="module")
def client(tmp_path_factory):
    tmp = tmp_path_factory.mktemp("state")
    main.STATE, main.DEALS = tmp, tmp / "deals"
    yield TestClient(main.app)
    shutil.rmtree(tmp, ignore_errors=True)


def parse_sse(text: str):
    events = []
    for block in text.strip().split("\n\n"):
        ev, data = None, None
        for line in block.splitlines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
        if ev:
            events.append((ev, data))
    return events


def test_env_and_create(client):
    assert client.get("/api/env").json()["presets"] == ["clean", "discrepant", "fraudulent"]
    r = client.post("/api/deal/create", json={"preset": "discrepant"})
    assert r.status_code == 200
    st = r.json()
    assert st["status"] == "CREATED" and st["lc"]["lc_number"] == "MLC-SG-2026-0142"
    assert client.get(f"/api/deal/{st['deal_id']}/documents/invoice.pdf").headers["content-type"] == "application/pdf"


def test_examine_and_mock_negotiation_stream(client):
    deal_id = client.post("/api/deal/create", json={"preset": "discrepant"}).json()["deal_id"]
    st = client.post(f"/api/deal/{deal_id}/examine", params={"parser": "template"}).json()
    assert st["examination"]["k"] == 2 and st["status"] == "EXAMINED"
    r = client.get(f"/api/deal/{deal_id}/negotiate/stream", params={"mode": "mock"})
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
    events = parse_sse(r.text)
    kinds = [k for k, _ in events]
    assert kinds[0] == "meta" and kinds[-1] == "done"
    agents = [d for k, d in events if k == "agent"]
    assert any(a["actor"] == "verifier" and a["action"] == "pay" for a in agents)  # verify beat
    assert any(a["actor"] == "referee" and a["action"] == "bounce" for a in agents)  # bounce beat
    assert {"ts_ms", "round", "actor", "action", "rungs", "cited", "rationale"} <= set(agents[0])
    settlement = [d for k, d in events if k == "settlement"]
    assert len(settlement) == 7 and all(s["status"].startswith("PLANNED_") for s in settlement)
    done = events[-1][1]
    assert done["status"] == "CLOSED" and 0 <= done["agreed_rungs"] <= 2
    assert done["payout"]["seller"] in ("9800", "9900", "10000")
    # replay from persisted state, no re-run
    r2 = client.get(f"/api/deal/{deal_id}/negotiate/stream", params={"mode": "mock"})
    ev2 = parse_sse(r2.text)
    assert ev2[0][1]["replay"] is True and [k for k, _ in ev2].count("agent") == len(agents)
    assert client.get(f"/api/deal/{deal_id}").json()["status"] == "NEGOTIATED"


def test_clean_and_fraud_paths(client):
    clean = client.post("/api/deal/create", json={"preset": "clean"}).json()["deal_id"]
    client.post(f"/api/deal/{clean}/examine", params={"parser": "template"})
    done = parse_sse(client.get(f"/api/deal/{clean}/negotiate/stream", params={"mode": "mock"}).text)[-1][1]
    assert done["agreed_rungs"] == 0 and done["payout"]["seller"] == "10000"
    fraud = client.post("/api/deal/create", json={"preset": "fraudulent"}).json()["deal_id"]
    client.post(f"/api/deal/{fraud}/examine", params={"parser": "template"})
    ev = parse_sse(client.get(f"/api/deal/{fraud}/negotiate/stream", params={"mode": "mock"}).text)
    # mock verifier confirms (no fraud); container mismatch stays negotiable with k=1
    assert ev[-1][1]["status"] == "CLOSED" and ev[-1][1]["agreed_rungs"] <= 1


def test_manual_settle_and_feed(client):
    deal_id = client.post("/api/deal/create", json={"preset": "discrepant"}).json()["deal_id"]
    client.post(f"/api/deal/{deal_id}/examine", params={"parser": "template"})
    r = client.post(f"/api/deal/{deal_id}/settle", json={"m": 2})
    assert r.status_code == 200 and r.json()["m"] == 2 and len(r.json()["events"]) == 7
    assert client.get("/api/feed", params={"deal": deal_id}).json() == []
    assert any(d["deal_id"] == deal_id for d in client.get("/api/deals").json())


# --------------------------------------------------------------------------- lock pre-flight (fake ledger)
import time  # noqa: E402
from decimal import Decimal  # noqa: E402

from test_lock_robustness import FakeWallet, FundedFake  # noqa: E402
from xrpl_escrow import TxResult  # noqa: E402


class TopupFake(FundedFake):
    """FundedFake plus the two calls top_up() makes: trust-line limit and an issuer mint."""

    def trust_limit(self, address, issuer):
        return Decimal("1000000000")

    def issue(self, issuer_wallet, destination, value):
        self.balances[destination] += Decimal(str(value))
        return TxResult(True, "MINT1", "tesSUCCESS")


ROLES = ("issuer", "buyer", "seller", "platform")
FAKE_WALLETS = {"rpc_url": None, "wallets": {k: {"address": f"r{k.upper()}"} for k in ROLES},
                "_wallets": {k: FakeWallet(f"r{k.upper()}") for k in ROLES}}


def _examined(client, preset="clean"):
    deal_id = client.post("/api/deal/create", json={"preset": preset}).json()["deal_id"]
    client.post(f"/api/deal/{deal_id}/examine", params={"parser": "template"})
    return deal_id


def _wait_not_locking(client, deal_id, seconds=5.0):
    deadline = time.time() + seconds
    while time.time() < deadline:
        st = client.get(f"/api/deal/{deal_id}").json()
        if st["status"] != "LOCKING":
            return st
        time.sleep(0.05)
    return client.get(f"/api/deal/{deal_id}").json()


def test_lock_preflight_warns_and_stays_examined_without_auto_topup(client, monkeypatch):
    ledger = TopupFake(buyer_balance="500")
    monkeypatch.setattr(main, "_wallets", lambda: FAKE_WALLETS)
    monkeypatch.setattr(main, "_ledger", lambda: ledger)
    monkeypatch.delenv("DEMO_AUTO_TOPUP", raising=False)
    deal_id = _examined(client)
    st = client.post(f"/api/deal/{deal_id}/lock").json()
    assert st["status"] == "EXAMINED" and st["escrow"] is None
    w = st["warnings"][-1]
    assert w["code"] == "INSUFFICIENT_RLUSD"
    assert "need 10100" in w["message"] and "have 500" in w["message"] and "scripts/topup_buyer.py" in w["message"]
    assert ledger.creates == 0 and ledger.balances["rBUYER"] == Decimal("500")


def test_lock_preflight_auto_topup_mints_then_locks(client, monkeypatch):
    ledger = TopupFake(buyer_balance="500")
    monkeypatch.setattr(main, "_wallets", lambda: FAKE_WALLETS)
    monkeypatch.setattr(main, "_ledger", lambda: ledger)
    monkeypatch.setenv("DEMO_AUTO_TOPUP", "true")
    deal_id = _examined(client)
    st = client.post(f"/api/deal/{deal_id}/lock").json()
    assert st["status"] == "LOCKING"
    info = [w for w in st["warnings"] if w["code"] == "INFO"]
    assert info[-1]["message"] == "Demo top-up: minted 199500 RLUSD from test issuer"
    assert any(f.get("kind") == "topup" and f["hash"] == "MINT1" for f in st["ledger_feed"])
    st = _wait_not_locking(client, deal_id)
    assert st["status"] == "LOCKED" and all(t["status"] == "LOCKED" for t in st["escrow"]["tranches"])
    assert ledger.balances["rBUYER"] == Decimal("200000") - Decimal("10100")


def test_lock_preflight_skips_topup_when_funded(client, monkeypatch):
    ledger = TopupFake(buyer_balance="50000")
    monkeypatch.setattr(main, "_wallets", lambda: FAKE_WALLETS)
    monkeypatch.setattr(main, "_ledger", lambda: ledger)
    monkeypatch.setenv("DEMO_AUTO_TOPUP", "true")
    deal_id = _examined(client)
    st = client.post(f"/api/deal/{deal_id}/lock").json()
    assert st["status"] == "LOCKING" and not any(w["code"] == "INFO" for w in st.get("warnings", []))
    st = _wait_not_locking(client, deal_id)
    assert st["status"] == "LOCKED" and ledger.balances["rBUYER"] == Decimal("50000") - Decimal("10100")
