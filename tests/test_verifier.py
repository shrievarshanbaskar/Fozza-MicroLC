"""Verifier agent: pure guards, provider policy, k mappings, skip and failure paths (no network)."""
import socket
from decimal import Decimal

import pytest

from negotiator_graph import AgentOffer, ScriptedAgent, build_graph, initial_state, run
from settlement_engine import REFUSED_M
from verifier_agent import (
    BudgetGuard, OracleClient, apply_verdicts, choose_provider, judge, make_verifier, should_verify,
)

PROVIDERS = [
    {"id": "harbor-ais", "price_rlusd": "0.05", "coverage": ["vessel", "voyage", "container_number", "atd",
                                                             "port_of_loading", "port_of_discharge"], "latency_ms": 450, "endpoint": "http://o/verify/harbor-ais"},
    {"id": "portlog-premium", "price_rlusd": "0.20", "coverage": ["vessel", "voyage", "container_number", "seal_number", "atd",
                                                                  "gate_in", "port_of_loading", "port_of_discharge"], "latency_ms": 120, "endpoint": "http://o/verify/portlog-premium"},
]
REGISTRY = {"providers": PROVIDERS}
SHIP = {"bl_number": "TUTSIN-26-08857", "container_number": "TCLU7702410", "vessel": "MV Sagar Kranti"}
D_QTY = {"rule_id": "R09", "code": "QTY_INCONSISTENT", "doc": "bill_of_lading", "field": "quantity", "found": 3900,
         "expected": 4000, "severity": "negotiable", "checkable": False, "article": "UCP600-14d", "message": "short"}
D_LATE = {"rule_id": "R15", "code": "LATE_SHIPMENT", "doc": "bill_of_lading", "field": "shipped_on_board_date",
          "found": "2026-08-23", "expected": "2026-08-20", "severity": "negotiable", "checkable": True, "article": "UCP600-20a-ii", "message": "late"}
D_CONT = {"rule_id": "R19", "code": "CONTAINER_MISMATCH", "doc": "packing_list", "field": "container_number",
          "found": "MSKU8811207", "expected": "TCLU7702410", "severity": "negotiable", "checkable": True, "article": "UCP600-14d", "message": "box"}


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", lambda *a, **k: (_ for _ in ()).throw(RuntimeError("network blocked")))


class FakeClient(OracleClient):
    def __init__(self, telemetry, ok=True, status=200, fail=False):
        super().__init__(registry_url="http://o", session=object())
        self.telemetry, self.ok, self.status, self.fail, self.calls = telemetry, ok, status, fail, []

    def discover(self):
        return REGISTRY

    def query(self, provider, params):
        self.calls.append((provider["id"], params))
        if self.fail:
            raise ConnectionError("oracle down")
        body = {"telemetry": self.telemetry, "signature": "sig"} if self.ok else {"detail": "no record"}
        return {"ok": self.ok, "status": self.status, "body": body, "tx_hash": "ABC123" if self.ok or self.status == 404 else None,
                "latency_ms": 5, "paid": True}


def deal(amount="10000"):
    return {"deal_id": "v1", "lc_amount": amount, "lc_number": "MLC-TEST", "shipment": SHIP}


def test_trigger_threshold():
    assert should_verify("10000", [D_LATE], "0.05")[0]  # 100 >= 1.0
    assert not should_verify("10000", [D_QTY], "0.05")[0]  # nothing checkable
    assert not should_verify("50", [D_LATE], "0.05")[0]  # 0.5 < 1.0


def test_budget_guard_caps_calls_and_spend():
    g = BudgetGuard()
    assert g.can_spend("0.20")[0]
    g.record("0.20", "portlog-premium", "H1")
    assert not g.can_spend("0.20")[0] and g.can_spend("0.05")[0]
    g.record("0.05", "harbor-ais", "H2")
    assert g.spent == Decimal("0.25") and not g.can_spend("0.01")[0]
    g2 = BudgetGuard()
    for i in range(3):
        g2.record("0.01", "harbor-ais", f"H{i}")
    assert not g2.can_spend("0.01")[0] and "call cap" in g2.can_spend("0.01")[1]


def test_provider_policy_cheapest_covering():
    p, why = choose_provider(PROVIDERS, {"atd"}, BudgetGuard())
    assert p["id"] == "harbor-ais" and "cheapest" in why
    p, _ = choose_provider(PROVIDERS, {"seal_number"}, BudgetGuard())
    assert p["id"] == "portlog-premium"
    g = BudgetGuard(); g.record("0.20", "x", None)
    assert choose_provider(PROVIDERS, {"seal_number"}, g)[0] is None


def test_judge_three_mappings():
    assert judge(D_LATE, SHIP, {"atd": "2026-08-23"})[0] == "CONFIRMS"
    assert judge(D_LATE, SHIP, {"atd": "2026-08-19"})[0] == "CONTRADICTS"
    assert judge(D_LATE, SHIP, {"atd": "2026-08-27"})[0] == "MISMATCH"
    assert judge(D_CONT, SHIP, {"vessel": "MV Sagar Kranti", "container_number": "TCLU7702410"})[0] == "CONFIRMS"
    assert judge(D_CONT, SHIP, {"vessel": "MV Ocean Pioneer", "container_number": "TCLU7702410"})[0] == "MISMATCH"


