"""Build docs/TRANSACTIONS.md from the proof artifacts (explorer-linked hash table)."""
from __future__ import annotations

import json
from pathlib import Path

EXPLORER = "https://testnet.xrpl.org/transactions/{}"
rows: list[tuple[str, str, str]] = []  # (group, label, hash)


def add(group, label, h):
    if h and len(str(h)) == 64:
        rows.append((group, label, h))


p1 = Path("proof/phase1_ledger.json")
if p1.exists():
    d = json.loads(p1.read_text())
    for k, v in d["bootstrap"].items():
        add("Bootstrap (issuer flags, trust lines, mint)", k.replace("_", " "), v)
    for k, v in d["escrow_spike_100_rlusd"].items():
        add("Escrow spike (100 RLUSD create + conditional finish)", k.replace("_", " "), v)
    for k, v in d["escrow_expiry_path_25_rlusd"].items():
        add("Escrow expiry path (premature cancel rejected, post-expiry refund)", k.replace("_", " "), v)

ts = Path("proof/tickets_spike.json")
if ts.exists():
    d = json.loads(ts.read_text())
    for i, r in enumerate(d["sequential"]):
        add("Tickets spike: sequential EscrowCreate", f"sequential #{i + 1}", r["hash"])
    for i, r in enumerate(d["tickets"]):
        add("Tickets spike: parallel EscrowCreate via TicketSequence (same ledger)", f"ticketed #{i + 1} (ticket {r['ticket_sequence']})", r["hash"])

for preset in ("discrepant", "fraudulent"):
    vp = Path(f"proof/verifier_live_{preset}.json")
    if vp.exists():
        d = json.loads(vp.read_text())
        for ev in d.get("evidence") or []:
            add(f"x402 oracle payment ({preset} preset, RLUSD via hosted facilitator)", f"{ev.get('provider')} {ev.get('price_rlusd')} RLUSD -> {ev.get('verdict')}", ev.get("tx_hash"))

rep = Path("proof/negotiation_report.json")
if rep.exists():
    d = json.loads(rep.read_text())
    for run in d["runs"]:
        g = f"Full loop: {run['preset']} preset (deal {run['deal_id']})"
        for t in run["lock"]["tranches"]:
            add(g, f"EscrowCreate {t['name']} {t['amount']} RLUSD -> {t['destination']}", t["create_hash"])
        for ev in (run["negotiation"] or {}).get("evidence", []):
            add(g, f"x402 payment to {ev.get('provider')} ({ev.get('price_rlusd')} RLUSD) -> {ev.get('verdict')}", ev.get("tx_hash"))
        for t in run["final_tranches"]:
            if t.get("action_hash"):
                verb = "EscrowFinish" if t["status"] == "RELEASED" else "EscrowCancel"
                add(g, f"{verb} {t['name']} {t['amount']} RLUSD -> {t['status']}", t["action_hash"])

out = ["# XRPL testnet transactions", "", "Every hash below is a validated transaction on the XRP Ledger testnet (`xrpl:1`).",
       "Wallet addresses are listed in `state/wallets.example.json` layout; the live set is printed by `scripts/bootstrap_wallets.py`.", ""]
current = None
for group, label, h in rows:
    if group != current:
        out += ["", f"## {group}", "", "| Step | Hash | Explorer |", "|---|---|---|"]
        current = group
    out.append(f"| {label} | `{h}` | [view]({EXPLORER.format(h)}) |")
Path("docs").mkdir(exist_ok=True)
Path("docs/TRANSACTIONS.md").write_text("\n".join(out) + "\n", encoding="utf-8")
print(f"{len(rows)} hashes -> docs/TRANSACTIONS.md")
