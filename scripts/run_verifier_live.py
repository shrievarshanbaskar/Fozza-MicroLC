"""Live end-to-end: examiner -> verifier agent (discover -> decide -> x402 pay on XRPL testnet -> evidence)
-> Groq negotiation citing the evidence. Requires the oracle service on ORACLE_URL and state/wallets.json.

    python scripts/run_verifier_live.py discrepant|fraudulent|clean [--scripted]

Writes proof/verifier_live_<preset>.json.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from dotenv import load_dotenv  # noqa: E402

load_dotenv(".env")

from doc_generator import generate_set  # noqa: E402
from examiner import TemplateParser, examine  # noqa: E402
from negotiator_graph import AgentOffer, ScriptedAgent, build_graph, initial_state, stream  # noqa: E402
from verifier_agent import BudgetGuard, OracleClient, make_verifier  # noqa: E402
from xrpl_escrow import LedgerClient, load_wallets  # noqa: E402


def main(preset: str, scripted: bool) -> dict:
    data = load_wallets()
    w = data["_wallets"]
    issuer = data["wallets"]["issuer"]["address"]
    lc = LedgerClient(data["rpc_url"])
    payer, oracle_addr = w["platform"], data["wallets"]["oracle"]["address"]
    payer_before, oracle_before = lc.iou_balance(payer.classic_address, issuer), lc.iou_balance(oracle_addr, issuer)

    exam = examine(generate_set(preset), TemplateParser())
    deal = {"deal_id": f"vl-{preset}", "lc_amount": "10000", "lc_number": exam["lc_number"],
            "applicant": "Meridian Apparel Trading Pte Ltd", "beneficiary": "Coimbatore Spinning Mills Pvt Ltd"}
    budget = BudgetGuard()
    verifier = make_verifier(OracleClient(payer_wallet=payer, rpc_url=data["rpc_url"]), budget)
    if scripted:
        buyer = ScriptedAgent("buyer", [AgentOffer(action="propose", rungs=exam["k"], cited=[d["rule_id"] for d in exam["discrepancies"]], rationale="scripted")])
        seller = ScriptedAgent("seller", [AgentOffer(action="accept", rungs=exam["k"], cited=[], rationale="scripted")])
        drafter = None
    else:
        from negotiation_agents import GroqAgent, GroqRefusalDrafter

        buyer, seller, drafter = GroqAgent("buyer"), GroqAgent("seller"), GroqRefusalDrafter()
    graph = build_graph(buyer, seller, verifier=verifier, refusal_drafter=drafter)

    t0 = time.time()
    events, final = [], None
    for kind, chunk in stream(graph, initial_state(deal, exam)):
        if kind == "event":
            events.append(chunk)
            tag = f"[{chunk['actor'].upper()}]"
            print(f"  {tag:10s} {chunk['action']:9s} rungs={chunk.get('rungs')} {chunk.get('rationale', '')[:150]}".encode("ascii", "replace").decode())
        else:
            final = chunk
    wall = round(time.time() - t0, 2)
    time.sleep(4)  # let the payment validate before reading balances
    payer_after, oracle_after = lc.iou_balance(payer.classic_address, issuer), lc.iou_balance(oracle_addr, issuer)
    out = {
        "preset": preset, "k_examiner": exam["k"], "k_final": final["k"], "route": final["route"], "status": final["status"],
        "agreed_rungs": final.get("agreed_rungs"), "payout": final.get("payout"), "wall_seconds": wall,
        "verifier": final.get("verifier"), "evidence": final.get("evidence"), "events": events,
        "refusal_notice": final.get("refusal_notice"),
        "balances": {"payer_rlusd_before": str(payer_before), "payer_rlusd_after": str(payer_after),
                     "oracle_rlusd_before": str(oracle_before), "oracle_rlusd_after": str(oracle_after)},
        "agents_cited_evidence": any("oracle" in (e.get("rationale") or "").lower() or "carrier" in (e.get("rationale") or "").lower()
                                     or "atd" in (e.get("rationale") or "").lower() or "verif" in (e.get("rationale") or "").lower()
                                     for e in events if e["actor"] in ("buyer", "seller")),
    }
    print(json.dumps({k: v for k, v in out.items() if k not in ("events", "evidence")}, indent=2, default=str)
          .encode("ascii", "replace").decode())
    Path("proof").mkdir(exist_ok=True)
    Path(f"proof/verifier_live_{preset}.json").write_text(json.dumps(out, indent=2, default=str))
    return out


if __name__ == "__main__":
    preset = sys.argv[1] if len(sys.argv) > 1 else "discrepant"
    main(preset, "--scripted" in sys.argv)
