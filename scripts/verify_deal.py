"""Read-only testnet verifier for completed MicroLC deals.

    python scripts/verify_deal.py <deal_id>     verify one deal
    python scripts/verify_deal.py --all         verify every SETTLED / REFUSED deal in state/deals/

Reads only state/deals/<id>/state.json (hashes and public party addresses). Never opens
state/wallets.json, never signs or submits anything. Every recorded EscrowCreate, EscrowFinish,
EscrowCancel and x402 Payment hash is looked up on the XRPL testnet; the stored settlement is
compared with payout_for(lc_amount, m). Exit status is non-zero if any hash is not a validated
tesSUCCESS transaction or the stored payout disagrees with the pure settlement function.
"""
from __future__ import annotations

import json
import sys
from decimal import Decimal
from pathlib import Path

from xrpl.clients import WebsocketClient
from xrpl.models.requests import AccountLines, AccountObjects, Tx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from settlement_engine import payout_for  # noqa: E402

WSS_URL = "wss://s.altnet.rippletest.net:51233"
DEALS_DIR = ROOT / "state" / "deals"
COMPLETED = {"SETTLED", "REFUSED"}


def lookup(client: WebsocketClient, tx_hash: str) -> dict:
    r = client.request(Tx(transaction=tx_hash)).result
    tx = r.get("tx_json", r)  # rippled api v2 nests the transaction; v1 flattens it
    return {
        "hash": tx_hash,
        "type": tx.get("TransactionType"),
        "result": (r.get("meta") or {}).get("TransactionResult"),
        "validated": r.get("validated") is True,
        "ledger_index": r.get("ledger_index"),
        "error": r.get("error"),
    }


def collect_hashes(state: dict) -> list[tuple[str, str]]:
    """(label, hash) for every ledger transaction the deal recorded."""
    out: list[tuple[str, str]] = []
    esc = state.get("escrow") or {}
    for t in esc.get("tranches") or []:
        if t.get("create_hash"):
            out.append((f"create {t['name']}", t["create_hash"]))
    for t in esc.get("tranches") or []:
        if t.get("action_hash"):
            out.append((f"{t.get('status', '').lower()} {t['name']}", t["action_hash"]))
    neg = state.get("negotiation") or {}
    seen = set()
    for entry in ((neg.get("verifier") or {}).get("budget") or {}).get("log", []):
        h = entry.get("tx_hash")
        if h and h not in seen:
            seen.add(h)
            out.append((f"x402 {entry.get('provider', '')}", h))
    for ev in neg.get("evidence") or []:
        h = ev.get("tx_hash")
        if h and h not in seen:
            seen.add(h)
            out.append((f"x402 {ev.get('provider', '')}", h))
    return out


