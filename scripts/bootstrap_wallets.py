"""Team: Fozza · Product: MicroLC — one-shot testnet bootstrap.

Funds five wallets from the XRPL testnet faucet, turns the issuer into an RLUSD-style
issuer that allows trust-line locking (XLS-85), opens trust lines, mints supply and
writes state/wallets.json (gitignored) plus state/wallets.example.json (placeholders).

    .\\.venv\\Scripts\\python.exe scripts\\bootstrap_wallets.py

Re-running overwrites state/wallets.json with a fresh set of wallets.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv()
from xrpl_escrow import EXPLORER_ACCOUNT, RLUSD_HEX, LedgerClient  # noqa: E402

ROLES = ["issuer", "buyer", "seller", "platform", "oracle"]
MINT = {"buyer": "50000", "platform": "1000"}  # platform holds a small RLUSD float to pay oracles
STATE_DIR = Path("state")


def main() -> int:
    lc = LedgerClient()
    print(f"rpc: {lc.rpc_url}")
    wallets = {}
    for role in ROLES:
        t0 = time.time()
        w = lc.fund_wallet()
        wallets[role] = w
        print(f"funded {role:9s} {w.classic_address}  ({time.time() - t0:.1f}s)")

    issuer = wallets["issuer"]
    for r in lc.enable_issuer_flags(issuer):
        print(f"issuer AccountSet {r.result} {r.hash}")
        if not r.ok:
            return 1

    for role in ROLES[1:]:
        r = lc.create_trustline(wallets[role], issuer.classic_address)
        print(f"trustline {role:9s} {r.result} {r.hash}")
        if not r.ok:
            return 1

    for role, value in MINT.items():
        r = lc.issue(issuer, wallets[role].classic_address, value)
        print(f"mint {value:>6s} RLUSD -> {role:9s} {r.result} {r.hash}")
        if not r.ok:
            return 1

    STATE_DIR.mkdir(exist_ok=True)
    data = {
        "network": os.getenv("XRPL_NETWORK", "xrpl:1"),
        "rpc_url": lc.rpc_url,
        "currency": RLUSD_HEX,
        "currency_display": "RLUSD",
        "wallets": {
            role: {
                "address": w.classic_address,
                "seed": w.seed,
                "public_key": w.public_key,
                "explorer": EXPLORER_ACCOUNT.format(w.classic_address),
            }
            for role, w in wallets.items()
        },
    }
    (STATE_DIR / "wallets.json").write_text(json.dumps(data, indent=2))
    example = json.loads(json.dumps(data))
    for role, w in example["wallets"].items():
        w["address"] = f"r{role.upper()}_ADDRESS_PLACEHOLDER"
        w["seed"] = "sPLACEHOLDER_NEVER_COMMIT_REAL_SEEDS"
        w["public_key"] = "ED_PLACEHOLDER"
        w["explorer"] = EXPLORER_ACCOUNT.format(w["address"])
    (STATE_DIR / "wallets.example.json").write_text(json.dumps(example, indent=2))

    print("\nbalances:")
    for role in ROLES:
        a = wallets[role].classic_address
        bal = "-" if role == "issuer" else lc.iou_balance(a, issuer.classic_address)
        print(f"  {role:9s} XRP={lc.xrp_balance(a):>8} RLUSD={bal}")
    print("\nwrote state/wallets.json and state/wallets.example.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