def test_apply_verdicts():
    ds, k = apply_verdicts([D_QTY, D_LATE], [{"rule_id": "R15", "verdict": "CONFIRMS", "summary": ""}])
    assert k == 2
    ds, k = apply_verdicts([D_QTY, D_LATE], [{"rule_id": "R15", "verdict": "CONTRADICTS", "summary": ""}])
    assert k == 1 and ds[0]["rule_id"] == "R09"
    ds, k = apply_verdicts([D_CONT], [{"rule_id": "R19", "verdict": "MISMATCH", "summary": "x"}])
    assert k == 2 and ds[-1]["rule_id"] == "R20" and ds[-1]["severity"] == "fatal"


def _graph_with(client, buyer_script, seller_script):
    verifier = make_verifier(client)
    return build_graph(ScriptedAgent("buyer", buyer_script), ScriptedAgent("seller", seller_script), verifier=verifier)


def test_confirms_keeps_k_and_injects_evidence():
    client = FakeClient({"atd": "2026-08-23", "vessel": "MV Sagar Kranti", "container_number": "TCLU7702410"})
    buyer = ScriptedAgent("buyer", [AgentOffer(action="propose", rungs=2, cited=["R09", "R15"], rationale="r")])
    seller = ScriptedAgent("seller", [AgentOffer(action="accept", rungs=2, cited=[], rationale="r")])
    st = run(build_graph(buyer, seller, verifier=make_verifier(client)),
             initial_state(deal(), {"discrepancies": [D_QTY, D_LATE], "k": 2}))
    assert st["k"] == 2 and st["evidence"][0]["verdict"] == "CONFIRMS"
    assert client.calls == [("harbor-ais", {"bl": "TUTSIN-26-08857", "container": "TCLU7702410"})]
    assert [e["action"] for e in st["offers"] if e["actor"] == "verifier"] == ["discover", "decide", "pay", "verify"]
    assert buyer.seen[0]["evidence"][0]["verdict"] == "CONFIRMS"  # agents see the evidence
    assert st["status"] == "CLOSED" and st["agreed_rungs"] == 2


def test_contradicts_drops_and_recomputes_k():
    client = FakeClient({"atd": "2026-08-19"})
    buyer = ScriptedAgent("buyer", [AgentOffer(action="propose", rungs=1, cited=["R09"], rationale="r")])
    seller = ScriptedAgent("seller", [AgentOffer(action="accept", rungs=1, cited=[], rationale="r")])
    st = run(build_graph(buyer, seller, verifier=make_verifier(client)),
             initial_state(deal(), {"discrepancies": [D_QTY, D_LATE], "k": 2}))
    assert st["k"] == 1 and [d["rule_id"] for d in st["discrepancies"]] == ["R09"]
    assert st["agreed_rungs"] == 1 and st["payout"]["seller"] == "9900"


def test_mismatch_raises_fraud_and_refuses():
    client = FakeClient({"vessel": "MV Ocean Pioneer", "container_number": "TCLU7702410", "atd": "2026-08-18"})
    st = run(_graph_with(client, [], []), initial_state(deal(), {"discrepancies": [D_CONT], "k": 1}))
    assert st["route"] == "refuse" and st["payout"]["m"] == REFUSED_M
    assert any(d["rule_id"] == "R20" for d in st["discrepancies"])
    assert "MV Ocean Pioneer" in st["refusal_notice"]


def test_skip_when_nothing_checkable_or_too_small():
    client = FakeClient({"atd": "x"})
    st = run(_graph_with(client, [AgentOffer(action="propose", rungs=1, cited=["R09"], rationale="r")],
                         [AgentOffer(action="accept", rungs=1, cited=[], rationale="r")]),
             initial_state(deal(), {"discrepancies": [D_QTY], "k": 1}))
    assert client.calls == [] and st["verifier"]["triggered"] is False
    st = run(_graph_with(client, [AgentOffer(action="propose", rungs=1, cited=["R15"], rationale="r")],
                         [AgentOffer(action="accept", rungs=1, cited=[], rationale="r")]),
             initial_state(deal("50"), {"discrepancies": [D_LATE], "k": 1}))
    assert client.calls == [] and "20x" in st["verifier"]["reason"]


def test_oracle_failure_warns_and_proceeds():
    client = FakeClient({}, fail=True)
    st = run(_graph_with(client, [AgentOffer(action="propose", rungs=2, cited=["R09", "R15"], rationale="r")],
                         [AgentOffer(action="accept", rungs=2, cited=[], rationale="r")]),
             initial_state(deal(), {"discrepancies": [D_QTY, D_LATE], "k": 2}))
    assert any(e["action"] == "warning" for e in st["offers"])
    assert st["k"] == 2 and st["status"] == "CLOSED"