def verify_deal(client: WebsocketClient, deal_id: str) -> bool:
    path = DEALS_DIR / deal_id / "state.json"
    if not path.exists():
        print(f"{deal_id}: no state.json at {path}")
        return False
    state = json.loads(path.read_text(encoding="utf-8"))
    esc = state.get("escrow") or {}
    settlement = state.get("settlement") or {}
    exam = state.get("examination") or {}
    parties = state.get("parties") or {}
    ok = True

    print(f"== {deal_id}  preset={state.get('preset')}  status={state.get('status')}  "
          f"k={exam.get('k')}  m={settlement.get('m')}  escrow={esc.get('status')} ==")

    # "complete" means the money moved on the ledger: locked, then every tranche finished or returned by
    # the settlement itself. A plan-only settlement, a failed lock or a pending sweep is not complete.
    tranches = esc.get("tranches") or []
    problems = []
    if state.get("status") not in COMPLETED:
        problems.append(f"deal status is {state.get('status')}, not SETTLED/REFUSED")
    if esc.get("status") != "LOCKED" or len(tranches) != 7:
        problems.append(f"escrow ladder not locked on ledger (escrow status {esc.get('status')}, {len(tranches)} tranches)")
    if settlement.get("mode") != "ledger":
        problems.append(f"settlement mode is {settlement.get('mode')!r}, not 'ledger' (payout never executed on chain)")
    unfinished = [f"{t['name']}={t.get('status')}" for t in tranches if t.get("status") not in ("RELEASED", "RETURNED")]
    if unfinished:
        problems.append("tranches not finalised: " + ", ".join(unfinished))
    for p in problems:
        print(f"  FAIL {p}")
    ok &= not problems

    hashes = collect_hashes(state)
    if not hashes:
        print("  no ledger hashes recorded")
        ok = False
    counts = {"EscrowCreate": 0, "EscrowFinish": 0, "EscrowCancel": 0, "Payment": 0}
    for label, h in hashes:
        r = lookup(client, h)
        good = r["validated"] and r["result"] == "tesSUCCESS"
        ok &= good
        if good and r["type"] in counts:
            counts[r["type"]] += 1
        flag = "ok " if good else "BAD"
        print(f"  {flag} {label:16} {h} {r['type']} {r['result']} validated={r['validated']} "
              f"ledger_index={r['ledger_index']}{'  error=' + r['error'] if r['error'] else ''}")
    print(f"  validated: {counts}")

    lc_amount = esc.get("lc_amount") or (state.get("lc") or {}).get("amount")
    m = settlement.get("m")
    if lc_amount is not None and m is not None:
        expected = payout_for(lc_amount, m)
        stored = settlement.get("payout") or {}
        keys = ("seller", "platform", "buyer_returned", "locked", "refused")
        match = all(str(expected[k]) == str(stored.get(k)) for k in keys)
        ok &= match
        print(f"  payout_for({lc_amount}, {m}) -> seller {expected['seller']} platform {expected['platform']} "
              f"returned {expected['buyer_returned']} refused={expected['refused']}")
        print(f"  stored settlement        -> seller {stored.get('seller')} platform {stored.get('platform')} "
              f"returned {stored.get('buyer_returned')} refused={stored.get('refused')}  "
              f"{'MATCH' if match else 'MISMATCH'}")
    else:
        print("  no settlement recorded; payout comparison skipped")
        ok = False

    buyer, issuer = parties.get("buyer"), parties.get("issuer")
    if buyer and issuer:
        objs = client.request(AccountObjects(account=buyer, type="escrow", limit=400)).result.get("account_objects", [])
        held = sum((Decimal(o["Amount"]["value"]) for o in objs if isinstance(o.get("Amount"), dict)), Decimal(0))
        print(f"  buyer escrow objects on ledger now: {len(objs)} holding {held} RLUSD (all deals, not just this one)")
        for who in ("buyer", "seller", "platform", "oracle"):
            addr = parties.get(who)
            if not addr:
                continue
            lines = client.request(AccountLines(account=addr, peer=issuer)).result.get("lines", [])
            bal = lines[0]["balance"] if lines else "0"
            print(f"  {who:8} RLUSD balance {bal}")
    print(f"  RESULT: {'PASS' if ok else 'FAIL'}\n")
    return ok


def completed_deal_ids() -> list[str]:
    """Deals that claim completion and put an escrow ladder on the ledger. Refusals whose lock never
    happened are listed as skipped: there is nothing on chain to verify."""
    ids = []
    for p in sorted(DEALS_DIR.glob("*/state.json")):
        try:
            st = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if st.get("status") not in COMPLETED:
            continue
        if not ((st.get("escrow") or {}).get("tranches")):
            print(f"skip {p.parent.name}: {st.get('status')} without a ledger lock (nothing on chain)")
            continue
        ids.append(p.parent.name)
    return ids


def main(argv: list[str]) -> int:
    if len(argv) != 2 or argv[1] in ("-h", "--help"):
        print(__doc__.strip())
        return 2
    ids = completed_deal_ids() if argv[1] == "--all" else [argv[1]]
    if not ids:
        print("no completed deals (status SETTLED or REFUSED) found in state/deals/")
        return 1
    with WebsocketClient(WSS_URL) as client:
        results = [verify_deal(client, d) for d in ids]
    failed = [d for d, r in zip(ids, results) if not r]
    print(f"{len(ids) - len(failed)}/{len(ids)} deals verified" + (f"; FAILED: {', '.join(failed)}" if failed else ""))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
