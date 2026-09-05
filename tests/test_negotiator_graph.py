"""Offline negotiation-graph tests with scripted agents under a socket guard (no network allowed)."""
import random
import socket

import pytest

from negotiator_graph import (
    MAX_ROUNDS, AgentOffer, ScriptedAgent, build_graph, check_offer, clamp_offer, decide_route, initial_state, run,
    stream,
)
from settlement_engine import REFUSED_M

DEAL = {"deal_id": "t1", "lc_amount": "10000", "lc_number": "MLC-TEST", "applicant": "Buyer Co", "beneficiary": "Seller Co"}
D_QTY = {"rule_id": "R09", "code": "QTY_INCONSISTENT", "doc": "bill_of_lading", "field": "quantity", "found": 3900,
         "expected": 4000, "severity": "negotiable", "article": "UCP600-14d", "message": "short"}
D_LATE = {"rule_id": "R15", "code": "LATE_SHIPMENT", "doc": "bill_of_lading", "field": "shipped_on_board_date",
          "found": "2026-08-23", "expected": "2026-08-20", "severity": "negotiable", "article": "UCP600-20a-ii", "message": "late"}
D_FATAL = {"rule_id": "R17", "code": "LC_EXPIRED", "doc": "presentation", "field": "presentation_date", "found": "x",
           "expected": "y", "severity": "fatal", "article": "UCP600-6d-i", "message": "expired"}


@pytest.fixture(autouse=True)
def socket_guard(monkeypatch):
    def _blocked(*a, **k):
        raise RuntimeError("network access attempted during offline test")

    monkeypatch.setattr(socket.socket, "connect", _blocked)


def exam(*ds):
    return {"discrepancies": list(ds), "k": len(ds)}


def O(action, rungs, cited=(), why="r"):
    return AgentOffer(action=action, rungs=rungs, cited=list(cited), rationale=why)


def test_route_decisions():
    assert decide_route(0, []) == "clean"
    assert decide_route(2, [D_QTY, D_LATE]) == "negotiable"
    assert decide_route(1, [D_FATAL]) == "refuse"
    assert decide_route(6, [D_QTY] * 6) == "refuse"


def test_bounce_path_then_agreement():
    buyer = ScriptedAgent("buyer", [O("propose", 4, ["R09", "R15"], "anchor high"), O("propose", 2, ["R09", "R15"]),
                                    O("accept", 1, ["R09"])])
    seller = ScriptedAgent("seller", [O("counter", 1, ["R09"], "demurrage")])
    st = run(build_graph(buyer, seller), initial_state(DEAL, exam(D_QTY, D_LATE)))
    acts = [(e["actor"], e["action"], e["rungs"]) for e in st["offers"]]
    assert ("referee", "bounce", 4) in acts
    assert acts.index(("referee", "bounce", 4)) < acts.index(("buyer", "propose", 2))
    assert st["agreed_rungs"] == 1 and st["status"] == "CLOSED"
    assert st["payout"]["seller"] == "9900" and st["payout"]["buyer_returned"] == "100"
    assert buyer.seen[1]["bounce_notice"] and "ceiling" in buyer.seen[1]["bounce_notice"]


def test_second_violation_is_clamped_not_bounced():
    buyer = ScriptedAgent("buyer", [O("propose", 9, ["R09"]), O("propose", 7, ["R09", "BOGUS"])])
    seller = ScriptedAgent("seller", [O("accept", 2, ["R09"])])
    st = run(build_graph(buyer, seller), initial_state(DEAL, exam(D_QTY, D_LATE)))
    acts = [(e["actor"], e["action"], e["rungs"]) for e in st["offers"]]
    assert acts.count(("referee", "bounce", 9)) == 1
    assert ("referee", "clamped", 2) in acts
    assert st["agreed_rungs"] == 2


