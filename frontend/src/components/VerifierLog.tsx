"use client";
import { AgentEvent, Evidence, Verifier } from "@/lib/api";
import Hash from "./Hash";
import InfoTip from "./InfoTip";

/** The real x402 exchange as it happened: request line, payment line, signed-confirmation line. */
export default function VerifierLog({ events, evidence, verifier, streaming }: { events: AgentEvent[]; evidence: Evidence[]; verifier?: Verifier | null; streaming: boolean }) {
  const v = events.filter((e) => e.actor === "verifier");
  const pay = v.find((e) => e.action === "pay");
  const warn = v.filter((e) => e.action === "warning");
  const active = streaming && v.length > 0 && !evidence.length && !warn.length;
  const paidHash = pay?.cited?.[0] && pay.cited[0].length === 64 ? pay.cited[0] : evidence.find((e) => e.tx_hash)?.tx_hash;
  return (
    <section className="card" data-testid="verifier-log">
      <header className="card-head">
        <span className="micro text-white/70 flex items-center gap-2">Verifier Agent Log <InfoTip tip="verifier" /></span>
        <span className={`badge ${active ? "bg-violet-500/30 text-violet-100" : v.length ? "bg-white/10 text-white/60" : "bg-white/5 text-white/30"}`}>
          {active && <span className="mr-1 inline-block h-1.5 w-1.5 rounded-full bg-violet-300 animate-ping" />}
          {active ? "Active · Sourcing x402 Evidence…" : v.length ? (verifier?.mock ? "Mock · No Payment" : "Complete") : "Idle"}
        </span>
      </header>
      <div className="p-3 mono text-white/80 space-y-1 max-h-[320px] overflow-y-auto overflow-x-hidden [overflow-wrap:anywhere]">
        {v.length === 0 && <div className="muted font-sans text-xs">No verification yet. Triggers when a discrepancy is oracle-checkable and worth at least 20x the query price.</div>}
        {v.map((e, i) => (
          <div key={i} className="grid grid-cols-[72px_1fr] gap-2" data-testid={`verifier-${e.action}`}>
            <span className={`micro ${e.action === "warning" ? "text-red-300" : "text-violet-300"}`}>{e.action}</span>
            <span className="min-w-0 [overflow-wrap:anywhere]">
              {e.action === "pay" && paidHash ? <>{e.rationale.split(" (tx ")[0]} · <Hash value={paidHash} /></> : e.rationale}
            </span>
          </div>
        ))}
        {evidence.filter((e) => e.verdict !== "UNAVAILABLE").map((e) => (
          <div key={e.rule_id} className="mt-2 rounded-btn border border-success/40 bg-success/10 p-2 text-green-200" data-testid="evidence-verified">
            <div className="font-sans text-xs font-semibold">✓ Independent Evidence Verified · {e.rule_id} {e.verdict}</div>
            <div className="text-[11px] text-green-100/80 break-all">{e.provider} · {e.price_rlusd ? `${e.price_rlusd} RLUSD paid` : "no payment"}{e.signature ? ` · signed ${e.signature.slice(0, 12)}…` : ""}</div>
          </div>
        ))}
      </div>
    </section>
  );
}
