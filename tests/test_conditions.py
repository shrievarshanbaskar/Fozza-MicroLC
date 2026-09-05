"""Offline tests for the PREIMAGE-SHA-256 condition encoder (no network)."""
import hashlib

from xrpl_escrow import _money, make_condition, verify_fulfillment


def test_condition_layout_matches_rippled_convention():
    cond, ful, pre = make_condition(bytes(range(32)))
    assert cond.startswith("A0258020") and cond.endswith("810120") and len(cond) == 78
    assert ful.startswith("A0228020") and len(ful) == 72
    assert cond[8:72] == hashlib.sha256(bytes(range(32))).hexdigest().upper()
    assert ful[8:] == pre


def test_fulfillment_verifies_only_against_own_condition():
    c1, f1, _ = make_condition()
    c2, f2, _ = make_condition()
    assert verify_fulfillment(c1, f1) and verify_fulfillment(c2, f2)
    assert not verify_fulfillment(c1, f2) and not verify_fulfillment(c2, f1)
    assert not verify_fulfillment(c1, "DEADBEEF")


def test_money_formatting_is_ledger_safe():
    assert _money("9500.00") == "9500"
    assert _money(0.1 + 0.2) == "0.3"
    assert _money("100.5") == "100.5"
    assert _money("0.000001") == "0.000001"
