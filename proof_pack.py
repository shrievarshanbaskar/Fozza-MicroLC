"""Team: Fozza · Product: MicroLC — proof pack: full loops through the running API against XRPL testnet.

    python proof_pack.py clean discrepant fraudulent   (any subset; default all three)

For each preset: create -> examine (Groq if configured) -> lock 101% in seven RLUSD escrows (Tickets)
-> live negotiation (verifier pays the x402 oracle when warranted, Groq agents, pure-code referee)
-> settlement on ledger -> wait for CancelAfter -> sweep expired tranches -> archive everything to
proof/negotiation_report.json (offers, latencies, hashes, balances).
Requires: API on :8000, oracle on :8001, state/wallets.json.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import httpx
from dotenv import load_dotenv

load_dotenv()
API = os.getenv("MICROLC_API_URL", "http://127.0.0.1:8000")
EXPLORER = "https://testnet.xrpl.org/transactions/{}"


def sse(url: str):
    with httpx.stream("GET", url, timeout=None) as r:
        r.raise_for_status()
        ev, data = None, None
        for line in r.iter_lines():
            if line.startswith("event: "):
                ev = line[7:]
            elif line.startswith("data: "):
                data = json.loads(line[6:])
            elif line == "" and ev:
                yield ev, data
                ev, data = None, None


def wait_lock(deal_id: str, timeout: float = 240) -> dict:
    t0 = time.time()
    while time.time() - t0 < timeout:
        st = httpx.get(f"{API}/api/deal/{deal_id}", timeout=30).json()
        if st["escrow"] and st["escrow"]["status"] in ("LOCKED", "FAILED") or st["status"] in ("LOCKED", "LOCK_FAILED"):
            return st
        time.sleep(3)
    raise TimeoutError("lock did not finish")


def run_preset(preset: str) -> dict:
    print(f"\n=== {preset} ===")
    bal0 = httpx.get(f"{API}/api/balances", timeout=60).json()
    st = httpx.post(f"{API}/api/deal/create", json={"preset": preset}, timeout=60).json()
    deal_id = st["deal_id"]
    t0 = time.time()
    st = httpx.post(f"{API}/api/deal/{deal_id}/examine", params={"parser": "auto"}, timeout=180).json()
    exam = st["examination"]
    print(f"examined: parser={exam['parser']} k={exam['k']} verdict={exam['verdict']} in {round(time.time() - t0, 1)}s")

    httpx.post(f"{API}/api/deal/{deal_id}/lock", timeout=60)
    t0 = time.time()
    st = wait_lock(deal_id)
    esc = st["escrow"]
    print(f"locked: {esc['status']} in {esc.get('lock_seconds')}s; {len(esc['tranches'])} tranches")
    for t in esc["tranches"]:
        print(f"   {t['name']:7s} {t['amount']:>8s} -> {t['destination']:8s} {t['create_hash']}")

    events, settlement, done = [], [], None
    t0 = time.time()
    for ev, data in sse(f"{API}/api/deal/{deal_id}/negotiate/stream?mode=live"):
        if ev == "agent":
            events.append(data)
            print(f"   [{data['actor'].upper():8s}] {data['action']:9s} rungs={data.get('rungs')} {str(data.get('rationale', ''))[:120]}".encode("ascii", "replace").decode())
        elif ev == "settlement":
            settlement.append(data)
            print(f"   settle {data['name']:7s} {data['action']:6s} {data['status']:15s} {data.get('hash') or ''}")
        elif ev == "done":
            done = data
    wall = round(time.time() - t0, 1)
    print(f"negotiated+settled in {wall}s: status={done['status']} m={done['agreed_rungs']} payout={done['payout']}")

    st = httpx.get(f"{API}/api/deal/{deal_id}", timeout=30).json()
    pending = [t for t in st["escrow"]["tranches"] if t["status"] in ("RETURN_PENDING", "LOCKED")]
    swept = []
    if pending:
        cancel_after = max(t["cancel_after"] for t in pending)
        wait_s = cancel_after + 946_684_800 - time.time() + 8
        print(f"waiting {int(max(wait_s, 0))}s for CancelAfter, then sweeping {len(pending)} tranche(s)")
        time.sleep(max(wait_s, 0))
        for attempt in range(3):
            r = httpx.post(f"{API}/api/deal/{deal_id}/sweep", timeout=300).json()
            swept = r["swept"]
            if swept and all(s["status"] == "RETURNED" for s in swept):
                break
            time.sleep(10)
        for s in swept:
            print(f"   sweep {s['name']:7s} {s['status']:9s} {s.get('hash')}")
    st = httpx.get(f"{API}/api/deal/{deal_id}", timeout=30).json()
    bal1 = httpx.get(f"{API}/api/balances", timeout=60).json()
    latencies = [e["latency_ms"] for e in events if e.get("latency_ms")]
    return {
        "preset": preset, "deal_id": deal_id, "examination": {k: v for k, v in exam.items() if k != "documents"},
        "lock": {"status": esc["status"], "seconds": esc.get("lock_seconds"),
                 "tranches": [{k: t[k] for k in ("name", "amount", "destination", "create_hash", "offer_sequence")} for t in esc["tranches"]]},
        "negotiation": st["negotiation"], "agent_latency_ms": latencies, "wall_seconds_negotiate_settle": wall,
        "settlement": st["settlement"], "swept": swept, "final_tranches": [{k: t.get(k) for k in ("name", "amount", "destination", "status", "action_hash", "action_result")} for t in st["escrow"]["tranches"]],
        "balances_before": bal0, "balances_after": bal1, "ledger_feed": st["ledger_feed"],
    }


if __name__ == "__main__":
    presets = sys.argv[1:] or ["clean", "discrepant", "fraudulent"]
    path = Path("proof/negotiation_report.json")
    report = json.loads(path.read_text()) if path.exists() else {"runs": []}
    for p in presets:
        report["runs"].append(run_preset(p))
        path.write_text(json.dumps(report, indent=2, default=str))
        print(f"archived -> {path}")
    hashes = []
    for r in report["runs"]:
        hashes += [t["create_hash"] for t in r["lock"]["tranches"]] + [t["action_hash"] for t in r["final_tranches"] if t.get("action_hash")]
        hashes += [e["tx_hash"] for e in (r["negotiation"] or {}).get("evidence", []) if e.get("tx_hash")]
    print(f"\n{len([h for h in hashes if h])} transaction hashes archived")
