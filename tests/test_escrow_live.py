"""Live XRPL testnet tests for the XLS-85 token-escrow layer.

Run after scripts/bootstrap_wallets.py:
    .\\.venv\\Scripts\\python.exe -m pytest tests/test_escrow_live.py -s -m live

Set MICROLC_TEST_EXPIRY (seconds, default 60) higher if the testnet is slow.
"""
import os
import time

import pytest

from xrpl_escrow import LedgerClient, load_wallets, make_condition

pytestmark = pytest.mark.live
EXPIRY = int(os.getenv("MICROLC_TEST_EXPIRY", "60"))


@pytest.fixture(scope="module")
def env():
    if not os.path.exists("state/wallets.json"):
        pytest.skip("state/wallets.json missing; run scripts/bootstrap_wallets.py")
    data = load_wallets()
    return LedgerClient(data["rpc_url"]), data["_wallets"], data["wallets"]["issuer"]["address"]


def test_create_and_finish_100_rlusd(env):
    lc, w, issuer = env
    before = lc.iou_balance(w["seller"].classic_address, issuer)
    cond, ful, _ = make_condition()
    c = lc.create_escrow(w["buyer"], w["seller"].classic_address, "100", issuer, cond, expiry_seconds=EXPIRY)
    print(f"\nEscrowCreate {c.result} {c.explorer}")
    assert c.ok and c.offer_sequence
    f = lc.finish_escrow(w["platform"], w["buyer"].classic_address, c.offer_sequence, cond, ful)
    print(f"EscrowFinish {f.result} {f.explorer}")
    assert f.ok
    after = lc.iou_balance(w["seller"].classic_address, issuer)
    assert after - before == 100


def test_premature_cancel_is_rejected_then_expiry_refunds(env):
    lc, w, issuer = env
    buyer_before = lc.iou_balance(w["buyer"].classic_address, issuer)
    cond, ful, _ = make_condition()
    c = lc.create_escrow(w["buyer"], w["seller"].classic_address, "25", issuer, cond, expiry_seconds=EXPIRY)
    print(f"\nEscrowCreate {c.result} {c.explorer}")
    assert c.ok
    assert lc.iou_balance(w["buyer"].classic_address, issuer) == buyer_before - 25  # locked leaves the line
    early = lc.cancel_escrow(w["platform"], w["buyer"].classic_address, c.offer_sequence)
    print(f"early EscrowCancel {early.result} {early.explorer}")
    assert not early.ok and early.result == "tecNO_PERMISSION"

    cancel_after = c.raw["tx_json"]["CancelAfter"] if "tx_json" in c.raw else c.raw["CancelAfter"]
    while lc.ledger_time() <= cancel_after:
        time.sleep(3)
    late_finish = lc.finish_escrow(w["platform"], w["buyer"].classic_address, c.offer_sequence, cond, ful)
    print(f"post-expiry EscrowFinish {late_finish.result}")
    assert not late_finish.ok
    refund = lc.cancel_escrow(w["platform"], w["buyer"].classic_address, c.offer_sequence)
    print(f"post-expiry EscrowCancel {refund.result} {refund.explorer}")
    assert refund.ok
    assert lc.iou_balance(w["buyer"].classic_address, issuer) == buyer_before
