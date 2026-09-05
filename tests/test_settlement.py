"""Offline settlement tests against a fake ledger. Sums must always equal 101% of the credit."""
from decimal import Decimal

import pytest

from settlement_engine import (
    REFUSED_M, RUNG_COUNT, Deal, SettlementEngine, decide, money, normalize_m, payout_for, payout_table,
    total_locked, tranche_plan,
)
from xrpl_escrow import TxResult, verify_fulfillment


class FakeWallet:
    def __init__(self, addr):
        self.classic_address = addr


class FakeLedger:
    """Tracks IOU balances the way rippled would for escrow create/finish/cancel."""

    def __init__(self, buyer_balance="20000"):
        self.balances = {"rBUYER": Decimal(buyer_balance), "rSELLER": Decimal(0), "rPLATFORM": Decimal(0)}
        self.escrows = {}
        self.seq = 100
        self.now = 1_000_000

    def ledger_time(self):
        return self.now

    def create_escrow(self, owner, destination, value, issuer, condition, expiry_seconds=180, **kw):
        self.seq += 1
        amt = Decimal(str(value))
        assert self.balances[owner.classic_address] >= amt
        self.balances[owner.classic_address] -= amt
        self.escrows[self.seq] = dict(dest=destination, amt=amt, cond=condition, owner=owner.classic_address,
                                      cancel_after=self.now + expiry_seconds)
        return TxResult(True, f"CREATE{self.seq}", "tesSUCCESS", self.seq, None, 1,
                        {"tx_json": {"CancelAfter": self.now + expiry_seconds}})

    def finish_escrow(self, finisher, owner, offer_sequence, condition, fulfillment):
        e = self.escrows.get(offer_sequence)
        if not e or self.now > e["cancel_after"] or not verify_fulfillment(e["cond"], fulfillment):
            return TxResult(False, "", "tecNO_PERMISSION")
        self.balances[e["dest"]] += e["amt"]
        del self.escrows[offer_sequence]
        return TxResult(True, f"FINISH{offer_sequence}", "tesSUCCESS")

    def cancel_escrow(self, canceller, owner, offer_sequence):
        e = self.escrows.get(offer_sequence)
        if not e or self.now <= e["cancel_after"]:
            return TxResult(False, "", "tecNO_PERMISSION")
        self.balances[e["owner"]] += e["amt"]
        del self.escrows[offer_sequence]
        return TxResult(True, f"CANCEL{offer_sequence}", "tesSUCCESS")


def test_plan_and_totals():
    plan = tranche_plan(10000)
    assert [t.name for t in plan] == ["base", "rung_1", "rung_2", "rung_3", "rung_4", "rung_5", "fee"]
    assert sum(money(t.amount) for t in plan) == money(total_locked(10000)) == Decimal("10100")


@pytest.mark.parametrize("m,seller,platform,buyer", [
    (0, "10000", "100", "0"), (1, "9900", "100", "100"), (2, "9800", "100", "200"),
    (5, "9500", "100", "500"), (REFUSED_M, "0", "0", "10100"), (None, "0", "0", "10100"), (9, "0", "0", "10100"),
])
def test_payout_for_is_pure_and_conserving(m, seller, platform, buyer):
    p = payout_for(10000, m)
    assert (p["seller"], p["platform"], p["buyer_returned"]) == (seller, platform, buyer)
    assert money(p["seller"]) + money(p["platform"]) + money(p["buyer_returned"]) == Decimal("10100")
    assert p["refused"] == (normalize_m(m) == REFUSED_M)


def test_decide_shape():
    acts = decide(2, tranche_plan(1))
    assert acts == {0: "finish", 1: "finish", 2: "finish", 3: "finish", 4: "expire", 5: "expire", 6: "finish"}
    assert set(decide(REFUSED_M).values()) == {"expire"}
    assert len(payout_table(10000)) == RUNG_COUNT + 2


@pytest.mark.parametrize("m", [0, 1, 2, 5, REFUSED_M])
def test_settle_against_fake_ledger(m):
    led = FakeLedger()
    eng = SettlementEngine(led)
    deal = None
    for deal in eng.open_deal(10000, FakeWallet("rBUYER"), "rSELLER", "rPLATFORM", "rISSUER", expiry_seconds=180):
        pass
    assert deal.status == "LOCKED" and led.balances["rBUYER"] == Decimal("20000") - Decimal("10100")
    events = list(eng.settle_iter(deal, m, FakeWallet("rPLATFORM")))
    assert len(events) == 7
    expected = payout_for(10000, m)
    assert led.balances["rSELLER"] == money(expected["seller"])
    assert led.balances["rPLATFORM"] == money(expected["platform"])
    pending = [e for e in events if e["status"] == "RETURN_PENDING"]
    assert len(pending) == (7 if m == REFUSED_M else m)
    # time passes; sweep returns the rest
    led.now += 1000
    swept = list(eng.sweep_expired(deal, FakeWallet("rPLATFORM")))
    assert len(swept) == len(pending) and all(e["status"] == "RETURNED" for e in swept)
    assert led.balances["rBUYER"] == Decimal("20000") - money(expected["seller"]) - money(expected["platform"])
    total = led.balances["rBUYER"] + led.balances["rSELLER"] + led.balances["rPLATFORM"]
    assert total == Decimal("20000") and not led.escrows
    assert deal.status == ("REFUSED" if m == REFUSED_M else "SETTLED")


def test_deal_roundtrip_hides_fulfillment():
    led = FakeLedger()
    deal = list(SettlementEngine(led).open_deal(500, FakeWallet("rBUYER"), "rSELLER", "rPLATFORM", "rISSUER"))[-1]
    public = deal.to_dict()
    assert all("fulfillment" not in t for t in public["tranches"])
    private = deal.to_dict(public=False)
    again = Deal.from_dict(private)
    assert again.tranches[0].fulfillment == deal.tranches[0].fulfillment
