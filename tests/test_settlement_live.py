"""Live: lock 101% in seven RLUSD escrows via Tickets, settle m=2, sweep after expiry. Prints hashes."""
import json, os, time
import pytest
from settlement_engine import SettlementEngine, payout_for
from xrpl_escrow import LedgerClient, load_wallets

pytestmark = pytest.mark.live
EXPIRY = int(os.getenv("MICROLC_TEST_EXPIRY", "90"))


def test_seven_escrow_deal_m2():
    if not os.path.exists("state/wallets.json"):
        pytest.skip("run scripts/bootstrap_wallets.py first")
    data = load_wallets(); w = data["_wallets"]; issuer = data["wallets"]["issuer"]["address"]
    lc = LedgerClient(data["rpc_url"])
    eng = SettlementEngine(lc, use_tickets=True)
    seller0 = lc.iou_balance(w["seller"].classic_address, issuer)
    plat0 = lc.iou_balance(w["platform"].classic_address, issuer)
    buyer0 = lc.iou_balance(w["buyer"].classic_address, issuer)
    t0 = time.time()
    deal = list(eng.open_deal(1000, w["buyer"], w["seller"].classic_address, w["platform"].classic_address, issuer, EXPIRY))[-1]
    lock_s = round(time.time() - t0, 1)
    print(f"\nlocked 7 escrows in {lock_s}s status={deal.status}")
    for t in deal.tranches:
        print(f"  {t.name:7s} {t.amount:>7s} -> {t.destination:8s} {t.create_hash}")
    assert deal.status == "LOCKED"
    assert lc.iou_balance(w["buyer"].classic_address, issuer) == buyer0 - 1010
    t0 = time.time()
    events = list(eng.settle_iter(deal, 2, w["platform"]))
    print(f"settled m=2 in {round(time.time()-t0,1)}s")
    for e in events:
        print(f"  {e['name']:7s} {e['action']:6s} {e['status']:15s} {e['result']} {e['hash']}")
    exp = payout_for(1000, 2)
    assert lc.iou_balance(w["seller"].classic_address, issuer) - seller0 == 980 == float(exp["seller"])
    assert lc.iou_balance(w["platform"].classic_address, issuer) - plat0 == 10
    pending = [t for t in deal.tranches if t.status == "RETURN_PENDING"]
    assert len(pending) == 2
    while lc.ledger_time() <= max(t.cancel_after for t in pending):
        time.sleep(4)
    swept = list(eng.sweep_expired(deal, w["platform"]))
    for e in swept:
        print(f"  sweep {e['name']:7s} {e['status']:9s} {e['hash']}")
    assert len(swept) == 2 and all(e["status"] == "RETURNED" for e in swept)
    assert lc.iou_balance(w["buyer"].classic_address, issuer) == buyer0 - 990
    os.makedirs("proof", exist_ok=True)
    json.dump({"lock_seconds": lock_s, "deal": deal.to_dict(), "events": events, "swept": swept},
              open("proof/phase3_live_deal.json", "w"), indent=2, default=str)
