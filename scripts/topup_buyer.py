"""Top up the demo buyer with RLUSD from the test issuer.

    python scripts/topup_buyer.py              # buyer ends with at least 100,000 RLUSD spendable
    python scripts/topup_buyer.py --target N   # a different floor

Each lock parks 101% of the credit in seven escrows, and anything the seller keeps or a failed lock
leaves stranded reduces what the buyer can spend next time. This mints the shortfall from our own
testnet issuer (state/wallets.json) after raising the buyer's trust-line limit if it is too low.
Testnet only: the issuer here is a faucet wallet, not Ripple's RLUSD issuer.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

from xrpl.models.requests import AccountLines

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xrpl_escrow import LedgerClient, load_wallets  # noqa: E402

DEFAULT_TARGET = Decimal("100000")


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", type=Decimal, default=DEFAULT_TARGET, help="minimum spendable RLUSD after top-up")
    ap.add_argument("--wallets", default="state/wallets.json")
    args = ap.parse_args()

    w = load_wallets(args.wallets)
    ledger = LedgerClient(w["rpc_url"])
    issuer, buyer = w["_wallets"]["issuer"], w["_wallets"]["buyer"]
    issuer_addr, buyer_addr = issuer.classic_address, buyer.classic_address

    lines = ledger.client.request(AccountLines(account=buyer_addr, peer=issuer_addr)).result.get("lines", [])
    line = next((l for l in lines if l["currency"] == ledger.currency), None)
    balance = Decimal(line["balance"]) if line else Decimal(0)
    limit = Decimal(line["limit"]) if line else Decimal(0)
    print(f"buyer {buyer_addr}\n  spendable RLUSD: {balance}\n  trust-line limit: {limit}\n  target: {args.target}")

    if balance >= args.target:
        print("nothing to do: balance already at or above target")
        return 0
    shortfall = args.target - balance

    if limit < args.target:
        new_limit = max(args.target * 10, Decimal("1000000000"))
        r = ledger.create_trustline(buyer, issuer_addr, limit=str(new_limit))
        print(f"  TrustSet limit -> {new_limit}: {r.result} {r.hash}")
        if not r.ok:
            return 1

    r = ledger.issue(issuer, buyer_addr, str(shortfall))
    print(f"  Payment issuer -> buyer {shortfall} RLUSD: {r.result} {r.hash}")
    if not r.ok:
        return 1
    print(f"  spendable RLUSD now: {ledger.iou_balance(buyer_addr, issuer_addr)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
