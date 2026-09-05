"""Live Groq negotiation runs on the discrepant preset. Checks legality, a visible bounce and wall time.

    python scripts/run_negotiation_live.py [runs=3] [gap_seconds=60]

Appends results to proof/negotiation_live_runs.json.
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
from negotiation_agents import GroqAgent  # noqa: E402
from negotiator_graph import build_graph, initial_state, stream  # noqa: E402


def one_run(idx: int) -> dict:
    out_dir = generate_set("discrepant")
    exam = examine(out_dir, TemplateParser())
    deal = {"deal_id": f"live{idx}", "lc_amount": "10000", "lc_number": exam["lc_number"],
            "applicant": "Meridian Apparel Trading Pte Ltd", "beneficiary": "Coimbatore Spinning Mills Pvt Ltd"}
    buyer, seller = GroqAgent("buyer"), GroqAgent("seller")
    graph = build_graph(buyer, seller)
    t0 = time.time()
    events, final = [], None
    for kind, chunk in stream(graph, initial_state(deal, exam)):
        if kind == "event":
            events.append(chunk)
            print(f"  r{chunk['round']} {chunk['actor']:8s} {chunk['action']:8s} rungs={chunk.get('rungs')} "
                  f"cited={chunk.get('cited')} {('%dms' % chunk['latency_ms']) if chunk.get('latency_ms') else ''}\n"
                  f"      {chunk.get('rationale', '')[:160]}")
        else:
            final = chunk
    wall = round(time.time() - t0, 2)
    k = final["k"]
    legal = final["status"] == "CLOSED" and 0 <= final["agreed_rungs"] <= k and all(
        0 <= e["rungs"] <= k and set(e["cited"]) <= {d["rule_id"] for d in final["discrepancies"]}
        for e in final["offers"] if e["actor"] in ("buyer", "seller"))
    bounce = any(e["action"] == "bounce" for e in events)
    llm_ok = all(c["ok"] for c in buyer.calls + seller.calls)
    res = {"run": idx, "k": k, "agreed_rungs": final["agreed_rungs"], "payout": final["payout"], "wall_seconds": wall,
           "legal": legal, "visible_bounce": bounce, "all_llm_calls_ok": llm_ok, "events": events,
           "llm_calls": len(buyer.calls) + len(seller.calls)}
    print(f"run {idx}: k={k} m={final['agreed_rungs']} wall={wall}s legal={legal} bounce={bounce} llm_ok={llm_ok} "
          f"seller={final['payout']['seller']} buyer_back={final['payout']['buyer_returned']}")
    return res


if __name__ == "__main__":
    runs = int(sys.argv[1]) if len(sys.argv) > 1 else 3
    gap = int(sys.argv[2]) if len(sys.argv) > 2 else 60
    path = Path("proof/negotiation_live_runs.json")
    results = json.loads(path.read_text()) if path.exists() else []
    for i in range(runs):
        results.append(one_run(len(results) + 1))
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(results, indent=2, default=str))
        if i < runs - 1:
            time.sleep(gap)
    ok = [r for r in results[-runs:] if r["legal"] and r["visible_bounce"] and r["wall_seconds"] < 5]
    print(f"GATE: {len(ok)}/{runs} runs legal + bounce + <5s")
