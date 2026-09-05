"""Offline: the lock refuses to start without funds, and a partial lock is rolled back with every hash kept."""
from decimal import Decimal

import pytest

from settlement_engine import InsufficientFunds, SettlementEngine, total_locked
from test_settlement import FakeLedger, FakeWallet
from xrpl_escrow import TxResult

BUYER, SELLER, PLATFORM, ISSUER = FakeWallet("rBUYER"), "rSELLER", "rPLATFORM", "rISSUER"


class FundedFake(FakeLedger):
    """FakeLedger plus the balance query the pre-flight uses, and an injectable EscrowCreate failure."""

    def __init__(self, buyer_balance="20000", fail_names=()):
        super().__init__(buyer_balance)
        self.fail_names = set(fail_names)
        self.creates = 0
        self.cancels = 0

    def iou_balance(self, address, issuer):
        return self.balances.get(address, Decimal(0))

    def create_escrow(self, owner, destination, value, issuer, condition, expiry_seconds=180, memo=None, **kw):
        self.creates += 1
        name = (memo or "").split()[-1]
        if name in self.fail_names or self.balances[owner.classic_address] < Decimal(str(value)):
            return TxResult(False, f"FAILED{self.creates}", "tecINSUFFICIENT_FUNDS")
        return super().create_escrow(owner, destination, value, issuer, condition, expiry_seconds, **kw)

    def create_escrows_parallel(self, owner, specs, issuer, expiry_seconds=180):
        return [self.create_escrow(owner, s["destination"], s["value"], issuer, s["condition"], expiry_seconds, s.get("memo"))
                for s in specs]

    def cancel_escrow(self, canceller, owner, offer_sequence):
        self.cancels += 1
        return super().cancel_escrow(canceller, owner, offer_sequence)


def open_all(eng, lc=10000):
    deal = None
    for deal in eng.open_deal(lc, BUYER, SELLER, PLATFORM, ISSUER, expiry_seconds=180, deal_id="t"):
        pass
    return deal


@pytest.mark.parametrize("use_tickets", [False, True])
def test_preflight_refuses_underfunded_buyer_before_any_submission(use_tickets):
    ledger = FundedFake(buyer_balance="6274")
    eng = SettlementEngine(ledger, use_tickets=use_tickets)
    with pytest.raises(InsufficientFunds) as exc:
        open_all(eng)
    assert exc.value.need == total_locked(10000) == "10100" and exc.value.have == "6274"
    assert "run scripts/topup_buyer.py" in str(exc.value)
    assert ledger.creates == 0 and ledger.escrows == {} and ledger.balances["rBUYER"] == Decimal("6274")


@pytest.mark.parametrize("use_tickets", [False, True])
def test_partial_lock_is_rolled_back_and_swept(use_tickets):
    ledger = FundedFake(buyer_balance="20000", fail_names={"rung_3"})
    eng = SettlementEngine(ledger, use_tickets=use_tickets)
    deal = open_all(eng)

    assert deal.status == "FAILED" and "rung_3 tecINSUFFICIENT_FUNDS" in deal.error
    by_name = {t.name: t for t in deal.tranches}
    assert by_name["rung_3"].status == "FAILED" and by_name["rung_3"].create_hash == "FAILED4"
    landed = ["base", "rung_1", "rung_2"] + (["rung_4", "rung_5", "fee"] if use_tickets else [])
    for name in landed:  # every escrow that landed keeps its create hash and was rolled back
        t = by_name[name]
        assert t.create_hash and t.create_hash.startswith("CREATE")
        assert t.status == "RETURN_PENDING" and t.action_result == "tecNO_PERMISSION"  # CancelAfter not reached yet
    if not use_tickets:  # sequential path stops submitting after the first failure
        assert all(by_name[n].status == "PLANNED" and by_name[n].create_hash is None for n in ("rung_4", "rung_5", "fee"))
        assert ledger.creates == 4
    assert len(deal.rollback) == len(landed) and ledger.cancels == len(landed)
    assert ledger.balances["rBUYER"] == Decimal("20000") - sum(Decimal(by_name[n].amount) for n in landed)

    # once CancelAfter passes, the sweep returns everything and the buyer is whole again
    ledger.now += 181
    events = list(eng.sweep_expired(deal, FakeWallet("rPLATFORM")))
    assert len(events) == len(landed) and all(e["status"] == "RETURNED" for e in events)
    assert all(by_name[n].status == "RETURNED" and by_name[n].action_hash.startswith("CANCEL") for n in landed)
    assert ledger.balances["rBUYER"] == Decimal("20000") and ledger.escrows == {}


def test_full_lock_still_works_and_records_create_results():
    ledger = FundedFake(buyer_balance="10100")
    deal = open_all(SettlementEngine(ledger, use_tickets=True))
    assert deal.status == "LOCKED" and deal.error is None and deal.rollback == []
    assert all(t.status == "LOCKED" and t.create_result == "tesSUCCESS" for t in deal.tranches)
    assert ledger.balances["rBUYER"] == Decimal(0)
