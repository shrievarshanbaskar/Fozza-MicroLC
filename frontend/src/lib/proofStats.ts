import fs from "node:fs";
import path from "node:path";

/** Build-time read of proof/negotiation_report.json. Every landing-page number comes from here or is omitted. */
export type ProofStats = {
  runs: number;
  avgExamSeconds: number | null;
  x402PaidRlusd: number | null;
  x402Payments: number;
  negotiationWallSeconds: number | null;
  meanAgentLatencyMs: number | null;
  sample: null | {
    dealId: string; k: number; m: number; seller: string; platform: string; buyerReturned: string; lcAmount: string;
    evidence: null | { provider: string; price: string; verdict: string; txHash: string; summary: string; signature: string | null };
    bounce: boolean; buyerAnchor: number | null; baseCreateHash: string | null; feeFinishHash: string | null; lockSeconds: number | null;
  };
};

type Run = {
  preset: string; deal_id: string; examination: { k: number; elapsed_ms?: number }; agent_latency_ms?: number[];
  lock: { seconds?: number; tranches: { name: string; create_hash: string | null }[] };
  negotiation: null | { k: number; status: string; wall_seconds?: number; agreed_rungs: number | null; payout: Record<string, string> | null;
    evidence: { provider?: string; price_rlusd?: string; verdict: string; tx_hash?: string | null; summary: string; signature?: string | null }[];
    events: { actor: string; action: string; rungs: number | null }[] };
  final_tranches: { name: string; status: string; action_hash?: string | null }[];
};

export function readProofStats(): ProofStats {
  const empty: ProofStats = { runs: 0, avgExamSeconds: null, x402PaidRlusd: null, x402Payments: 0, negotiationWallSeconds: null, meanAgentLatencyMs: null, sample: null };
  try {
    const p = path.join(process.cwd(), "..", "proof", "negotiation_report.json");
    const runs: Run[] = JSON.parse(fs.readFileSync(p, "utf8")).runs;
    if (!runs.length) return empty;
    const exam = runs.map((r) => r.examination.elapsed_ms).filter((x): x is number => !!x);
    const paid = runs.flatMap((r) => r.negotiation?.evidence || []).filter((e) => e.tx_hash && e.price_rlusd);
    const neg = runs.filter((r) => r.negotiation && r.negotiation.k > 0 && r.negotiation.status === "CLOSED" && r.negotiation.wall_seconds).map((r) => r.negotiation!.wall_seconds!);
    const lat = runs.flatMap((r) => r.agent_latency_ms || []);
    const disc = runs.find((r) => r.preset === "discrepant" && r.negotiation?.status === "CLOSED") || runs.find((r) => r.negotiation?.status === "CLOSED") || null;
    const n = disc?.negotiation || null;
    const ev = n?.evidence.find((e) => e.tx_hash) || null;
    const anchor = n?.events.find((e) => e.actor === "buyer" && e.action === "propose") || null;
    return {
      runs: runs.length,
      avgExamSeconds: exam.length ? exam.reduce((a, b) => a + b, 0) / exam.length / 1000 : null,
      x402PaidRlusd: paid.length ? paid.reduce((a, e) => a + Number(e.price_rlusd), 0) : null,
      x402Payments: paid.length,
      negotiationWallSeconds: neg.length ? neg.reduce((a, b) => a + b, 0) / neg.length : null,
      meanAgentLatencyMs: lat.length ? lat.reduce((a, b) => a + b, 0) / lat.length : null,
      sample: disc && n && n.payout ? {
        dealId: disc.deal_id, k: n.k, m: n.agreed_rungs ?? 0, seller: n.payout.seller, platform: n.payout.platform, buyerReturned: n.payout.buyer_returned, lcAmount: n.payout.lc_amount,
        evidence: ev ? { provider: ev.provider || "", price: ev.price_rlusd || "", verdict: ev.verdict, txHash: ev.tx_hash!, summary: ev.summary, signature: ev.signature || null } : null,
        bounce: n.events.some((e) => e.action === "bounce"), buyerAnchor: anchor?.rungs ?? null,
        baseCreateHash: disc.lock.tranches.find((t) => t.name === "base")?.create_hash || null,
        feeFinishHash: disc.final_tranches.find((t) => t.name === "fee")?.action_hash || null,
        lockSeconds: disc.lock.seconds ?? null,
      } : null,
    };
  } catch {
    return empty;
  }
}