def test_default_after_three_rounds():
    buyer = ScriptedAgent("buyer", [O("propose", 2, ["R09"]), O("counter", 2, ["R09"]), O("counter", 2, ["R09"])])
    seller = ScriptedAgent("seller", [O("counter", 0), O("counter", 0), O("counter", 0)])
    st = run(build_graph(buyer, seller), initial_state(DEAL, exam(D_QTY, D_LATE)))
    assert st["round_no"] == MAX_ROUNDS + 1
    assert any(e["action"] == "default" for e in st["offers"])
    assert st["agreed_rungs"] == 2 and st["payout"]["seller"] == "9800"


def test_clean_skips_agents():
    buyer = ScriptedAgent("buyer", [O("propose", 1, ["R09"])])
    seller = ScriptedAgent("seller", [O("accept", 1, ["R09"])])
    st = run(build_graph(buyer, seller), initial_state(DEAL, exam()))
    assert st["route"] == "clean" and not buyer.seen and not seller.seen
    assert st["agreed_rungs"] == 0 and st["payout"]["seller"] == "10000" and st["payout"]["platform"] == "100"


def test_refuse_path_releases_nothing():
    buyer = ScriptedAgent("buyer", [O("propose", 1, ["R17"])])
    seller = ScriptedAgent("seller", [O("accept", 1, ["R17"])])
    st = run(build_graph(buyer, seller), initial_state(DEAL, exam(D_QTY, D_FATAL)))
    assert st["route"] == "refuse" and not buyer.seen
    assert "R17" in st["refusal_notice"] and st["payout"]["m"] == REFUSED_M
    assert st["payout"]["seller"] == "0" and st["payout"]["buyer_returned"] == "10100"


def test_stream_emits_custom_events():
    buyer = ScriptedAgent("buyer", [O("propose", 1, ["R09"])])
    seller = ScriptedAgent("seller", [O("accept", 1, ["R09"])])
    items = list(stream(build_graph(buyer, seller), initial_state(DEAL, exam(D_QTY))))
    events = [c for kind, c in items if kind == "event"]
    final = [c for kind, c in items if kind == "final"][0]
    assert [e["action"] for e in events] == ["route", "propose", "accept"]  # legal offers emitted once
    assert all({"ts_ms", "round", "actor", "action", "rungs", "cited", "rationale"} <= set(e) for e in events)
    assert final["agreed_rungs"] == 1


def test_check_and_clamp_are_consistent():
    ids = {"R09", "R15"}
    assert check_offer(O("propose", 2, ["R09"]), 2, ids, None, True) == []
    assert check_offer(O("accept", 1, ["R09"]), 2, ids, None, False)  # nothing to accept
    c = clamp_offer(O("accept", 8, ["ZZ"]), 2, ids, None, True)
    assert c.action == "propose" and c.rungs == 2 and set(c.cited) == ids
    assert check_offer(c, 2, ids, None, True) == []


@pytest.mark.parametrize("seed", range(25))
def test_property_agreed_rungs_always_in_range(seed):
    rnd = random.Random(seed)
    k = rnd.randint(1, 5)
    ds = [dict(D_QTY, rule_id=r) for r in ["R05", "R07", "R08", "R09", "R10"][:k]]
    ids = [d["rule_id"] for d in ds]

    def rand_offer():
        action = rnd.choice(["propose", "counter", "accept", "accept"])
        rungs = rnd.randint(-3, 9)
        cited = rnd.sample(ids + ["BAD"], rnd.randint(0, len(ids) + 1))
        return O(action, rungs, cited)

    buyer = ScriptedAgent("buyer", [rand_offer() for _ in range(12)])
    seller = ScriptedAgent("seller", [rand_offer() for _ in range(12)])
    st = run(build_graph(buyer, seller), initial_state(DEAL, exam(*ds)))
    assert st["status"] == "CLOSED"
    assert 0 <= st["agreed_rungs"] <= k
    assert len(st["offers"]) <= 30
    seller_amt = float(st["payout"]["seller"])
    assert seller_amt == 10000 - 100 * st["agreed_rungs"]
    for e in st["offers"]:
        if e["actor"] in ("buyer", "seller") and e.get("valid"):
            assert 0 <= e["rungs"] <= k and set(e["cited"]) <= set(ids)
