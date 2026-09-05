"""Top up the demo buyer with RLUSD from the test issuer.

    python scripts/topup_buyer.py              # buyer ends with at least 100,000 RLUSD spendable
    python scripts/topup_buyer.py --target N   # a different floor

Each lock parks 101% of the credit in seven escrows, and anything the seller keeps or a failed lock
leaves stranded reduces what the buyer can spend next time. This mints the shortfall from our own
testnet issuer (state/wallets.json) after raising the buyer's trust-line limit if it is too low.
Testnet only: the issuer here is a faucet wallet, not Ripple's RLUSD issuer. The API's lock
pre-flight reuses top_up() when DEMO_AUTO_TOPUP=true.
"""
from __future__ import annotations

import argparse
import sys
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from xrpl_escrow import LedgerClient, load_wallets  # noqa: E402

DEFAULT_TARGET = Decimal("100000")


def top_up(ledger, issuer_wallet, buyer_wallet, target=DEFAULT_TARGET, log=print) -> dict:
    """Mint RLUSD issuer -> buyer until the buyer's spendable balance reaches `target`.

    Returns {"minted": Decimal, "balance": Decimal, "tx_hash": str | None, "trustset_hash": str | None}.
    Raises RuntimeError if a TrustSet or the Payment is rejected. Never mints when already at target.
    """
    target = Decimal(str(target))
    issuer_addr, buyer_addr = issuer_wallet.classic_address, buyer_wallet.classic_address
    balance = Decimal(str(ledger.iou_balance(buyer_addr, issuer_addr)))
    out = {"minted": Decimal(0), "balance": balance, "tx_hash": None, "trustset_hash": None}
    if balance >= target:
        return out
    shortfall = target - balance

    limit_query = getattr(ledger, "trust_limit", None)
    limit = Decimal(str(limit_query(buyer_addr, issuer_addr))) if limit_query else None
    if limit is not None and limit < target:
        new_limit = max(target * 10, Decimal("1000000000"))
        r = ledger.create_trustline(buyer_wallet, issuer_addr, limit=str(new_limit))
        log(f"  TrustSet limit -> {new_limit}: {r.result} {r.hash}")
        if not r.ok:
            raise RuntimeError(f"TrustSet rejected: {r.result}")
        out["trustset_hash"] = r.hash

    r = ledger.issue(issuer_wallet, buyer_addr, str(shortfall))
    log(f"  Payment issuer -> buyer {shortfall} RLUSD: {r.result} {r.hash}")
    if not r.ok:
        raise RuntimeError(f"mint rejected: {r.result}")
    out.update(minted=shortfall, tx_hash=r.hash, balance=Decimal(str(ledger.iou_balance(buyer_addr, issuer_addr))))
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    ap.add_argument("--target", type=Decimal, default=DEFAULT_TARGET, help="minimum spendable RLUSD after top-up")
    ap.add_argument("--wallets", default="state/wallets.json")
    args = ap.parse_args()

    w = load_wallets(args.wallets)
    ledger = LedgerClient(w["rpc_url"])
    issuer, buyer = w["_wallets"]["issuer"], w["_wallets"]["buyer"]
    before = ledger.iou_balance(buyer.classic_address, issuer.classic_address)
    print(f"buyer {buyer.classic_address}\n  spendable RLUSD: {before}\n  target: {args.target}")
    try:
        res = top_up(ledger, issuer, buyer, args.target)
    except RuntimeError as exc:
        print(f"  {exc}")
        return 1
    if res["minted"] == 0:
        print("nothing to do: balance already at or above target")
    else:
        print(f"  spendable RLUSD now: {res['balance']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
